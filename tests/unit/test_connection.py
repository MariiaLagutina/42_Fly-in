"""Connection: endpoints, naming, defaults, and transport mode."""

import copy
import pickle

import pytest

from airlanes.model.connection import Connection
from airlanes.model.transport_mode import TransportMode
from airlanes.model.zone import Zone


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


# --- Fixed endpoints (ADR-027) ----------------------------------------------


@pytest.mark.parametrize("endpoint", ["zone_a", "zone_b"])
def test_endpoints_cannot_be_reassigned(
    zones: tuple[Zone, Zone, Zone], endpoint: str
) -> None:
    alpha, bravo, charlie = zones
    connection = Connection(alpha, bravo)

    with pytest.raises(AttributeError, match=endpoint):
        setattr(connection, endpoint, charlie)
    with pytest.raises(AttributeError, match=endpoint):
        delattr(connection, endpoint)
    assert (connection.zone_a, connection.zone_b) == (alpha, bravo)


def test_capacity_mode_and_distance_can_be_set_after_creation(
    zones: tuple[Zone, Zone, Zone],
) -> None:
    """The parser sets the distance and the default capacity after it
    creates the connection."""
    alpha, bravo, _ = zones
    connection = Connection(alpha, bravo)

    connection.distance = 450
    connection.max_link_capacity = 3
    connection.mode = TransportMode.ROAD

    assert connection.distance == 450
    assert connection.max_link_capacity == 3
    assert connection.mode is TransportMode.ROAD


def test_copies_keep_their_endpoints_fixed(
    zones: tuple[Zone, Zone, Zone],
) -> None:
    alpha, bravo, charlie = zones
    connection = Connection(alpha, bravo, 2, TransportMode.ROAD)
    connection.distance = 120

    shallow = copy.copy(connection)
    deep = copy.deepcopy(connection)

    assert shallow.zone_a is alpha and shallow.zone_b is bravo
    assert deep.zone_a is not alpha and deep.zone_a.name == "alpha"
    assert deep.zone_b.name == "bravo"
    for copied in (shallow, deep):
        assert (copied.distance, copied.max_link_capacity) == (120, 2)
        assert copied.mode is TransportMode.ROAD
        assert copied.connects(copied.zone_a)
        with pytest.raises(AttributeError):
            copied.zone_a = charlie


def test_the_constructor_sets_every_field(
    zones: tuple[Zone, Zone, Zone],
) -> None:
    alpha, bravo, _ = zones
    connection = Connection(alpha, bravo, 4, TransportMode.ROAD)

    assert connection.zone_a is alpha and connection.zone_b is bravo
    assert connection.max_link_capacity == 4
    assert connection.mode is TransportMode.ROAD
    assert connection.distance == 0


def test_a_connection_takes_no_other_attributes(
    zones: tuple[Zone, Zone, Zone],
) -> None:
    """Fields live in slots (ADR-027): there is no `__dict__`."""
    alpha, bravo, _ = zones
    connection = Connection(alpha, bravo)

    assert not hasattr(connection, "__dict__")
    with pytest.raises(AttributeError):
        setattr(connection, "label", "extra")


def test_pickling_keeps_the_fields_and_the_guard(
    zones: tuple[Zone, Zone, Zone],
) -> None:
    alpha, bravo, charlie = zones
    connection = Connection(alpha, bravo, 2, TransportMode.ROAD)
    connection.distance = 300

    restored = pickle.loads(pickle.dumps(connection))

    assert (restored.zone_a.name, restored.zone_b.name) == ("alpha", "bravo")
    assert (restored.max_link_capacity, restored.distance) == (2, 300)
    assert restored.mode is TransportMode.ROAD
    with pytest.raises(AttributeError):
        restored.zone_b = charlie


def test_a_subclass_keeps_the_endpoint_guard(
    zones: tuple[Zone, Zone, Zone],
) -> None:
    """A subclass without slots of its own may add attributes, but its
    endpoints stay fixed."""
    alpha, bravo, charlie = zones

    class LabelledConnection(Connection):
        label: str

    connection = LabelledConnection(alpha, bravo)
    connection.label = "extra"

    assert connection.label == "extra"
    assert connection.connects(alpha)
    with pytest.raises(AttributeError):
        connection.zone_a = charlie
