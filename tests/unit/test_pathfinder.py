"""Pathfinder: shape of planned routes and reachability.

Only the API the simulator uses is tested. Search order, cost weights, and
the reservation table format are implementation details, and the unused
search methods (`find_path_dijkstra`, `find_multiple_paths`, `heuristic`)
are intentionally not covered.
"""

from graph import Graph
from pathfinder import Pathfinder
from tests.support.graphs import Link, build_graph, end_hub, hub, start_hub
from zone import Zone, ZoneType


def plan_alone(graph: Graph) -> list[Zone]:
    """Plan one route with no other aircraft reserved."""
    assert graph.start_zone is not None and graph.end_zone is not None
    return Pathfinder(graph).find_cooperative_path(
        graph.start_zone, graph.end_zone, {}, {}, {}
    )


def assert_valid_route(graph: Graph, route: list[Zone]) -> None:
    assert route[0] is graph.start_zone
    assert route[-1] is graph.end_zone
    for current, following in zip(route, route[1:]):
        if following is not current:
            assert graph.has_connection(current, following)
        assert following.is_accessible()


def test_route_runs_from_start_to_end_along_lanes() -> None:
    graph = build_graph(
        [start_hub(), hub("a"), hub("b"), end_hub()],
        [Link("start", "a"), Link("a", "b"), Link("b", "goal")],
    )

    route = plan_alone(graph)

    assert_valid_route(graph, route)
    assert [zone.name for zone in route] == ["start", "a", "b", "goal"]


def test_route_avoids_blocked_hubs() -> None:
    graph = build_graph(
        [
            start_hub(),
            hub("wall", ZoneType.BLOCKED),
            hub("a"),
            hub("b"),
            end_hub(),
        ],
        [
            Link("start", "wall"),
            Link("wall", "goal"),
            Link("start", "a"),
            Link("a", "b"),
            Link("b", "goal"),
        ],
    )

    route = plan_alone(graph)

    assert_valid_route(graph, route)
    assert "wall" not in {zone.name for zone in route}


def test_no_route_when_end_is_unreachable() -> None:
    graph = build_graph(
        [start_hub(), hub("a"), end_hub()], [Link("start", "a")]
    )

    assert plan_alone(graph) == []


def test_no_route_when_only_path_is_blocked() -> None:
    graph = build_graph(
        [start_hub(), hub("wall", ZoneType.BLOCKED), end_hub()],
        [Link("start", "wall"), Link("wall", "goal")],
    )

    assert plan_alone(graph) == []


def test_reachability_check() -> None:
    graph = build_graph(
        [start_hub(), hub("a"), end_hub(), hub("island")],
        [Link("start", "a"), Link("a", "goal")],
    )
    pathfinder = Pathfinder(graph)
    start = graph.get_zone("start")
    goal = graph.get_zone("goal")
    island = graph.get_zone("island")
    assert start is not None and goal is not None and island is not None

    assert pathfinder.find_path_bfs(start, goal)
    assert pathfinder.find_path_bfs(start, island) == []
