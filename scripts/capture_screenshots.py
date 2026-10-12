"""
Capture the README screenshots from the Pygame viewers, headless.

Each screenshot is the window surface of one replayed turn, saved without
an operating-system frame. Weather comes from a fixed seed, flight numbers
from a fixed seed of the global generator, and the clock behind the
rainbow hub colour is frozen, so the same environment always produces the
same PNG files. Fonts come from the system, so other machines may render
text differently.

Usage: uv run --locked python -m scripts.capture_screenshots [OUT_DIR]
(default docs/images; `make screenshots`).
"""
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import random
import sys
import time

import pygame

from airlanes.events import EventDispatcher
from airlanes.mapfile import Parser
from airlanes.output.pygame.airlines import (
    AirlinesWindow,
    PygameAirlinesVisualizer,
    view_for,
)
from airlanes.output.pygame.standard import (
    DroneSimulationWindow,
    PygameStandardVisualizer,
)
from airlanes.simulation.engine import Simulator
from airlanes.world.weather import RandomWeather

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "images"

# Seed of the global generator, which draws the flight numbers.
FLIGHT_NUMBER_SEED = 0
# Any fixed time; the rainbow hub colour is a function of it.
FROZEN_CLOCK = 1000.0


@dataclass(frozen=True)
class Shot:
    file_name: str
    map_path: str
    turn: int
    # Weather seed of the dispatch center; None for the standard viewer,
    # which runs without weather.
    weather_seed: int | None


SHOTS = (
    Shot("europe-simulation.png", "maps/bonus/europa_map.txt", 13, 39),
    Shot("germany-simulation.png", "maps/bonus/germany_map.txt", 9, 11),
    Shot(
        "challenger-turn-viewer.png",
        "maps/challenger/01_the_impossible_dream.txt",
        24,
        None,
    ),
)


@contextmanager
def headless() -> Iterator[None]:
    """SDL's dummy video driver, so no window opens, and a frozen clock."""
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
    real_time = time.time
    time.time = lambda: FROZEN_CLOCK
    try:
        yield
    finally:
        time.time = real_time


def dispatch_center(shot: Shot) -> AirlinesWindow:
    """The dispatch center of a seeded run, at the shot's turn. Call it
    inside `headless()`."""
    graph, nb_aircraft = Parser().parse(str(REPO_ROOT / shot.map_path))
    viewer = PygameAirlinesVisualizer(graph)
    dispatcher = EventDispatcher()
    dispatcher.add_listener(viewer)
    weather = RandomWeather(graph, seed=shot.weather_seed)
    Simulator(graph, nb_aircraft, dispatcher, weather=weather).run()

    random.seed(FLIGHT_NUMBER_SEED)
    window = AirlinesWindow(viewer, view_for(shot.map_path))
    window.is_playing = False
    window._goto_turn(shot.turn)
    return window


def turn_viewer(shot: Shot) -> DroneSimulationWindow:
    """The standard turn viewer of the shot's map. Call it inside
    `headless()`."""
    graph, nb_aircraft = Parser().parse(str(REPO_ROOT / shot.map_path))
    viewer = PygameStandardVisualizer(graph, nb_aircraft)
    dispatcher = EventDispatcher()
    dispatcher.add_listener(viewer)
    Simulator(graph, nb_aircraft, dispatcher).run()

    window = DroneSimulationWindow(viewer)
    window.autoplay = False
    return window


def capture(shot: Shot, out_dir: Path) -> str:
    """Save the shot as a PNG in `out_dir`; return its SHA-256."""
    path = out_dir / shot.file_name
    with headless():
        try:
            if shot.weather_seed is None:
                viewer = turn_viewer(shot)
                viewer.draw(viewer.frames[shot.turn])
                surface = viewer.screen
            else:
                window = dispatch_center(shot)
                window.draw()
                surface = window.screen
            pygame.image.save(surface, str(path))
        finally:
            pygame.quit()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str]) -> int:
    out_dir = Path(argv[0]) if argv else DEFAULT_OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    for shot in SHOTS:
        digest = capture(shot, out_dir)
        print(f"{digest}  {out_dir / shot.file_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
