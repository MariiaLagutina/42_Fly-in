"""Structural deadlock handling on a single turn (ADR-020).

Each test places two aircraft by hand in neighbouring one-slot hubs, each
heading for the other's hub over a lane for one, and calls
`resolve_deadlock` with both as departures that were not kept. The
simulation tests cover how such deadlocks arise; these check what one turn
of handling decides.
"""

import pytest

from airlanes.events import AgentRerouted
from airlanes.model.connection import Connection
from airlanes.model.drone import Drone
from airlanes.model.graph import Graph
from airlanes.model.transport_mode import TransportMode
from airlanes.routing.pathfinder import Pathfinder
from airlanes.simulation.deadlock import DeadlockError, resolve_deadlock
from airlanes.world.weather import WeatherCondition, WeatherState

from tests.support.graphs import Link, build_graph, end_hub, hub, start_hub

ROAD = TransportMode.ROAD
STORM = WeatherCondition.STORM


def swap_with_ways_around(mode: TransportMode = TransportMode.AIR) -> Graph:
    """`a` and `b` share a lane for one; both have their own lane to the
    goal (450 km, of the given mode)."""
    return build_graph(
        [start_hub(), hub("a"), hub("b"), end_hub()],
        [
            Link("start", "a"),
            Link("a", "b"),
            Link("a", "goal", distance=450, mode=mode),
            Link("b", "goal", distance=450, mode=mode),
        ],
    )


def aircraft(graph: Graph, drone_id: int, at: str, *path: str) -> Drone:
    drone = Drone(drone_id, graph.zones[at])
    drone.path = [graph.zones[name] for name in path]
    return drone


def swapping_pair(graph: Graph) -> list[Drone]:
    return [
        aircraft(graph, 1, "a", "b", "goal"),
        aircraft(graph, 2, "b", "a", "goal"),
    ]


def blocked_departures(
    graph: Graph, drones: list[Drone]
) -> list[tuple[Drone, Connection]]:
    moves = []
    for drone in drones:
        next_zone = drone.next_zone()
        assert next_zone is not None
        connection = graph.get_connection(drone.current_zone, next_zone)
        assert connection is not None
        moves.append((drone, connection))
    return moves


def resolve(
    graph: Graph,
    drones: list[Drone],
    weather: WeatherState | None = None,
    candidates: list[Drone] | None = None,
) -> AgentRerouted | None:
    return resolve_deadlock(
        5,
        blocked_departures(
            graph, drones if candidates is None else candidates
        ),
        [],
        drones,
        graph,
        Pathfinder(graph),
        weather or WeatherState(),
    )


def path_names(drone: Drone) -> list[str]:
    return [zone.name for zone in drone.path]


def test_first_aircraft_with_a_way_around_takes_it() -> None:
    """Both have a way around; only D1, first in aircraft order, takes it."""
    graph = swap_with_ways_around()
    d1, d2 = swapping_pair(graph)

    event = resolve(graph, [d1, d2])

    assert event == AgentRerouted(5, "D1", "a", ("goal",), "deadlock")
    assert path_names(d1) == ["goal"]
    assert path_names(d2) == ["a", "goal"]


def test_way_around_is_taken_under_the_current_weather() -> None:
    """A storm closes D1's way around, so D2 takes its own."""
    graph = swap_with_ways_around()
    d1, d2 = swapping_pair(graph)

    event = resolve(graph, [d1, d2], WeatherState({"a-goal": STORM}))

    assert event == AgentRerouted(5, "D2", "b", ("goal",), "deadlock")
    assert path_names(d1) == ["b", "goal"]


def test_aircraft_wait_when_only_clear_weather_opens_a_way() -> None:
    graph = swap_with_ways_around()
    d1, d2 = swapping_pair(graph)
    storm = WeatherState({"a-goal": STORM, "b-goal": STORM})

    assert resolve(graph, [d1, d2], storm) is None
    assert path_names(d1) == ["b", "goal"]
    assert path_names(d2) == ["a", "goal"]


def test_no_way_around_in_any_weather_stops_the_run() -> None:
    """The ways around are roads that the aircraft cannot drive after the
    road they have already driven, whatever the weather."""
    graph = swap_with_ways_around(ROAD)
    d1, d2 = swapping_pair(graph)
    for drone in (d1, d2):
        drone.road_km_since_air = 400

    with pytest.raises(DeadlockError) as error:
        resolve(graph, [d1, d2])

    assert error.value.turn_number == 5
    assert error.value.aircraft == ("D1", "D2")
    assert error.value.hubs == ("a", "b")
    assert str(error.value) == (
        "Deadlock at turn 5: D1, D2 wait for each other at a, b, "
        "and no route avoids it."
    )
    assert path_names(d1) == ["b", "goal"]
    assert path_names(d2) == ["a", "goal"]


def test_waiting_for_an_aircraft_that_is_not_blocked_is_no_deadlock() -> None:
    """D1 waits for D2, but D2 did not try to leave this turn (it may be
    waiting for weather), so nothing is decided: D1 keeps its route even
    though a way around exists."""
    graph = swap_with_ways_around()
    d1, d2 = swapping_pair(graph)

    assert resolve(graph, [d1, d2], candidates=[d1]) is None
    assert path_names(d1) == ["b", "goal"]
