from enum import Enum
from typing import Optional
from zone import Zone


class DroneState(Enum):
    WAITING = "waiting"
    MOVING = "moving"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"


class Drone:
    """Represents a delivery drone moving through zones."""
    def __init__(self, drone_id: int, start_zone: Zone) -> None:
        self.drone_id = drone_id
        self.current_zone = start_zone
        self.path: list[Zone] = []
        self.state: DroneState = DroneState.WAITING
        self.transit_turns_left: int = 0
        self.transit_target: Optional[Zone] = None
        self.transit_connection_name: Optional[str] = None

    @property
    def label(self) -> str:
        """Return human-readable drone identifier."""
        return f"D{self.drone_id}"

    def is_delivered(self) -> bool:
        """Check if the drone has completed its delivery."""
        return self.state == DroneState.DELIVERED

    def has_path(self) -> bool:
        """Check whether the drone still has planned movement."""
        return len(self.path) > 0

    def next_zone(self) -> Optional[Zone]:
        """Return the next zone in the planned path."""
        return self.path[0] if self.path else None

    def advance(self) -> Optional[Zone]:
        """Move the drone to the next zone in its path."""
        if not self.path:
            return None

        self.current_zone = self.path.pop(0)
        return self.current_zone

    def __repr__(self) -> str:
        """Return a string representation of the drone."""
        return (
            f"Drone({self.label}, zone={self.current_zone.name}, "
            f"state={self.state.value})"
        )
