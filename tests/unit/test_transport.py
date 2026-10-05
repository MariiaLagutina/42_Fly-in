"""Transport rules: availability and travel time per mode and weather.

Travel times follow documented speeds and weather rules (DECISION-001) and
are asserted exactly.
"""

import pytest

from airlanes.model.connection import Connection
from airlanes.model.transport_mode import TransportMode
from airlanes.world.transport import is_available, travel_time
from airlanes.world.weather import WeatherCondition
from airlanes.model.zone import Zone, ZoneType

AIR = TransportMode.AIR
ROAD = TransportMode.ROAD
CLEAR = WeatherCondition.CLEAR


def lane(mode: TransportMode, distance: int) -> Connection:
    connection = Connection(Zone("a", 0, 0), Zone("b", 1, 0), mode=mode)
    connection.distance = distance
    return connection


def destination(zone_type: ZoneType = ZoneType.NORMAL) -> Zone:
    return Zone("b", 1, 0, zone_type)


@pytest.mark.parametrize(
    ("mode", "condition", "available"),
    [
        (AIR, WeatherCondition.CLEAR, True),
        (AIR, WeatherCondition.RAIN, True),
        (AIR, WeatherCondition.TAILWIND, True),
        (AIR, WeatherCondition.SNOW, False),
        (AIR, WeatherCondition.STORM, False),
        (ROAD, WeatherCondition.CLEAR, True),
        (ROAD, WeatherCondition.RAIN, True),
        (ROAD, WeatherCondition.TAILWIND, True),
        (ROAD, WeatherCondition.SNOW, True),
        (ROAD, WeatherCondition.STORM, True),
    ],
)
def test_availability_depends_on_mode_and_weather(
    mode: TransportMode, condition: WeatherCondition, available: bool
) -> None:
    """Storm and snow ground aircraft; roads stay usable in any weather."""
    assert is_available(lane(mode, 300), condition) is available


@pytest.mark.parametrize("condition", list(WeatherCondition))
@pytest.mark.parametrize("mode", list(TransportMode))
def test_weather_never_changes_a_lane(
    mode: TransportMode, condition: WeatherCondition
) -> None:
    connection = lane(mode, 300)

    is_available(connection, condition)
    travel_time(connection, destination(), condition)

    assert connection.mode is mode
    assert connection.distance == 300


@pytest.mark.parametrize(
    ("mode", "distance", "expected_turns"),
    [
        pytest.param(ROAD, 100, 1, id="road-100km"),
        pytest.param(ROAD, 150, 2, id="road-150km"),
        pytest.param(ROAD, 250, 3, id="road-250km"),
        pytest.param(AIR, 150, 1, id="air-150km"),
        pytest.param(AIR, 450, 2, id="air-450km"),
        pytest.param(AIR, 900, 3, id="air-900km"),
    ],
)
def test_clear_travel_time_follows_the_mode_speed(
    mode: TransportMode, distance: int, expected_turns: int
) -> None:
    """Road at 100 km/h, air at 400 km/h, rounded up to whole turns. The
    mode comes from the map, not from the distance."""
    connection = lane(mode, distance)

    assert travel_time(connection, destination(), CLEAR) == expected_turns


@pytest.mark.parametrize(
    ("condition", "expected_turns"),
    [
        (WeatherCondition.RAIN, 3),
        (WeatherCondition.SNOW, 4),
        (WeatherCondition.STORM, 4),
    ],
)
def test_bad_weather_adds_turns_to_road_legs(
    condition: WeatherCondition, expected_turns: int
) -> None:
    """150 km of road takes 2 turns; rain adds one, snow and storm two."""
    connection = lane(ROAD, 150)

    assert travel_time(connection, destination(), condition) == expected_turns


def test_tailwind_halves_the_distance_of_air_legs_only() -> None:
    """900 km of air takes 3 turns, as 450 km with a tailwind 2. Roads are
    not affected."""
    air, road = lane(AIR, 900), lane(ROAD, 150)
    tailwind = WeatherCondition.TAILWIND

    assert travel_time(air, destination(), tailwind) == 2
    assert travel_time(road, destination(), tailwind) == 2


def test_restricted_hub_does_not_change_distance_travel_time() -> None:
    """On lanes with a distance, the destination's zone type is ignored
    (DECISION-001, documented behavior; DECISION-011 is open)."""
    connection = lane(AIR, 450)

    assert travel_time(
        connection, destination(ZoneType.RESTRICTED), CLEAR
    ) == travel_time(connection, destination(), CLEAR)


@pytest.mark.parametrize("condition", list(WeatherCondition))
def test_lane_without_distance_costs_the_hub_entry(
    condition: WeatherCondition,
) -> None:
    """Abstract lanes keep the assignment rule: entering a restricted hub
    takes two turns, any other hub one."""
    connection = lane(AIR, 0)

    assert travel_time(connection, destination(), condition) == 1
    assert travel_time(
        connection, destination(ZoneType.RESTRICTED), condition
    ) == 2
