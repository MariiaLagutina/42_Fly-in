from airlanes.events import (
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
from airlanes.model.connection import Connection
from airlanes.model.drone import Drone, DroneState
from airlanes.model.graph import Graph
from airlanes.model.transport_mode import TransportMode
from airlanes.model.zone import Zone
from airlanes.results import (
    Arrival,
    Departure,
    Reroute,
    TurnOutcome,
    TurnResult,
)
from airlanes.routing.pathfinder import Pathfinder
from airlanes.routing.policy import RoutingPolicy
from airlanes.simulation.deadlock import resolve_deadlock
from airlanes.simulation.departures import (
    plan_departures,
    select_feasible_moves,
)
from airlanes.world.transport import is_available, travel_time
from airlanes.world.weather import NoWeather, WeatherProvider, WeatherState


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
        self.turns: list[TurnResult] = []
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
        if self.graph.start_zone is self.graph.end_zone:
            raise ValueError("Graph start and end zones must be different.")

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

    def run(self) -> list[TurnResult]:
        """
        Every turn that completes is kept as a `TurnResult`, including turns
        without outcomes (ADR-023, ADR-024): turn numbers run 1, 2, ..., N
        without gaps. A turn interrupted by an exception is not kept. Which
        turns are printed is decided by the output, not here.
        """
        self._assign_paths()
        turn_number = 1
        while not self._all_delivered():
            turn = self._execute_turn(turn_number)
            self.turns.append(turn)
            turn_number += 1
            if turn_number > 10000:
                raise RuntimeError("Simulation exceeded 10000 turns.")
        return self.turns

    def _all_delivered(self) -> bool:
        return all(drone.is_delivered() for drone in self.drones)

    def _execute_turn(self, turn_number: int) -> TurnResult:
        """
        A turn is processed in phases: finish existing transit, let aircraft
        at hubs replace routes that became unusable, plan departures from a
        stable snapshot, keep the moves that fit hub capacity, apply them,
        then look for aircraft that block each other for good.
        """
        outcomes: list[TurnOutcome] = []
        # The same moves in the assignment-style form that `TurnFinished`
        # carries. Kept alongside the outcomes until the event contract is
        # decided (DECISION-012).
        movements: list[tuple[str, str]] = []
        self._emit(TurnStarted(turn_number))
        self._update_weather(turn_number)

        zone_occupancy = self._count_zone_occupancy()
        connection_usage = self._count_active_connection_usage()
        moved_drone_ids: set[int] = set()

        self._finish_in_transit_drones(
            outcomes, movements, turn_number, zone_occupancy, moved_drone_ids
        )
        self._reconsider_routes(outcomes, turn_number, moved_drone_ids)

        candidates = plan_departures(
            self.drones, self.graph, self.weather, moved_drone_ids
        )

        feasible_moves = select_feasible_moves(
            self.drones, candidates, connection_usage
        )

        self._apply_planned_moves(
            outcomes,
            movements,
            turn_number,
            feasible_moves,
            zone_occupancy,
            moved_drone_ids,
        )
        deadlock_reroute = resolve_deadlock(
            turn_number,
            candidates,
            feasible_moves,
            self.drones,
            self.graph,
            self.pathfinder,
            self.weather,
        )
        if deadlock_reroute is not None:
            reroute, event = deadlock_reroute
            outcomes.append(reroute)
            self._emit(event)

        self._emit(TurnFinished(turn_number, tuple(movements)))
        self._emit_capacity_snapshot(
            turn_number, zone_occupancy, connection_usage
        )
        return TurnResult(turn_number, tuple(outcomes))

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
        self,
        outcomes: list[TurnOutcome],
        turn_number: int,
        moved_drone_ids: set[int],
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

            hub = drone.current_zone.name
            old_route = tuple(zone.name for zone in drone.path)
            new_route = tuple(zone.name for zone in route)
            drone.path = route
            outcomes.append(Reroute(drone.label, hub, old_route, new_route))
            self._emit(
                AgentRerouted(
                    turn_number, drone.label, hub, new_route, "weather"
                )
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
        outcomes: list[TurnOutcome],
        movements: list[tuple[str, str]],
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

            # A leg in transit always has its destination and lane: both
            # are set together with the state at departure.
            target = drone.transit_target
            lane = drone.transit_connection_name
            assert target is not None and lane is not None

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
            outcomes.append(Arrival(drone.label, origin, target.name, lane))
            movements.append((drone.label, target.name))
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

    def _apply_planned_moves(
        self,
        outcomes: list[TurnOutcome],
        movements: list[tuple[str, str]],
        turn_number: int,
        planned_moves: list[tuple[Drone, Connection]],
        zone_occupancy: dict[str, int],
        moved_drone_ids: set[int],
    ) -> None:
        """Apply moves already checked by `select_feasible_moves`."""
        for drone, connection in planned_moves:
            # Every kept move was planned from the aircraft's next hub, and
            # no route changes between planning and this point.
            next_zone = drone.next_zone()
            assert next_zone is not None

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

                outcomes.append(
                    Departure(drone.label, origin, next_zone.name, conn_name)
                )
                movements.append((drone.label, conn_name))
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
            assert moved_to is not None

            if moved_to.is_end:
                drone.state = DroneState.DELIVERED
            else:
                drone.state = DroneState.WAITING

            # A leg that takes one turn starts and finishes in this turn.
            leg = (drone.label, origin, moved_to.name, conn_name)
            outcomes.append(Departure(*leg))
            outcomes.append(Arrival(*leg))
            movements.append((drone.label, moved_to.name))
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
            if drone.state != DroneState.IN_TRANSIT:
                continue
            # Counted before this turn's arrivals: a leg in transit has its
            # lane and at least one turn left.
            conn_name = drone.transit_connection_name
            assert conn_name is not None and drone.transit_turns_left > 0
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

    def print_stats(self) -> None:
        print(f"Total turns: {len(self.turns)}")
        for drone in self.drones:
            print(
                f"{drone.label}: Path length={len(drone.path)}, "
                f"Delivered={drone.is_delivered()}"
            )
