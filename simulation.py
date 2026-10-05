from connection import Connection
from drone import Drone, DroneState
from graph import Graph
from pathfinder import Pathfinder
from routing_policy import RoutingPolicy
from transport import TransportMode, is_available, travel_time
from zone import Zone
from weather import NoWeather, WeatherProvider, WeatherState
from events import (
    AgentMoved,
    AgentInTransit,
    AgentRerouted,
    CapacitySnapshot,
    EventDispatcher,
    SimulationEvent,
    TurnFinished,
    TurnStarted,
    WeatherChanged,
)


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


class SimulationTurn:
    def __init__(self, turn_number: int) -> None:
        self.turn_number = turn_number
        self.movements: list[tuple[str, str]] = []

    def add_movement(self, drone_label: str, destination: str) -> None:
        self.movements.append((drone_label, destination))

    def to_output_line(self) -> str:
        return " ".join(
            f"{drone_label}-{destination}"
            for drone_label, destination in self.movements
        )


class Simulator:
    def __init__(
        self,
        graph: Graph,
        nb_drones: int,
        dispatcher: EventDispatcher | None = None,
        weather: WeatherProvider | None = None,
        policy: RoutingPolicy | None = None,
    ) -> None:
        self.graph = graph
        self.nb_drones = nb_drones
        self.dispatcher = dispatcher
        self.weather_provider: WeatherProvider = (
            weather if weather is not None else NoWeather()
        )
        self.weather = WeatherState()
        self.policy = policy if policy is not None else RoutingPolicy()
        self.drones: list[Drone] = []
        self.pathfinder = Pathfinder(graph, self.policy)
        self.turns: list[SimulationTurn] = []
        self._create_drones()

    def _create_drones(self) -> None:
        if self.graph.start_zone is None:
            raise ValueError("Graph has no start zone.")

        for i in range(1, self.nb_drones + 1):
            drone = Drone(i, self.graph.start_zone)
            self.drones.append(drone)

    def _assign_paths(self) -> None:
        if self.graph.start_zone is None or self.graph.end_zone is None:
            raise ValueError("Graph must have start and end zones.")

        reservations: dict[tuple[str, int], int] = {}
        conn_reserv: dict[tuple[str, int], int] = {}
        global_usage: dict[str, int] = {}

        for drone in self.drones:
            path = self.pathfinder.find_cooperative_path(
                self.graph.start_zone,
                self.graph.end_zone,
                reservations,
                conn_reserv,
                global_usage,
            )

            if not path:
                raise RuntimeError(
                    "No valid route found between start and end zones."
                )

            drone.path = path[1:]
            self.pathfinder.reserve_path(
                path, reservations, conn_reserv, global_usage
            )

    def _path_cost(self, path: list[Zone]) -> int:
        return sum(zone.movement_cost() for zone in path[1:])

    def run(self) -> list[SimulationTurn]:
        self._assign_paths()
        turn_number = 1
        while not self._all_delivered():
            turn = self._execute_turn(turn_number)
            if turn.movements:
                self.turns.append(turn)
            turn_number += 1
            if turn_number > 10000:
                raise RuntimeError("Simulation exceeded 10000 turns.")
        return self.turns

    def _all_delivered(self) -> bool:
        return all(drone.is_delivered() for drone in self.drones)

    def _execute_turn(self, turn_number: int) -> SimulationTurn:
        """
        A turn is processed in phases: finish existing transit, let aircraft
        at hubs replace routes that became unusable, plan departures from a
        stable snapshot, keep the moves that fit hub capacity, apply them,
        then look for aircraft that block each other for good.
        """
        turn = SimulationTurn(turn_number)
        self._emit(TurnStarted(turn_number))
        self._update_weather(turn_number)

        zone_occupancy = self._count_zone_occupancy()
        connection_usage = self._count_active_connection_usage()
        moved_drone_ids: set[int] = set()

        self._finish_in_transit_drones(
            turn, turn_number, zone_occupancy, moved_drone_ids
        )
        self._reconsider_routes(turn_number, moved_drone_ids)

        candidates = self._plan_departures(moved_drone_ids)

        feasible_moves = self._select_feasible_moves(
            candidates, connection_usage
        )

        self._apply_planned_moves(
            turn,
            turn_number,
            feasible_moves,
            zone_occupancy,
            moved_drone_ids,
        )
        self._resolve_deadlock(turn_number, candidates, feasible_moves)

        self._emit(TurnFinished(turn_number, tuple(turn.movements)))
        self._emit_capacity_snapshot(
            turn_number, zone_occupancy, connection_usage
        )
        return turn

    def _update_weather(self, turn_number: int) -> None:
        """
        Take this turn's weather from the provider and report every
        connection whose condition changed. Weather can only describe
        connections the map defines.
        """
        weather = self.weather_provider.weather_for_turn(turn_number)
        known = {connection.name() for connection in self.graph.connections}
        unknown = sorted(set(weather.connection_names) - known)
        if unknown:
            raise ValueError(
                f"Weather refers to unknown connections: {', '.join(unknown)}"
            )

        for connection in self.graph.connections:
            name = connection.name()
            condition = weather.condition_of(name)
            if condition is self.weather.condition_of(name):
                continue
            self._emit(
                WeatherChanged(
                    turn_number,
                    name,
                    condition.value,
                    is_available(connection, condition),
                )
            )
        self.weather = weather

    def _reconsider_routes(
        self, turn_number: int, moved_drone_ids: set[int]
    ) -> None:
        """
        Decision point for every aircraft waiting at a hub (ADR-011,
        ADR-018, ADR-021).

        An aircraft reconsiders its route only when the current weather
        makes its remaining route slower than the same route in clear
        weather; a closed leg makes it infinitely slow. Weather that only
        makes other routes faster is no reason to reconsider. The search
        uses the complete current weather, so once triggered it may choose
        a route that a tailwind makes faster. It ignores other aircraft:
        capacity stays the executor's job.

        Reconsidering does not imply rerouting. A route that is still open
        is replaced only by a strictly faster one under the same weather; a
        tie keeps it. A closed route is replaced by any route found. With
        none, the aircraft waits in the hub, which is always safe, and keeps
        its route for when the weather clears. Routes are always planned
        within the consecutive-road limit from the aircraft's current road
        distance. Aircraft in transit are committed to their leg.
        """
        if self.weather == WeatherState():
            return

        end_zone = self.graph.end_zone
        assert end_zone is not None
        for drone in self.drones:
            if (
                drone.is_delivered()
                or drone.state == DroneState.IN_TRANSIT
                or drone.drone_id in moved_drone_ids
            ):
                continue

            current = self.pathfinder.route_travel_time(
                drone.current_zone, drone.path, self.weather
            )
            if not self._weather_slows(drone, current):
                continue

            route = self.pathfinder.find_route(
                drone.current_zone,
                end_zone,
                self.weather,
                drone.road_km_since_air,
            )
            if route is None or self.pathfinder.route_travel_time(
                drone.current_zone, route, self.weather
            ) >= current:
                continue

            drone.path = route
            self._emit(
                AgentRerouted(
                    turn_number,
                    drone.label,
                    drone.current_zone.name,
                    tuple(zone.name for zone in route),
                    "weather",
                )
            )

    def _resolve_deadlock(
        self,
        turn_number: int,
        candidates: list[tuple[Drone, Connection]],
        kept: list[tuple[Drone, Connection]],
    ) -> None:
        """
        Handle a structural deadlock among the aircraft that could not
        leave this turn (ADR-020).

        The first aircraft of the deadlock, in aircraft order, that has a
        route under the current weather avoiding the hub it waits for takes
        it. If none has one now, but one would exist with every lane open,
        the aircraft wait: that check is not a forecast, only a probe of
        whether the topology and the routing policy leave a way out once a
        temporary weather restriction is gone. Otherwise no change of
        weather can help, and the run stops with `DeadlockError`.
        """
        kept_ids = {drone.drone_id for drone, _connection in kept}
        blocked = [
            drone for drone, _connection in candidates
            if drone.drone_id not in kept_ids
        ]
        deadlocked = self._deadlocked_aircraft(blocked)
        if not deadlocked:
            return

        end_zone = self.graph.end_zone
        assert end_zone is not None
        for drone in deadlocked:
            route = self._route_around(drone, end_zone, self.weather)
            if route is not None:
                drone.path = route
                self._emit(
                    AgentRerouted(
                        turn_number,
                        drone.label,
                        drone.current_zone.name,
                        tuple(zone.name for zone in route),
                        "deadlock",
                    )
                )
                return

        if any(
            self._route_around(drone, end_zone, WeatherState()) is not None
            for drone in deadlocked
        ):
            return

        raise DeadlockError(
            turn_number,
            tuple(drone.label for drone in deadlocked),
            tuple(sorted({drone.current_zone.name for drone in deadlocked})),
        )

    def _deadlocked_aircraft(self, blocked: list[Drone]) -> list[Drone]:
        """
        The largest set of blocked aircraft in which everything that blocks
        a member is itself a member: the aircraft in or flying to its full
        destination hub, and the aircraft on its full lane. Nothing outside
        the set can release it. An aircraft waiting for weather, for a
        planned wait, or for an aircraft in transit is never part of it.
        """
        holders: dict[str, list[int]] = {}
        on_lane: dict[str, list[int]] = {}
        for drone in self.drones:
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
            connection = self.graph.get_connection(
                drone.current_zone, next_zone
            )
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
        self, drone: Drone, end_zone: Zone, weather: WeatherState
    ) -> list[Zone] | None:
        """A route to the end that avoids the hub the aircraft waits for."""
        next_zone = drone.next_zone()
        assert next_zone is not None
        return self.pathfinder.find_route(
            drone.current_zone,
            end_zone,
            weather,
            drone.road_km_since_air,
            frozenset({next_zone.name}),
        )

    def _weather_slows(self, drone: Drone, turns_now: float) -> bool:
        """Whether the remaining route, taking `turns_now` turns under the
        current weather, is slower than in clear weather: the trigger for
        reconsidering it (ADR-021)."""
        return turns_now > self.pathfinder.route_travel_time(
            drone.current_zone, drone.path, WeatherState()
        )

    def _finish_in_transit_drones(
        self,
        turn: SimulationTurn,
        turn_number: int,
        zone_occupancy: dict[str, int],
        moved_drone_ids: set[int],
    ) -> None:
        for drone in self.drones:
            if drone.state != DroneState.IN_TRANSIT:
                continue

            drone.transit_turns_left -= 1
            if drone.transit_turns_left > 0:
                continue

            target = drone.transit_target
            if target is None:
                continue

            origin = drone.current_zone.name
            drone.current_zone = target
            drone.transit_target = None
            drone.transit_connection_name = None
            if target.is_end:
                drone.state = DroneState.DELIVERED
            else:
                drone.state = DroneState.WAITING

            zone_occupancy[target.name] = (
                zone_occupancy.get(target.name, 0) + 1
            )
            turn.add_movement(drone.label, target.name)
            self._emit(
                AgentMoved(
                    turn_number,
                    drone.label,
                    origin,
                    target.name,
                    target.is_end,
                )
            )
            moved_drone_ids.add(drone.drone_id)

    def _plan_departures(
        self, moved_drone_ids: set[int]
    ) -> list[tuple[Drone, Connection]]:
        """
        Aircraft that want to leave their hub this turn on an open lane, in
        aircraft order. Planned waits are used up here. No lane capacity or
        departure slot is taken yet: those go only to moves that are
        admitted (DECISION-008).
        """
        candidates: list[tuple[Drone, Connection]] = []

        for drone in self.drones:
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

            connection = self.graph.get_connection(
                drone.current_zone, next_zone
            )
            if connection is None or not is_available(
                connection, self.weather.condition_of(connection.name())
            ):
                continue

            candidates.append((drone, connection))

        return candidates

    def _count_outgoing_by_zone(
        self, planned_moves: list[tuple[Drone, Connection]]
    ) -> dict[str, int]:
        outgoing_counts: dict[str, int] = {}
        for drone, _connection in planned_moves:
            name = drone.current_zone.name
            outgoing_counts[name] = outgoing_counts.get(name, 0) + 1
        return outgoing_counts

    def _select_feasible_moves(
        self,
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
            with_lane = self._assign_lanes(
                candidates, connection_usage, excluded
            )
            kept = self._admit_to_hubs(with_lane)
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
            connection_usage[conn_name] = (
                connection_usage.get(conn_name, 0) + 1
            )
        return kept

    def _assign_lanes(
        self,
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
        self, moves: list[tuple[Drone, Connection]]
    ) -> list[tuple[Drone, Connection]]:
        """
        Keep only the moves whose destination still has room after the turn.

        A hub's load includes aircraft flying towards it: an aircraft on a
        multi-turn leg cannot wait on the connection, so its arrival slot is
        held from departure. A hub is freed only by departures that are kept,
        so rejecting one move can invalidate others; selection repeats until
        no move is rejected. The selection only shrinks, so it terminates.
        """
        load = self._count_hub_load()
        selected = moves

        while True:
            leaving = self._count_outgoing_by_zone(selected)
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

    def _count_hub_load(self) -> dict[str, int]:
        """Aircraft in each hub, plus aircraft flying towards it."""
        load: dict[str, int] = {}
        for drone in self.drones:
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

    def _apply_planned_moves(
        self,
        turn: SimulationTurn,
        turn_number: int,
        planned_moves: list[tuple[Drone, Connection]],
        zone_occupancy: dict[str, int],
        moved_drone_ids: set[int],
    ) -> None:
        """Apply moves already checked by `_select_feasible_moves`."""
        for drone, connection in planned_moves:
            next_zone = drone.next_zone()
            if next_zone is None:
                continue

            current_count = zone_occupancy.get(next_zone.name, 0)
            zone_occupancy[drone.current_zone.name] -= 1
            drone.road_km_since_air = self._road_km_after_departure(
                drone, connection
            )

            conn_name = connection.name()
            # Travel time is fixed at departure, under the current weather.
            transit_time = travel_time(
                connection, next_zone, self.weather.condition_of(conn_name)
            )

            if transit_time > 1:
                origin = drone.current_zone.name
                drone.path.pop(0)
                drone.state = DroneState.IN_TRANSIT
                drone.transit_target = next_zone
                drone.transit_connection_name = conn_name
                drone.transit_turns_left = transit_time - 1

                turn.add_movement(drone.label, conn_name)
                self._emit(
                    AgentInTransit(
                        turn_number,
                        drone.label,
                        origin,
                        conn_name,
                        next_zone.name,
                    )
                )
                moved_drone_ids.add(drone.drone_id)
                continue

            zone_occupancy[next_zone.name] = current_count + 1
            origin = drone.current_zone.name
            moved_to = drone.advance()

            if moved_to is None:
                continue
            if moved_to.is_end:
                drone.state = DroneState.DELIVERED
            else:
                drone.state = DroneState.WAITING

            turn.add_movement(drone.label, moved_to.name)
            self._emit(
                AgentMoved(
                    turn_number,
                    drone.label,
                    origin,
                    moved_to.name,
                    moved_to.is_end,
                )
            )
            moved_drone_ids.add(drone.drone_id)

    def _road_km_after_departure(
        self, drone: Drone, connection: Connection
    ) -> int:
        """Consecutive road distance once the aircraft takes this leg. The
        executor follows routes that respect the limit, so it only records
        the distance here."""
        if connection.mode is TransportMode.ROAD:
            return drone.road_km_since_air + connection.distance
        return 0

    def _emit(self, event: SimulationEvent) -> None:
        if self.dispatcher is not None:
            self.dispatcher.dispatch(event)

    def _count_zone_occupancy(self) -> dict[str, int]:
        zone_occupancy: dict[str, int] = {}
        for drone in self.drones:
            if drone.is_delivered() or drone.state == DroneState.IN_TRANSIT:
                continue
            name = drone.current_zone.name
            zone_occupancy[name] = zone_occupancy.get(name, 0) + 1
        return zone_occupancy

    def _count_active_connection_usage(self) -> dict[str, int]:
        connection_usage: dict[str, int] = {}
        for drone in self.drones:
            if (
                drone.state == DroneState.IN_TRANSIT
                and drone.transit_connection_name is not None
                and drone.transit_turns_left > 0
            ):
                conn_name = drone.transit_connection_name
                connection_usage[conn_name] = (
                    connection_usage.get(conn_name, 0) + 1
                )
        return connection_usage

    def _emit_capacity_snapshot(
        self,
        turn_number: int,
        zone_occupancy: dict[str, int],
        connection_usage: dict[str, int],
    ) -> None:
        if self.dispatcher is None:
            return

        zone_usage = tuple(
            (
                zone.name,
                zone_occupancy.get(zone.name, 0),
                zone.effective_capacity(),
            )
            for zone in self.graph.zones.values()
        )
        link_usage = tuple(
            (
                connection.name(),
                connection_usage.get(connection.name(), 0),
                connection.max_link_capacity,
            )
            for connection in self.graph.connections
        )
        self._emit(CapacitySnapshot(turn_number, zone_usage, link_usage))

    def print_results(self) -> None:
        for turn in self.turns:
            print(turn.to_output_line())

    def print_stats(self) -> None:
        print(f"Total turns: {len(self.turns)}")
        for drone in self.drones:
            print(
                f"{drone.label}: Path length={len(drone.path)}, "
                f"Delivered={drone.is_delivered()}"
            )
