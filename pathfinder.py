import heapq
import math
from collections import deque
from typing import TypeAlias
from zone import Zone
from graph import Graph

PathHeapItem: TypeAlias = tuple[float, int, Zone, list[Zone]]
TimedPathHeapItem: TypeAlias = tuple[float, int, int, Zone, list[Zone]]


class Pathfinder:
    def __init__(self, graph: Graph) -> None:
        self.graph = graph

    def find_path_bfs(self, start: Zone, end: Zone) -> list[Zone]:
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

        return [], 999999

    def find_multiple_paths(
        self, start: Zone, end: Zone, n: int
    ) -> list[list[Zone]]:
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
        visited: set[tuple[str, int]] = set()
        counter = 0
        min_heap: list[TimedPathHeapItem] = [
            (0.0, counter, 0, start, [start])
        ]

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
                if next_zone == current_zone:
                    move_cost = 1
                else:
                    conn = self.graph.get_connection(current_zone, next_zone)
                    if conn and conn.distance > 0:
                        if conn.distance < 200:
                            # Car mode: base speed is 100 km/h.
                            move_cost = math.ceil(conn.distance / 100.0)
                            if conn.weather_condition in ("storm", "snow"):
                                move_cost += 2
                            elif conn.weather_condition == "rain":
                                move_cost += 1
                            move_cost = max(1, move_cost)
                        else:
                            # Airplane mode: base speed is 400 km/h.
                            eff_dist = float(conn.distance)
                            if conn.weather_condition == "tailwind":
                                eff_dist /= 2.0
                            move_cost = max(1, math.ceil(eff_dist / 400.0))
                    else:
                        move_cost = next_zone.movement_cost()

                next_t = t + move_cost
                priority_discount = (
                    0.1 if next_zone.zone_type.name == "PRIORITY" else 0.0
                )

                booked_zone = reservations.get((next_zone.name, next_t), 0)
                if booked_zone >= next_zone.effective_capacity():
                    continue

                if next_zone != current_zone:
                    conn = self.graph.get_connection(current_zone, next_zone)
                    if conn:
                        if conn.distance > 0:
                            if (
                                conn_reserv.get((f"{conn.name()}_dept", t), 0)
                                > 0
                            ):
                                continue
                            conflict = False
                            for tau in range(t, t + move_cost):
                                if (
                                    conn_reserv.get((conn.name(), tau), 0)
                                    >= conn.max_link_capacity
                                ):
                                    conflict = True
                                    break
                            if conflict:
                                continue
                        else:
                            if (
                                conn_reserv.get((conn.name(), t), 0)
                                >= conn.max_link_capacity
                            ):
                                continue

                hist_traffic = global_usage.get(next_zone.name, 0) * 0.01
                curr_traffic = booked_zone * 0.02

                counter += 1
                traffic = hist_traffic + curr_traffic
                sort_time = score + move_cost - priority_discount + traffic

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

    def _pathfinding_cost(self, zone: Zone) -> float:
        reservation_penalty = (
            0.1 * zone.reservations if hasattr(zone, "reservations") else 0
        )
        if zone.zone_type.name == "PRIORITY":
            return 0.5 + reservation_penalty
        return float(zone.movement_cost()) + reservation_penalty

    def heuristic(self, zone: Zone, end: Zone) -> float:
        dx = float(zone.x - end.x)
        dy = float(zone.y - end.y)
        return math.sqrt((dx * dx) + (dy * dy))
