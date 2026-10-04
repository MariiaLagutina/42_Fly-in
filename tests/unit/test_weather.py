"""Weather providers and the weather state they produce.

Providers never use the global `random` module: `RandomWeather` owns its
generator, so a seed reproduces a run and no test has to save or restore
global state. The exact sequence of conditions for a seed is an
implementation detail and is not asserted.
"""

import random
from collections.abc import Iterator

import pytest

from connection import Connection
from events import EventDispatcher, SimulationEvent, WeatherChanged
from graph import Graph
from weather import (
    NoWeather,
    RandomWeather,
    ScriptedWeather,
    WeatherCondition,
    WeatherProvider,
    WeatherState,
    WeatherSystem,
)
from zone import Zone

TURNS = 60


def build_graph() -> Graph:
    graph = Graph()
    zones = [Zone(name, index, 0) for index, name in enumerate("abcde")]
    for zone in zones:
        graph.add_zone(zone)
    for zone_a, zone_b in zip(zones, zones[1:]):
        graph.add_connection(Connection(zone_a, zone_b))
    graph.add_connection(Connection(zones[0], zones[-1]))
    return graph


def connection_names(graph: Graph) -> set[str]:
    return {connection.name() for connection in graph.connections}


def run(provider: WeatherProvider, turns: int = TURNS) -> list[WeatherState]:
    return [provider.weather_for_turn(turn) for turn in range(1, turns + 1)]


# --- WeatherState -----------------------------------------------------------


def test_missing_connection_is_clear() -> None:
    state = WeatherState({"a-b": WeatherCondition.STORM})

    assert state.condition_of("a-b") is WeatherCondition.STORM
    assert state.condition_of("b-c") is WeatherCondition.CLEAR


def test_clear_entries_are_not_listed() -> None:
    state = WeatherState({
        "a-b": WeatherCondition.CLEAR,
        "b-c": WeatherCondition.RAIN,
    })

    assert set(state.connection_names) == {"b-c"}
    assert state == WeatherState({"b-c": WeatherCondition.RAIN})


def test_state_is_a_snapshot() -> None:
    conditions = {"a-b": WeatherCondition.SNOW}
    state = WeatherState(conditions)

    conditions["a-b"] = WeatherCondition.CLEAR

    assert state.condition_of("a-b") is WeatherCondition.SNOW


# --- NoWeather --------------------------------------------------------------


def test_no_weather_is_always_clear() -> None:
    assert all(state == WeatherState() for state in run(NoWeather()))


# --- RandomWeather ----------------------------------------------------------


def test_same_seed_gives_the_same_weather() -> None:
    graph = build_graph()

    first = run(RandomWeather(graph, seed=3))
    second = run(RandomWeather(graph, seed=3))

    assert first == second
    assert any(state != WeatherState() for state in first)


def test_random_weather_does_not_use_global_random() -> None:
    graph = build_graph()
    random.seed(1)
    with_seed_1 = run(RandomWeather(graph, seed=0))
    random.seed(2)
    saved = random.getstate()

    with_seed_2 = run(RandomWeather(graph, seed=0))

    assert with_seed_1 == with_seed_2
    assert random.getstate() == saved


def test_zero_storm_chance_keeps_everything_clear() -> None:
    provider = RandomWeather(build_graph(), seed=0, storm_chance=0.0)

    assert all(state == WeatherState() for state in run(provider))


def test_certain_storm_chance_changes_every_connection() -> None:
    graph = build_graph()
    provider = RandomWeather(graph, seed=0, storm_chance=1.0)

    state = provider.weather_for_turn(1)

    assert set(state.connection_names) == connection_names(graph)


def test_random_weather_describes_only_map_connections() -> None:
    graph = build_graph()

    for state in run(RandomWeather(graph, seed=5, storm_chance=0.5)):
        assert set(state.connection_names) <= connection_names(graph)


# --- ScriptedWeather --------------------------------------------------------


def test_scripted_weather_follows_its_schedule() -> None:
    provider = ScriptedWeather({
        2: {"a-b": WeatherCondition.STORM},
        4: {"a-b": WeatherCondition.CLEAR, "b-c": WeatherCondition.RAIN},
    })

    states = run(provider, turns=5)

    assert [s.condition_of("a-b") for s in states] == [
        WeatherCondition.CLEAR,
        WeatherCondition.STORM,
        WeatherCondition.STORM,
        WeatherCondition.CLEAR,
        WeatherCondition.CLEAR,
    ]
    assert states[3].condition_of("b-c") is WeatherCondition.RAIN


