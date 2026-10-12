"""Standard Pygame viewer: the window title, the caption of a turn without
movement (BUG-010), and the unchanged drawing of the original maps.

Runs headless with SDL's dummy video driver and records the text the
history bar renders and the shapes the viewer draws.
"""

import hashlib
from pathlib import Path
import time
from typing import Any

import pygame
import pytest

from airlanes.events import EventDispatcher
from airlanes.mapfile import Parser
from airlanes.output.pygame.standard import (
    DroneSimulationWindow,
    PygameStandardVisualizer,
)
from airlanes.simulation.engine import Simulator

from tests.support.graphs import Link, build_graph, end_hub, start_hub


class RecordingFont:
    def __init__(self, font: pygame.font.Font) -> None:
        self.font = font
        self.texts: list[str] = []

    def render(
        self, text: str, antialias: bool, color: tuple[int, int, int]
    ) -> pygame.Surface:
        self.texts.append(text)
        return self.font.render(text, antialias, color)


def test_only_the_frame_before_the_first_turn_is_the_initial_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 900 km air leg takes 3 turns. On turn 2 the aircraft is in the
    air: the turn completed, but nothing departed or arrived."""
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    graph = build_graph(
        [start_hub(), end_hub()], [Link("start", "goal", distance=900)]
    )
    viewer = PygameStandardVisualizer(graph, 1)
    dispatcher = EventDispatcher()
    dispatcher.add_listener(viewer)
    Simulator(graph, 1, dispatcher).run()

    window = DroneSimulationWindow(viewer)
    try:
        font = window.text_font
        captions = []
        for frame in (window.frames[0], window.frames[2]):
            recorder = RecordingFont(font)
            monkeypatch.setattr(window, "text_font", recorder)
            window._draw_history_bar(frame)
            captions.append((frame.turn_number, recorder.texts))
    finally:
        pygame.quit()

    assert captions == [
        (0, ["Initial state (all aircraft at the start hub)"]),
        (2, ["No departures or arrivals this turn"]),
    ]


def test_the_window_is_titled_after_the_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    graph = build_graph([start_hub(), end_hub()], [Link("start", "goal")])
    viewer = PygameStandardVisualizer(graph, 1)
    dispatcher = EventDispatcher()
    dispatcher.add_listener(viewer)
    Simulator(graph, 1, dispatcher).run()

    DroneSimulationWindow(viewer)
    try:
        title, _icon_title = pygame.display.get_caption()
    finally:
        pygame.quit()

    assert title == "Mariia's Airlanes — Turn Viewer"


REPO_ROOT = Path(__file__).resolve().parents[2]

# The standard viewer's lanes and hubs on the original challenge maps, as
# drawn before the geographic lane styling (Stage 9b base, 3cc1360). The
# geographic styling must never reach this viewer.
ORIGINAL_MAP_DRAWING = {
    "easy/01_linear_path.txt":
        "f75af825d24b62dbb98db451ec3137da211b891e4191e69be185806a91263d74",
    "easy/02_simple_fork.txt":
        "ad3040aa00cd03d5508b1dc86a66714581b37c4c2986a4a33e2ab45c2e1ba8d1",
    "easy/03_basic_capacity.txt":
        "146ab2ef3616a7d408ddb17c542f288ad5019f12d76e1dbf26949dad1d2b6706",
    "medium/01_dead_end_trap.txt":
        "bfde32455188d552ca49549358954747131383dc8c38646f03d83f4dbeeb9197",
    "medium/02_circular_loop.txt":
        "00936de8ae47f9e74d1ced223f9f25f42423dc95446595237a3342b45f278c04",
    "medium/03_priority_puzzle.txt":
        "79eb785afa9dd3fb1dc134a7b4ce844468f2191c9d9e99a464e19c4ab237e108",
    "hard/01_maze_nightmare.txt":
        "2c3b2db1e1241d94398d79661b93030d6f98510d317a43b1197d8148e261cc67",
    "hard/02_capacity_hell.txt":
        "580e513dfaad9949ed0bb1fe8808c4a0d3172329036733dda18d210f82cd3d0f",
    "hard/03_ultimate_challenge.txt":
        "3992dcd892a7c5dd3e582ec96ad91246dbbf2ed8cd836f73778288303be1575b",
    "challenger/01_the_impossible_dream.txt":
        "72c2e1f009dd1ec07b250ecea57ea6e2dfccda8fbd4852c33c7867a9629d1ffb",
}


def drawing_fingerprint(
    monkeypatch: pytest.MonkeyPatch, map_name: str
) -> str:
    """SHA-256 of every line and circle the viewer draws over all frames of
    the map: lane geometry, colours, widths, active lanes and hubs. Text
    is left out, as fonts differ between machines."""
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    # The rainbow hub colour follows the clock.
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    calls: list[tuple[Any, ...]] = []
    line, circle = pygame.draw.line, pygame.draw.circle

    def record_line(
        surface: pygame.Surface, color: Any, start: Any, end: Any,
        width: int = 1,
    ) -> pygame.Rect:
        calls.append(("line", tuple(color), tuple(start), tuple(end), width))
        return line(surface, color, start, end, width)

    def record_circle(
        surface: pygame.Surface, color: Any, center: Any, radius: float,
        width: int = 0,
    ) -> pygame.Rect:
        calls.append(("circle", tuple(color), tuple(center), radius, width))
        return circle(surface, color, center, radius, width)

    monkeypatch.setattr(pygame.draw, "line", record_line)
    monkeypatch.setattr(pygame.draw, "circle", record_circle)

    graph, nb_aircraft = Parser().parse(str(REPO_ROOT / "maps" / map_name))
    viewer = PygameStandardVisualizer(graph, nb_aircraft)
    dispatcher = EventDispatcher()
    dispatcher.add_listener(viewer)
    Simulator(graph, nb_aircraft, dispatcher).run()
    window = DroneSimulationWindow(viewer)
    digest = hashlib.sha256()
    try:
        for frame in window.frames:
            calls.clear()
            window.draw(frame)
            digest.update(repr(calls).encode())
    finally:
        pygame.quit()
    return digest.hexdigest()


@pytest.mark.parametrize("map_name", sorted(ORIGINAL_MAP_DRAWING))
def test_the_original_maps_keep_their_standard_drawing(
    monkeypatch: pytest.MonkeyPatch, map_name: str
) -> None:
    fingerprint = drawing_fingerprint(monkeypatch, map_name)

    assert fingerprint == ORIGINAL_MAP_DRAWING[map_name]
