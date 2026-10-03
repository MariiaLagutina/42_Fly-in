"""Zone: entry cost, accessibility, and capacity by zone type and role."""

import math

import pytest

from zone import Zone, ZoneType


def test_defaults() -> None:
    zone = Zone("hub", 1, 2)

    assert zone.name == "hub"
    assert (zone.x, zone.y) == (1, 2)
    assert zone.zone_type is ZoneType.NORMAL
    assert zone.color is None
    assert zone.max_drones == 1
    assert not zone.is_start
    assert not zone.is_end


@pytest.mark.parametrize(
    ("zone_type", "expected_cost"),
    [
        (ZoneType.NORMAL, 1),
        (ZoneType.PRIORITY, 1),
        (ZoneType.RESTRICTED, 2),
    ],
)
def test_movement_cost(zone_type: ZoneType, expected_cost: int) -> None:
    """Restricted hubs take two turns to enter; other accessible hubs one."""
    assert Zone("hub", 0, 0, zone_type).movement_cost() == expected_cost


@pytest.mark.parametrize(
    ("zone_type", "accessible"),
    [
        (ZoneType.NORMAL, True),
        (ZoneType.PRIORITY, True),
        (ZoneType.RESTRICTED, True),
        (ZoneType.BLOCKED, False),
    ],
)
def test_only_blocked_zones_are_inaccessible(
    zone_type: ZoneType, accessible: bool
) -> None:
    assert Zone("hub", 0, 0, zone_type).is_accessible() is accessible


def test_regular_hub_capacity_is_max_drones() -> None:
    assert Zone("hub", 0, 0, max_drones=4).effective_capacity() == 4


@pytest.mark.parametrize(
    ("is_start", "is_end"),
    [(True, False), (False, True)],
    ids=["start", "end"],
)
def test_start_and_end_hubs_have_unlimited_capacity(
    is_start: bool, is_end: bool
) -> None:
    zone = Zone("hub", 0, 0, max_drones=2, is_start=is_start, is_end=is_end)

    assert zone.effective_capacity() == math.inf
