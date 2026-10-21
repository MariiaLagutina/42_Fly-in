"""Scenarios (ADR-029): chosen start and end hubs on a fresh graph, the
vehicle count, routing modes, the route check before a run, and runs with
typed results."""

import hashlib
from itertools import permutations
import math
from pathlib import Path
import random
import sys
from typing import Any

import pytest

from airlanes import scenario
from airlanes.events import (
    AgentMoved,
    CapacitySnapshot,
    TurnFinished,
    TurnStarted,
)
from airlanes.mapfile import Parser
from airlanes.model.graph import Graph
from airlanes.model.transport_mode import TransportMode
from airlanes.routing.policy import RoutingPolicy
from airlanes.scenario import (
    DEFAULT_VEHICLE_COUNT,
    MAX_VEHICLE_COUNT,
    MIN_VEHICLE_COUNT,
    RouteCheck,
    RouteCheckStatus,
    RoutingMode,
    ScenarioError,
    ScenarioResult,
    ScenarioStatus,
    available_routing_modes,
    check_route,
    load_scenario_graph,
    normalize_vehicle_count,
    routing_policy,
    run_scenario,
)
from airlanes.simulation.engine import Simulator
from airlanes.world.weather import (
    RandomWeather,
    ScriptedWeather,
    WeatherCondition,
    WeatherState,
)

from tests.support.graphs import Link, build_graph, end_hub, hub, start_hub
from tests.support.simulation import (
    EventRecorder,
    SimulationRun,
    check_invariants,
    departure_modes,
    RouteSearch,
    record_route_searches,
    run_simulation,
)

MAPS_DIR = Path(__file__).resolve().parents[2] / "maps"
GERMANY = MAPS_DIR / "bonus" / "germany_map.txt"
EUROPE = MAPS_DIR / "bonus" / "europa_map.txt"


def terminals(graph: Graph) -> tuple[list[str], list[str]]:
    """Names of the hubs flagged as start and as end."""
    zones = graph.zones.values()
    return (
        [zone.name for zone in zones if zone.is_start],
        [zone.name for zone in zones if zone.is_end],
    )


def test_the_chosen_hubs_are_the_only_terminals() -> None:
    graph = load_scenario_graph(GERMANY, "Berlin", "Munich")

    assert terminals(graph) == (["Berlin"], ["Munich"])
    assert graph.start_zone is graph.zones["Berlin"]
    assert graph.end_zone is graph.zones["Munich"]


def test_the_map_terminals_can_swap_roles() -> None:
    graph = load_scenario_graph(GERMANY, "Munich", "Kiel")

    assert terminals(graph) == (["Munich"], ["Kiel"])
    assert graph.start_zone is graph.zones["Munich"]
    assert graph.end_zone is graph.zones["Kiel"]


def test_the_former_terminals_have_their_map_capacity() -> None:
    """Kiel and Munich set max_drones=10; only terminals are unlimited."""
    graph = load_scenario_graph(GERMANY, "Berlin", "Hamburg")

    assert graph.zones["Kiel"].effective_capacity() == 10
    assert graph.zones["Munich"].effective_capacity() == 10
    assert graph.zones["Berlin"].effective_capacity() == math.inf
    assert graph.zones["Hamburg"].effective_capacity() == math.inf


def test_the_former_start_hub_is_reported_with_its_capacity() -> None:
    """The capacity snapshot lists every hub except the start and end hubs
    (ADR-026): Kiel now, Berlin and Munich not."""
    graph = load_scenario_graph(GERMANY, "Berlin", "Munich")

    run = run_simulation(graph, 10)

    assert check_invariants(run) == []
    snapshots = [e for e in run.events if isinstance(e, CapacitySnapshot)]
    assert snapshots
    for snapshot in snapshots:
        hubs = {name: capacity for name, _, capacity in snapshot.hub_load}
        assert hubs["Kiel"] == 10
        assert "Berlin" not in hubs and "Munich" not in hubs


def test_nothing_else_changes() -> None:
    """Hubs keep their map data and lanes stay as the map defines them."""
    original, _ = Parser().parse(str(GERMANY))

    graph = load_scenario_graph(GERMANY, "Berlin", "Munich")

    def hubs(g: Graph) -> list[tuple[object, ...]]:
        return [
            (z.name, z.x, z.y, z.zone_type, z.color, z.max_drones,
             z.population)
            for z in g.zones.values()
        ]

    def lanes(g: Graph) -> list[tuple[object, ...]]:
        return [
            (c.name(), c.mode, c.distance, c.max_link_capacity)
            for c in g.connections
        ]

    assert hubs(graph) == hubs(original)
    assert lanes(graph) == lanes(original)


def test_the_map_file_is_not_changed() -> None:
    before = hashlib.sha256(GERMANY.read_bytes()).hexdigest()

    load_scenario_graph(GERMANY, "Berlin", "Munich")
    load_scenario_graph(GERMANY, "Dresden", "Kiel")

    assert hashlib.sha256(GERMANY.read_bytes()).hexdigest() == before


def test_every_call_builds_an_independent_graph() -> None:
    first = load_scenario_graph(GERMANY, "Berlin", "Munich")
    second = load_scenario_graph(GERMANY, "Dresden", "Kiel")

    assert first is not second
    assert not {id(z) for z in first.zones.values()} & {
        id(z) for z in second.zones.values()
    }
    assert not {id(c) for c in first.connections} & {
        id(c) for c in second.connections
    }
    # The second call did not move the first graph's terminals.
    assert terminals(first) == (["Berlin"], ["Munich"])
    assert terminals(second) == (["Dresden"], ["Kiel"])


