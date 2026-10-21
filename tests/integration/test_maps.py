"""Bundled maps as reference scenarios for the whole simulation.

Each map must be delivered completely without breaking any invariant.
Turn counts are compared against the documented performance targets of the
original assignment, never against the current algorithm's exact result, so
better routing never breaks these tests. Routes are not asserted.
"""

from itertools import permutations
from pathlib import Path
import random

import pytest

from airlanes.events import AgentMoved, AgentRerouted, WeatherChanged
from airlanes.mapfile import Parser
from airlanes.model.graph import Graph
from airlanes.model.transport_mode import TransportMode
from airlanes.routing.pathfinder import Pathfinder
from airlanes.routing.policy import RoutingPolicy
from airlanes.simulation.engine import NoRouteError
from airlanes.world.weather import (
    RandomWeather,
    ScriptedWeather,
    WeatherCondition,
    WeatherState,
)

from tests.support.simulation import (
    SimulationRun,
    check_invariants,
    check_outcomes_against_events,
    delivery_turns,
    departure_modes,
    planned_delivery_turns,
    record_route_searches,
    run_simulation,
)

MAPS_DIR = Path(__file__).resolve().parents[2] / "maps"
MAP_FILES = sorted(MAPS_DIR.glob("*/*.txt"))

# Documented targets ("Target <= N turns"). The challenger and bonus maps
# have no target and are only required to finish.
TURN_BUDGETS = {
    "easy/01_linear_path.txt": 6,
    "easy/02_simple_fork.txt": 6,
    "easy/03_basic_capacity.txt": 8,
    "medium/01_dead_end_trap.txt": 15,
    "medium/02_circular_loop.txt": 20,
    "medium/03_priority_puzzle.txt": 12,
    "hard/01_maze_nightmare.txt": 45,
    "hard/02_capacity_hell.txt": 60,
    "hard/03_ultimate_challenge.txt": 35,
}

WEATHER_MAPS = ["bonus/germany_map.txt", "bonus/europa_map.txt"]


def map_id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def simulate(
    relative_path: str, weather_seed: int | None = None
) -> SimulationRun:
    """Run a bundled map, with seeded random weather if a seed is given."""
    graph, nb_aircraft = Parser().parse(str(MAPS_DIR / relative_path))
    weather = (
        RandomWeather(graph, seed=weather_seed)
        if weather_seed is not None
        else None
    )
    return run_simulation(graph, nb_aircraft, weather=weather)


def test_maps_are_found() -> None:
    assert MAP_FILES


def test_every_budgeted_map_exists() -> None:
    assert set(TURN_BUDGETS) <= {map_id(path) for path in MAP_FILES}


@pytest.mark.parametrize("map_file", MAP_FILES, ids=map_id)
def test_map_is_delivered_without_violations(map_file: Path) -> None:
    """Without weather, every planned route stays usable, so no aircraft
    reroutes."""
    run = simulate(map_id(map_file))

    assert check_invariants(run) == []
    assert not any(isinstance(e, AgentRerouted) for e in run.events)


@pytest.mark.parametrize("map_file", MAP_FILES, ids=map_id)
def test_aircraft_are_delivered_when_planned(map_file: Path) -> None:
    """Planner and executor apply one capacity model (ADR-019), so without
    weather every aircraft is delivered on the turn its plan says."""
    graph, nb_aircraft = Parser().parse(str(map_file))
    planned = planned_delivery_turns(graph, nb_aircraft)

    run = simulate(map_id(map_file))

    assert delivery_turns(run) == planned


@pytest.mark.parametrize(
    ("relative_path", "budget"), sorted(TURN_BUDGETS.items())
)
def test_map_meets_its_turn_budget(relative_path: str, budget: int) -> None:
    run = simulate(relative_path)

    assert run.turn_count <= budget


@pytest.mark.parametrize("map_file", MAP_FILES, ids=map_id)
def test_result_keeps_every_turn(map_file: Path) -> None:
    """The run finishes, so every started turn completed and must be in
    the result (ADR-023), including turns without movement."""
    run = simulate(map_id(map_file))

    assert [turn.turn_number for turn in run.simulator.turns] == list(
        range(1, run.turn_count + 1)
    )


@pytest.mark.parametrize("seed", [None, 0, 1, 2])
@pytest.mark.parametrize("map_file", MAP_FILES, ids=map_id)
def test_turn_results_agree_with_the_event_stream(
    map_file: Path, seed: int | None
) -> None:
    """Turn results and events describe the same facts, in the same order,
    until the event contract is decided (DECISION-012)."""
    run = simulate(map_id(map_file), weather_seed=seed)

    assert check_outcomes_against_events(run) == []


@pytest.mark.parametrize("map_file", MAP_FILES, ids=map_id)
def test_simulation_without_weather_is_deterministic(map_file: Path) -> None:
    first = simulate(map_id(map_file))
    second = simulate(map_id(map_file))

    assert first.output == second.output


@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("relative_path", WEATHER_MAPS)
def test_weather_keeps_invariants(relative_path: str, seed: int) -> None:
    """Weather may delay or speed up flights but must not break any rule."""
    run = simulate(relative_path, weather_seed=seed)

    assert check_invariants(run) == []


