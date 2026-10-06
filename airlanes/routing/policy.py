"""Routing policy: limits that routing applies on top of the map.

The map defines which connections exist and how they travel (see
`airlanes.world.transport`). The routing policy decides which of those
journeys routing is willing to choose.
"""

from dataclasses import dataclass

from airlanes.model.connection import Connection
from airlanes.model.transport_mode import TransportMode


@dataclass(frozen=True)
class RoutingPolicy:
    """
    `max_consecutive_road_km`: the longest stretch of consecutive road legs a
    route may contain (ADR-017). An air leg ends the stretch. A road beyond
    the limit may exist; routing just does not choose it.
    """

    max_consecutive_road_km: int = 700

    def road_km_after(
        self, road_km: int, connection: Connection
    ) -> int | None:
        """
        Consecutive road distance after travelling `connection`, or None if
        that would exceed the limit. Air legs, including lanes without a
        distance, reset it to zero.
        """
        if connection.mode is not TransportMode.ROAD:
            return 0
        total = road_km + connection.distance
        if total > self.max_consecutive_road_km:
            return None
        return total
