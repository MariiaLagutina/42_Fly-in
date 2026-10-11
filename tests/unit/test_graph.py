"""Graph: zone lookup, start/end registration, connections, and neighbors.

Lookups are pinned as they behave, including cases the parser never
produces: duplicate lanes, loops, and `get_connection(a, a)`, which
returns the first lane of `a` rather than a loop. The lookups are also
checked against a plain scan of the lane list on random graphs.
"""

import random

import pytest

from airlanes.model.connection import Connection
from airlanes.model.graph import Graph
from airlanes.model.zone import Zone, ZoneType


def build_graph(
    zones: list[Zone], links: list[tuple[str, str]]
) -> Graph:
    graph = Graph()
    for zone in zones:
        graph.add_zone(zone)
    for name_a, name_b in links:
        zone_a = graph.get_zone(name_a)
        zone_b = graph.get_zone(name_b)
        assert zone_a is not None and zone_b is not None
        graph.add_connection(Connection(zone_a, zone_b))
    return graph


def neighbor_names(graph: Graph, name: str) -> set[str]:
    zone = graph.get_zone(name)
    assert zone is not None
    return {neighbor.name for neighbor in graph.get_neighbors(zone)}


def test_empty_graph() -> None:
    graph = Graph()

    assert graph.zones == {}
    assert graph.connections == []
    assert graph.start_zone is None
    assert graph.end_zone is None


def test_get_zone_by_name() -> None:
    hub = Zone("hub", 0, 0)
    graph = build_graph([hub], [])

    assert graph.get_zone("hub") is hub
    assert graph.get_zone("missing") is None


def test_start_and_end_zones_are_registered() -> None:
    start = Zone("start", 0, 0, is_start=True)
    goal = Zone("goal", 1, 0, is_end=True)
    graph = build_graph([start, Zone("hub", 2, 0), goal], [])

    assert graph.start_zone is start
    assert graph.end_zone is goal


def test_get_connection_is_symmetric() -> None:
    graph = build_graph(
        [Zone("a", 0, 0), Zone("b", 1, 0)], [("a", "b")]
    )
    a = graph.get_zone("a")
    b = graph.get_zone("b")
    assert a is not None and b is not None

    connection = graph.get_connection(a, b)
    assert connection is not None
    assert graph.get_connection(b, a) is connection
    assert graph.has_connection(a, b)
    assert graph.has_connection(b, a)


def test_unconnected_zones_have_no_connection() -> None:
    graph = build_graph(
        [Zone("a", 0, 0), Zone("b", 1, 0), Zone("c", 2, 0)],
        [("a", "b")],
    )
    a = graph.get_zone("a")
    c = graph.get_zone("c")
    assert a is not None and c is not None

    assert graph.get_connection(a, c) is None
    assert not graph.has_connection(a, c)


def test_neighbors_are_reachable_in_both_directions() -> None:
    graph = build_graph(
        [Zone("a", 0, 0), Zone("b", 1, 0), Zone("c", 2, 0)],
        [("a", "b"), ("c", "b")],
    )

    assert neighbor_names(graph, "b") == {"a", "c"}
    assert neighbor_names(graph, "a") == {"b"}
    assert neighbor_names(graph, "c") == {"b"}


def test_blocked_zones_are_not_neighbors() -> None:
    graph = build_graph(
        [
            Zone("a", 0, 0),
            Zone("wall", 1, 0, ZoneType.BLOCKED),
            Zone("b", 2, 0),
        ],
        [("a", "wall"), ("a", "b")],
    )

    assert neighbor_names(graph, "a") == {"b"}


def test_isolated_zone_has_no_neighbors() -> None:
    graph = build_graph([Zone("a", 0, 0), Zone("lonely", 5, 5)], [])

    assert neighbor_names(graph, "lonely") == set()


# --- Lookup contract -----------------------------------------------------


def scan_connection(graph: Graph, zone_a: Zone, zone_b: Zone) -> (
    Connection | None
):
    """Reference: the first lane in map order that joins both zones."""
    for connection in graph.connections:
        if connection.connects(zone_a) and connection.connects(zone_b):
            return connection
    return None


def scan_neighbors(graph: Graph, zone: Zone) -> list[Zone]:
    """Reference: the other end of every lane of `zone`, in map order,
    when it is accessible."""
    return [
        connection.other_end(zone)
        for connection in graph.connections
        if connection.connects(zone)
        and connection.other_end(zone).is_accessible()
    ]


def zones_named(*names: str) -> list[Zone]:
    return [Zone(name, 0, 0) for name in names]


def graph_of(zones: list[Zone], lanes: list[tuple[Zone, Zone]]) -> Graph:
    graph = Graph()
    for zone in zones:
        graph.add_zone(zone)
    for zone_a, zone_b in lanes:
        graph.add_connection(Connection(zone_a, zone_b))
    return graph


def test_the_first_of_duplicate_lanes_is_returned() -> None:
    a, b = zones_named("a", "b")
    graph = graph_of([a, b], [(b, a), (a, b), (b, a)])
    first = graph.connections[0]

    assert graph.get_connection(a, b) is first
    assert graph.get_connection(b, a) is first


def test_a_zone_with_itself_gives_its_first_lane() -> None:
    a, b, c, lonely = zones_named("a", "b", "c", "lonely")
    graph = graph_of([a, b, c, lonely], [(b, c), (b, a), (a, c), (a, a)])

    assert graph.get_connection(a, a) is graph.connections[1]
    assert graph.get_connection(c, c) is graph.connections[0]
    assert graph.get_connection(lonely, lonely) is None


def test_a_loop_makes_a_zone_its_own_neighbor() -> None:
    a, b = zones_named("a", "b")
    graph = graph_of([a, b], [(a, a), (a, b)])

    assert graph.get_connection(a, a) is graph.connections[0]
    assert graph.get_neighbors(a) == [a, b]


