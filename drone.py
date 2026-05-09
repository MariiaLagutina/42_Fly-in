from typing import Optional
from zone import Zone


class DroneState:
    WAITING = "waiting"
    MOVING = "moving"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"


class Drone:
    def __init__(self, drone_id: int, start_zone: Zone) -> None:
        self.drone_id = drone_id
        self.current_zone = start_zone
        self.path: list[Zone] = []
        self.state: str = DroneState.WAITING
        self.transit_turns_left: int = 0
        self.transit_target: Optional[Zone] = None

    @property
    def label(self) -> str:
        return f"D{self.drone_id}"

    def is_delivered(self) -> bool:
        return self.state == DroneState.DELIVERED

    def has_path(self) -> bool:
        return len(self.path) > 0

    def next_zone(self) -> Optional[Zone]:
        return self.path[0] if self.path else None

    def advance(self) -> Optional[Zone]:
        if not self.path:
            return None

        self.current_zone = self.path.pop(0)
        return self.current_zone

    def __repr__(self) -> str:
        return (
            f"Drone({self.label}, zone={self.current_zone.name}, "
            f"state={self.state})"
        )