def test_europe_terminals_are_reassigned_too() -> None:
    graph = load_scenario_graph(EUROPE, "Milan", "Lisbon")

    assert terminals(graph) == (["Milan"], ["Lisbon"])
    assert graph.zones["Reykjavik"].effective_capacity() == 15
    assert graph.zones["Athens"].effective_capacity() == 15


@pytest.mark.parametrize(
    ("map_file", "start", "end"),
    [(GERMANY, "Kiel", "Munich"), (EUROPE, "Reykjavik", "Athens")],
    ids=["germany", "europe"],
)
def test_choosing_the_map_terminals_gives_the_map_graph(
    map_file: Path, start: str, end: str
) -> None:
    original, _ = Parser().parse(str(map_file))

    graph = load_scenario_graph(map_file, start, end)

    assert terminals(graph) == terminals(original) == ([start], [end])
    assert graph.start_zone is graph.zones[start]
    assert graph.end_zone is graph.zones[end]
    assert {
        z.name: z.effective_capacity() for z in graph.zones.values()
    } == {z.name: z.effective_capacity() for z in original.zones.values()}


@pytest.mark.parametrize(
    ("map_file", "first", "second"),
    [(GERMANY, "Berlin", "Munich"), (EUROPE, "Lisbon", "Helsinki")],
    ids=["germany", "europe"],
)
def test_a_reversed_selection_swaps_the_roles(
    map_file: Path, first: str, second: str
) -> None:
    there = load_scenario_graph(map_file, first, second)
    back = load_scenario_graph(map_file, second, first)

    assert terminals(there) == ([first], [second])
    assert terminals(back) == ([second], [first])
    assert back.start_zone is back.zones[second]
    assert back.end_zone is back.zones[first]


def test_new_terminals_keep_their_map_capacity_value() -> None:
    """Terminals are unlimited through `effective_capacity`; their own
    `max_drones` is not overwritten."""
    graph = load_scenario_graph(GERMANY, "Berlin", "Schwerin")

    assert graph.zones["Berlin"].max_drones == 36
    assert graph.zones["Schwerin"].max_drones == 1
    assert graph.zones["Berlin"].effective_capacity() == math.inf
    assert graph.zones["Schwerin"].effective_capacity() == math.inf


@pytest.mark.parametrize(
    "map_file", [GERMANY, EUROPE], ids=["germany", "europe"]
)
def test_every_pair_of_hubs_gives_consistent_terminals(
    map_file: Path,
) -> None:
    """For every ordered pair of hubs: exactly the two chosen hubs are
    terminals, the graph references them, and every other hub is limited
    by its unchanged map capacity."""
    original, _ = Parser().parse(str(map_file))
    capacities = {z.name: z.max_drones for z in original.zones.values()}

    for start, end in permutations(capacities, 2):
        graph = load_scenario_graph(map_file, start, end)

        assert terminals(graph) == ([start], [end])
        assert graph.start_zone is graph.zones[start]
        assert graph.end_zone is graph.zones[end]
        for zone in graph.zones.values():
            assert zone.max_drones == capacities[zone.name]
            expected = (
                math.inf if zone.name in (start, end)
                else capacities[zone.name]
            )
            assert zone.effective_capacity() == expected


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("Atlantis", "Munich", "Unknown hub: Atlantis."),
        ("Berlin", "Atlantis", "Unknown hub: Atlantis."),
        ("Berlin", "Berlin", "Start and end hubs must be different."),
    ],
)
def test_unusable_hubs_are_rejected(
    start: str, end: str, message: str
) -> None:
    with pytest.raises(ScenarioError) as error:
        load_scenario_graph(GERMANY, start, end)

    assert str(error.value) == message


BLOCKED_MAP = (
    "nb_drones: 1\n"
    "start_hub: a 0 0\n"
    "hub: wall 1 0 [zone=blocked]\n"
    "hub: b 2 0\n"
    "end_hub: c 3 0\n"
    "connection: a-b\n"
    "connection: b-c\n"
    "connection: a-wall\n"
)


@pytest.mark.parametrize(
    ("start", "end"), [("wall", "c"), ("a", "wall")]
)
def test_a_blocked_hub_cannot_be_a_terminal(
    tmp_path: Path, start: str, end: str
) -> None:
    map_file = tmp_path / "map.txt"
    map_file.write_text(BLOCKED_MAP, encoding="utf-8")

    with pytest.raises(ScenarioError) as error:
        load_scenario_graph(map_file, start, end)

    assert str(error.value) == "A start or end hub cannot be blocked: wall."


def test_a_hub_between_the_map_terminals_can_be_chosen(
    tmp_path: Path,
) -> None:
    map_file = tmp_path / "map.txt"
    map_file.write_text(BLOCKED_MAP, encoding="utf-8")

    graph = load_scenario_graph(map_file, "b", "a")

    assert terminals(graph) == (["b"], ["a"])


# --- Vehicle count -----------------------------------------------------------


def test_the_vehicle_count_limits() -> None:
    assert (DEFAULT_VEHICLE_COUNT, MIN_VEHICLE_COUNT, MAX_VEHICLE_COUNT) == (
        10, 1, 100
    )


