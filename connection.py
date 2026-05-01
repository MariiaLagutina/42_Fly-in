from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zone import Zone


class Connection:
    def __init__(
        self,
        zone_a: "Zone",
        zone_b: "Zone",
        max_link_capacity: int = 1,
    ) -> None:
        self.zone_a = zone_a
        self.zone_b = zone_b
        self.max_link_capacity = max_link_capacity
        self.current_drones = 0

    def connects(self, zone: "Zone") -> bool:
        return zone == self.zone_a or zone == self.zone_b

    def other_end(self, zone: "Zone") -> "Zone":
        if zone == self.zone_a:
            return self.zone_b
        elif zone == self.zone_b:
            return self.zone_a
        else:
            raise ValueError(
                f"Zone {zone.name} is not connected by this connection."
            )

    def has_capacity(self) -> bool:
        return self.current_drones < self.max_link_capacity

    def name(self) -> str:
        return f"{self.zone_a.name}-{self.zone_b.name}"

    def __repr__(self) -> str:
        return f"Connection({self.zone_a.name}, {self.zone_b.name})"