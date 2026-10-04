"""Connection: endpoints, naming, defaults, and transport mode."""

import pytest

from connection import Connection
from transport import TransportMode
from zone import Zone


@pytest.fixture
def zones() -> tuple[Zone, Zone, Zone]:
    return Zone("alpha", 0, 0), Zone("bravo", 1, 0), Zone("charlie", 2, 0)


def test_defaults(zones: tuple[Zone, Zone, Zone]) -> None:
    alpha, bravo, _ = zones
    connection = Connection(alpha, bravo)

    assert connection.max_link_capacity == 1
    assert connection.distance == 0
    assert connection.mode is TransportMode.AIR


def test_explicit_capacity(zones: tuple[Zone, Zone, Zone]) -> None:
    alpha, bravo, _ = zones

    assert Connection(alpha, bravo, 3).max_link_capacity == 3


def test_connects_both_endpoints_only(
    zones: tuple[Zone, Zone, Zone],
) -> None:
    alpha, bravo, charlie = zones
    connection = Connection(alpha, bravo)

    assert connection.connects(alpha)
    assert connection.connects(bravo)
    assert not connection.connects(charlie)


def test_other_end_works_in_both_directions(
    zones: tuple[Zone, Zone, Zone],
) -> None:
    alpha, bravo, _ = zones
    connection = Connection(alpha, bravo)

    assert connection.other_end(alpha) is bravo
    assert connection.other_end(bravo) is alpha


def test_other_end_rejects_an_unrelated_zone(
    zones: tuple[Zone, Zone, Zone],
) -> None:
    alpha, bravo, charlie = zones

    with pytest.raises(ValueError):
        Connection(alpha, bravo).other_end(charlie)


def test_name_follows_declaration_order(
    zones: tuple[Zone, Zone, Zone],
) -> None:
    alpha, bravo, _ = zones

    assert Connection(alpha, bravo).name() == "alpha-bravo"
    assert Connection(bravo, alpha).name() == "bravo-alpha"


def test_explicit_mode(zones: tuple[Zone, Zone, Zone]) -> None:
    alpha, bravo, _ = zones

    connection = Connection(alpha, bravo, mode=TransportMode.ROAD)

    assert connection.mode is TransportMode.ROAD
