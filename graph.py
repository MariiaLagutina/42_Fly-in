from typing import Optional
from zone import Zone
from connection import Connection


class Graph:
    def __init__(self) -> None:
        self.zones: dict[str, Zone] = {}
        self.connections: list[Connection] = []
        self.start_zone: Optional[Zone] = None
        self.end_zone: Optional[Zone] = None

    def add_zone(self, zone: Zone) -> None:
        self.zones[zone.name] = zone
        if zone.is_start:
            self.start_zone = zone
        if zone.is_end:
            self.end_zone = zone

    def add_connection(self, connection: Connection) -> None:
        self.connections.append(connection)

    def get_zone(self, name: str) -> Optional[Zone]:
        return self.zones.get(name)

    def get_neighbors(self, zone: Zone) -> list[Zone]:
        neighbors = []
        for conn in self.connections:
            if conn.connects(zone):
                neighbor = conn.other_end(zone)
                if neighbor.is_accessible():
                    neighbors.append(neighbor)
        return neighbors

    def get_connection(
        self, zone_a: Zone, zone_b: Zone
    ) -> Optional[Connection]:
        for conn in self.connections:
            if conn.connects(zone_a) and conn.connects(zone_b):
                return conn
        return None

    def __repr__(self) -> str:
        return (
            f"Graph(zones={len(self.zones)}, "
            f"connections={len(self.connections)})"
        )
