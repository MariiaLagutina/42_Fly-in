"""Structural deadlocks: aircraft that block each other for good (ADR-020).

After the turn's departures are applied, the aircraft that could not leave
are checked for a deadlock. One of them takes a way around if there is one
now; if there is one only once the weather clears, they wait; otherwise the
run stops with `DeadlockError`. Resolving a deadlock replaces the route of
the aircraft that takes a way around, and returns the event that reports it
for the simulator to emit.
"""

from airlanes.model.connection import Connection
from airlanes.model.drone import Drone, DroneState
from airlanes.model.graph import Graph
from airlanes.model.zone import Zone
from airlanes.routing.pathfinder import Pathfinder
from airlanes.world.weather import WeatherState
from airlanes.events import AgentRerouted


class DeadlockError(RuntimeError):
    """Aircraft block each other for good: none of them can move, and no
    route avoids the hub it waits for, whatever the weather (ADR-020)."""

    def __init__(
        self,
        turn_number: int,
        aircraft: tuple[str, ...],
        hubs: tuple[str, ...],
    ) -> None:
        self.turn_number = turn_number
        self.aircraft = aircraft
        self.hubs = hubs
        super().__init__(
            f"Deadlock at turn {turn_number}: {', '.join(aircraft)} wait "
            f"for each other at {', '.join(hubs)}, and no route avoids it."
        )


def resolve_deadlock(
    turn_number: int,
    candidates: list[tuple[Drone, Connection]],
    kept: list[tuple[Drone, Connection]],
    drones: list[Drone],
    graph: Graph,
    pathfinder: Pathfinder,
    weather: WeatherState,
) -> AgentRerouted | None:
    """
    Handle a structural deadlock among the aircraft that could not
    leave this turn (ADR-020).

    The first aircraft of the deadlock, in aircraft order, that has a
    route under the current weather avoiding the hub it waits for takes
    it: its `path` is replaced, and the reroute event is returned. If none
    has one now, but one would exist with every lane open, the aircraft
    wait: that check is not a forecast, only a probe of whether the
    topology and the routing policy leave a way out once a temporary
    weather restriction is gone. Otherwise no change of weather can help,
    and the run stops with `DeadlockError`.
    """
    kept_ids = {drone.drone_id for drone, _connection in kept}
    blocked = [
        drone for drone, _connection in candidates
        if drone.drone_id not in kept_ids
    ]
    deadlocked = _deadlocked_aircraft(drones, graph, blocked)
    if not deadlocked:
        return None

    end_zone = graph.end_zone
    assert end_zone is not None
    for drone in deadlocked:
        route = _route_around(pathfinder, drone, end_zone, weather)
        if route is not None:
            drone.path = route
            return AgentRerouted(
                turn_number,
                drone.label,
                drone.current_zone.name,
                tuple(zone.name for zone in route),
                "deadlock",
            )

    if any(
        _route_around(pathfinder, drone, end_zone, WeatherState()) is not None
        for drone in deadlocked
    ):
        return None

    raise DeadlockError(
        turn_number,
        tuple(drone.label for drone in deadlocked),
        tuple(sorted({drone.current_zone.name for drone in deadlocked})),
    )


def _deadlocked_aircraft(
    drones: list[Drone], graph: Graph, blocked: list[Drone]
) -> list[Drone]:
    """
    The largest set of blocked aircraft in which everything that blocks
    a member is itself a member: the aircraft in or flying to its full
    destination hub, and the aircraft on its full lane. Nothing outside
    the set can release it. An aircraft waiting for weather, for a
    planned wait, or for an aircraft in transit is never part of it.
    """
    holders: dict[str, list[int]] = {}
    on_lane: dict[str, list[int]] = {}
    for drone in drones:
        if drone.is_delivered():
            continue
        hub = drone.current_zone
        if drone.state == DroneState.IN_TRANSIT:
            assert drone.transit_target is not None
            hub = drone.transit_target
            if drone.transit_connection_name is not None:
                on_lane.setdefault(
                    drone.transit_connection_name, []
                ).append(drone.drone_id)
        holders.setdefault(hub.name, []).append(drone.drone_id)

    blockers: dict[int, set[int]] = {}
    for drone in blocked:
        next_zone = drone.next_zone()
        if next_zone is None:
            continue
        connection = graph.get_connection(drone.current_zone, next_zone)
        assert connection is not None
        waits_for: set[int] = set()
        in_hub = holders.get(next_zone.name, [])
        if len(in_hub) >= next_zone.effective_capacity():
            waits_for.update(in_hub)
        on_connection = on_lane.get(connection.name(), [])
        if len(on_connection) >= connection.max_link_capacity:
            waits_for.update(on_connection)
        blockers[drone.drone_id] = waits_for

    members = set(blockers)
    changed = True
    while changed:
        changed = False
        for drone_id in sorted(members):
            waits_for = blockers[drone_id]
            if not waits_for or not waits_for <= members:
                members.discard(drone_id)
                changed = True
    return [drone for drone in blocked if drone.drone_id in members]


def _route_around(
    pathfinder: Pathfinder,
    drone: Drone,
    end_zone: Zone,
    weather: WeatherState,
) -> list[Zone] | None:
    """A route to the end that avoids the hub the aircraft waits for."""
    next_zone = drone.next_zone()
    assert next_zone is not None
    return pathfinder.find_route(
        drone.current_zone,
        end_zone,
        weather,
        drone.road_km_since_air,
        frozenset({next_zone.name}),
    )