@pytest.mark.parametrize(
    ("value", "count"),
    [
        ("1", 1),
        ("10", 10),
        ("25", 25),
        ("99", 99),
        ("100", 100),
        ("007", 7),
        (" 25 ", 25),
        ("\t42\n", 42),
    ],
)
def test_a_count_in_range_is_kept(value: str, count: int) -> None:
    assert normalize_vehicle_count(value) == count


@pytest.mark.parametrize(
    ("value", "count"),
    [
        ("0", 1),
        ("-0", 1),
        ("-1", 1),
        ("-5", 1),
        (" -5 ", 1),
        ("101", 100),
        ("999999", 100),
        ("99999999999999999999999", 100),
    ],
)
def test_a_count_out_of_range_is_clamped(value: str, count: int) -> None:
    assert normalize_vehicle_count(value) == count


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "abc",
        "7.5",
        "1e2",
        "+5",
        "-",
        "--5",
        "5 5",
        "0x10",
        "1_000",
        "10 drones",
        "١٢",  # Arabic-Indic digits
        "１２",  # fullwidth digits
        "²",  # superscript two
    ],
)
def test_empty_or_invalid_input_gives_the_default(value: str) -> None:
    assert normalize_vehicle_count(value) == 10


# Longer than Python's limit on converting a string to an integer, which
# `int` enforces with a ValueError; 4300 digits unless configured.
LONG = max(sys.get_int_max_str_digits(), 4300) + 1


@pytest.mark.parametrize(
    ("value", "count"),
    [
        ("9" * LONG, 100),
        ("1" + "0" * LONG, 100),
        (" " + "9" * LONG + " ", 100),
        ("-" + "9" * LONG, 1),
        ("-" + "0" * LONG, 1),
        ("0" * LONG, 1),
        ("0" * LONG + "42", 42),
        ("0" * LONG + "100", 100),
        ("0" * LONG + "101", 100),
    ],
)
def test_a_count_of_any_length_is_normalized(value: str, count: int) -> None:
    assert normalize_vehicle_count(value) == count


# --- Running a scenario ------------------------------------------------------


def test_a_scenario_is_delivered() -> None:
    result = run_scenario(GERMANY, "Berlin", "Munich", 10, weather_seed=0)

    assert result.status is ScenarioStatus.DELIVERED
    assert (result.delivered, result.vehicles) == (10, 10)
    assert [turn.turn_number for turn in result.turns] == list(
        range(1, len(result.turns) + 1)
    )
    assert result.message == (
        f"Delivered in {len(result.turns)} turns. "
        "10 of 10 vehicles reached Munich."
    )


@pytest.mark.parametrize("vehicles", [MIN_VEHICLE_COUNT, MAX_VEHICLE_COUNT])
def test_the_vehicle_count_limits_can_be_run(vehicles: int) -> None:
    result = run_scenario(GERMANY, "Berlin", "Munich", vehicles, 0)

    assert result.status is ScenarioStatus.DELIVERED
    assert result.delivered == vehicles


def test_one_vehicle_is_one_vehicle_in_the_message() -> None:
    result = run_scenario(GERMANY, "Kiel", "Hamburg", 1, weather_seed=0)

    assert result.message.endswith(" 1 of 1 vehicle reached Hamburg.")


@pytest.mark.parametrize("vehicles", [0, -1, 101, True, 5.0, "10", None])
def test_an_invalid_vehicle_count_is_rejected(vehicles: object) -> None:
    with pytest.raises(ScenarioError) as error:
        run_scenario(GERMANY, "Berlin", "Munich", vehicles)  # type: ignore

    assert str(error.value) == (
        "The vehicle count must be a whole number from 1 to 100: "
        f"{vehicles!r}."
    )


def test_listeners_receive_the_run_events() -> None:
    first, second = EventRecorder(), EventRecorder()

    result = run_scenario(
        GERMANY, "Berlin", "Munich", 10, 0, listeners=[first, second]
    )

    assert first.events == second.events
    assert first.events[0] == TurnStarted(1)
    finished = [e for e in first.events if isinstance(e, TurnFinished)]
    assert len(finished) == len(result.turns)
    delivered = [
        e for e in first.events if isinstance(e, AgentMoved) and e.delivered
    ]
    assert len(delivered) == 10


def run_with_events(
    map_file: Path, start: str, end: str, vehicles: int, seed: int
) -> tuple[ScenarioResult, list[object]]:
    recorder = EventRecorder()
    result = run_scenario(
        map_file, start, end, vehicles, seed, listeners=[recorder]
    )
    return result, list(recorder.events)


def test_a_seed_makes_runs_reproducible_and_runs_are_independent() -> None:
    """The same scenario and seed give the same run, before and after a
    run of another scenario on the same map."""
    first = run_with_events(GERMANY, "Berlin", "Munich", 10, 3)
    other = run_with_events(GERMANY, "Munich", "Kiel", 50, 4)
    again = run_with_events(GERMANY, "Berlin", "Munich", 10, 3)

    assert again == first
    assert other != first


