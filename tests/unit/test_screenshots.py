"""README screenshots and animations: capture is reproducible, and what
each caption says is drawn in the captured turns. Runs headless."""

import hashlib
from pathlib import Path

from PIL import Image, ImageSequence
import pygame
import pytest

from airlanes.events import AgentRerouted
from airlanes.model.transport_mode import TransportMode
from airlanes.output.pygame.airlines import AirlinesWindow
from airlanes.output.pygame.lanes import capacity_class
from scripts.capture_screenshots import (
    ANIMATIONS,
    FRAME_MS,
    HOLD_MS,
    SHOTS,
    Animation,
    Shot,
    capture,
    capture_animation,
    dispatch_center,
    headless,
    seeded_dispatch_center,
    turn_viewer,
)


def shot(file_name: str) -> Shot:
    return next(s for s in SHOTS if s.file_name == file_name)


def animation(file_name: str) -> Animation:
    return next(a for a in ANIMATIONS if a.file_name == file_name)


def test_capturing_screenshots_twice_gives_identical_files(
    tmp_path: Path,
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()

    for s in SHOTS:
        digest = capture(s, first)
        assert capture(s, second) == digest
        assert hashlib.sha256(
            (first / s.file_name).read_bytes()
        ).hexdigest() == digest
        image = pygame.image.load(first / s.file_name)
        if s.crop is not None:
            assert image.get_size() == (s.crop[2], s.crop[3])
        else:
            assert image.get_height() == 800


@pytest.mark.parametrize("a", ANIMATIONS, ids=lambda a: a.file_name)
def test_an_animation_has_one_frame_per_turn_and_is_reproducible(
    tmp_path: Path, a: Animation
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()

    assert capture_animation(a, first) == capture_animation(a, second)
    gif = Image.open(first / a.file_name)
    assert gif.size == (1350, 800)
    assert gif.info["loop"] == 0
    # The iterator moves one image through the frames; read each frame's
    # duration while it is current.
    durations = [
        frame.info["duration"] for frame in ImageSequence.Iterator(gif)
    ]
    assert len(durations) == a.last_turn - a.first_turn + 1
    assert durations == [FRAME_MS] * (len(durations) - 1) + [HOLD_MS]


class RecordingFont:
    def __init__(self, font: pygame.font.Font) -> None:
        self.font = font
        self.texts: list[str] = []

    def render(
        self, text: str, antialias: bool, color: tuple[int, int, int]
    ) -> pygame.Surface:
        self.texts.append(text)
        return self.font.render(text, antialias, color)


def board_statuses(window: AirlinesWindow) -> list[str]:
    """The statuses drawn on the visible part of the departure board."""
    font = window.badge_font
    recorder = RecordingFont(font)
    window.badge_font = recorder  # type: ignore[assignment]
    try:
        window._draw_sidebar()
    finally:
        window.badge_font = font
    # The other badge on a card is the aircraft label, "(D1)".
    return [t for t in recorder.texts if not t.startswith("(")]


def lane_states(window: AirlinesWindow) -> list[tuple[str, bool]]:
    """(weather, closed) of every lane."""
    return [
        (
            window.connection_weather.get(lane.name(), "clear"),
            not window.connection_open.get(lane.name(), True),
        )
        for lane in window.graph.connections
    ]


def vehicles_in_transit(
    window: AirlinesWindow,
) -> list[tuple[int, int, bool]]:
    """(x, y, is_car) of every vehicle group drawn on a lane."""
    groups = window._group_vehicles_by_point()
    return [
        (point[0], point[1], is_car)
        for (point, is_car), labels in groups.items()
        if window.drone_positions[labels[0]].kind == "connection"
    ]


def test_the_europe_shot_shows_all_weather_closures_and_a_reroute() -> None:
    with headless():
        try:
            window = dispatch_center(shot("europe-simulation.png"))
            states = lane_states(window)
            statuses = board_statuses(window)
            planes = vehicles_in_transit(window)
        finally:
            pygame.quit()

    assert {w for w, _ in states} == {
        "clear", "rain", "snow", "storm", "tailwind"
    }
    assert {w for w, closed in states if closed} == {"snow", "storm"}
    assert "WEATHER REROUTE" in statuses
    assert len(planes) >= 3


def test_the_germany_detail_shows_cars_roads_and_a_closed_air_lane() -> None:
    s = shot("germany-detail.png")
    assert s.crop is not None
    left, top, width, height = s.crop

    def inside(x: float, y: float) -> bool:
        return left <= x < left + width and top <= y < top + height

    with headless():
        try:
            window = dispatch_center(s)
            cars = [
                (x, y) for x, y, car in vehicles_in_transit(window) if car
            ]
            shown = [
                lane for lane in window.graph.connections
                if inside(lane.zone_a.x, lane.zone_a.y)
                and inside(lane.zone_b.x, lane.zone_b.y)
            ]
            closed_air = [
                lane for lane in shown
                if lane.mode is TransportMode.AIR
                and not window.connection_open.get(lane.name(), True)
            ]
        finally:
            pygame.quit()

    assert sum(inside(x, y) for x, y in cars) >= 3
    assert {lane.mode for lane in shown} == {
        TransportMode.AIR, TransportMode.ROAD
    }
    assert {capacity_class(lane.max_link_capacity) for lane in shown} >= {
        0, 1
    }
    assert closed_air


def test_the_germany_detail_is_a_frame_of_the_germany_animation() -> None:
    detail = shot("germany-detail.png")
    germany = animation("germany-dispatch-center.gif")

    assert (detail.map_path, detail.weather_seed) == (
        germany.map_path, germany.weather_seed
    )
    assert germany.first_turn <= detail.turn <= germany.last_turn


Frame = tuple[int, list[tuple[str, bool]], list[str], list[bool]]


def animation_turns(a: Animation) -> list[Frame]:
    """(turn, lane states, board statuses, is_car of each vehicle in
    transit) for every frame of the animation."""
    rows = []
    with headless():
        try:
            window = seeded_dispatch_center(a.map_path, a.weather_seed)
            for turn in range(a.first_turn, a.last_turn + 1):
                window._goto_turn(turn)
                rows.append(
                    (
                        window.current_turn,
                        lane_states(window),
                        board_statuses(window),
                        [car for _, _, car in vehicles_in_transit(window)],
                    )
                )
        finally:
            pygame.quit()
    return rows


def test_the_germany_animation_shows_closures_cars_and_reroutes() -> None:
    a = animation("germany-dispatch-center.gif")
    rows = animation_turns(a)

    assert [turn for turn, _, _, _ in rows] == list(
        range(a.first_turn, a.last_turn + 1)
    )
    closed = [sum(c for _, c in states) for _, states, _, _ in rows]
    # Air lanes close and reopen: the count rises, then reaches zero.
    assert max(closed) >= 3 and closed[-1] == 0
    assert all(any(vehicles) for _, _, _, vehicles in rows)
    assert any(not car for _, _, _, vehicles in rows for car in vehicles)
    assert any("WEATHER REROUTE" in board for _, _, board, _ in rows)


def test_the_europe_animation_shows_traffic_closures_and_reroutes() -> None:
    a = animation("europe-dispatch-center.gif")
    rows = animation_turns(a)

    closed = {sum(c for _, c in states) for _, states, _, _ in rows}
    assert len(closed) > 1
    assert all(len(vehicles) >= 2 for _, _, _, vehicles in rows)
    assert all("WEATHER REROUTE" in board for _, _, board, _ in rows)


@pytest.mark.parametrize("a", ANIMATIONS, ids=lambda a: a.file_name)
def test_the_animated_reroutes_are_weather_reroutes(a: Animation) -> None:
    with headless():
        try:
            window = seeded_dispatch_center(a.map_path, a.weather_seed)
            reroutes = [
                e for e in window.visualizer.event_queue
                if isinstance(e, AgentRerouted)
                and a.first_turn <= e.turn_number <= a.last_turn
            ]
        finally:
            pygame.quit()

    assert reroutes
    assert {e.reason for e in reroutes} == {"weather"}


def test_the_challenger_shot_shows_a_busy_turn_with_active_lanes() -> None:
    s = shot("challenger-turn-viewer.png")
    with headless():
        try:
            window = turn_viewer(s)
            frame = window.frames[s.turn]
            active, _ = window._active_connections(frame)
        finally:
            pygame.quit()

    assert frame.turn_number == s.turn
    assert len(active) >= 2
    assert len(frame.movements) >= 15


@pytest.mark.parametrize(
    "s",
    [s for s in SHOTS if s.weather_seed is not None],
    ids=lambda s: s.file_name,
)
def test_geographic_shots_use_their_map_background(s: Shot) -> None:
    with headless():
        try:
            window = dispatch_center(s)
        finally:
            pygame.quit()
    assert window.bg_image is not None
