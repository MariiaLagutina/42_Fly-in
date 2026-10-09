"""Benchmark scenarios: experiments E1 to E5 and their weather.

Each scenario has a stable id and is rebuilt from code alone: a bundled map
file, or generator parameters and a seed. Its weather source is created
anew for every execution, from the same seed, so repeats see the same
weather.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
import functools
from pathlib import Path
import random

from airlanes.model.graph import Graph
from airlanes.model.transport_mode import TransportMode
from airlanes.world.weather import (
    NoWeather,
    RandomWeather,
    ScriptedWeather,
    WeatherCondition,
    WeatherProvider,
)
from benchmarks.maps import (
    MapSpec,
    generate_bottleneck_map,
    generate_map,
    with_aircraft,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MAPS_DIR = REPO_ROOT / "maps"
CHALLENGER = MAPS_DIR / "challenger" / "01_the_impossible_dream.txt"
EUROPE = MAPS_DIR / "bonus" / "europa_map.txt"

# The question each experiment answers.
EXPERIMENTS = {
    "E1": "What do the bundled maps cost, and what does weather add?",
    "E2": "How does time grow with the hub count at a fixed lane density?",
    "E3": "How does time grow with the lane count at a fixed hub count?",
    "E4": "How does time grow with the aircraft count on one graph?",
    "E5": "How do bottlenecks, restricted hubs, weather disruption, high "
          "load, missing routes and deadlocks behave?",
    "smoke": "Does the benchmark itself work? Not a measurement.",
}

# Waves of storms for the weather-disruption scenario: each wave closes a
# share of the air lanes on its first turn and clears them later.
WAVE_STARTS = (2, 8, 14, 20)
WAVE_LENGTH = 3
WAVE_SHARE = 0.4

# The road-budget trap of `tests/unit/test_simulation.py`: snow on `E-h1`
# sends D1 round through `h2` and `h0` while D2 waits in `h0` for `h2`,
# and every way around breaks the 700 km road limit (ADR-020).
DEADLOCK_TRAP = """\
# Benchmark map: a structural deadlock without a way around
nb_drones: 2
start_hub: S 0 0
end_hub: E 4 0
hub: h0 1 1
hub: h1 2 2
hub: h2 3 3
connection: h0-S [max_link_capacity=3 distance=400km mode=road]
connection: h2-h1 [max_link_capacity=3 distance=250km mode=road]
connection: E-h2 [max_link_capacity=3 distance=300km mode=road]
connection: h0-E [distance=450km mode=road]
connection: S-h1 [distance=400km mode=road]
connection: E-h1
connection: h0-h2
"""

Param = int | float | str


@dataclass(frozen=True)
class Weather:
    """How a scenario's weather is made: `none`, `random` (`RandomWeather`
    with `seed`), `waves` (scripted storm waves drawn with `seed`) or
    `deadlock-snow` (the snow that closes the trap)."""

    kind: str = "none"
    seed: int | None = None

    @property
    def label(self) -> str:
        if self.seed is None:
            return self.kind
        return f"{self.kind}-{self.seed}"

    def provider(self, graph: Graph) -> WeatherProvider:
        """A new weather source, in its initial state."""
        if self.kind == "none":
            return NoWeather()
        if self.kind == "random":
            return RandomWeather(graph, seed=self.seed)
        if self.kind == "waves":
            return ScriptedWeather(storm_waves(graph, self.seed or 0))
        if self.kind == "deadlock-snow":
            return ScriptedWeather({4: {"E-h1": WeatherCondition.SNOW}})
        raise ValueError(f"Unknown weather: {self.kind}")


def storm_waves(
    graph: Graph, seed: int
) -> dict[int, dict[str, WeatherCondition]]:
    """Each wave storms a random share of the air lanes for a few turns."""
    rng = random.Random(seed)
    air = sorted(
        connection.name()
        for connection in graph.connections
        if connection.mode is TransportMode.AIR
    )
    schedule: dict[int, dict[str, WeatherCondition]] = {}
    for start in WAVE_STARTS:
        hit = rng.sample(air, round(WAVE_SHARE * len(air)))
        schedule.setdefault(start, {}).update(
            {name: WeatherCondition.STORM for name in hit}
        )
        schedule.setdefault(start + WAVE_LENGTH, {}).update(
            {name: WeatherCondition.CLEAR for name in hit}
        )
    return schedule


@dataclass(frozen=True)
class Scenario:
    """
    `expected` is the status the scenario is built to end with: `ok`,
    `no_route` or `deadlock`. `mechanism` names what the scenario must
    exercise, checked from its events: `bottleneck`, `restricted` or
    `weather`. Scenarios with `profile` are also run under cProfile.
    """

    scenario_id: str
    experiment: str
    weather: Weather
    params: dict[str, Param] = field(default_factory=dict)
    map_path: Path | None = None
    text: Callable[[], str] | None = None
    expected: str = "ok"
    mechanism: str | None = None
    profile: bool = False

    def map_text(self) -> str:
        if self.text is not None:
            return _cached_text(self.scenario_id, self.text)
        assert self.map_path is not None
        return self.map_path.read_text(encoding="utf-8")


_TEXTS: dict[str, str] = {}


def _cached_text(scenario_id: str, build: Callable[[], str]) -> str:
    """Generated maps are built once per process."""
    if scenario_id not in _TEXTS:
        _TEXTS[scenario_id] = build()
    return _TEXTS[scenario_id]


SEEDS = (1, 2, 3)
# Generated maps mix in some roads, as the bonus maps do.
ROAD_SHARE = 0.2


def _synthetic(
    experiment: str,
    name: str,
    spec: MapSpec,
    profile: bool = False,
) -> Scenario:
    return Scenario(
        scenario_id=f"{experiment}/{name}-s{spec.seed}",
        experiment=experiment,
        weather=Weather(),
        params={
            "hubs": spec.hubs,
            "degree": spec.degree,
            "aircraft": spec.aircraft,
            "seed": spec.seed,
            "road_share": spec.road_share,
        },
        text=functools.partial(generate_map, spec),
        profile=profile,
    )


def _bundled() -> list[Scenario]:
    scenarios = []
    for path in sorted(MAPS_DIR.glob("*/*.txt")):
        name = f"{path.parent.name}-{path.stem}"
        weathers = [Weather()] + [Weather("random", s) for s in (0, 1, 2)]
        for weather in weathers:
            scenarios.append(Scenario(
                scenario_id=f"E1/{name}/{weather.label}",
                experiment="E1",
                weather=weather,
                params={"map": name, "weather": weather.label},
                map_path=path,
                profile=path == CHALLENGER and weather.kind == "none",
            ))
    return scenarios


def _graph_size() -> list[Scenario]:
    return [
        _synthetic(
            "E2", f"h{hubs}",
            MapSpec(hubs, 3.0, 10, seed, road_share=ROAD_SHARE),
            profile=hubs == 400 and seed == 1,
        )
        for hubs in (25, 50, 100, 200, 400)
        for seed in SEEDS
    ]


def _lane_density() -> list[Scenario]:
    return [
        _synthetic(
            "E3", f"d{degree}",
            MapSpec(100, degree, 10, seed, road_share=ROAD_SHARE),
        )
        for degree in (2.5, 3.0, 4.0, 6.0)
        for seed in SEEDS
    ]


def _aircraft_load() -> list[Scenario]:
    return [
        _synthetic(
            "E4", f"a{aircraft}",
            MapSpec(100, 3.0, aircraft, seed, road_share=ROAD_SHARE),
            profile=aircraft == 100 and seed == 1,
        )
        for aircraft in (1, 5, 10, 25, 50, 100)
        for seed in SEEDS
    ]


def _challenger_with(aircraft: int) -> str:
    return with_aircraft(CHALLENGER.read_text(encoding="utf-8"), aircraft)


def _stress() -> list[Scenario]:
    restricted = MapSpec(
        50, 3.0, 25, 1, restricted_share=1.0, abstract_lanes=True
    )
    scenarios = [
        Scenario(
            scenario_id="E5/bottleneck",
            experiment="E5",
            weather=Weather(),
            params={"cluster_hubs": 30, "aircraft": 50, "seed": 1},
            text=functools.partial(generate_bottleneck_map, 30, 50, 1),
            mechanism="bottleneck",
        ),
        Scenario(
            scenario_id="E5/restricted",
            experiment="E5",
            weather=Weather(),
            params={"hubs": 50, "aircraft": 25, "seed": 1,
                    "restricted_share": 1.0, "lanes": "abstract"},
            text=functools.partial(generate_map, restricted),
            mechanism="restricted",
        ),
        Scenario(
            scenario_id="E5/weather-waves",
            experiment="E5",
            weather=Weather("waves", 0),
            params={"map": "bonus-europa_map", "weather": "waves-0"},
            map_path=EUROPE,
            mechanism="weather",
            profile=True,
        ),
    ]
    scenarios += [
        Scenario(
            scenario_id=f"E5/challenger-a{aircraft}",
            experiment="E5",
            weather=Weather(),
            params={"map": "challenger-01_the_impossible_dream",
                    "aircraft": aircraft},
            text=functools.partial(_challenger_with, aircraft),
        )
        for aircraft in (50, 100)
    ]
    scenarios += [
        Scenario(
            scenario_id="E5/disconnected",
            experiment="E5",
            weather=Weather(),
            params={"cluster_hubs": 30, "aircraft": 50, "seed": 1,
                    "gate": "blocked"},
            text=functools.partial(
                generate_bottleneck_map, 30, 50, 1, gate_blocked=True
            ),
            expected="no_route",
        ),
        Scenario(
            scenario_id="E5/deadlock",
            experiment="E5",
            weather=Weather("deadlock-snow"),
            params={"map": "road-budget-trap", "aircraft": 2},
            text=lambda: DEADLOCK_TRAP,
            expected="deadlock",
        ),
    ]
    return scenarios


def _smoke() -> list[Scenario]:
    return [Scenario(
        scenario_id="smoke/tiny",
        experiment="smoke",
        weather=Weather("random", 0),
        params={"hubs": 8, "aircraft": 3, "seed": 1},
        text=functools.partial(generate_map, MapSpec(8, 3.0, 3, 1)),
        profile=True,
    )]


def all_scenarios() -> list[Scenario]:
    """Every scenario, in run order; the smoke scenario comes last."""
    return (
        _bundled() + _graph_size() + _lane_density() + _aircraft_load()
        + _stress() + _smoke()
    )


def scenario_by_id(scenario_id: str) -> Scenario:
    for scenario in all_scenarios():
        if scenario.scenario_id == scenario_id:
            return scenario
    raise KeyError(scenario_id)