def test_every_run_has_its_own_graph_and_new_weather(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a seed, each run gets a new random weather provider for its
    own graph."""
    made: list[tuple[Graph, int | None, RandomWeather]] = []

    def recording_weather(
        graph: Graph, seed: int | None = None
    ) -> RandomWeather:
        weather = RandomWeather(graph, seed=seed)
        made.append((graph, seed, weather))
        return weather

    monkeypatch.setattr(scenario, "RandomWeather", recording_weather)

    run_scenario(GERMANY, "Berlin", "Munich", 10)
    run_scenario(GERMANY, "Berlin", "Munich", 10)

    assert [seed for _, seed, _ in made] == [None, None]
    assert made[0][0] is not made[1][0]
    assert made[0][2] is not made[1][2]


def test_running_does_not_change_the_map_file() -> None:
    before = hashlib.sha256(GERMANY.read_bytes()).hexdigest()

    run_scenario(GERMANY, "Berlin", "Munich", 10, 0)

    assert hashlib.sha256(GERMANY.read_bytes()).hexdigest() == before


def write_map(tmp_path: Path, text: str) -> Path:
    map_file = tmp_path / "map.txt"
    map_file.write_text(text, encoding="utf-8")
    return map_file


def test_a_scenario_without_a_route_does_not_start(tmp_path: Path) -> None:
    map_file = write_map(
        tmp_path,
        "nb_drones: 1\n"
        "start_hub: a 0 0\n"
        "hub: b 1 0\n"
        "end_hub: c 2 0\n"
        "connection: a-b\n",
    )
    recorder = EventRecorder()

    result = run_scenario(map_file, "a", "c", 3, 0, listeners=[recorder])

    assert result == ScenarioResult(
        ScenarioStatus.NO_ROUTE,
        (),
        0,
        3,
        "No route from a to c. 0 of 3 vehicles reached c.",
    )
    assert recorder.events == []


def scripted(
    schedule: dict[int, dict[str, WeatherCondition]],
) -> object:
    """A stand-in for `RandomWeather` that follows a fixed schedule."""
    def weather(graph: Graph, seed: int | None = None) -> ScriptedWeather:
        return ScriptedWeather(schedule)
    return weather


# The road-budget trap of `tests/unit/test_simulation.py`: snow on `E-h1`
# on turn 4 sends D1 round through `h2` and `h0` while D2 waits in `h0`
# for `h2`, and every way around breaks the 700 km road budget.
DEADLOCK_TRAP = (
    "nb_drones: 2\n"
    "start_hub: S 0 0\n"
    "end_hub: E 4 0\n"
    "hub: h0 1 1\n"
    "hub: h1 2 2\n"
    "hub: h2 3 3\n"
    "connection: h0-S [max_link_capacity=3 distance=400km mode=road]\n"
    "connection: h2-h1 [max_link_capacity=3 distance=250km mode=road]\n"
    "connection: E-h2 [max_link_capacity=3 distance=300km mode=road]\n"
    "connection: h0-E [distance=450km mode=road]\n"
    "connection: S-h1 [distance=400km mode=road]\n"
    "connection: E-h1\n"
    "connection: h0-h2\n"
)


def test_a_deadlock_ends_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    map_file = write_map(tmp_path, DEADLOCK_TRAP)
    monkeypatch.setattr(
        scenario,
        "RandomWeather",
        scripted({4: {"E-h1": WeatherCondition.SNOW}}),
    )

    result = run_scenario(map_file, "S", "E", 2)

    assert result.status is ScenarioStatus.DEADLOCK
    # The turn that raised did not complete.
    assert len(result.turns) == 7
    assert result.delivered < result.vehicles
    assert result.message.startswith("Deadlock on turn 8 at h0, h2. ")


def test_the_turn_limit_ends_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The only lane is closed for good, so the run reaches 10,000 turns."""
    map_file = write_map(
        tmp_path,
        "nb_drones: 1\n"
        "start_hub: start 0 0\n"
        "end_hub: goal 1 0\n"
        "connection: start-goal [distance=450km]\n",
    )
    monkeypatch.setattr(
        scenario,
        "RandomWeather",
        scripted({1: {"start-goal": WeatherCondition.STORM}}),
    )

    result = run_scenario(map_file, "start", "goal", 1)

    assert result.status is ScenarioStatus.TURN_LIMIT
    assert len(result.turns) == 10000
    assert result.delivered == 0
    assert result.message == (
        "Stopped after 10000 turns. 0 of 1 vehicle reached goal."
    )


# --- Routing modes -----------------------------------------------------------

AIR, ROAD = TransportMode.AIR, TransportMode.ROAD
MIXED = RoutingMode.MIXED
ROAD_ONLY = RoutingMode.ROAD_ONLY
AIR_ONLY = RoutingMode.AIR_ONLY


def test_the_modes_in_presentation_order() -> None:
    assert [(mode, mode.value) for mode in RoutingMode] == [
        (MIXED, "Mixed"),
        (ROAD_ONLY, "Road only"),
        (AIR_ONLY, "Air only"),
    ]


@pytest.mark.parametrize(
    ("mode", "policy"),
    [
        (MIXED, RoutingPolicy(700, frozenset({AIR, ROAD}))),
        (ROAD_ONLY, RoutingPolicy(None, frozenset({ROAD}))),
        (AIR_ONLY, RoutingPolicy(700, frozenset({AIR}))),
    ],
)
def test_each_mode_has_its_routing_policy(
    mode: RoutingMode, policy: RoutingPolicy
) -> None:
    assert routing_policy(mode) == policy


def test_mixed_is_the_policy_the_simulator_uses_by_default() -> None:
    graph, nb_aircraft = Parser().parse(str(GERMANY))

    assert routing_policy(MIXED) == Simulator(graph, nb_aircraft).policy


def test_germany_offers_every_mode() -> None:
    graph, _ = Parser().parse(str(GERMANY))

    assert available_routing_modes(graph) == (MIXED, ROAD_ONLY, AIR_ONLY)


def test_europe_offers_air_only() -> None:
    graph, _ = Parser().parse(str(EUROPE))

    assert available_routing_modes(graph) == (AIR_ONLY,)


@pytest.mark.parametrize(
    ("modes", "offered"),
    [
        pytest.param([AIR], (AIR_ONLY,), id="air"),
        pytest.param([ROAD], (ROAD_ONLY,), id="road"),
        pytest.param([ROAD, AIR], (MIXED, ROAD_ONLY, AIR_ONLY), id="mixed"),
        pytest.param([AIR, ROAD], (MIXED, ROAD_ONLY, AIR_ONLY), id="mixed-2"),
        pytest.param([], (), id="no-lanes"),
    ],
)
def test_the_offered_modes_follow_the_lanes(
    modes: list[TransportMode], offered: tuple[RoutingMode, ...]
) -> None:
    hubs = ["start", *(f"h{i}" for i in range(len(modes))), "goal"]
    graph = build_graph(
        [start_hub(), *(hub(name) for name in hubs[1:-1]), end_hub()],
        [
            Link(here, there, distance=100, mode=mode)
            for here, there, mode in zip(hubs, hubs[1:], modes)
        ],
    )

    assert available_routing_modes(graph) == offered


def test_a_mode_is_offered_without_a_route_between_the_hubs() -> None:
    """Kiel's only lane is a road, so Air only has no route from Kiel. The
    map still offers it, and running it reports the missing route."""
    graph = load_scenario_graph(GERMANY, "Kiel", "Munich")

    assert AIR_ONLY in available_routing_modes(graph)
    result = run_scenario(GERMANY, "Kiel", "Munich", 3, 0, mode=AIR_ONLY)
    assert result.status is ScenarioStatus.NO_ROUTE
    assert result.message == (
        "No route from Kiel to Munich. 0 of 3 vehicles reached Munich."
    )


def recorded_runs(monkeypatch: pytest.MonkeyPatch) -> list[SimulationRun]:
    """Every run the scenario starts from now on, with its events, for the
    invariant checker."""
    runs: list[SimulationRun] = []

    def recording_simulator(*args: Any, **kwargs: Any) -> Simulator:
        simulator = Simulator(*args, **kwargs)
        recorder = EventRecorder()
        assert simulator.dispatcher is not None
        simulator.dispatcher.add_listener(recorder)
        runs.append(SimulationRun(
            simulator.graph, len(simulator.drones), simulator,
            recorder.events, [],
        ))
        return simulator

    monkeypatch.setattr(scenario, "Simulator", recording_simulator)
    return runs


@pytest.mark.parametrize("mode", list(RoutingMode))
def test_a_scenario_runs_in_every_mode(
    mode: RoutingMode, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hamburg and Berlin are joined by an air lane and by road."""
    runs = recorded_runs(monkeypatch)

    result = run_scenario(GERMANY, "Hamburg", "Berlin", 10, 0, mode=mode)

    assert result.status is ScenarioStatus.DELIVERED
    assert result.delivered == 10
    [run] = runs
    assert run.simulator.policy == routing_policy(mode)
    assert check_invariants(run) == []
    assert departure_modes(run) <= routing_policy(mode).transport_modes


def test_road_only_drives_kiel_to_dresden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """730 km of consecutive road, beyond the 700 km of Mixed."""
    runs = recorded_runs(monkeypatch)

    result = run_scenario(GERMANY, "Kiel", "Dresden", 10, 0, mode=ROAD_ONLY)

    assert result.status is ScenarioStatus.DELIVERED
    assert result.delivered == 10
    [run] = runs
    assert check_invariants(run) == []
    assert departure_modes(run) == {ROAD}
    assert {d.road_km_since_air for d in run.simulator.drones} == {730}


def test_air_only_departs_on_no_road(monkeypatch: pytest.MonkeyPatch) -> None:
    runs = recorded_runs(monkeypatch)

    result = run_scenario(
        GERMANY, "Frankfurt", "Munich", 10, 0, mode=AIR_ONLY
    )

    assert result.status is ScenarioStatus.DELIVERED
    [run] = runs
    assert check_invariants(run) == []
    assert departure_modes(run) == {AIR}


@pytest.mark.parametrize(
    ("start", "end", "seed"),
    [("Berlin", "Munich", 0), ("Kiel", "Dresden", 1), ("Munich", "Kiel", 2)],
)
def test_mixed_runs_as_a_scenario_without_a_mode(
    start: str, end: str, seed: int
) -> None:
    before = run_with_events(GERMANY, start, end, 10, seed)
    recorder = EventRecorder()

    mixed = run_scenario(
        GERMANY, start, end, 10, seed, [recorder], mode=MIXED
    )

    assert (mixed, list(recorder.events)) == before


def test_air_only_on_europe_runs_as_a_scenario_without_a_mode() -> None:
    before = run_with_events(EUROPE, "Reykjavik", "Athens", 10, 0)
    recorder = EventRecorder()

    air = run_scenario(
        EUROPE, "Reykjavik", "Athens", 10, 0, [recorder], mode=AIR_ONLY
    )

    assert (air, list(recorder.events)) == before


@pytest.mark.parametrize("mode", [MIXED, ROAD_ONLY])
def test_a_mode_the_map_does_not_offer_is_rejected(
    mode: RoutingMode, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = recorded_runs(monkeypatch)

    with pytest.raises(ScenarioError) as error:
        run_scenario(EUROPE, "Reykjavik", "Athens", 10, 0, mode=mode)

    assert str(error.value) == (
        f"{mode.value} is not available on this map. "
        "Available modes: Air only."
    )
    assert runs == []


NO_LANES = (
    "nb_drones: 1\n"
    "start_hub: a 0 0\n"
    "end_hub: c 2 0\n"
)


def test_a_map_without_lanes_offers_no_mode(tmp_path: Path) -> None:
    map_file = write_map(tmp_path, NO_LANES)

    with pytest.raises(ScenarioError) as error:
        run_scenario(map_file, "a", "c", 1, 0, mode=AIR_ONLY)

    assert str(error.value) == (
        "Air only is not available on this map. Available modes: none."
    )


def test_a_map_without_lanes_has_no_route_without_a_mode(
    tmp_path: Path,
) -> None:
    """As before routing modes existed."""
    result = run_scenario(write_map(tmp_path, NO_LANES), "a", "c", 1, 0)

    assert result.status is ScenarioStatus.NO_ROUTE


def test_the_hubs_are_checked_before_the_mode() -> None:
    with pytest.raises(ScenarioError) as error:
        run_scenario(EUROPE, "Atlantis", "Athens", 10, mode=MIXED)

    assert str(error.value) == "Unknown hub: Atlantis."


def test_runs_in_different_modes_share_no_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run in another mode, with other hubs, leaves nothing behind: the
    same scenario runs the same, each run on its own graph with its own
    vehicles, and each graph has the map's capacities."""
    runs = recorded_runs(monkeypatch)

    first = run_with_events(GERMANY, "Kiel", "Dresden", 10, 5)
    recorder = EventRecorder()
    road = run_scenario(
        GERMANY, "Kiel", "Dresden", 10, 5, [recorder], mode=ROAD_ONLY
    )
    other = run_scenario(GERMANY, "Dresden", "Kiel", 100, 6, mode=MIXED)
    again = run_scenario(
        GERMANY, "Kiel", "Dresden", 10, 5, [EventRecorder()], mode=ROAD_ONLY
    )

    assert other.status is ScenarioStatus.DELIVERED
    assert again == road != first[0]
    road_only = routing_policy(ROAD_ONLY)
    assert [run.simulator.policy for run in runs] == [
        RoutingPolicy(), road_only, RoutingPolicy(), road_only,
    ]
    assert runs[1].events == runs[3].events
    assert len({id(run.graph) for run in runs}) == 4
    assert len({id(d) for run in runs for d in run.simulator.drones}) == 130
    map_graph, _ = Parser().parse(str(GERMANY))
    for run in runs:
        assert check_invariants(run) == []
        for name, zone in run.graph.zones.items():
            assert zone.max_drones == map_graph.zones[name].max_drones
    assert list(recorder.events) == runs[1].events


# --- Route check before a run ------------------------------------------------
# Synthetic maps are written to files, as the check reads a map file. The
# route searches are recorded to show which modes were tried, in which
# order and weather, and what each found.

ROUTE = RouteCheckStatus.ROUTE
MODE_CHANGED = RouteCheckStatus.MODE_CHANGED
NO_ROUTE = RouteCheckStatus.NO_ROUTE


def searched(
    searches: list[RouteSearch],
) -> list[tuple[RoutingPolicy, tuple[str, ...] | None]]:
    """The policy and the route found of each search, all in clear
    weather."""
    assert all(search.weather == WeatherState() for search in searches)
    return [(search.policy, search.route) for search in searches]


# 800 km of road, over the 700 km of Mixed; the air lane `x-y` leads
# nowhere but gives the map both modes.
LONG_ROAD = (
    "nb_drones: 1\n"
    "start_hub: S 0 0\n"
    "hub: a 1 0\n"
    "end_hub: E 2 0\n"
    "hub: x 0 1\n"
    "hub: y 1 1\n"
    "connection: S-a [distance=400km mode=road]\n"
    "connection: a-E [distance=400km mode=road]\n"
    "connection: x-y [distance=300km]\n"
)

# Air lanes from S to E exist, but only through a blocked hub; the road
# is too long for Mixed.
AIR_THROUGH_A_BLOCKED_HUB = LONG_ROAD + (
    "hub: wall 1 2 [zone=blocked]\n"
    "connection: S-wall [distance=300km]\n"
    "connection: wall-E [distance=300km]\n"
)

# A short road from S to E, and an air lane from S that leads nowhere.
SHORT_ROAD = (
    "nb_drones: 1\n"
    "start_hub: S 0 0\n"
    "hub: a 1 0\n"
    "end_hub: E 2 0\n"
    "hub: x 0 1\n"
    "connection: S-a [distance=100km mode=road]\n"
    "connection: a-E [distance=100km mode=road]\n"
    "connection: S-x [distance=300km]\n"
)

# An air lane from S to E, and a road that leads nowhere.
DIRECT_AIR = (
    "nb_drones: 1\n"
    "start_hub: S 0 0\n"
    "end_hub: E 2 0\n"
    "hub: x 0 1\n"
    "hub: y 1 1\n"
    "connection: S-E [distance=300km]\n"
    "connection: x-y [distance=100km mode=road]\n"
)

# Both modes, but S and E are in different parts of the map.
APART = (
    "nb_drones: 1\n"
    "start_hub: S 0 0\n"
    "hub: a 1 0\n"
    "hub: b 2 0\n"
    "end_hub: E 3 0\n"
    "connection: S-a [distance=300km]\n"
    "connection: b-E [distance=100km mode=road]\n"
)


def test_a_mode_with_a_route_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    searches = record_route_searches(monkeypatch)

    check = check_route(write_map(tmp_path, SHORT_ROAD), "S", "E", ROAD_ONLY)

    assert check == RouteCheck(
        ROUTE, ROAD_ONLY, ROAD_ONLY, "Road only has a route from S to E."
    )
    assert searched(searches) == [(routing_policy(ROAD_ONLY), ("a", "E"))]


def test_mixed_over_its_road_budget_changes_to_road_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    searches = record_route_searches(monkeypatch)

    check = check_route(write_map(tmp_path, LONG_ROAD), "S", "E", MIXED)

    assert check == RouteCheck(
        MODE_CHANGED, MIXED, ROAD_ONLY,
        "Mixed has no route from S to E. Mode changed to Road only. "
        "Press Start Simulation to run.",
    )
    assert searched(searches) == [
        (routing_policy(MIXED), None),
        (routing_policy(ROAD_ONLY), ("a", "E")),
    ]


def test_air_lanes_without_a_route_are_no_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The map has air lanes from S and to E, so it offers Air only, but
    they meet at a blocked hub. Mixed is over its budget on the road, so
    the check goes on to Road only."""
    map_file = write_map(tmp_path, AIR_THROUGH_A_BLOCKED_HUB)
    graph = load_scenario_graph(map_file, "S", "E")
    assert available_routing_modes(graph) == (MIXED, ROAD_ONLY, AIR_ONLY)
    searches = record_route_searches(monkeypatch)

    check = check_route(map_file, "S", "E", AIR_ONLY)

    assert (check.status, check.mode) == (MODE_CHANGED, ROAD_ONLY)
    assert searched(searches) == [
        (routing_policy(AIR_ONLY), None),
        (routing_policy(MIXED), None),
        (routing_policy(ROAD_ONLY), ("a", "E")),
    ]


@pytest.mark.parametrize(
    ("text", "requested"),
    [
        pytest.param(SHORT_ROAD, AIR_ONLY, id="road-only-also-has-one"),
        pytest.param(DIRECT_AIR, ROAD_ONLY, id="air-only-also-has-one"),
    ],
)
def test_mixed_is_proposed_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    requested: RoutingMode,
) -> None:
    """Both other modes have a route; Mixed comes first, and the check
    stops there."""
    map_file = write_map(tmp_path, text)
    other = ({MIXED, ROAD_ONLY, AIR_ONLY} - {MIXED, requested}).pop()
    assert check_route(map_file, "S", "E", other).status is ROUTE
    searches = record_route_searches(monkeypatch)

    check = check_route(map_file, "S", "E", requested)

    assert (check.status, check.requested, check.mode) == (
        MODE_CHANGED, requested, MIXED
    )
    assert [policy for policy, _ in searched(searches)] == [
        routing_policy(requested), routing_policy(MIXED)
    ]


@pytest.mark.parametrize("requested", list(RoutingMode))
def test_no_mode_with_a_route_keeps_the_hubs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, requested: RoutingMode
) -> None:
    searches = record_route_searches(monkeypatch)

    check = check_route(write_map(tmp_path, APART), "S", "E", requested)

    assert check == RouteCheck(
        NO_ROUTE, requested, None,
        "No mode has a route from S to E. Choose other hubs.",
    )
    assert [policy for policy, _ in searched(searches)] == [
        routing_policy(requested),
        *(routing_policy(m) for m in RoutingMode if m is not requested),
    ]
    assert all(route is None for _, route in searched(searches))


def test_the_only_mode_without_a_route_is_named(tmp_path: Path) -> None:
    map_file = write_map(
        tmp_path,
        "nb_drones: 1\n"
        "start_hub: S 0 0\n"
        "hub: a 1 0\n"
        "end_hub: E 2 0\n"
        "connection: S-a\n",
    )

    check = check_route(map_file, "S", "E", AIR_ONLY)

    assert check == RouteCheck(
        NO_ROUTE, AIR_ONLY, None,
        "Air only has no route from S to E. Choose other hubs.",
    )


@pytest.mark.parametrize(
    ("start", "end", "requested", "status", "mode"),
    [
        ("Kiel", "Dresden", ROAD_ONLY, ROUTE, ROAD_ONLY),
        ("Kiel", "Dresden", MIXED, ROUTE, MIXED),
        ("Hamburg", "Berlin", AIR_ONLY, ROUTE, AIR_ONLY),
        ("Kiel", "Munich", AIR_ONLY, MODE_CHANGED, MIXED),
        ("Berlin", "Munich", ROAD_ONLY, MODE_CHANGED, MIXED),
    ],
)
def test_germany_routes(
    start: str,
    end: str,
    requested: RoutingMode,
    status: RouteCheckStatus,
    mode: RoutingMode,
) -> None:
    check = check_route(GERMANY, start, end, requested)

    assert (check.status, check.requested, check.mode) == (
        status, requested, mode
    )


@pytest.mark.parametrize(
    ("mode", "pairs"), [(MIXED, 240), (ROAD_ONLY, 78), (AIR_ONLY, 78)]
)
def test_germany_pairs_with_a_route_in_each_mode(
    mode: RoutingMode, pairs: int
) -> None:
    """The counts of the study behind ADR-029; Mixed reaches every pair,
    so every change of mode lands on Mixed."""
    graph, _ = Parser().parse(str(GERMANY))
    checks = [
        check_route(GERMANY, start, end, mode)
        for start, end in permutations(graph.zones, 2)
    ]

    assert sum(check.status is ROUTE for check in checks) == pairs
    assert {check.mode for check in checks} == {mode, MIXED}


def test_europe_keeps_air_only(monkeypatch: pytest.MonkeyPatch) -> None:
    searches = record_route_searches(monkeypatch)

    check = check_route(EUROPE, "Reykjavik", "Milan", AIR_ONLY)

    assert (check.status, check.mode) == (ROUTE, AIR_ONLY)
    assert [policy for policy, _ in searched(searches)] == [
        routing_policy(AIR_ONLY)
    ]


@pytest.mark.parametrize(
    ("map_file", "start", "end", "mode", "message"),
    [
        (EUROPE, "Atlantis", "Milan", AIR_ONLY, "Unknown hub: Atlantis."),
        (EUROPE, "Milan", "Milan", AIR_ONLY,
         "Start and end hubs must be different."),
        (EUROPE, "Reykjavik", "Milan", MIXED,
         "Mixed is not available on this map. Available modes: Air only."),
        (EUROPE, "Reykjavik", "Milan", ROAD_ONLY,
         "Road only is not available on this map. "
         "Available modes: Air only."),
    ],
)
def test_hubs_and_modes_are_checked_as_for_a_run(
    map_file: Path, start: str, end: str, mode: RoutingMode, message: str
) -> None:
    with pytest.raises(ScenarioError) as error:
        check_route(map_file, start, end, mode)

    assert str(error.value) == message


def test_a_blocked_hub_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ScenarioError) as error:
        check_route(write_map(tmp_path, BLOCKED_MAP), "a", "wall", AIR_ONLY)

    assert str(error.value) == "A start or end hub cannot be blocked: wall."


def test_a_map_without_lanes_has_no_mode_to_check(tmp_path: Path) -> None:
    with pytest.raises(ScenarioError) as error:
        check_route(write_map(tmp_path, NO_LANES), "a", "c", AIR_ONLY)

    assert str(error.value) == (
        "Air only is not available on this map. Available modes: none."
    )


def test_the_check_runs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No simulator, no weather and no use of the global random state."""
    def must_not_be_called(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the route check must not start a run")

    monkeypatch.setattr(scenario, "Simulator", must_not_be_called)
    monkeypatch.setattr(scenario, "RandomWeather", must_not_be_called)
    saved = random.getstate()

    for mode in RoutingMode:
        check_route(GERMANY, "Kiel", "Dresden", mode)
    check_route(GERMANY, "Kiel", "Munich", AIR_ONLY)

    assert random.getstate() == saved


def test_each_check_reads_its_own_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The graphs a check loads keep the map's capacities and only the
    chosen hubs as terminals; the map file is only read."""
    loaded: list[Graph] = []
    load = scenario.load_scenario_graph

    def recording_load(map_path: str | Path, start: str, end: str) -> Graph:
        graph = load(map_path, start, end)
        loaded.append(graph)
        return graph

    monkeypatch.setattr(scenario, "load_scenario_graph", recording_load)
    before = hashlib.sha256(GERMANY.read_bytes()).hexdigest()

    check_route(GERMANY, "Kiel", "Munich", AIR_ONLY)
    check_route(GERMANY, "Munich", "Kiel", ROAD_ONLY)

    assert hashlib.sha256(GERMANY.read_bytes()).hexdigest() == before
    assert len(loaded) == 2 and loaded[0] is not loaded[1]
    map_graph, _ = Parser().parse(str(GERMANY))
    for graph, (start, end) in zip(loaded, [("Kiel", "Munich"),
                                            ("Munich", "Kiel")]):
        assert terminals(graph) == ([start], [end])
        for name, zone in graph.zones.items():
            assert zone.max_drones == map_graph.zones[name].max_drones


def test_repeated_checks_agree() -> None:
    first = check_route(GERMANY, "Kiel", "Munich", AIR_ONLY)
    check_route(GERMANY, "Kiel", "Dresden", ROAD_ONLY)
    check_route(EUROPE, "Reykjavik", "Milan", AIR_ONLY)

    assert check_route(GERMANY, "Kiel", "Munich", AIR_ONLY) == first


def test_a_check_changes_no_later_run() -> None:
    """A run after checks is the run without them, and the mode the check
    shows runs to delivery."""
    before = run_with_events(GERMANY, "Kiel", "Munich", 10, 3)

    check = check_route(GERMANY, "Kiel", "Munich", AIR_ONLY)
    check_route(GERMANY, "Kiel", "Dresden", ROAD_ONLY)
    after = run_with_events(GERMANY, "Kiel", "Munich", 10, 3)

    assert after == before
    assert check.mode is MIXED
    shown = run_scenario(GERMANY, "Kiel", "Munich", 10, 3, mode=check.mode)
    assert shown == before[0]
    assert shown.status is ScenarioStatus.DELIVERED


@pytest.mark.parametrize("mode", list(RoutingMode))
def test_no_route_in_the_check_is_no_route_in_the_run(
    tmp_path: Path, mode: RoutingMode
) -> None:
    """The check and the simulator search alike in clear weather."""
    map_file = write_map(tmp_path, APART)

    assert check_route(map_file, "S", "E", mode).status is NO_ROUTE
    result = run_scenario(map_file, "S", "E", 2, 0, mode=mode)
    assert result.status is ScenarioStatus.NO_ROUTE
