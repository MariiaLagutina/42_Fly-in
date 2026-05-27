import heapq
import math
from collections import deque
from typing import TypeAlias
from zone import Zone
from graph import Graph
from config import SimulationConfig

PathHeapItem: TypeAlias = tuple[float, int, Zone, list[Zone]]
TimedPathHeapItem: TypeAlias = tuple[float, int, int, Zone, list[Zone]]


class Pathfinder:
    """Manages routing algorithms and state-aware path planning."""

    def __init__(self, graph: Graph) -> None:
        self.graph = graph

    def find_path_bfs(self, start: Zone, end: Zone) -> list[Zone]:
        """Finds the shortest structural route using BFS without weights."""
        visited = set()
        queue = deque([(start, [start])])

        while queue:
            current_zone, path = queue.popleft()
            if current_zone in visited:
                continue
            visited.add(current_zone)

            if current_zone == end:
                return path

            for neighbor in self.graph.get_neighbors(current_zone):
                if neighbor not in visited:
                    queue.append((neighbor, path + [neighbor]))

        return []

    def find_path_dijkstra(
        self, start: Zone, end: Zone
    ) -> tuple[list[Zone], float]:
        """Calculates the lowest-cost static path using Dijkstra."""
        visited = set()
        counter = 0
        min_heap: list[PathHeapItem] = [(0.0, counter, start, [start])]

        while min_heap:
            cost, _, current_zone, path = heapq.heappop(min_heap)
            if current_zone in visited:
                continue
            visited.add(current_zone)

            if current_zone == end:
                return path, cost

            for neighbor in self.graph.get_neighbors(current_zone):
                if neighbor not in visited:
                    total_cost = cost + self._pathfinding_cost(neighbor)
                    counter += 1
                    heapq.heappush(
                        min_heap,
                        (total_cost, counter, neighbor, path + [neighbor]),
                    )

        return [], SimulationConfig.UNREACHABLE_COST

    def find_multiple_paths(
        self, start: Zone, end: Zone, n: int
    ) -> list[list[Zone]]:
        """Finds up to n distinct paths to distribute drone traffic."""
        if n <= 0:
            return []

        counter = 0
        found_paths: list[list[Zone]] = []
        seen_complete_paths: set[tuple[str, ...]] = set()
        min_heap: list[tuple[float, int, list[Zone]]] = [
            (0.0, counter, [start])
        ]

        while min_heap and len(found_paths) < n:
            cost, _, path = heapq.heappop(min_heap)
            current_zone = path[-1]

            if current_zone == end:
                path_key = tuple(zone.name for zone in path)
                if path_key not in seen_complete_paths:
                    seen_complete_paths.add(path_key)
                    found_paths.append(path)
                continue

            for neighbor in self.graph.get_neighbors(current_zone):
                if neighbor in path:
                    continue

                counter += 1
                new_cost = cost + self._pathfinding_cost(neighbor)
                heapq.heappush(
                    min_heap, (new_cost, counter, path + [neighbor])
                )

        return found_paths

    def find_cooperative_path(
        self,
        start: Zone,
        end: Zone,
        reservations: dict[tuple[str, int], int],
        conn_reserv: dict[tuple[str, int], int],
        global_usage: dict[str, int],
    ) -> list[Zone]:
        """Calculates optimal conflict-free routes considering constraints."""
        if not self.find_path_bfs(start, end):
            return []

        visited: set[tuple[str, int]] = set()
        counter = 0
        min_heap: list[TimedPathHeapItem] = [(0.0, counter, 0, start, [start])]

        while min_heap:
            score, _, t, current_zone, path = heapq.heappop(min_heap)

            state = (current_zone.name, t)
            if state in visited:
                continue
            visited.add(state)

            if current_zone == end:
                return path

            possible_moves = list(self.graph.get_neighbors(current_zone))
            possible_moves.append(current_zone)

            for next_zone in possible_moves:
                move_cost = self._calculate_move_cost(current_zone, next_zone)
                next_t = t + move_cost

                # Reject the move if capacity is exceeded
                if not self._is_move_valid(
                    current_zone,
                    next_zone,
                    t,
                    move_cost,
                    reservations,
                    conn_reserv,
                ):
                    continue

                # Traffic balancing and priority calculations
                priority_discount = (
                    SimulationConfig.PRIORITY_ZONE_DISCOUNT
                    if next_zone.zone_type.name == "PRIORITY"
                    else 0.0
                )

                booked = reservations.get((next_zone.name, next_t), 0)
                hist_traffic = (
                    global_usage.get(next_zone.name, 0)
                    * SimulationConfig.HIST_TRAFFIC_WEIGHT
                )
                curr_traffic = booked * SimulationConfig.CURR_TRAFFIC_WEIGHT

                counter += 1
                sort_time = (
                    score
                    + move_cost
                    - priority_discount
                    + hist_traffic
                    + curr_traffic
                )

                heapq.heappush(
                    min_heap,
                    (
                        sort_time,
                        counter,
                        next_t,
                        next_zone,
                        path + [next_zone],
                    ),
                )

        return []

    def _calculate_move_cost(self, current_zone: Zone, next_zone: Zone) -> int:
        """Calculates travel time based on distance and weather."""
        if next_zone == current_zone:
            return 1

        conn = self.graph.get_connection(current_zone, next_zone)
        if not conn or conn.distance <= 0:
            return int(next_zone.movement_cost())

        if conn.distance < SimulationConfig.AIR_TRAVEL_MIN_DIST:
            cost = math.ceil(conn.distance / SimulationConfig.CAR_SPEED_KMH)
            if conn.weather_condition in ("storm", "snow"):
                cost += SimulationConfig.WEATHER_PENALTY_SEVERE
            elif conn.weather_condition == "rain":
                cost += SimulationConfig.WEATHER_PENALTY_MILD
            return max(1, cost)

        eff_dist = float(conn.distance)
        if conn.weather_condition == "tailwind":
            eff_dist /= SimulationConfig.TAILWIND_DIST_DIVISOR

        cost = math.ceil(eff_dist / SimulationConfig.AIRPLANE_SPEED_KMH)
        return max(1, cost)

    def _is_move_valid(
        self,
        curr_zone: Zone,
        next_zone: Zone,
        t: int,
        move_cost: int,
        reservations: dict[tuple[str, int], int],
        conn_reserv: dict[tuple[str, int], int],
    ) -> bool:
        """Checks if the destination and connections have available capacity"""
        next_t = t + move_cost

        # Check if the destination zone is full when we arrive
        booked = reservations.get((next_zone.name, next_t), 0)
        if booked >= next_zone.effective_capacity():
            return False

        if next_zone == curr_zone:
            return True

        conn = self.graph.get_connection(curr_zone, next_zone)
        if not conn:
            return True

        # Check for mid-air collisions/head-on traffic on the connection
        if conn.distance > 0:
            if conn_reserv.get((f"{conn.name()}_dept", t), 0) > 0:
                return False
            for tau in range(t, t + move_cost):
                reserved = conn_reserv.get((conn.name(), tau), 0)
                if reserved >= conn.max_link_capacity:
                    return False
        else:
            if conn_reserv.get((conn.name(), t), 0) >= conn.max_link_capacity:
                return False

        return True

    def _pathfinding_cost(self, zone: Zone) -> float:
        """Returns the base movement cost plus traffic penalties."""
        reservation_penalty = (
            SimulationConfig.RESERVATION_PENALTY_WEIGHT * zone.reservations
            if hasattr(zone, "reservations")
            else 0
        )
        if zone.zone_type.name == "PRIORITY":
            return (
                SimulationConfig.PRIORITY_ZONE_BASE_COST + reservation_penalty
            )
        return float(zone.movement_cost()) + reservation_penalty

    def heuristic(self, zone: Zone, end: Zone) -> float:
        """Estimates cost using straight-line Euclidean distance."""
        dx = float(zone.x - end.x)
        dy = float(zone.y - end.y)
        return math.sqrt((dx * dx) + (dy * dy))
