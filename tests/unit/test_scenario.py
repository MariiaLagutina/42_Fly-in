"""Scenarios (ADR-029): chosen start and end hubs on a fresh graph, the
vehicle count, and runs with typed results."""

import hashlib
from itertools import permutations
import math
from pathlib import Path
import sys

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
from airlanes.scenario import (
    DEFAULT_VEHICLE_COUNT,
    MAX_VEHICLE_COUNT,
    MIN_VEHICLE_COUNT,
    ScenarioError,
    ScenarioResult,
    ScenarioStatus,
    load_scenario_graph,
    normalize_vehicle_count,
    run_scenario,
)
from airlanes.world.weather import (
    RandomWeather,
    ScriptedWeather,
    WeatherCondition,
)

from tests.support.simulation import (
    EventRecorder,
    check_invariants,
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
