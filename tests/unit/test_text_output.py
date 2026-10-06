"""Assignment-style text output rendered from turn results (ADR-024).

The result says what happened; the renderer decides what the assignment's
format shows: lanes for legs that start, hubs for legs that finish, and
nothing for reroutes.
"""

import pytest

from airlanes.output.text import Visualizer, movement_tokens
from airlanes.results import Arrival, Departure, Reroute, TurnResult

from tests.support.graphs import Link, build_graph, end_hub, hub, start_hub

GRAPH = build_graph(
    [start_hub(), hub("a"), end_hub()],
    [Link("start", "a"), Link("a", "goal", distance=900)],
)


def render(*outcomes: Departure | Arrival | Reroute) -> str:
    return Visualizer(GRAPH).render_turn(TurnResult(1, outcomes))


def test_a_departure_shows_its_lane() -> None:
    assert render(Departure("D1", "a", "goal", "a-goal")) == "D1-a-goal"


def test_an_arrival_shows_its_hub() -> None:
    assert render(Arrival("D1", "a", "goal", "a-goal")) == "D1-goal"


def test_a_one_turn_leg_is_shown_once_by_its_arrival() -> None:
    assert render(
        Departure("D1", "start", "a", "start-a"),
        Arrival("D1", "start", "a", "start-a"),
        Departure("D2", "a", "goal", "a-goal"),
    ) == "D1-a D2-a-goal"


def test_reroutes_are_not_shown() -> None:
    assert render(Reroute("D1", "a", ("goal",), ("start", "goal"))) == ""
    assert render(
        Reroute("D1", "a", ("goal",), ("start", "goal")),
        Departure("D1", "a", "start", "start-a"),
    ) == "D1-start-a"


def test_a_turn_without_outcomes_shows_nothing() -> None:
    assert render() == ""


def test_tokens_follow_the_order_of_the_outcomes() -> None:
    result = TurnResult(
        4,
        (
            Arrival("D2", "a", "goal", "a-goal"),
            Departure("D3", "start", "a", "start-a"),
            Arrival("D3", "start", "a", "start-a"),
            Departure("D1", "a", "goal", "a-goal"),
        ),
    )

    assert movement_tokens(result) == (
        ("D2", "goal"),
        ("D3", "a"),
        ("D1", "a-goal"),
    )


@pytest.mark.parametrize(
    "lane",
    [
        pytest.param(
            Link("start", "goal", distance=900), id="declared-forward"
        ),
        pytest.param(
            Link("goal", "start", distance=900), id="declared-reverse"
        ),
    ],
)
def test_a_departure_is_colored_by_its_destination(lane: Link) -> None:
    """The lane name follows the map's declaration order, so it says
    nothing about direction; the color comes from where the leg goes
    (BUG-008)."""
    graph = build_graph([start_hub(), end_hub()], [lane])
    graph.zones["start"].color = "red"
    graph.zones["goal"].color = "blue"
    lane_name = f"{lane.zone_a}-{lane.zone_b}"
    result = TurnResult(1, (Departure("D1", "start", "goal", lane_name),))

    assert Visualizer(graph, use_color=True).render_turn(result) == (
        f"\033[34mD1-{lane_name}\033[0m"
    )
