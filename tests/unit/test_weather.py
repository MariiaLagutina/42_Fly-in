"""Weather system: invariants that hold for any random outcome.

Weather draws from the global `random` module, even when no change can
happen. Every test here restores the previous global state afterwards
(`restore_global_random`), and tests that need reproducible randomness seed
it through `seeded_random` or `fixed_seed`, so no test depends on run order.
The exact
sequence of weather events for a seed is an implementation detail and is not
asserted.
"""

import random
from collections.abc import Iterator

import pytest

from connection import Connection
from events import EventDispatcher, SimulationEvent, WeatherChanged
from graph import Graph
from weather import WeatherSystem
from zone import Zone

CLOSING_CONDITIONS = {"storm", "snow"}
KNOWN_CONDITIONS = {"clear", "storm", "snow", "rain", "tailwind"}
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
