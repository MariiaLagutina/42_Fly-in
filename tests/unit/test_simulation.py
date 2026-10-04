"""Simulation on small synthetic graphs.

Every run is checked against the full invariant set in
`tests.support.simulation`. Scenarios add one targeted assertion each.
Exact turn counts are asserted only where the rules define them: a single
aircraft on a single route, where restricted hubs and the documented
distance travel-time formula leave no room for another valid answer.
"""

import pytest

from graph import Graph
from tests.support.graphs import Link, build_graph, end_hub, hub, start_hub
from tests.support.simulation import (
    check_invariants,
    peak_hub_occupancy,
    run_simulation,
)
from zone import ZoneType


def test_single_aircraft_on_a_linear_route() -> None:
    graph = build_graph(
        [start_hub(), hub("a"), end_hub()],
        [Link("start", "a"), Link("a", "goal")],
    )

    run = run_simulation(graph, 1)

    assert check_invariants(run) == []
    assert run.output == ["D1-a", "D1-goal"]


def test_restricted_hub_takes_two_turns_to_enter() -> None:
    graph = build_graph(
        [start_hub(), hub("slow", ZoneType.RESTRICTED), end_hub()],
        [Link("start", "slow"), Link("slow", "goal")],
    )

    run = run_simulation(graph, 1)

    assert check_invariants(run) == []
    assert run.output == ["D1-start-slow", "D1-slow", "D1-goal"]


def test_aircraft_wait_for_a_single_slot_hub() -> None:
    graph = build_graph(
        [start_hub(), hub("gate", capacity=1), end_hub()],
        [Link("start", "gate"), Link("gate", "goal")],
    )

    run = run_simulation(graph, 4)

    assert check_invariants(run) == []


@pytest.mark.parametrize("capacity", [1, 2])
def test_lane_capacity_limits_simultaneous_use(capacity: int) -> None:
    graph = build_graph(
        [start_hub(), end_hub()], [Link("start", "goal", capacity)]
    )

    run = run_simulation(graph, 5)

    assert check_invariants(run) == []


def test_aircraft_spread_over_parallel_routes() -> None:
    graph = build_graph(
        [start_hub(), hub("north"), hub("south"), end_hub()],
        [
            Link("start", "north"),
            Link("north", "goal"),
            Link("start", "south"),
            Link("south", "goal"),
        ],
    )

    run = run_simulation(graph, 4)

    assert check_invariants(run) == []


def test_blocked_hub_is_never_entered() -> None:
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

    run = run_simulation(graph, 3)

    assert check_invariants(run) == []
    for label in ("D1", "D2", "D3"):
        assert "wall" not in run.visited_zones(label)


def test_priority_hub_is_preferred_over_an_equal_route() -> None:
    graph = build_graph(
        [
            start_hub(),
            hub("plain"),
            hub("fast", ZoneType.PRIORITY),
            end_hub(),
        ],
        [
            Link("start", "plain"),
            Link("plain", "goal"),
            Link("start", "fast"),
            Link("fast", "goal"),
        ],
    )

    run = run_simulation(graph, 1)

    assert check_invariants(run) == []
    assert run.visited_zones("D1") == ["fast", "goal"]


def test_start_and_end_hold_every_aircraft() -> None:
    """Start and end hubs ignore `max_drones`."""
    graph = build_graph(
        [start_hub(capacity=1), end_hub(capacity=1)],
        [Link("start", "goal", capacity=5)],
    )

    run = run_simulation(graph, 5)

    assert check_invariants(run) == []


@pytest.mark.parametrize(
    "graph",
    [
        pytest.param(
            build_graph([start_hub(), hub("a"), end_hub()],
                        [Link("start", "a")]),
            id="disconnected",
        ),
        pytest.param(
            build_graph(
                [start_hub(), hub("wall", ZoneType.BLOCKED), end_hub()],
                [Link("start", "wall"), Link("wall", "goal")],
            ),
            id="only-through-blocked",
        ),
    ],
)
def test_missing_route_fails_before_the_first_turn(graph: Graph) -> None:
    with pytest.raises(RuntimeError):
        run_simulation(graph, 2)


# --- Distance-based travel time ---------------------------------------------
# Road legs (< 200 km) travel at 100 km/h, air legs at 400 km/h, rounded up
# to whole turns. Rain adds one turn to road legs; a tailwind halves the
# distance of air legs. Weather is set by hand and the random weather system
# stays off, so these runs are deterministic.


@pytest.mark.parametrize(
    ("distance", "weather", "expected_turns"),
    [
        pytest.param(100, "clear", 1, id="road-100km"),
        pytest.param(150, "clear", 2, id="road-150km"),
        pytest.param(199, "clear", 2, id="road-199km"),
        pytest.param(200, "clear", 1, id="air-200km"),
        pytest.param(450, "clear", 2, id="air-450km"),
        pytest.param(900, "clear", 3, id="air-900km"),
        pytest.param(150, "rain", 3, id="road-150km-rain"),
        pytest.param(900, "tailwind", 2, id="air-900km-tailwind"),
    ],
)
def test_distance_and_weather_set_travel_time(
    distance: int, weather: str, expected_turns: int
) -> None:
    graph = build_graph(
        [start_hub(), end_hub()],
        [Link("start", "goal", distance=distance)],
    )
    (lane,) = graph.connections
    lane.set_weather(weather, is_open=True)

    run = run_simulation(graph, 1)

    assert check_invariants(run) == []
    assert run.turn_count == expected_turns


# --- Regression: hub capacity (BUG-001, BUG-002) ----------------------------
# Three aircraft pass a one-slot `gate` and then a one-slot restricted hub
# `slow`. Before the fix, an aircraft whose departure from `gate` was
# rejected still counted as having left it, so a second aircraft moved in
# (BUG-002); and two aircraft departing towards `slow` in the same turn did
# not see each other as incoming, so both arrived (BUG-001). Each test checks
# one hub, so each bug is detected independently of the other.


def build_gate_and_restricted_hub() -> Graph:
    return build_graph(
        [
            start_hub(),
            hub("gate"),
            hub("slow", ZoneType.RESTRICTED),
            end_hub(),
        ],
        [
            Link("start", "gate"),
            Link("gate", "slow", capacity=2),
            Link("slow", "goal", capacity=2),
        ],
    )


def test_rejected_departure_does_not_free_its_hub() -> None:
    """BUG-002: `gate` never holds more than its single slot."""
    run = run_simulation(build_gate_and_restricted_hub(), 3)

    assert peak_hub_occupancy(run)["gate"] <= 1


def test_simultaneous_multi_turn_arrivals_respect_capacity() -> None:
    """BUG-001: `slow` never holds more than its single slot."""
    run = run_simulation(build_gate_and_restricted_hub(), 3)

    assert peak_hub_occupancy(run)["slow"] <= 1


def test_restricted_hub_with_room_for_two_is_not_overfilled() -> None:
    """BUG-001 with a larger hub: six aircraft, a restricted hub for two."""
    graph = build_graph(
        [
            start_hub(),
            hub("slow", ZoneType.RESTRICTED, capacity=2),
            hub("side", ZoneType.PRIORITY, capacity=3),
            end_hub(),
        ],
        [
            Link("slow", "goal", capacity=2),
            Link("start", "side", capacity=2),
            Link("slow", "start", capacity=3),
        ],
    )

    run = run_simulation(graph, 6)

    assert peak_hub_occupancy(run)["slow"] <= 2
