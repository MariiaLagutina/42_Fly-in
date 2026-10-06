"""Pathfinder: shape of planned routes, reachability, and the road budget.

Only the API the simulator uses is tested. Search order, cost weights, and
the reservation table format are implementation details, and the unused
search methods (`find_path_bfs`, `find_path_dijkstra`, `find_multiple_paths`,
`heuristic`) are intentionally not covered.
"""

import math

from airlanes.model.graph import Graph
from airlanes.model.transport_mode import TransportMode
from airlanes.model.zone import Zone, ZoneType
from airlanes.routing.pathfinder import Pathfinder
from airlanes.routing.policy import RoutingPolicy
from airlanes.world.weather import WeatherCondition, WeatherState

from tests.support.graphs import Link, build_graph, end_hub, hub, start_hub

ROAD = TransportMode.ROAD


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


def route_names(route: list[Zone] | None) -> list[str] | None:
    return None if route is None else [zone.name for zone in route]


def find(
    graph: Graph,
    weather: WeatherState | None = None,
    road_km: int = 0,
    policy: RoutingPolicy | None = None,
) -> list[str] | None:
    """Route from start to goal with `find_route`, as hub names."""
    assert graph.start_zone is not None and graph.end_zone is not None
    return route_names(Pathfinder(graph, policy).find_route(
        graph.start_zone, graph.end_zone, weather or WeatherState(), road_km
    ))


def road_chain(*distances: int) -> Graph:
    """start -> h1 -> ... -> goal, one road lane per distance."""
    names = (
        ["start"] + [f"h{i}" for i in range(1, len(distances))] + ["goal"]
    )
    return build_graph(
        [start_hub(), *(hub(name) for name in names[1:-1]), end_hub()],
        [
            Link(a, b, distance=d, mode=ROAD)
            for a, b, d in zip(names, names[1:], distances)
        ],
    )


# --- find_route: reachability and weather ----------------------------------


def test_find_route_returns_the_hubs_after_start() -> None:
    graph = build_graph(
        [start_hub(), hub("a"), end_hub(), hub("island")],
        [Link("start", "a"), Link("a", "goal")],
    )

    assert find(graph) == ["a", "goal"]


def test_find_route_reports_an_unreachable_destination() -> None:
    graph = build_graph(
        [start_hub(), hub("a"), end_hub()], [Link("start", "a")]
    )

    assert find(graph) is None


def test_find_route_avoids_lanes_closed_by_weather() -> None:
    graph = build_graph(
        [start_hub(), hub("a"), hub("b"), end_hub()],
        [
            Link("start", "a", distance=450),
            Link("a", "goal", distance=450),
            Link("start", "b", distance=900),
            Link("b", "goal", distance=900),
        ],
    )
    storm = WeatherState({"a-goal": WeatherCondition.STORM})

    assert find(graph) == ["a", "goal"]
    assert find(graph, storm) == ["b", "goal"]
    assert find(graph, WeatherState({
        "a-goal": WeatherCondition.STORM, "b-goal": WeatherCondition.SNOW,
    })) is None


def test_find_route_keeps_roads_open_in_a_storm() -> None:
    graph = road_chain(150)

    assert find(graph, WeatherState({
        "start-goal": WeatherCondition.STORM
    })) == ["goal"]


# --- route_travel_time: a route's travel time under weather (ADR-021) -----


def road_then_air() -> Graph:
    """start -> a by 150 km of road, a -> goal by 900 km of air."""
    return build_graph(
        [start_hub(), hub("a"), end_hub()],
        [
            Link("start", "a", distance=150, mode=ROAD),
            Link("a", "goal", distance=900),
        ],
    )


def travel_time_of(
    graph: Graph, route: list[str], weather: WeatherState | None = None
) -> float:
    assert graph.start_zone is not None
    return Pathfinder(graph).route_travel_time(
        graph.start_zone,
        [graph.zones[name] for name in route],
        weather or WeatherState(),
    )


def test_route_travel_time_adds_the_legs_under_the_weather() -> None:
    """Road 2 turns and air 3 turns in clear weather; a storm adds two turns
    to the road, a tailwind halves the air distance."""
    graph = road_then_air()

    assert travel_time_of(graph, ["a", "goal"]) == 5
    assert travel_time_of(graph, ["a", "goal"], WeatherState({
        "start-a": WeatherCondition.STORM,
        "a-goal": WeatherCondition.TAILWIND,
    })) == 6


def test_route_travel_time_ignores_planned_waits() -> None:
    graph = road_then_air()

    assert travel_time_of(graph, ["start", "a", "a", "goal"]) == 5


def test_route_travel_time_of_a_closed_route_is_infinite() -> None:
    graph = road_then_air()

    assert travel_time_of(graph, ["a", "goal"], WeatherState({
        "a-goal": WeatherCondition.SNOW
    })) == math.inf


# --- consecutive-road budget (ADR-017) -------------------------------------


def test_consecutive_road_within_the_budget_is_allowed() -> None:
    assert find(road_chain(250, 300)) == ["h1", "goal"]


def test_consecutive_road_over_the_budget_is_rejected() -> None:
    assert find(road_chain(400, 400)) is None


def test_an_air_leg_resets_the_road_budget() -> None:
    graph = build_graph(
        [start_hub(), hub("a"), hub("b"), end_hub()],
        [
            Link("start", "a", distance=500, mode=ROAD),
            Link("a", "b", distance=900),
            Link("b", "goal", distance=600, mode=ROAD),
        ],
    )

    assert find(graph) == ["a", "b", "goal"]


def test_lanes_without_distance_do_not_use_road_budget() -> None:
    graph = build_graph(
        [start_hub(), hub("a"), hub("b"), end_hub()],
        [
            Link("start", "a", distance=500, mode=ROAD),
            Link("a", "b"),
            Link("b", "goal", distance=600, mode=ROAD),
        ],
    )

    assert find(graph) == ["a", "b", "goal"]


def test_road_already_driven_counts_towards_the_budget() -> None:
    graph = road_chain(300)

    assert find(graph, road_km=400) == ["goal"]
    assert find(graph, road_km=401) is None


def test_road_budget_follows_the_policy() -> None:
    graph = road_chain(250, 300)

    assert find(graph, policy=RoutingPolicy(500)) is None


def budget_trap() -> Graph:
    """Two ways to reach `h`, both arriving after four turns: by road
    (400 km) or by air (no road). Only the air way can continue over the
    400 km road to the goal."""
    return build_graph(
        [start_hub(), hub("a"), hub("b"), hub("h"), end_hub()],
        [
            Link("start", "a", distance=200, mode=ROAD),
            Link("start", "b", distance=800),
            Link("a", "h", distance=200, mode=ROAD),
            Link("b", "h", distance=800),
            Link("h", "goal", distance=400, mode=ROAD),
        ],
    )


def test_find_route_keeps_a_slower_way_with_less_road() -> None:
    """Remembering only the first arrival at `h` would lose the air way and
    report no route."""
    assert find(budget_trap()) == ["b", "h", "goal"]


def test_cooperative_plan_respects_the_road_budget() -> None:
    graph = budget_trap()

    route = plan_alone(graph)

    assert_valid_route(graph, route)
    assert [zone.name for zone in route if zone.name != "start"] == [
        "b", "h", "goal"
    ]


def test_no_cooperative_plan_when_only_route_breaks_the_budget() -> None:
    assert plan_alone(road_chain(400, 400)) == []
