"""Routing policy: limits that routing applies on top of the map.

The map defines which connections exist and how they travel (see
`airlanes.world.transport`). The routing policy decides which of those
journeys routing is willing to choose: which transport modes it may use,
and how much consecutive road a route may contain.

Both route searches ask `road_km_after` about every lane they consider and
skip the lane when it answers None, so the policy's rules live only here.
They assume one lane between two hubs, as the map format guarantees: a
route is a sequence of hubs, and the lane between two of them is found
again by its ends.
"""

from dataclasses import dataclass, field

from airlanes.model.connection import Connection
from airlanes.model.transport_mode import TransportMode


@dataclass(frozen=True)
class RoutingPolicy:
    """
    `max_consecutive_road_km`: the longest stretch of consecutive road legs a
    route may contain (ADR-017), or None for no limit (ADR-029). An air leg
    ends the stretch. A road beyond the limit may exist; routing just does
    not choose it.

    `transport_modes`: the modes of the lanes routing may use (ADR-029). A
    lane of another mode stays in the graph; routing just does not choose
    it. The default policy, every mode with a 700 km limit, is the policy
    of the CLI.
    """

    max_consecutive_road_km: int | None = 700
    transport_modes: frozenset[TransportMode] = frozenset(TransportMode)
    # Whether some mode is excluded; when none is, `road_km_after` skips
    # the mode test, which runs for every lane a search considers.
    _restricted: bool = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.transport_modes:
            raise ValueError("A routing policy needs at least one mode.")
        limit = self.max_consecutive_road_km
        if limit is not None and limit < 0:
            raise ValueError(
                f"The consecutive-road limit must not be negative: {limit}."
            )
        restricted = self.transport_modes != frozenset(TransportMode)
        object.__setattr__(self, "_restricted", restricted)

    def allows(self, connection: Connection) -> bool:
        """Whether routing may use a lane of this connection's mode."""
        return connection.mode in self.transport_modes

    def road_km_after(
        self, road_km: int, connection: Connection
    ) -> int | None:
        """
        Consecutive road distance after travelling `connection`, or None if
        routing may not take it: its mode is not permitted, or it would
        exceed the limit. Air legs, including lanes without a distance,
        reset it to zero.
        """
        if self._restricted and not self.allows(connection):
            return None
        if connection.mode is not TransportMode.ROAD:
            return 0
        total = road_km + connection.distance
        limit = self.max_consecutive_road_km
        if limit is not None and total > limit:
            return None
        return total
