"""Routing policy: the consecutive-road budget (ADR-017)."""

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
