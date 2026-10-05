"""Departures: which aircraft leave their hub this turn.

Departures are chosen in two steps. Planning collects the aircraft that want
to leave on an open lane, in aircraft order. Selection then hands out lane
capacity and departure slots and keeps only the moves that fit their
destination hubs (ADR-019, DECISION-008). The simulator applies the kept
moves.
"""

from airlanes.model.connection import Connection
from airlanes.model.drone import Drone, DroneState
from airlanes.model.graph import Graph
from airlanes.world.transport import is_available
from airlanes.world.weather import WeatherState


def plan_departures(
    drones: list[Drone],
    graph: Graph,
    weather: WeatherState,
    moved_drone_ids: set[int],
) -> list[tuple[Drone, Connection]]:
    """
    Aircraft that want to leave their hub this turn on an open lane, in
    aircraft order. Planned waits are used up here. No lane capacity or
    departure slot is taken yet: those go only to moves that are
    admitted (DECISION-008).
    """
    candidates: list[tuple[Drone, Connection]] = []

    for drone in drones:
        if (
            drone.is_delivered()
            or drone.state == DroneState.IN_TRANSIT
            or drone.drone_id in moved_drone_ids
            or not drone.has_path()
        ):
            continue

        next_zone = drone.next_zone()
        if next_zone is None:
            continue

        if next_zone.name == drone.current_zone.name:
            drone.advance()
            continue

        connection = graph.get_connection(drone.current_zone, next_zone)
        if connection is None or not is_available(
            connection, weather.condition_of(connection.name())
        ):
            continue

        candidates.append((drone, connection))

    return candidates


def _count_outgoing_by_zone(
    planned_moves: list[tuple[Drone, Connection]]
) -> dict[str, int]:
    outgoing_counts: dict[str, int] = {}
    for drone, _connection in planned_moves:
        name = drone.current_zone.name
        outgoing_counts[name] = outgoing_counts.get(name, 0) + 1
    return outgoing_counts


def select_feasible_moves(
    drones: list[Drone],
    candidates: list[tuple[Drone, Connection]],
    connection_usage: dict[str, int],
) -> list[tuple[Drone, Connection]]:
    """
    Choose this turn's departures from the candidates.

    Lanes are handed out in aircraft order: lane capacity, and the one
    departure slot of a distance lane. The moves that got a lane must
    then fit their destination hubs. A move that holds a lane but cannot
    enter its hub gives the lane back: it is excluded for this turn and
    lanes are handed out again, so another aircraft can use that lane.
    Each round excludes one move, so selection ends after at most as
    many rounds as there are candidates. Kept moves are added to
    `connection_usage`.
    """
    excluded: set[int] = set()
    while True:
        with_lane = _assign_lanes(candidates, connection_usage, excluded)
        kept = _admit_to_hubs(drones, with_lane)
        if len(kept) == len(with_lane):
            break
        kept_ids = {drone.drone_id for drone, _connection in kept}
        first_rejected = next(
            drone
            for drone, _connection in with_lane
            if drone.drone_id not in kept_ids
        )
        excluded.add(first_rejected.drone_id)

    for _drone, connection in kept:
        conn_name = connection.name()
        connection_usage[conn_name] = connection_usage.get(conn_name, 0) + 1
    return kept


def _assign_lanes(
    candidates: list[tuple[Drone, Connection]],
    connection_usage: dict[str, int],
    excluded: set[int],
) -> list[tuple[Drone, Connection]]:
    """Candidates that get room on their lane, in aircraft order,
    counting aircraft already on the lane."""
    used = dict(connection_usage)
    departed: set[str] = set()
    with_lane: list[tuple[Drone, Connection]] = []
    for drone, connection in candidates:
        if drone.drone_id in excluded:
            continue
        conn_name = connection.name()
        if used.get(conn_name, 0) >= connection.max_link_capacity:
            continue
        if connection.distance > 0:
            # One departure per direction per turn (DECISION-008).
            direction = f"{conn_name}:{drone.current_zone.name}"
            if direction in departed:
                continue
            departed.add(direction)
        used[conn_name] = used.get(conn_name, 0) + 1
        with_lane.append((drone, connection))
    return with_lane


def _admit_to_hubs(
    drones: list[Drone], moves: list[tuple[Drone, Connection]]
) -> list[tuple[Drone, Connection]]:
    """
    Keep only the moves whose destination still has room after the turn.

    A hub's load includes aircraft flying towards it: an aircraft on a
    multi-turn leg cannot wait on the connection, so its arrival slot is
    held from departure. A hub is freed only by departures that are kept,
    so rejecting one move can invalidate others; selection repeats until
    no move is rejected. The selection only shrinks, so it terminates.
    """
    load = _count_hub_load(drones)
    selected = moves

    while True:
        leaving = _count_outgoing_by_zone(selected)
        admitted: dict[str, int] = {}
        kept: list[tuple[Drone, Connection]] = []

        for drone, connection in selected:
            next_zone = drone.next_zone()
            if next_zone is None:
                continue
            name = next_zone.name
            used = (
                load.get(name, 0)
                - leaving.get(name, 0)
                + admitted.get(name, 0)
            )
            if used >= next_zone.effective_capacity():
                continue
            admitted[name] = admitted.get(name, 0) + 1
            kept.append((drone, connection))

        if len(kept) == len(selected):
            return kept
        selected = kept


def _count_hub_load(drones: list[Drone]) -> dict[str, int]:
    """Aircraft in each hub, plus aircraft flying towards it."""
    load: dict[str, int] = {}
    for drone in drones:
        if drone.is_delivered():
            continue
        hub = drone.current_zone
        if (
            drone.state == DroneState.IN_TRANSIT
            and drone.transit_target is not None
        ):
            hub = drone.transit_target
        load[hub.name] = load.get(hub.name, 0) + 1
    return load
