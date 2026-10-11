"""Lane styling of the geographic dispatch-center view: capacity widths and
shades, draw order and outlines, lane geometry, and dashed closed lanes.
Runs headless."""

import math
from typing import Any

import pygame
import pytest

from airlanes.events import EventDispatcher
from airlanes.model.connection import Connection
from airlanes.model.transport_mode import TransportMode
from airlanes.model.zone import Zone
from airlanes.output.pygame.airlines import (
    AirlinesWindow,
    PygameAirlinesVisualizer,
)
from airlanes.output.pygame.lanes import (
    OUTLINE_COLOR,
    WEATHER_SHADES,
    LaneStroke,
    dash_segments,
    draw_lanes,
    lane_color,
    lane_width,
    offset_line,
    parallel_offsets,
)
from airlanes.simulation.engine import Simulator
from airlanes.world.weather import ScriptedWeather, WeatherCondition

from tests.support.graphs import Link, build_graph


def luminance(color: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        v = value / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


@pytest.mark.parametrize(
    ("capacity", "width"), [(1, 3), (2, 4), (3, 4), (5, 5), (10, 5)]
)
def test_lane_width_follows_the_capacity_class(
    capacity: int, width: int
) -> None:
    assert lane_width(capacity) == width


def test_no_lane_is_wider_than_five_pixels() -> None:
    assert max(lane_width(capacity) for capacity in range(1, 50)) == 5


@pytest.mark.parametrize("condition", sorted(WEATHER_SHADES))
def test_a_larger_capacity_class_has_a_deeper_shade(condition: str) -> None:
    shades = [lane_color(condition, capacity) for capacity in (1, 2, 5, 10)]

    assert len(set(shades)) == 4
    darkness = [luminance(shade) for shade in shades]
    assert darkness == sorted(darkness, reverse=True)


def test_capacities_in_one_class_share_a_shade() -> None:
    assert lane_color("rain", 2) == lane_color("rain", 3)
    assert lane_color("rain", 4) == lane_color("rain", 6)
    assert lane_color("rain", 7) == lane_color("rain", 100)


def test_the_7_plus_class_differs_from_4_to_6_by_shade_only() -> None:
    assert lane_width(5) == lane_width(10)
    for condition in WEATHER_SHADES:
        assert lane_color(condition, 5) != lane_color(condition, 10)


def test_snow_and_rain_shades_never_meet() -> None:
    # The two blues differ only in lightness: the darkest snow stays
    # lighter than the lightest rain.
    darkest_snow = min(luminance(c) for c in WEATHER_SHADES["snow"])
    lightest_rain = max(luminance(c) for c in WEATHER_SHADES["rain"])
    assert darkest_snow > 2 * lightest_rain


def test_an_unknown_condition_is_drawn_as_clear() -> None:
    assert lane_color("fog", 3) == lane_color("clear", 3)


class LineRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def __call__(
        self, surface: Any, color: Any, start: Any, end: Any, width: int
    ) -> None:
        self.calls.append((tuple(color), start, end, width))


@pytest.fixture
def drawn(monkeypatch: pytest.MonkeyPatch) -> LineRecorder:
    recorder = LineRecorder()
    monkeypatch.setattr(pygame.draw, "line", recorder)
    return recorder


def stroke(width: int, color: tuple[int, int, int], y: float) -> LaneStroke:
    return LaneStroke((0.0, y), (100.0, y), color, width)


def test_lanes_are_drawn_with_their_width_inside_a_one_pixel_outline(
    drawn: LineRecorder,
) -> None:
    draw_lanes(pygame.Surface((1, 1)), [stroke(4, (1, 2, 3), 10)])

    assert drawn.calls == [
        (OUTLINE_COLOR, (0.0, 10), (100.0, 10), 6),
        ((1, 2, 3), (0.0, 10), (100.0, 10), 4),
    ]


def test_wide_lanes_go_first_and_outlines_go_under_every_lane(
    drawn: LineRecorder,
) -> None:
    narrow = stroke(3, (1, 1, 1), 1)
    wide = stroke(5, (2, 2, 2), 2)
    middle = stroke(4, (3, 3, 3), 3)

    draw_lanes(pygame.Surface((1, 1)), [narrow, wide, middle])

    assert [(color, width) for color, _, _, width in drawn.calls] == [
        (OUTLINE_COLOR, 7),
        (OUTLINE_COLOR, 6),
        (OUTLINE_COLOR, 5),
        ((2, 2, 2), 5),
        ((3, 3, 3), 4),
        ((1, 1, 1), 3),
    ]


def test_a_single_lane_has_no_offset() -> None:
    assert parallel_offsets(1) == [0.0]
    assert offset_line((10, 20), (50, 80), 0.0) == ((10.0, 20.0), (50.0, 80.0))


@pytest.mark.parametrize("count", [2, 3, 4])
def test_parallel_lanes_are_spread_symmetrically(count: int) -> None:
    offsets = parallel_offsets(count)

    assert len(set(offsets)) == count
    assert sum(offsets) == pytest.approx(0.0)
    assert offsets == sorted(offsets)
    assert sorted(-o for o in offsets) == offsets


def test_an_offset_line_stays_parallel_at_the_offset_distance() -> None:
    start, end = offset_line((0, 0), (30, 40), 5.0)

    assert (end[0] - start[0], end[1] - start[1]) == pytest.approx((30, 40))
    # Distance from the original line through the origin along (30, 40).
    assert abs(30 * start[1] - 40 * start[0]) / 50 == pytest.approx(5.0)


def window_over(
    monkeypatch: pytest.MonkeyPatch,
    zones: list[Zone],
    connections: list[tuple[str, str, int]],
    weather: ScriptedWeather | None = None,
) -> AirlinesWindow:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    graph = build_graph(zones, [])
    for a, b, capacity in connections:
        zone_a, zone_b = graph.zones[a], graph.zones[b]
        connection = Connection(zone_a, zone_b, capacity)
        connection.distance = 100
        graph.add_connection(connection)
    viewer = PygameAirlinesVisualizer(graph)
    dispatcher = EventDispatcher()
    dispatcher.add_listener(viewer)
    Simulator(graph, 1, dispatcher, weather=weather).run()
    window = AirlinesWindow(viewer)
    return window


def geo_hubs() -> list[Zone]:
    return [
        Zone("start", 100, 100, is_start=True),
        Zone("mid", 300, 100),
        Zone("goal", 300, 400, is_end=True),
    ]


def test_dispatch_center_lanes_join_hub_centres_with_capacity_style(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = window_over(
        monkeypatch, geo_hubs(), [("start", "mid", 1), ("mid", "goal", 5)]
    )
    try:
        strokes = window._lane_strokes()
    finally:
        pygame.quit()

    # Each lane runs between the centres of its hubs, from the hub whose
    # name sorts first.
    assert strokes == [
        LaneStroke((300.0, 100.0), (100.0, 100.0), lane_color("clear", 1), 3),
        LaneStroke((300.0, 400.0), (300.0, 100.0), lane_color("clear", 5), 5),
    ]


def test_lane_colour_follows_the_replayed_weather(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weather = ScriptedWeather({2: {"mid-goal": WeatherCondition.RAIN}})
    window = window_over(
        monkeypatch,
        geo_hubs(),
        [("start", "mid", 1), ("mid", "goal", 2)],
        weather,
    )
    try:
        window._goto_turn(1)
        before = window._lane_strokes()[1].color
        window._goto_turn(2)
        during = window._lane_strokes()[1].color
    finally:
        pygame.quit()

    assert before == lane_color("clear", 2)
    assert during == lane_color("rain", 2)


def test_parallel_connections_are_drawn_apart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = window_over(
        monkeypatch,
        geo_hubs(),
        [("start", "mid", 1), ("mid", "start", 1), ("mid", "goal", 1)],
    )
    try:
        strokes = window._lane_strokes()
    finally:
        pygame.quit()

    first, second = strokes[0], strokes[1]
    # Lanes between start (100, 100) and mid (300, 100) are horizontal:
    # spread 7 px apart, symmetric around y = 100, and as long as the gap
    # between the hubs.
    assert sorted([first.start[1], second.start[1]]) == [96.5, 103.5]
    for lane in (first, second):
        assert lane.start[1] == lane.end[1]
        assert math.dist(lane.start, lane.end) == pytest.approx(200)


def test_dashes_follow_the_lane_with_regular_gaps() -> None:
    segments = list(dash_segments((0.0, 0.0), (40.0, 0.0)))

    assert segments == [
        ((0.0, 0.0), (10.0, 0.0)),
        ((17.0, 0.0), (27.0, 0.0)),
        ((34.0, 0.0), (40.0, 0.0)),
    ]


def test_a_closed_lane_is_drawn_as_outlined_dashes(
    drawn: LineRecorder,
) -> None:
    closed = LaneStroke((0.0, 5.0), (40.0, 5.0), (9, 9, 9), 3, closed=True)

    draw_lanes(pygame.Surface((1, 1)), [closed])

    outlines = [c for c in drawn.calls if c[0] == OUTLINE_COLOR]
    dashes = [c for c in drawn.calls if c[0] == (9, 9, 9)]
    assert len(outlines) == len(dashes) == 3
    assert [(start, end) for _, start, end, _ in dashes] == [
        ((0.0, 5.0), (10.0, 5.0)),
        ((17.0, 5.0), (27.0, 5.0)),
        ((34.0, 5.0), (40.0, 5.0)),
    ]
    assert {width for _, _, _, width in outlines} == {5}


def closure_by_turn(
    monkeypatch: pytest.MonkeyPatch, mode: TransportMode
) -> list[bool]:
    """Whether the start-mid lane is drawn dashed, from the initial state
    through each replayed turn. Storm from turn 2, clear again on turn 4."""
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    graph = build_graph(
        [
            Zone("start", 100, 100, is_start=True),
            Zone("mid", 300, 100),
            Zone("goal", 300, 400, is_end=True),
        ],
        [
            Link("start", "mid", distance=100, mode=mode),
            Link("mid", "goal", distance=100),
        ],
    )
    viewer = PygameAirlinesVisualizer(graph)
    dispatcher = EventDispatcher()
    dispatcher.add_listener(viewer)
    weather = ScriptedWeather(
        {
            2: {"start-mid": WeatherCondition.STORM},
            4: {"start-mid": WeatherCondition.CLEAR},
        }
    )
    # Four aircraft through single-capacity hubs keep the run going past
    # turn 4.
    Simulator(graph, 4, dispatcher, weather=weather).run()
    window = AirlinesWindow(viewer)
    try:
        dashed = []
        for turn in range(min(6, len(window.turn_indices))):
            window._goto_turn(turn)
            dashed.append(window._lane_strokes()[0].closed)
    finally:
        pygame.quit()
    return dashed


def test_an_air_lane_is_dashed_while_the_simulator_reports_it_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert closure_by_turn(monkeypatch, TransportMode.AIR) == [
        False, False, True, True, False, False,
    ]


def test_a_road_lane_stays_solid_in_a_storm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert closure_by_turn(monkeypatch, TransportMode.ROAD) == [False] * 6
