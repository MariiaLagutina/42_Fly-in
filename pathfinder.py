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
        """
        Finds the shortest path from start to end using Breadth-First Search.
        Used for unweighted graphs or when we want the path with
        the fewest hops, regardless of movement cost.
        """
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
        """
        Finds the lowest-cost path from start to end using Dijkstra's algorithm
        Prioritizes routes based on zone types and applies traffic penalties.
        """
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
        """
        Finds up to n distinct paths from start to end using a modified
        Dijkstra's algorithm. Paths are prioritized based on their total cost,
        which includes zone movement costs and traffic penalties.
        """
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
                    min_heap,
                    (new_cost, counter, path + [neighbor]),
                )

        return found_paths

    def find_cooperative_path(
        self,
        start: Zone,
        end: Zone,
        reservations: dict[tuple[str, int], int],
        conn_reservations: dict[tuple[str, int], int],
        global_usage: dict[str, int],
    ) -> list[Zone]:
        pass

    def _pathfinding_cost(self, zone: Zone) -> float:
        """
        Calculates the cost of moving through a zone,
        including any reservation penalties.
        """
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
