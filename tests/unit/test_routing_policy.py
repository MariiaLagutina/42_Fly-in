"""Routing policy: the consecutive-road budget (ADR-017), which transport
modes routing may use, and running without a budget (ADR-029)."""

import dataclasses

import pytest

from airlanes.model.connection import Connection
from airlanes.model.transport_mode import TransportMode
from airlanes.model.zone import Zone
from airlanes.routing.policy import RoutingPolicy


def lane(mode: TransportMode, distance: int) -> Connection:
    connection = Connection(Zone("a", 0, 0), Zone("b", 1, 0), mode=mode)
    connection.distance = distance
    return connection


def road(distance: int) -> Connection:
    return lane(TransportMode.ROAD, distance)


def test_default_limit_is_700_km() -> None:
    assert RoutingPolicy().max_consecutive_road_km == 700


def test_consecutive_road_legs_add_up() -> None:
    policy = RoutingPolicy()

    assert policy.road_km_after(250, road(300)) == 550


def test_road_up_to_the_limit_is_allowed() -> None:
    assert RoutingPolicy().road_km_after(400, road(300)) == 700


def test_road_beyond_the_limit_is_rejected() -> None:
    assert RoutingPolicy().road_km_after(400, road(400)) is None


def test_an_air_leg_resets_the_road_distance() -> None:
    air = lane(TransportMode.AIR, 900)

    assert RoutingPolicy().road_km_after(500, air) == 0


def test_a_lane_without_distance_is_air_and_costs_no_road() -> None:
    abstract = lane(TransportMode.AIR, 0)

    assert RoutingPolicy().road_km_after(500, abstract) == 0


def test_limit_is_configurable() -> None:
    policy = RoutingPolicy(max_consecutive_road_km=300)

    assert policy.road_km_after(0, road(300)) == 300
    assert policy.road_km_after(0, road(301)) is None


# --- Transport modes and an unlimited budget (ADR-029) ----------------------

AIR_ONLY = RoutingPolicy(transport_modes=frozenset({TransportMode.AIR}))
ROAD_ONLY = RoutingPolicy(None, frozenset({TransportMode.ROAD}))


def air(distance: int) -> Connection:
    return lane(TransportMode.AIR, distance)


def test_the_default_policy_permits_every_mode() -> None:
    policy = RoutingPolicy()

    assert policy.transport_modes == frozenset(TransportMode)
    assert policy.allows(air(900)) and policy.allows(road(100))


def test_a_positional_limit_keeps_every_mode() -> None:
    policy = RoutingPolicy(500)

    assert policy == RoutingPolicy(
        max_consecutive_road_km=500, transport_modes=frozenset(TransportMode)
    )
    assert policy.road_km_after(0, road(500)) == 500
    assert policy.road_km_after(0, road(501)) is None


def test_an_excluded_road_lane_is_rejected() -> None:
    assert not AIR_ONLY.allows(road(10))
    assert AIR_ONLY.road_km_after(0, road(10)) is None


def test_an_excluded_air_lane_is_rejected() -> None:
    assert not ROAD_ONLY.allows(air(900))
    assert ROAD_ONLY.road_km_after(0, air(900)) is None


def test_a_lane_without_distance_is_an_air_lane_for_the_modes() -> None:
    abstract = air(0)

    assert ROAD_ONLY.road_km_after(0, abstract) is None
    assert AIR_ONLY.road_km_after(300, abstract) == 0


def test_a_permitted_air_lane_resets_the_road_distance() -> None:
    assert AIR_ONLY.road_km_after(500, air(900)) == 0


def test_without_a_limit_road_has_no_budget() -> None:
    assert ROAD_ONLY.road_km_after(700, road(800)) == 1500
    assert RoutingPolicy(None).road_km_after(10_000, road(1)) == 10_001


def test_a_zero_limit_allows_no_road() -> None:
    policy = RoutingPolicy(0)

    assert policy.road_km_after(0, road(1)) is None
    assert policy.road_km_after(0, air(100)) == 0


def test_no_permitted_mode_is_an_error() -> None:
    with pytest.raises(ValueError) as error:
        RoutingPolicy(transport_modes=frozenset())

    assert str(error.value) == "A routing policy needs at least one mode."


def test_a_negative_limit_is_an_error() -> None:
    with pytest.raises(ValueError) as error:
        RoutingPolicy(-1)

    assert str(error.value) == (
        "The consecutive-road limit must not be negative: -1."
    )


@pytest.mark.parametrize(
    "policy",
    [RoutingPolicy(), RoutingPolicy(300), RoutingPolicy(None), AIR_ONLY,
     ROAD_ONLY],
    ids=["default", "every-mode-300", "unlimited", "air-only", "road-only"],
)
@pytest.mark.parametrize(
    "connection",
    [air(0), air(900), road(100)],
    ids=["abstract", "air", "road"],
)
def test_a_lane_is_rejected_exactly_when_its_mode_is_excluded(
    policy: RoutingPolicy, connection: Connection
) -> None:
    """Within the budget, `road_km_after` rejects a lane for its mode
    alone, by the same rule as `allows`."""
    assert (policy.road_km_after(0, connection) is None) == (
        not policy.allows(connection)
    )


# --- Every mode permitted: the mode test is skipped --------------------------

BOTH_MODES = frozenset({TransportMode.AIR, TransportMode.ROAD})


@pytest.mark.parametrize("limit", [700, 300, None], ids=str)
def test_naming_both_modes_is_the_same_policy(limit: int | None) -> None:
    named = RoutingPolicy(limit, BOTH_MODES)
    implicit = RoutingPolicy(limit)

    assert named == implicit and hash(named) == hash(implicit)
    assert repr(named) == repr(implicit)


def test_every_mode_with_a_custom_limit_keeps_the_budget() -> None:
    policy = RoutingPolicy(300, BOTH_MODES)

    assert policy.road_km_after(200, road(100)) == 300
    assert policy.road_km_after(200, road(101)) is None
    assert policy.road_km_after(200, air(900)) == 0


def test_every_mode_without_a_limit_has_no_budget() -> None:
    policy = RoutingPolicy(None, BOTH_MODES)

    assert policy.road_km_after(10_000, road(800)) == 10_800
    assert policy.road_km_after(10_000, air(0)) == 0


def test_the_policy_fields_are_only_the_limit_and_the_modes() -> None:
    names = [f.name for f in dataclasses.fields(RoutingPolicy) if f.init]

    assert names == ["max_consecutive_road_km", "transport_modes"]
    assert repr(RoutingPolicy()) == (
        "RoutingPolicy(max_consecutive_road_km=700, "
        f"transport_modes={frozenset(TransportMode)!r})"
    )


def test_a_replaced_policy_filters_by_its_own_modes() -> None:
    narrowed = dataclasses.replace(
        RoutingPolicy(), transport_modes=frozenset({TransportMode.AIR})
    )

    assert narrowed == AIR_ONLY
    assert narrowed.road_km_after(0, road(10)) is None
    widened = dataclasses.replace(AIR_ONLY, transport_modes=BOTH_MODES)
    assert widened.road_km_after(0, road(10)) == 10
