"""README screenshots: capture is reproducible, and each captured turn shows
what its README caption says. Runs headless."""

import hashlib
from pathlib import Path

import pygame
import pytest

from airlanes.events import AgentRerouted
from airlanes.model.transport_mode import TransportMode
from airlanes.output.pygame.lanes import capacity_class
from scripts.capture_screenshots import (
    SHOTS,
    Shot,
    capture,
    dispatch_center,
    headless,
    turn_viewer,
)


def shot(file_name: str) -> Shot:
    return next(s for s in SHOTS if s.file_name == file_name)


def test_capturing_twice_gives_identical_files(tmp_path: Path) -> None:
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
        assert image.get_width() >= 1200 and image.get_height() == 800


def lane_facts(file_name: str) -> list[tuple[TransportMode, int, str, bool]]:
    """(mode, capacity class, weather, closed) of every lane in the shot."""
    with headless():
        try:
            window = dispatch_center(shot(file_name))
            return [
                (
                    lane.mode,
                    capacity_class(lane.max_link_capacity),
                    window.connection_weather.get(lane.name(), "clear"),
                    not window.connection_open.get(lane.name(), True),
                )
                for lane in window.graph.connections
            ]
        finally:
            pygame.quit()


def test_the_europe_shot_shows_weather_closures_and_capacities() -> None:
    lanes = lane_facts("europe-simulation.png")

    assert {capacity for _, capacity, _, _ in lanes} >= {0, 1}
    closed = {weather for _, _, weather, closed in lanes if closed}
    assert closed == {"snow", "storm"}
    assert any(w == "rain" and not c for _, _, w, c in lanes)


def test_the_germany_shot_shows_air_and_road_under_weather() -> None:
    lanes = lane_facts("germany-simulation.png")

    assert {capacity for _, capacity, _, _ in lanes} == {0, 1}
    assert any(
        mode is TransportMode.AIR and weather == "snow" and closed
        for mode, _, weather, closed in lanes
    )
    assert any(
        mode is TransportMode.ROAD and weather == "snow" and not closed
        for mode, _, weather, closed in lanes
    )


def test_the_germany_shot_shows_a_car_and_a_weather_reroute() -> None:
    with headless():
        try:
            window = dispatch_center(shot("germany-simulation.png"))
            groups = window._group_vehicles_by_point()
            cars = [car for (_, car) in groups if car]
            statuses = {
                window._determine_flight_status(label, info)[0]
                for label, info in window.flight_data.items()
            }
            reroutes = [
                e for e in window.visualizer.event_queue
                if isinstance(e, AgentRerouted) and e.reason == "weather"
            ]
        finally:
            pygame.quit()

    assert cars
    assert "WEATHER REROUTE" in statuses
    assert reroutes


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
