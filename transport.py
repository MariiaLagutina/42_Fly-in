"""Transport modes of connections.

A connection's transport mode is map data: the map declares whether a lane is
an air or a road lane. It is never inferred from distance, coordinates, or
names.
"""

from enum import Enum


class TransportMode(Enum):
    AIR = "air"
    ROAD = "road"


def default_link_capacity(mode: TransportMode, distance: int) -> int:
    """Lane capacity used when the map does not set `max_link_capacity`."""
    if distance <= 0:
        return 1
    if mode is TransportMode.ROAD:
        return 3
    return 2 if distance > 500 else 1
