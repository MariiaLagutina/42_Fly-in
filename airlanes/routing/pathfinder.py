import heapq
import math
from typing import TypeAlias

from airlanes.config import SimulationConfig
from airlanes.model.graph import Graph
from airlanes.model.zone import Zone
from airlanes.routing.policy import RoutingPolicy
from airlanes.world.transport import is_available, travel_time
from airlanes.world.weather import WeatherCondition, WeatherState

TimedPathHeapItem: TypeAlias = tuple[float, int, int, int, Zone, list[Zone]]
RouteHeapItem: TypeAlias = tuple[int, int, int, Zone, list[Zone]]


class Pathfinder:
    """Manages routing algorithms and state-aware path planning."""

    def __init__(
        self, graph: Graph, policy: RoutingPolicy | None = None
    ) -> None:
        self.graph = graph
        self.policy = policy if policy is not None else RoutingPolicy()

    def find_cooperative_path(
        self,
        start: Zone,
        end: Zone,
        reservations: dict[tuple[str, int], int],
        conn_reserv: dict[tuple[str, int], int],
        global_usage: dict[str, int],
    ) -> list[Zone]:
        """
        Calculates optimal conflict-free routes considering constraints.

        A route never returns to a hub it has left: waiting happens in
        place, never through a detour that only passes time (ADR-014,
        DECISION-007).

        A search state is a hub at a turn, together with the consecutive
        road distance driven to reach it. Two partial routes can reach the
        same hub at the same turn with different road distances, and the one
        with less road may continue where the other cannot. A partial route
        is therefore dropped only when another one reached the same hub at
        the same turn with no higher score and no more road.
        """
        if self.find_route(start, end, WeatherState()) is None:
            return []

        reached: dict[tuple[str, int], list[tuple[float, int]]] = {}
        counter = 0
        min_heap: list[TimedPathHeapItem] = [
            (0.0, counter, 0, 0, start, [start])
        ]

        while min_heap:
            score, _, t, road_km, current_zone, path = heapq.heappop(min_heap)

            labels = reached.setdefault((current_zone.name, t), [])
            if any(
                seen_score <= score and seen_road <= road_km
                for seen_score, seen_road in labels
            ):
                continue
            labels.append((score, road_km))

            if current_zone == end:
                return path

            possible_moves = list(self.graph.get_neighbors(current_zone))
            possible_moves.append(current_zone)

            for next_zone in possible_moves:
                if next_zone != current_zone and next_zone in path:
                    continue
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

                next_road_km: int | None = road_km
                if next_zone != current_zone:
                    conn = self.graph.get_connection(current_zone, next_zone)
                    assert conn is not None
                    next_road_km = self.policy.road_km_after(road_km, conn)
                if next_road_km is None:
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
                        next_road_km,
                        next_zone,
                        path + [next_zone],
                    ),
                )

        return []

    def find_route(
        self,
        start: Zone,
        end: Zone,
        weather: WeatherState,
        road_km: int = 0,
        avoid: frozenset[str] = frozenset(),
    ) -> list[Zone] | None:
        """
        Fastest route from `start` to `end` under the given weather, ignoring
        other aircraft. Returns the hubs after `start`, or None if no route
        is available.

        Lanes the weather makes unavailable are not used, and neither are
        routes that break the routing policy's consecutive-road limit.
        `road_km` is the road distance already driven since the last air
        leg. A route never visits a hub twice, nor any hub named in
        `avoid`. As in the cooperative search, a partial route is dropped
        only when another one reached the same hub no later and with no
        more road.
        """
        reached: dict[str, list[tuple[int, int]]] = {}
        counter = 0
        heap: list[RouteHeapItem] = [(0, counter, road_km, start, [start])]

        while heap:
            turns, _, road, zone, path = heapq.heappop(heap)

            labels = reached.setdefault(zone.name, [])
            if any(
                seen_turns <= turns and seen_road <= road
                for seen_turns, seen_road in labels
            ):
                continue
            labels.append((turns, road))

            if zone == end:
                return path[1:]

            for connection in self.graph.connections:
                if not connection.connects(zone):
                    continue
                next_zone = connection.other_end(zone)
                if (
                    not next_zone.is_accessible()
                    or next_zone in path
                    or next_zone.name in avoid
                ):
                    continue
                condition = weather.condition_of(connection.name())
                if not is_available(connection, condition):
                    continue
                next_road = self.policy.road_km_after(road, connection)
                if next_road is None:
                    continue
                counter += 1
                heapq.heappush(
                    heap,
                    (
                        turns + travel_time(connection, next_zone, condition),
                        counter,
                        next_road,
                        next_zone,
                        path + [next_zone],
                    ),
                )

        return None

    def route_travel_time(
        self, start: Zone, route: list[Zone], weather: WeatherState
    ) -> float:
        """
        Turns that the legs of `route` from `start` take under `weather`,
        with travel times from the transport rules, or infinity if the
        weather closes one of them. Planned waits are not legs and add
        nothing.
        """
        total = 0
        current = start
        for zone in route:
            if zone is current:
                continue
            connection = self.graph.get_connection(current, zone)
            assert connection is not None
            condition = weather.condition_of(connection.name())
            if not is_available(connection, condition):
                return math.inf
            total += travel_time(connection, zone, condition)
            current = zone
        return total

    def _calculate_move_cost(self, current_zone: Zone, next_zone: Zone) -> int:
        """Travel time of a planned step. The initial plan is made before the
        first weather is observed, so it is a deterministic clear-weather
        baseline (ADR-021)."""
        if next_zone == current_zone:
            return 1

        # Planned steps come from graph neighbors, so a lane joins them.
        conn = self.graph.get_connection(current_zone, next_zone)
        assert conn is not None

        return travel_time(conn, next_zone, WeatherCondition.CLEAR)

    def reserve_path(
        self,
        path: list[Zone],
        reservations: dict[tuple[str, int], int],
        conn_reserv: dict[tuple[str, int], int],
        global_usage: dict[str, int],
    ) -> None:
        """
        Record a planned route in the reservation tables, with the same
        capacity rules that `_is_move_valid` checks and that the executor
        applies (ADR-008, ADR-019):

        - a hub is held from the turn a leg towards it departs until the
          aircraft leaves it again; a wait holds the hub for one more turn;
        - a lane is held on every turn of a leg, from departure to arrival;
        - a distance lane allows one departure per direction per turn.

        Start and end hubs hold any number of aircraft and are not booked.
        """
        t = 0
        for current_zone, next_zone in zip(path, path[1:]):
            cost = self._calculate_move_cost(current_zone, next_zone)
            if next_zone != current_zone:
                conn = self.graph.get_connection(current_zone, next_zone)
                assert conn is not None
                if conn.distance > 0:
                    key = self._departure_key(conn.name(), current_zone)
                    conn_reserv[(key, t)] = 1
                for tau in range(t, t + cost):
                    conn_reserv[(conn.name(), tau)] = (
                        conn_reserv.get((conn.name(), tau), 0) + 1
                    )
            if not next_zone.is_start and not next_zone.is_end:
                for tau in self._held_turns(
                    current_zone, next_zone, t, cost
                ):
                    reservations[(next_zone.name, tau)] = (
                        reservations.get((next_zone.name, tau), 0) + 1
                    )
                global_usage[next_zone.name] = (
                    global_usage.get(next_zone.name, 0) + 1
                )
            t += cost

    @staticmethod
    def _held_turns(
        current_zone: Zone, next_zone: Zone, t: int, cost: int
    ) -> range:
        """Turns on which a step from turn `t` holds `next_zone`. A leg holds
        its destination from departure, as the executor does (ADR-008)."""
        first = t + 1 if next_zone != current_zone else t + cost
        return range(first, t + cost + 1)

    @staticmethod
    def _departure_key(conn_name: str, origin: Zone) -> str:
        """One departure per distance lane and direction per turn
        (DECISION-008)."""
        return f"{conn_name}_dept_{origin.name}"

    def _is_move_valid(
        self,
        curr_zone: Zone,
        next_zone: Zone,
        t: int,
        move_cost: int,
        reservations: dict[tuple[str, int], int],
        conn_reserv: dict[tuple[str, int], int],
    ) -> bool:
        """Checks if the destination and connections have available capacity
        under the rules of `reserve_path`."""
        capacity = next_zone.effective_capacity()
        for tau in self._held_turns(curr_zone, next_zone, t, move_cost):
            if reservations.get((next_zone.name, tau), 0) >= capacity:
                return False

        if next_zone == curr_zone:
            return True

        conn = self.graph.get_connection(curr_zone, next_zone)
        assert conn is not None

        if conn.distance > 0:
            key = self._departure_key(conn.name(), curr_zone)
            if conn_reserv.get((key, t), 0) > 0:
                return False
        for tau in range(t, t + move_cost):
            reserved = conn_reserv.get((conn.name(), tau), 0)
            if reserved >= conn.max_link_capacity:
                return False

        return True
