"""Departure planning and selection, without running a whole simulation.

Each test places aircraft by hand and checks one rule of the departure
boundary: planned waits, closed lanes, lane capacity shared by both
directions, one departure per direction on a distance lane, and hub load
that counts aircraft flying towards a hub (ADR-019, DECISION-008).
"""

from airlanes.model.connection import Connection
from airlanes.model.drone import Drone, DroneState
from airlanes.model.graph import Graph
from airlanes.model.transport_mode import TransportMode
from airlanes.simulation.departures import (
    plan_departures,
    select_feasible_moves,
)
from airlanes.world.weather import WeatherCondition, WeatherState

from tests.support.graphs import Link, build_graph, end_hub, hub, start_hub

ROAD = TransportMode.ROAD


def aircraft(graph: Graph, drone_id: int, at: str, *path: str) -> Drone:
    drone = Drone(drone_id, graph.zones[at])
    drone.path = [graph.zones[name] for name in path]
    return drone


def labels(moves: list[tuple[Drone, Connection]]) -> list[str]:
    return [drone.label for drone, _connection in moves]


def plan(
    graph: Graph, drones: list[Drone], weather: WeatherState | None = None
) -> list[tuple[Drone, Connection]]:
    return plan_departures(drones, graph, weather or WeatherState(), set())


def test_planned_wait_is_used_up_without_departing() -> None:
    graph = build_graph(
        [start_hub(), end_hub()], [Link("start", "goal")]
    )
    waiting = aircraft(graph, 1, "start", "start", "goal")

    assert plan(graph, [waiting]) == []
    assert waiting.current_zone.name == "start"
    assert [zone.name for zone in waiting.path] == ["goal"]


def test_only_open_lanes_give_candidates() -> None:
    graph = build_graph(
        [start_hub(capacity=2), hub("a"), hub("b"), end_hub()],
        [
            Link("start", "a", distance=450),
            Link("start", "b", distance=150, mode=ROAD),
            Link("a", "goal"),
            Link("b", "goal"),
        ],
    )
    drones = [
        aircraft(graph, 1, "start", "a", "goal"),
        aircraft(graph, 2, "start", "b", "goal"),
    ]
    storm = WeatherState({
        "start-a": WeatherCondition.STORM,
        "start-b": WeatherCondition.STORM,
    })

    assert labels(plan(graph, drones)) == ["D1", "D2"]
    assert labels(plan(graph, drones, storm)) == ["D2"]


def test_aircraft_that_cannot_enter_its_hub_gives_its_lane_back() -> None:
    """D1 gets the one-aircraft lane first but cannot enter `h`, which D2
    holds. D1 is excluded, so D2 takes the same lane in the other direction
    and leaves: both directions share the lane's capacity."""
    graph = build_graph(
        [start_hub(), hub("h"), end_hub()],
        [Link("start", "h"), Link("h", "goal")],
    )
    drones = [
        aircraft(graph, 1, "start", "h", "goal"),
        aircraft(graph, 2, "h", "start"),
    ]
    usage: dict[str, int] = {}

    kept = select_feasible_moves(drones, plan(graph, drones), usage)

    assert labels(kept) == ["D2"]
    assert usage == {"start-h": 1}


def test_distance_lane_allows_one_departure_per_direction() -> None:
    graph = build_graph(
        [start_hub(capacity=2), hub("a", capacity=3), end_hub()],
        [Link("start", "a", capacity=3, distance=450), Link("a", "goal")],
    )
    drones = [
        aircraft(graph, 1, "start", "a"),
        aircraft(graph, 2, "start", "a"),
        aircraft(graph, 3, "a", "start"),
    ]
    usage: dict[str, int] = {}

    kept = select_feasible_moves(drones, plan(graph, drones), usage)

    assert labels(kept) == ["D1", "D3"]
    assert usage == {"start-a": 2}


def test_aircraft_flying_towards_a_hub_hold_its_slot() -> None:
    graph = build_graph(
        [start_hub(), hub("a"), hub("b"), end_hub()],
        [
            Link("start", "a"),
            Link("b", "a", distance=900),
            Link("a", "goal"),
        ],
    )
    arriving = aircraft(graph, 1, "b")
    arriving.state = DroneState.IN_TRANSIT
    arriving.transit_target = graph.zones["a"]
    arriving.transit_connection_name = "b-a"
    arriving.transit_turns_left = 2
    departing = aircraft(graph, 2, "start", "a")
    usage = {"b-a": 1}

    kept = select_feasible_moves(
        [arriving, departing], plan(graph, [arriving, departing]), usage
    )

    assert kept == []
    assert usage == {"b-a": 1}
