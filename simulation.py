import math

from connection import Connection
from drone import Drone, DroneState
from graph import Graph
from pathfinder import Pathfinder
from zone import Zone
from weather import WeatherSystem
from events import (
    AgentMoved,
    AgentRefueling,
    CapacitySnapshot,
    EventDispatcher,
    SimulationEvent,
    TurnFinished,
    TurnStarted,
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
        enable_dynamic_weather: bool = False,
    ) -> None:
        self.graph = graph
        self.nb_drones = nb_drones
        self.dispatcher = dispatcher
        self.enable_dynamic_weather = enable_dynamic_weather
        self.drones: list[Drone] = []
        self.pathfinder = Pathfinder(graph)
        self.weather_system = WeatherSystem(graph, dispatcher)
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

            drone.path = path[1:] if path else []
            t = 0
            for i in range(len(path) - 1):
                z_curr, z_next = path[i], path[i + 1]

                if z_next == z_curr:
                    cost = 1
                else:
                    conn = self.graph.get_connection(z_curr, z_next)
                    if conn and conn.distance > 0:
                        if conn.distance < 200:
                            cost = math.ceil(conn.distance / 100.0)
                            if self.enable_dynamic_weather:
                                if conn.weather_condition in ("storm", "snow"):
                                    cost += 2
                                elif conn.weather_condition == "rain":
                                    cost += 1
                            cost = max(1, cost)
                        else:
                            eff_dist = float(conn.distance)
                            if (
                                self.enable_dynamic_weather
                                and conn.weather_condition == "tailwind"
                            ):
                                eff_dist /= 2.0
                            cost = max(1, math.ceil(eff_dist / 400.0))
                    else:
                        cost = z_next.movement_cost()

                if z_next != z_curr:
                    conn = self.graph.get_connection(z_curr, z_next)
                    if conn:
                        if conn.distance > 0:
                            conn_reserv[(f"{conn.name()}_dept", t)] = 1
                        for tau in range(t, t + cost):
                            conn_reserv[(conn.name(), tau)] = (
                                conn_reserv.get((conn.name(), tau), 0) + 1
                            )

                t += cost
                if not z_next.is_start and not z_next.is_end:
                    reservations[(z_next.name, t)] = reservations.get(
                        (z_next.name, t), 0
                    ) + 1
                    global_usage[z_next.name] = global_usage.get(
                        z_next.name, 0
                    ) + 1

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
        turn = SimulationTurn(turn_number)
        self._emit(TurnStarted(turn_number))
        if self.enable_dynamic_weather:
            self.weather_system.update_weather(turn_number)

        zone_occupancy = self._count_zone_occupancy()
        connection_usage = self._count_active_connection_usage()
        moved_drone_ids: set[int] = set()
        planned_moves: list[tuple[Drone, Connection]] = []
        departed_this_turn: set[str] = set()

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
            if connection is None or not connection.is_open:
                continue

            conn_name = connection.name()
            used = connection_usage.get(conn_name, 0)
            if used >= connection.max_link_capacity:
                continue

            if connection.distance > 0 and conn_name in departed_this_turn:
                continue

            connection_usage[conn_name] = used + 1
            if connection.distance > 0:
                departed_this_turn.add(conn_name)
            planned_moves.append((drone, connection))

        outgoing_counts: dict[str, int] = {}
        for drone, _connection in planned_moves:
            name = drone.current_zone.name
            outgoing_counts[name] = outgoing_counts.get(name, 0) + 1

        incoming_counts: dict[str, int] = {}
        for drone, connection in planned_moves:
            next_zone = drone.next_zone()
            if next_zone is None:
                continue

            current_count = zone_occupancy.get(next_zone.name, 0)
            outgoing = outgoing_counts.get(next_zone.name, 0)
            incoming = incoming_counts.get(next_zone.name, 0)
            available_count = current_count - outgoing + incoming

            if available_count >= next_zone.effective_capacity():
                continue

            zone_occupancy[drone.current_zone.name] -= 1
            transit_time = self._calculate_transit_time(next_zone, connection)
            conn_name = connection.name()

            if transit_time > 1:
                origin = drone.current_zone.name
                drone.path.pop(0)
                drone.state = DroneState.IN_TRANSIT
                drone.transit_target = next_zone
                drone.transit_connection_name = conn_name
                drone.transit_turns_left = transit_time - 1

                turn.add_movement(drone.label, conn_name)
                self._emit(
                    AgentRefueling(
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
            incoming_counts[next_zone.name] = incoming + 1
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

        self._emit(TurnFinished(turn_number, tuple(turn.movements)))
        self._emit_capacity_snapshot(
            turn_number, zone_occupancy, connection_usage
        )
        return turn

    def _calculate_transit_time(
        self, next_zone: Zone, connection: Connection
    ) -> int:
        if connection.distance > 0:
            if connection.distance < 200:
                base_turns = math.ceil(connection.distance / 100.0)
                if self.enable_dynamic_weather:
                    if connection.weather_condition in ("storm", "snow"):
                        base_turns += 2
                    elif connection.weather_condition == "rain":
                        base_turns += 1
                return max(1, base_turns)

            eff_distance = float(connection.distance)
            if (
                self.enable_dynamic_weather
                and connection.weather_condition == "tailwind"
            ):
                eff_distance /= 2.0
            return max(1, math.ceil(eff_distance / 400.0))

        base_time = next_zone.movement_cost()
        if not self.enable_dynamic_weather:
            return base_time

        if connection.weather_condition == "tailwind":
            return max(1, base_time - 1)
        elif connection.weather_condition == "rain":
            return base_time + 1

        return base_time

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