@pytest.mark.parametrize("relative_path", WEATHER_MAPS)
def test_seeded_weather_is_reproducible(relative_path: str) -> None:
    first = simulate(relative_path, weather_seed=4)
    second = simulate(relative_path, weather_seed=4)

    assert first.output == second.output


def test_weather_does_not_touch_global_random() -> None:
    saved = random.getstate()

    simulate(WEATHER_MAPS[0], weather_seed=0)

    assert random.getstate() == saved


@pytest.mark.parametrize("relative_path", WEATHER_MAPS)
def test_every_hub_reaches_every_other_hub(relative_path: str) -> None:
    """The geographic maps are connected: in clear weather, routing finds a
    route from every hub to every other one. Milan had no lanes, so no
    route on the Europe map started or ended there."""
    graph, _ = Parser().parse(str(MAPS_DIR / relative_path))
    pathfinder = Pathfinder(graph)

    unreachable = [
        (start.name, end.name)
        for start, end in permutations(graph.zones.values(), 2)
        if pathfinder.find_route(start, end, WeatherState()) is None
    ]

    assert unreachable == []


EUROPE = "bonus/europa_map.txt"


def test_milan_is_joined_to_zurich_by_one_air_lane() -> None:
    graph, _ = Parser().parse(str(MAPS_DIR / EUROPE))
    milan, zurich = graph.zones["Milan"], graph.zones["Zurich"]

    lanes = [lane for lane in graph.connections if lane.connects(milan)]

    assert [lane.name() for lane in lanes] == ["Zurich-Milan"]
    lane = lanes[0]
    assert lane.mode is TransportMode.AIR
    assert lane.distance == 220
    assert lane.max_link_capacity == 1
    assert graph.get_neighbors(milan) == [zurich]
    assert milan in graph.get_neighbors(zurich)


def with_terminals(graph: Graph, start: str, end: str) -> Graph:
    """The parsed graph with other start and end hubs. The map's own
    terminals become ordinary hubs with their map capacity."""
    for zone in graph.zones.values():
        zone.is_start = zone.name == start
        zone.is_end = zone.name == end
    graph.start_zone = graph.zones[start]
    graph.end_zone = graph.zones[end]
    return graph


@pytest.mark.parametrize("seed", [None, 0])
@pytest.mark.parametrize(
    ("start", "end"),
    [("Milan", "Athens"), ("Reykjavik", "Milan")],
    ids=["from-milan", "to-milan"],
)
def test_aircraft_fly_from_and_to_milan(
    start: str, end: str, seed: int | None
) -> None:
    graph, nb_aircraft = Parser().parse(str(MAPS_DIR / EUROPE))
    graph = with_terminals(graph, start, end)
    weather = RandomWeather(graph, seed=seed) if seed is not None else None

    run = run_simulation(graph, nb_aircraft, weather=weather)

    assert check_invariants(run) == []
    assert all(drone.is_delivered() for drone in run.simulator.drones)
    assert all(
        drone.current_zone.name == end for drone in run.simulator.drones
    )


def test_a_storm_closes_the_milan_lane_until_it_clears() -> None:
    """A closed lane is a weather state of a lane that exists: aircraft for
    Milan wait in Zurich and fly once it reopens."""
    graph, _ = Parser().parse(str(MAPS_DIR / EUROPE))
    graph = with_terminals(graph, "Zurich", "Milan")
    weather = ScriptedWeather(
        {
            1: {"Zurich-Milan": WeatherCondition.STORM},
            4: {"Zurich-Milan": WeatherCondition.CLEAR},
        }
    )

    run = run_simulation(graph, 3, weather=weather)

    assert check_invariants(run) == []
    changes = [
        (e.turn_number, e.is_open)
        for e in run.events
        if isinstance(e, WeatherChanged)
        and e.connection_name == "Zurich-Milan"
    ]
    assert changes == [(1, False), (4, True)]
    arrivals = [
        e.turn_number
        for e in run.events
        if isinstance(e, AgentMoved) and e.destination == "Milan"
    ]
    assert len(arrivals) == 3
    assert min(arrivals) >= 4


# --- Transport modes and an unlimited road budget (ADR-029) -----------------

GERMANY = "bonus/germany_map.txt"
AIR, ROAD = TransportMode.AIR, TransportMode.ROAD
AIR_ONLY = RoutingPolicy(transport_modes=frozenset({AIR}))
ROAD_ONLY = RoutingPolicy(
    max_consecutive_road_km=None, transport_modes=frozenset({ROAD})
)
# The only road from Kiel to Dresden: 95 + 150 + 140 + 120 + 35 + 190 km.
KIEL_DRESDEN_BY_ROAD = [
    "Hamburg", "Hanover", "Magdeburg", "Potsdam", "Berlin", "Dresden"
]


def germany(start: str, end: str) -> tuple[Graph, int]:
    graph, nb_aircraft = Parser().parse(str(MAPS_DIR / GERMANY))
    return with_terminals(graph, start, end), nb_aircraft