def test_scripted_weather_applies_skipped_turns() -> None:
    provider = ScriptedWeather({
        1: {"a-b": WeatherCondition.SNOW},
        2: {"b-c": WeatherCondition.TAILWIND},
    })

    state = provider.weather_for_turn(3)

    assert state == WeatherState({
        "a-b": WeatherCondition.SNOW,
        "b-c": WeatherCondition.TAILWIND,
    })


# --- WeatherSystem (global random) ------------------------------------------
# Still used by the simulator. Its tests save and restore the global random
# state, which they seed.

CLOSING_CONDITIONS = {"storm", "snow"}
KNOWN_CONDITIONS = {"clear", "storm", "snow", "rain", "tailwind"}


class StateCheckingListener:
    """Records weather events and checks them against the live lane state."""

    def __init__(self, graph: Graph) -> None:
        self.connections = {conn.name(): conn for conn in graph.connections}
        self.events: list[WeatherChanged] = []
        self.mismatches: list[WeatherChanged] = []

    def handle(self, event: SimulationEvent) -> None:
        if not isinstance(event, WeatherChanged):
            return
        self.events.append(event)
        connection = self.connections[event.connection_name]
        if (
            connection.weather_condition != event.condition
            or connection.is_open != event.is_open
        ):
            self.mismatches.append(event)


@pytest.fixture(autouse=True)
def restore_global_random() -> Iterator[None]:
    saved_state = random.getstate()
    yield
    random.setstate(saved_state)


@pytest.fixture(params=[0, 1, 2, 3])
def seeded_random(request: pytest.FixtureRequest) -> int:
    """Several seeds, for invariants that should hold on any trajectory."""
    seed: int = request.param
    random.seed(seed)
    return seed


@pytest.fixture
def fixed_seed() -> int:
    """One seed, for checks whose outcome does not depend on the draw."""
    random.seed(0)
    return 0


def run_weather(
    turns: int, storm_chance: float | None = None
) -> tuple[Graph, StateCheckingListener, list[list[tuple[str, bool]]]]:
    """Run the weather system and snapshot every lane after each turn."""
    graph = build_graph()
    dispatcher = EventDispatcher()
    listener = StateCheckingListener(graph)
    dispatcher.add_listener(listener)
    weather = WeatherSystem(graph, dispatcher)
    if storm_chance is not None:
        weather.storm_chance = storm_chance

    snapshots = []
    for turn in range(1, turns + 1):
        weather.update_weather(turn)
        snapshots.append(
            [(conn.weather_condition, conn.is_open)
             for conn in graph.connections]
        )
    return graph, listener, snapshots


def test_zero_storm_chance_keeps_all_lanes_clear() -> None:
    graph, listener, _ = run_weather(TURNS, storm_chance=0.0)

    assert listener.events == []
    for connection in graph.connections:
        assert connection.weather_condition == "clear"
        assert connection.is_open


def test_certain_storm_chance_changes_every_clear_lane(
    seeded_random: int,
) -> None:
    graph, listener, _ = run_weather(1, storm_chance=1.0)

    for connection in graph.connections:
        assert connection.weather_condition != "clear"
    assert {event.connection_name for event in listener.events} == {
        connection.name() for connection in graph.connections
    }


def test_lane_state_matches_its_weather_after_every_turn(
    seeded_random: int,
) -> None:
    """Storm and snow close a lane; every other condition leaves it open."""
    _, _, snapshots = run_weather(TURNS)

    for lanes in snapshots:
        for condition, is_open in lanes:
            assert condition in KNOWN_CONDITIONS
            assert is_open is (condition not in CLOSING_CONDITIONS)


def test_events_match_lane_state_when_dispatched(seeded_random: int) -> None:
    _, listener, _ = run_weather(TURNS)

    assert listener.events, "the seeded run should produce weather changes"
    assert listener.mismatches == []
    for event in listener.events:
        assert event.is_open is (event.condition not in CLOSING_CONDITIONS)


def test_events_carry_the_current_turn_number(fixed_seed: int) -> None:
    graph = build_graph()
    dispatcher = EventDispatcher()
    listener = StateCheckingListener(graph)
    dispatcher.add_listener(listener)
    weather = WeatherSystem(graph, dispatcher)
    weather.storm_chance = 1.0

    weather.update_weather(7)

    assert listener.events
    assert {event.turn_number for event in listener.events} == {7}


def test_runs_without_a_dispatcher(fixed_seed: int) -> None:
    graph = build_graph()
    weather = WeatherSystem(graph)
    weather.storm_chance = 1.0

    weather.update_weather(1)

    for connection in graph.connections:
        assert connection.weather_condition != "clear"
