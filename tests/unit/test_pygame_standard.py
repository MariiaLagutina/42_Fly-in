"""Standard Pygame viewer: the caption of a turn without movement (BUG-010).

Runs headless with SDL's dummy video driver and records the text the
history bar renders.
"""

import pygame
import pytest

from airlanes.events import EventDispatcher
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
        (0, ["Initial state (all drones at base)"]),
        (2, ["No departures or arrivals this turn"]),
    ]
