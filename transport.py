"""Transport rules: how weather affects each transport mode.

This module is the only place that combines a connection's transport mode,
its static data, and the current weather into availability and travel time.
Weather never changes a connection's mode or its physical distance, and it
cannot create a connection: these rules only judge connections that the map
defines.

The numeric weather penalties are provisional. Their final semantics belong
to DECISION-001 (docs/engineering/open-decisions.md).
"""

import math
from enum import Enum
from typing import TYPE_CHECKING

from config import SimulationConfig
from weather import WeatherCondition

if TYPE_CHECKING:
    from connection import Connection
    from zone import Zone


class TransportMode(Enum):
    AIR = "air"
    ROAD = "road"


# Conditions under which aircraft cannot fly a leg. Roads stay usable in any
# weather; bad weather only makes them slower.
_CLOSES_AIR = frozenset({WeatherCondition.STORM, WeatherCondition.SNOW})
_SLOWS_ROAD_SEVERELY = frozenset(
    {WeatherCondition.STORM, WeatherCondition.SNOW}
)


def is_available(
    connection: "Connection", condition: WeatherCondition
) -> bool:
    """Whether a leg can start on the connection under the given weather."""
    if connection.mode is TransportMode.ROAD:
        return True
    return condition not in _CLOSES_AIR


def travel_time(
    connection: "Connection",
    destination: "Zone",
    condition: WeatherCondition,
) -> int:
    """Turns needed to travel the connection towards `destination`."""
    if connection.distance <= 0:
        return destination.movement_cost()

    if connection.mode is TransportMode.ROAD:
        turns = math.ceil(connection.distance / SimulationConfig.CAR_SPEED_KMH)
        if condition in _SLOWS_ROAD_SEVERELY:
            turns += SimulationConfig.WEATHER_PENALTY_SEVERE
        elif condition is WeatherCondition.RAIN:
            turns += SimulationConfig.WEATHER_PENALTY_MILD
        return max(1, turns)

    effective_distance = float(connection.distance)
    if condition is WeatherCondition.TAILWIND:
        effective_distance /= SimulationConfig.TAILWIND_DIST_DIVISOR
    turns = math.ceil(effective_distance / SimulationConfig.AIRPLANE_SPEED_KMH)
    return max(1, turns)


def default_link_capacity(mode: TransportMode, distance: int) -> int:
    """Lane capacity used when the map does not set `max_link_capacity`."""
    if distance <= 0:
        return 1
    if mode is TransportMode.ROAD:
        return 3
    return 2 if distance > 500 else 1
