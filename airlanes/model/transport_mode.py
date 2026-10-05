"""How a connection is travelled: by air or by road (ADR-016).

The mode is map data. How weather affects each mode is decided by the
transport rules in `airlanes.world.transport`.
"""

from enum import Enum


class TransportMode(Enum):
    AIR = "air"
    ROAD = "road"