def test_neighbors_keep_map_order_and_duplicates() -> None:
    a, b, c = zones_named("a", "b", "c")
    graph = graph_of([a, b, c], [(a, c), (b, a), (c, a), (a, a)])

    neighbors = graph.get_neighbors(a)

    assert neighbors == [c, b, c, a]
    assert [id(zone) for zone in neighbors] == [id(c), id(b), id(c), id(a)]


def test_accessibility_is_checked_on_every_call() -> None:
    a, b, c = zones_named("a", "b", "c")
    graph = graph_of([a, b, c], [(a, b), (a, c)])

    b.zone_type = ZoneType.BLOCKED
    assert graph.get_neighbors(a) == [c]
    b.zone_type = ZoneType.NORMAL
    assert graph.get_neighbors(a) == [b, c]
    # A lane to a blocked zone is still a lane.
    c.zone_type = ZoneType.BLOCKED
    assert graph.get_connection(a, c) is graph.connections[1]


def test_zones_are_told_apart_by_identity_not_name() -> None:
    a, x_registered, x_other = zones_named("a", "x", "x")
    graph = graph_of([a, x_registered], [(a, x_other)])

    assert graph.get_connection(a, x_registered) is None
    assert graph.get_connection(a, x_other) is graph.connections[0]
    neighbors = graph.get_neighbors(a)
    assert len(neighbors) == 1 and neighbors[0] is x_other
    assert graph.get_neighbors(x_registered) == []


def test_zones_outside_the_graph_can_be_connected() -> None:
    a, b, c = zones_named("a", "b", "c")
    graph = graph_of([], [(a, b), (b, c)])

    assert graph.zones == {}
    assert graph.get_connection(c, b) is graph.connections[1]
    assert graph.get_neighbors(b) == [a, c]


def test_a_zone_without_lanes_has_none() -> None:
    a, b, unknown = zones_named("a", "b", "unknown")
    graph = graph_of([a, b], [(a, b)])

    assert graph.get_connection(a, unknown) is None
    assert graph.get_connection(unknown, a) is None
    assert graph.get_neighbors(unknown) == []


def test_neighbors_are_a_new_list_on_every_call() -> None:
    a, b = zones_named("a", "b")
    graph = graph_of([a, b], [(a, b)])

    first = graph.get_neighbors(a)
    first.append(a)
    first.clear()

    second = graph.get_neighbors(a)
    assert second == [b]
    assert second is not graph.get_neighbors(a)


def test_lanes_added_after_lookups_are_found() -> None:
    """The parser checks for a duplicate before adding every lane."""
    a, b, c = zones_named("a", "b", "c")
    graph = graph_of([a, b, c], [])

    assert not graph.has_connection(a, b)
    graph.add_connection(Connection(a, b))
    assert graph.has_connection(b, a)
    assert graph.get_neighbors(a) == [b]
    graph.add_connection(Connection(c, a))
    assert graph.get_neighbors(a) == [b, c]
    assert graph.get_connection(a, c) is graph.connections[1]


def test_lanes_appended_to_the_list_directly_are_found() -> None:
    """`add_connection` is the supported way to add a lane; a lane appended
    to `connections` directly is still found."""
    a, b, c = zones_named("a", "b", "c")
    graph = graph_of([a, b, c], [(a, b)])
    assert graph.get_neighbors(a) == [b]

    graph.connections.append(Connection(c, a))

    assert graph.get_connection(a, c) is graph.connections[1]
    assert graph.get_neighbors(a) == [b, c]


def random_graph(rng: random.Random) -> tuple[Graph, list[Zone]]:
    """Duplicates in both directions, loops, blocked zones, a zone that
    shares a registered zone's name, and a zone outside the graph."""
    zones = [
        Zone(f"z{i}", 0, 0, rng.choice(list(ZoneType)))
        for i in range(rng.randint(1, 8))
    ]
    graph = Graph()
    for zone in zones:
        graph.add_zone(zone)
    candidates = zones + [Zone("z0", 0, 0), Zone("outside", 0, 0)]
    for _ in range(rng.randint(0, 16)):
        graph.add_connection(
            Connection(rng.choice(candidates), rng.choice(candidates))
        )
    return graph, candidates + [Zone("absent", 0, 0)]


def assert_matches_scan(graph: Graph, probes: list[Zone]) -> None:
    for zone_a in probes:
        for zone_b in probes:
            assert graph.get_connection(zone_a, zone_b) is scan_connection(
                graph, zone_a, zone_b
            )
            assert graph.has_connection(zone_a, zone_b) == (
                scan_connection(graph, zone_a, zone_b) is not None
            )
        neighbors = graph.get_neighbors(zone_a)
        expected = scan_neighbors(graph, zone_a)
        assert [id(zone) for zone in neighbors] == [
            id(zone) for zone in expected
        ]


@pytest.mark.parametrize("seed", range(200))
def test_lookups_match_a_scan_of_the_lane_list(seed: int) -> None:
    rng = random.Random(seed)
    graph, probes = random_graph(rng)
    assert_matches_scan(graph, probes)

    # Lanes added between lookups, as the parser does.
    for _ in range(3):
        zone_a, zone_b = rng.choice(probes), rng.choice(probes)
        graph.add_connection(Connection(zone_a, zone_b))
        assert_matches_scan(graph, probes)

    # Accessibility changes after the lanes exist.
    for zone in probes:
        zone.zone_type = rng.choice(list(ZoneType))
    assert_matches_scan(graph, probes)

    # A lane appended to the list directly.
    graph.connections.append(
        Connection(rng.choice(probes), rng.choice(probes))
    )
    assert_matches_scan(graph, probes)
