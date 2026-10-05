"""Graph: zone lookup, start/end registration, connections, and neighbors.

Connections are only queried between distinct zones; self-loops are a known
open issue and are not part of the tested contract.
"""

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
