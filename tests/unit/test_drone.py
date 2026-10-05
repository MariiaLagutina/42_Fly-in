"""Drone (one aircraft): label, initial state, and movement along its path."""

import pytest

from airlanes.model.drone import Drone, DroneState
from airlanes.model.zone import Zone


@pytest.fixture
def route() -> tuple[Zone, Zone, Zone]:
    return Zone("start", 0, 0, is_start=True), Zone("mid", 1, 0), Zone(
        "goal", 2, 0, is_end=True
    )


@pytest.mark.parametrize(("drone_id", "label"), [(1, "D1"), (12, "D12")])
def test_label(
    route: tuple[Zone, Zone, Zone], drone_id: int, label: str
) -> None:
    start, _, _ = route

    assert Drone(drone_id, start).label == label


def test_initial_state(route: tuple[Zone, Zone, Zone]) -> None:
    start, _, _ = route
    drone = Drone(1, start)

    assert drone.current_zone is start
    assert drone.state is DroneState.WAITING
    assert not drone.is_delivered()
    assert not drone.has_path()
    assert drone.next_zone() is None


def test_advance_without_path_stays_in_place(
    route: tuple[Zone, Zone, Zone],
) -> None:
    start, _, _ = route
    drone = Drone(1, start)

    assert drone.advance() is None
    assert drone.current_zone is start


def test_next_zone_does_not_move_the_drone(
    route: tuple[Zone, Zone, Zone],
) -> None:
    start, mid, goal = route
    drone = Drone(1, start)
    drone.path = [mid, goal]

    assert drone.next_zone() is mid
    assert drone.next_zone() is mid
    assert drone.current_zone is start
    assert drone.path == [mid, goal]


def test_advance_follows_the_path_in_order(
    route: tuple[Zone, Zone, Zone],
) -> None:
    start, mid, goal = route
    drone = Drone(1, start)
    drone.path = [mid, goal]

    assert drone.advance() is mid
    assert drone.current_zone is mid
    assert drone.has_path()

    assert drone.advance() is goal
    assert drone.current_zone is goal
    assert not drone.has_path()


@pytest.mark.parametrize(
    ("state", "delivered"),
    [
        (DroneState.WAITING, False),
        (DroneState.IN_TRANSIT, False),
        (DroneState.DELIVERED, True),
    ],
)
def test_is_delivered_only_in_delivered_state(
    route: tuple[Zone, Zone, Zone], state: DroneState, delivered: bool
) -> None:
    start, _, _ = route
    drone = Drone(1, start)
    drone.state = state

    assert drone.is_delivered() is delivered
