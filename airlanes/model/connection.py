from typing import TYPE_CHECKING

from airlanes.model.transport_mode import TransportMode

if TYPE_CHECKING:
    from airlanes.model.zone import Zone


class Connection:
    """Represents a connection between two zones."""
    def __init__(
        self,
        zone_a: "Zone",
        zone_b: "Zone",
        max_link_capacity: int = 1,
        mode: TransportMode = TransportMode.AIR,
    ) -> None:
        """Initialize connection configuration and state."""
        self.zone_a = zone_a
        self.zone_b = zone_b
        self.max_link_capacity = max_link_capacity
        self.mode = mode
        self.distance: int = 0

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
