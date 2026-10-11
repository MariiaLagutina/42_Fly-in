from typing import TYPE_CHECKING

from airlanes.model.transport_mode import TransportMode

if TYPE_CHECKING:
    from airlanes.model.zone import Zone


# Attributes fixed once a connection is created.
_ENDPOINTS = frozenset({"zone_a", "zone_b"})


class Connection:
    """
    Represents a connection between two zones.

    Its endpoints are fixed once it is created: the graph indexes its lanes
    by hub (ADR-027), so reassigning or deleting `zone_a` or `zone_b`
    raises `AttributeError`. Capacity, mode and distance can still be set
    after creation. Attributes live in slots, so a connection has no
    `__dict__` and takes no attributes beyond these five; reading them
    stays a plain slot access, which a guard on a `__dict__` would slow
    down (ADR-027).
    """

    __slots__ = ("zone_a", "zone_b", "max_link_capacity", "mode", "distance")

    zone_a: "Zone"
    zone_b: "Zone"
    max_link_capacity: int
    mode: TransportMode
    distance: int

    def __init__(
        self,
        zone_a: "Zone",
        zone_b: "Zone",
        max_link_capacity: int = 1,
        mode: TransportMode = TransportMode.AIR,
    ) -> None:
        """Initialize connection configuration and state."""
        # Set directly, past the endpoint guard of `__setattr__`.
        object.__setattr__(self, "zone_a", zone_a)
        object.__setattr__(self, "zone_b", zone_b)
        object.__setattr__(self, "max_link_capacity", max_link_capacity)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "distance", 0)

    def __setattr__(self, name: str, value: object) -> None:
        if name in _ENDPOINTS and hasattr(self, name):
            raise AttributeError(
                f"A connection's {name} cannot change after it is created."
            )
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        if name in _ENDPOINTS:
            raise AttributeError(
                f"A connection's {name} cannot be deleted."
            )
        object.__delattr__(self, name)

    def connects(self, zone: "Zone") -> bool:
        """Check if the connection connects to the given zone."""
        return zone == self.zone_a or zone == self.zone_b

    def other_end(self, zone: "Zone") -> "Zone":
        """Return the zone on the other end of the connection."""
        if zone == self.zone_a:
            return self.zone_b
        elif zone == self.zone_b:
            return self.zone_a
        else:
            raise ValueError(
                f"Zone {zone.name} is not connected by this connection."
            )

    def name(self) -> str:
        """Return the name of the connection."""
        return f"{self.zone_a.name}-{self.zone_b.name}"

    def __repr__(self) -> str:
        """Return a string representation of the connection."""
        return f"Connection({self.zone_a.name}, {self.zone_b.name})"