def road_km_of(graph: Graph, start: str, route: list[str]) -> int:
    hubs = [start, *route]
    total = 0
    for here, there in zip(hubs, hubs[1:]):
        lane = graph.get_connection(graph.zones[here], graph.zones[there])
        assert lane is not None and lane.mode is ROAD
        total += lane.distance
    return total


def test_road_only_drives_kiel_to_dresden_by_road() -> None:
    """730 km of consecutive road: beyond the 700 km of the default policy,
    within road only, which has no limit."""
    graph, nb_aircraft = germany("Kiel", "Dresden")

    run = run_simulation(graph, nb_aircraft, policy=ROAD_ONLY)

    assert check_invariants(run) == []
    assert road_km_of(graph, "Kiel", KIEL_DRESDEN_BY_ROAD) == 730
    assert departure_modes(run) == {ROAD}
    for drone in run.simulator.drones:
        assert drone.is_delivered()
        assert run.visited_zones(drone.label) == KIEL_DRESDEN_BY_ROAD
        assert drone.road_km_since_air == 730


def test_the_default_policy_flies_part_of_kiel_to_dresden() -> None:
    """Control: the default policy cannot drive 730 km, so it flies
    Hamburg-Berlin, which ends the road stretch: only Berlin-Dresden, 190
    km, counts at the end."""
    graph, nb_aircraft = germany("Kiel", "Dresden")

    run = run_simulation(graph, nb_aircraft)

    assert check_invariants(run) == []
    assert departure_modes(run) == {AIR, ROAD}
    for drone in run.simulator.drones:
        assert drone.is_delivered()
        assert run.visited_zones(drone.label) == [
            "Hamburg", "Berlin", "Dresden"
        ]
        assert drone.road_km_since_air == 190


def test_a_storm_on_the_road_does_not_make_road_only_fly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The storm slows Hanover-Magdeburg, so aircraft before it reconsider
    their route; Hamburg-Berlin by air would be faster, but every search
    under road only finds the same road."""
    graph, _ = germany("Kiel", "Dresden")
    searches = record_route_searches(monkeypatch)
    weather = ScriptedWeather(
        {1: {"Hanover-Magdeburg": WeatherCondition.STORM}}
    )

    run = run_simulation(graph, 3, weather=weather, policy=ROAD_ONLY)

    assert check_invariants(run) == []
    road = ["Kiel", *KIEL_DRESDEN_BY_ROAD]
    replanning = [s for s in searches if s.weather != WeatherState()]
    assert replanning
    for search in replanning:
        assert search.policy == ROAD_ONLY
        assert search.route == tuple(road[road.index(search.start) + 1:])
    assert not any(isinstance(e, AgentRerouted) for e in run.events)
    assert departure_modes(run) == {ROAD}
    assert all(drone.is_delivered() for drone in run.simulator.drones)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_road_only_keeps_to_the_road_in_random_weather(
    seed: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph, nb_aircraft = germany("Kiel", "Dresden")
    searches = record_route_searches(monkeypatch)

    run = run_simulation(
        graph, nb_aircraft, RandomWeather(graph, seed=seed), ROAD_ONLY
    )

    assert check_invariants(run) == []
    assert any(s.weather != WeatherState() for s in searches)
    assert departure_modes(run) == {ROAD}
    assert all(drone.is_delivered() for drone in run.simulator.drones)
    assert {d.road_km_since_air for d in run.simulator.drones} == {730}


@pytest.mark.parametrize(
    ("start", "end"),
    [("Kiel", "Munich"), ("Berlin", "Munich")],
)
def test_air_only_has_no_route_from_a_road_only_hub(
    start: str, end: str
) -> None:
    """Kiel's only lane is a road; Berlin's air lanes reach only Hamburg
    and Schwerin, whose other lanes are roads."""
    graph, nb_aircraft = germany(start, end)

    with pytest.raises(NoRouteError):
        run_simulation(graph, nb_aircraft, policy=AIR_ONLY)


@pytest.mark.parametrize("seed", [None, 0, 1])
def test_air_only_flies_frankfurt_to_munich(seed: int | None) -> None:
    graph, nb_aircraft = germany("Frankfurt", "Munich")
    weather = RandomWeather(graph, seed=seed) if seed is not None else None

    run = run_simulation(graph, nb_aircraft, weather, AIR_ONLY)

    assert check_invariants(run) == []
    assert departure_modes(run) == {AIR}
    assert all(drone.is_delivered() for drone in run.simulator.drones)


@pytest.mark.parametrize("seed", [None, 0, 1, 2])
def test_air_only_changes_nothing_on_a_map_of_air_lanes(
    seed: int | None,
) -> None:
    """Every lane of the Europe map is an air lane."""
    graph, nb_aircraft = Parser().parse(str(MAPS_DIR / EUROPE))
    weather = RandomWeather(graph, seed=seed) if seed is not None else None
    default = simulate(EUROPE, seed)

    run = run_simulation(graph, nb_aircraft, weather, AIR_ONLY)

    assert check_invariants(run) == []
    assert run.events == default.events
    assert run.output == default.output
