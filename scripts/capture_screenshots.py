"""
Capture the README screenshots and animations from the Pygame viewers,
headless.

A screenshot is the window surface of one replayed turn, or a 1:1 crop of
it, saved without an operating-system frame. An animation is one frame
per consecutive turn of a single run, nothing in between, saved as a
looping GIF. Weather comes from a fixed seed, flight numbers from a fixed
seed of a local generator, and the clock behind the rainbow hub colour
is frozen, so the same environment always produces the same files. Fonts
come from the system, so other machines may render text differently.

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

from PIL import Image
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

# Seed of the local generator, which draws the flight numbers.
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
    # (left, top, width, height) of a 1:1 crop of the window; None keeps
    # the whole window.
    crop: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class Animation:
    """Consecutive turns of one dispatch-center run, first to last."""
    file_name: str
    map_path: str
    weather_seed: int
    first_turn: int
    last_turn: int


GERMANY = "maps/bonus/germany_map.txt"
EUROPE = "maps/bonus/europa_map.txt"

SHOTS = (
    Shot("europe-simulation.png", EUROPE, 22, 25),
    # A crop of the Germany animation's turn 9, around Hamburg and Berlin.
    Shot("germany-detail.png", GERMANY, 9, 46, crop=(360, 70, 480, 400)),
    Shot(
        "challenger-turn-viewer.png",
        "maps/challenger/01_the_impossible_dream.txt",
        24,
        None,
    ),
)

ANIMATIONS = (
    Animation("germany-dispatch-center.gif", GERMANY, 46, 3, 13),
    Animation("europe-dispatch-center.gif", EUROPE, 59, 15, 25),
)

# Display time of each turn, and of the last turn before the loop starts
# again.
FRAME_MS = 1200
HOLD_MS = 2500


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


def seeded_dispatch_center(
    map_path: str, weather_seed: int | None
) -> AirlinesWindow:
    """The dispatch center over a finished run with seeded weather. Call it
    inside `headless()`."""
    graph, nb_aircraft = Parser().parse(str(REPO_ROOT / map_path))
    viewer = PygameAirlinesVisualizer(graph)
    dispatcher = EventDispatcher()
    dispatcher.add_listener(viewer)
    weather = RandomWeather(graph, seed=weather_seed)
    Simulator(graph, nb_aircraft, dispatcher, weather=weather).run()

    return AirlinesWindow(
        viewer, view_for(map_path), rng=random.Random(FLIGHT_NUMBER_SEED)
    )


def dispatch_center(shot: Shot) -> AirlinesWindow:
    """The dispatch center paused at the shot's turn. Call it inside
    `headless()`."""
    window = seeded_dispatch_center(shot.map_path, shot.weather_seed)
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
            if shot.crop is not None:
                surface = surface.subsurface(pygame.Rect(shot.crop))
            pygame.image.save(surface, str(path))
        finally:
            pygame.quit()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def animation_frames(animation: Animation) -> list[Image.Image]:
    """One image of the whole window per turn, first to last."""
    frames = []
    with headless():
        try:
            window = seeded_dispatch_center(
                animation.map_path, animation.weather_seed
            )
            # The window plays the turns, as in autoplay.
            window.is_playing = True
            for turn in range(animation.first_turn, animation.last_turn + 1):
                window._goto_turn(turn)
                window.draw()
                frames.append(
                    Image.frombytes(
                        "RGB",
                        window.screen.get_size(),
                        pygame.image.tobytes(window.screen, "RGB"),
                    )
                )
        finally:
            pygame.quit()
    return frames


def capture_animation(animation: Animation, out_dir: Path) -> str:
    """Save the animation as a looping GIF in `out_dir`; return its
    SHA-256."""
    frames = animation_frames(animation)
    # One palette for every frame, taken from the first and the middle
    # turn, so colours do not flicker from turn to turn.
    width, height = frames[0].size
    sample = Image.new("RGB", (width, height * 2))
    sample.paste(frames[0], (0, 0))
    sample.paste(frames[len(frames) // 2], (0, height))
    palette = sample.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    images = [
        frame.quantize(palette=palette, dither=Image.Dither.NONE)
        for frame in frames
    ]
    path = out_dir / animation.file_name
    images[0].save(
        path,
        save_all=True,
        append_images=images[1:],
        duration=[FRAME_MS] * (len(images) - 1) + [HOLD_MS],
        loop=0,
        optimize=True,
        disposal=1,
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str]) -> int:
    out_dir = Path(argv[0]) if argv else DEFAULT_OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    for shot in SHOTS:
        digest = capture(shot, out_dir)
        print(f"{digest}  {out_dir / shot.file_name}")
    for animation in ANIMATIONS:
        digest = capture_animation(animation, out_dir)
        print(f"{digest}  {out_dir / animation.file_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
