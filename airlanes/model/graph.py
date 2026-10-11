from typing import Optional

from airlanes.model.connection import Connection
from airlanes.model.zone import Zone


class Graph:
    """
    Represents the entire grid of zones and connections.

    Lane lookups follow the contract of ADR-027. `get_connection` returns
    the first lane in map order that joins both zones, in either direction;
    for a zone with itself, that is the zone's first lane. `get_neighbors`
    returns the other end of every lane of a zone in map order, repeats
    included, when that zone is accessible at the time of the call. Zones
    are told apart by identity, not by name, and need not be registered.

    Both lookups go through an index of each zone's lanes in map order,
    kept up to date by `add_connection`, the supported way to add a lane.
    A lane appended to `connections` directly is picked up because the
    list's length no longer matches the index, which is then rebuilt. That
    check only sees length: replacing or reordering lanes in the list is
    not supported, and neither is changing a lane's ends (`Connection`
    refuses it).
    """

    def __init__(self) -> None:
        self.zones: dict[str, Zone] = {}
        self.connections: list[Connection] = []
        self.start_zone: Optional[Zone] = None
        self.end_zone: Optional[Zone] = None
        # Lanes of each zone, in map order; a loop is listed once.
        self._lanes: dict[Zone, list[Connection]] = {}
        self._indexed = 0

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
        if self._indexed == len(self.connections) - 1:
            self._index(connection)

    def has_connection(self, zone_a: Zone, zone_b: Zone) -> bool:
        """Check if there is a connection between two zones."""
        return self.get_connection(zone_a, zone_b) is not None

    def get_zone(self, name: str) -> Optional[Zone]:
        """Return the zone with the given name, or None if not found."""
        return self.zones.get(name)

    def get_neighbors(self, zone: Zone) -> list[Zone]:
        """Return a list of neighboring zones connected to the given zone."""
        neighbors = []
        for conn in self._lanes_of(zone):
            neighbor = conn.other_end(zone)
            if neighbor.is_accessible():
                neighbors.append(neighbor)
        return neighbors

    def get_connection(
        self, zone_a: Zone, zone_b: Zone
    ) -> Optional[Connection]:
        """Return the connection between two zones, or None if not found."""
        # Every lane joining both zones is a lane of `zone_a`, in the same
        # order as in `connections`.
        for conn in self._lanes_of(zone_a):
            if conn.connects(zone_b):
                return conn
        return None

    def _lanes_of(self, zone: Zone) -> list[Connection]:
        """The zone's lanes in map order. Callers must not change the list."""
        if self._indexed != len(self.connections):
            self._rebuild_index()
        return self._lanes.get(zone, [])

    def _index(self, connection: Connection) -> None:
        lanes_a = self._lanes.setdefault(connection.zone_a, [])
        lanes_a.append(connection)
        # A loop's two ends are the same key, so it is listed once, as a
        # scan of `connections` would find it once.
        lanes_b = self._lanes.setdefault(connection.zone_b, [])
        if lanes_b is not lanes_a:
            lanes_b.append(connection)
        self._indexed += 1

    def _rebuild_index(self) -> None:
        self._lanes = {}
        self._indexed = 0
        for connection in self.connections:
            self._index(connection)

    def __repr__(self) -> str:
        """Return a string representation of the graph."""
        return (
            f"Graph(zones={len(self.zones)}, "
            f"connections={len(self.connections)})"
        )
