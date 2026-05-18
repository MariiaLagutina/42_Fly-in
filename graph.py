from typing import Optional
from zone import Zone
from connection import Connection


class Graph:
    """Represents the entire grid of zones and connections."""
    def __init__(self) -> None:
        self.zones: dict[str, Zone] = {}
        self.connections: list[Connection] = []
        self.start_zone: Optional[Zone] = None
        self.end_zone: Optional[Zone] = None

    def add_zone(self, zone: Zone) -> None:
        """Add a zone to the graph."""
        self.zones[zone.name] = zone
        if zone.is_start:
            self.start_zone = zone
        if zone.is_end:
            self.end_zone = zone

    def add_connection(self, connection: Connection) -> None:
        """Add a connection to the graph."""
        self.connections.append(connection)

    def has_connection(self, zone_a: Zone, zone_b: Zone) -> bool:
        """Check if there is a connection between two zones."""
        return self.get_connection(zone_a, zone_b) is not None

    def get_zone(self, name: str) -> Optional[Zone]:
        """Return the zone with the given name, or None if not found."""
        return self.zones.get(name)

    def get_neighbors(self, zone: Zone) -> list[Zone]:
        """Return a list of neighboring zones connected to the given zone."""
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
        """Return the connection between two zones, or None if not found."""
        for conn in self.connections:
            if conn.connects(zone_a) and conn.connects(zone_b):
                return conn
        return None

    def __repr__(self) -> str:
        """Return a string representation of the graph."""
        return (
            f"Graph(zones={len(self.zones)}, "
            f"connections={len(self.connections)})"
        )
