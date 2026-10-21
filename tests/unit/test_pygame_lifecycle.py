"""Exclusive Airlines playback sessions, with dummy SDL and finite inputs."""
from collections.abc import Iterator
import random
import subprocess
import sys

import pygame
import pytest

from airlanes import cli
from airlanes.events import EventDispatcher
from airlanes.model.connection import Connection
from airlanes.output.pygame.airlines import (
    AirlinesWindow,
    PlaybackExit,
    PygameAirlinesVisualizer,
    run_pygame_airlines,
)
from airlanes.simulation.engine import Simulator
from tests.support.graphs import Link, build_graph, end_hub, start_hub


@pytest.fixture(autouse=True)
def dummy_sdl(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    pygame.quit()
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    yield
    pygame.quit()


@pytest.fixture
def viewer() -> PygameAirlinesVisualizer:
    graph = build_graph([start_hub(), end_hub()], [Link("start", "goal")])
    visualizer = PygameAirlinesVisualizer(graph)
    dispatcher = EventDispatcher()
    dispatcher.add_listener(visualizer)
    Simulator(graph, 2, dispatcher).run()
    return visualizer


@pytest.fixture
def screen() -> pygame.Surface:
    pygame.init()
    surface = pygame.display.set_mode((1350, 800))
    pygame.display.set_caption("Caller menu")
    return surface


def finite_inputs(
    monkeypatch: pytest.MonkeyPatch, batches: list[list[pygame.event.Event]]
) -> None:
    events = iter(batches)
    ticks = iter(range(0, 100000, 1001))
    monkeypatch.setattr(pygame.event, "get", lambda: next(events))
    monkeypatch.setattr(pygame.time, "get_ticks", lambda: next(ticks))


def closed() -> pygame.event.Event:
    return pygame.event.Event(pygame.QUIT)


def lane_state(lane: Connection) -> tuple[str, str, int, object, int]:
    return (
        lane.zone_a.name, lane.zone_b.name, lane.max_link_capacity,
        lane.mode, lane.distance,
    )


def assert_usable(screen: pygame.Surface) -> None:
    assert pygame.display.get_init()
    assert pygame.font.get_init()
    assert pygame.display.get_surface() is screen
    assert pygame.display.get_caption()[0] == "Caller menu"
    screen.fill((1, 2, 3))
    pygame.display.flip()
    assert pygame.font.SysFont("Arial", 12).render("Menu", True, "white")


@pytest.mark.parametrize("caller_owned", [False, True])
def test_completion_presents_final_frame_then_returns(
    monkeypatch: pytest.MonkeyPatch, viewer: PygameAirlinesVisualizer,
    screen: pygame.Surface, caller_owned: bool,
) -> None:
    finite_inputs(monkeypatch, [[], []])
    presented: list[int] = []
    draw = AirlinesWindow.draw
    flip = pygame.display.flip
    last_drawn: list[int] = []

    def record_draw(window: AirlinesWindow) -> None:
        draw(window)
        last_drawn.append(window.current_turn_index)

    def record_flip() -> None:
        flip()
        presented.append(last_drawn[-1])

    monkeypatch.setattr(AirlinesWindow, "draw", record_draw)
    monkeypatch.setattr(pygame.display, "flip", record_flip)
    assert run_pygame_airlines(
        viewer, screen=screen if caller_owned else None,
        return_on_completion=True,
    ) is PlaybackExit.COMPLETED
    assert presented == [1, 2]
    # This assertion also proves execution resumed after the call.
    if caller_owned:
        assert_usable(screen)
    else:
        assert not pygame.display.get_init()
        assert not pygame.font.get_init()


def test_default_holds_final_frame_and_accepts_reset(
    monkeypatch: pytest.MonkeyPatch, viewer: PygameAirlinesVisualizer,
    screen: pygame.Surface,
) -> None:
    finite_inputs(monkeypatch, [[], [], [], [pygame.event.Event(
        pygame.KEYDOWN, key=pygame.K_r,
    )], [closed()]])
    window = AirlinesWindow(viewer, screen=screen)
    frames: list[tuple[int, bool]] = []
    monkeypatch.setattr(window, "draw", lambda: frames.append(
        (window.current_turn_index, window.is_playing)
    ))
    assert window.run_loop() is PlaybackExit.CLOSED
    assert frames == [(1, True), (2, True), (2, False), (0, False)]
    assert_usable(screen)


@pytest.mark.parametrize("caller_owned", [False, True])
def test_close_precedes_completion_and_stops_updates(
    monkeypatch: pytest.MonkeyPatch, viewer: PygameAirlinesVisualizer,
    screen: pygame.Surface, caller_owned: bool,
) -> None:
    window = AirlinesWindow(viewer, screen=screen if caller_owned else None)
    window._goto_turn(len(window.turn_indices) - 1)
    finite_inputs(monkeypatch, [[closed(), pygame.event.Event(
        pygame.KEYDOWN, key=pygame.K_r,
    )]])

    def forbidden(*args: object) -> None:
        pytest.fail("update/draw/present after close")

    monkeypatch.setattr(window, "_goto_turn", forbidden)
    monkeypatch.setattr(window, "draw", forbidden)
    monkeypatch.setattr(pygame.display, "flip", forbidden)
    assert window.run_loop(return_on_completion=True) is PlaybackExit.CLOSED
    monkeypatch.undo()
    if caller_owned:
        assert_usable(screen)
    else:
        assert not pygame.display.get_init()


@pytest.mark.parametrize("caller_owned", [False, True])
@pytest.mark.parametrize("stage", ["constructor", "render"])
def test_ownership_on_failures(
    monkeypatch: pytest.MonkeyPatch, viewer: PygameAirlinesVisualizer,
    screen: pygame.Surface, caller_owned: bool, stage: str,
) -> None:
    def fail(window: AirlinesWindow) -> None:
        raise RuntimeError("injected failure")

    monkeypatch.setattr(
        AirlinesWindow, "_load_assets" if stage == "constructor" else "draw",
        fail,
    )
    finite_inputs(monkeypatch, [[]])
    with pytest.raises(RuntimeError, match="injected failure"):
        run_pygame_airlines(viewer, screen=screen if caller_owned else None)
    if caller_owned:
        assert_usable(screen)
    else:
        assert not pygame.display.get_init()
        assert not pygame.font.get_init()


def test_caller_mode_never_manages_pygame(
    monkeypatch: pytest.MonkeyPatch, viewer: PygameAirlinesVisualizer,
    screen: pygame.Surface,
) -> None:
    def forbidden(*args: object) -> None:
        pytest.fail("caller-owned Pygame was managed by Airlines")

    with monkeypatch.context() as guard:
        for owner, name in (
            (pygame, "init"), (pygame, "quit"),
            (pygame.display, "init"), (pygame.display, "quit"),
            (pygame.display, "set_mode"), (pygame.display, "set_caption"),
            (pygame.font, "init"),
        ):
            guard.setattr(owner, name, forbidden)
        finite_inputs(guard, [[closed()]])
        result = run_pygame_airlines(viewer, screen=screen)
        assert result is PlaybackExit.CLOSED
    assert_usable(screen)


@pytest.mark.parametrize("invalid", ["offscreen", "size", "font", "closed"])
def test_rejects_unsuitable_caller_display_without_cleanup(
    viewer: PygameAirlinesVisualizer, screen: pygame.Surface, invalid: str,
) -> None:
    supplied = screen
    if invalid == "offscreen":
        supplied = pygame.Surface((1350, 800))
    elif invalid == "size":
        supplied = pygame.display.set_mode((100, 100))
    elif invalid == "font":
        pygame.font.quit()
    else:
        pygame.display.quit()
    display_initialized = pygame.display.get_init()
    font_initialized = pygame.font.get_init()
    with pytest.raises(ValueError, match="initialized 1350 x 800"):
        AirlinesWindow(viewer, screen=supplied)
    assert pygame.display.get_init() == display_initialized
    assert pygame.font.get_init() == font_initialized
    if invalid == "offscreen":
        assert_usable(screen)


@pytest.mark.parametrize("caller_owned", [False, True])
def test_sequential_sessions_have_fresh_playback_state(
    monkeypatch: pytest.MonkeyPatch, viewer: PygameAirlinesVisualizer,
    screen: pygame.Surface, caller_owned: bool,
) -> None:
    for finish in (True, False, True):
        finite_inputs(monkeypatch, [[], []] if finish else [[closed()]])
        window = AirlinesWindow(
            viewer, screen=screen if caller_owned else None,
        )
        assert window.current_turn_index == 0
        assert window.connection_weather == {}
        assert window.is_playing
        assert window.run_loop(return_on_completion=True) is (
            PlaybackExit.COMPLETED if finish else PlaybackExit.CLOSED
        )
        if caller_owned:
            assert_usable(screen)
        else:
            assert not pygame.display.get_init()


def test_local_random_labels_and_replay_do_not_change_simulation(
    monkeypatch: pytest.MonkeyPatch, viewer: PygameAirlinesVisualizer,
    screen: pygame.Surface,
) -> None:
    saved = random.getstate()
    events = tuple(viewer.event_queue)
    zones = [vars(zone).copy() for zone in viewer.graph.zones.values()]
    lanes = [lane_state(lane) for lane in viewer.graph.connections]
    finite_inputs(monkeypatch, [[], []])
    window = AirlinesWindow(viewer, screen=screen, rng=random.Random(0))
    labels = [info["flight"] for info in window.flight_data.values()]
    assert labels == ["M876", "N141"]
    assert window.run_loop(return_on_completion=True) is PlaybackExit.COMPLETED
    other = AirlinesWindow(viewer, screen=screen, rng=random.Random(0))
    assert [info["flight"] for info in other.flight_data.values()] == labels
    AirlinesWindow(viewer, screen=screen)
    assert random.getstate() == saved
    assert tuple(viewer.event_queue) == events
    assert [vars(zone) for zone in viewer.graph.zones.values()] == zones
    assert [lane_state(lane) for lane in viewer.graph.connections] == lanes


def test_cli_returns_success_after_real_viewer_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finite_inputs(monkeypatch, [[closed()]])
    monkeypatch.setattr(sys, "argv", [
        "main.py", "maps/easy/01_linear_path.txt", "--pygame-airlines",
    ])
    assert cli.main() == cli.EXIT_OK
    assert not pygame.display.get_init()


@pytest.mark.parametrize("entry", ["main.py", "airlanes"])
def test_cli_entry_points_exit_zero_after_close(entry: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", """
import runpy
import sys
import pygame
entry = sys.argv[1]
sys.argv = [entry, 'maps/easy/01_linear_path.txt', '--pygame-airlines']
pygame.event.get = lambda: [pygame.event.Event(pygame.QUIT)]
if entry == 'main.py':
    runpy.run_path(entry, run_name='__main__')
else:
    runpy.run_module(entry, run_name='__main__')
raise RuntimeError('CLI entry point did not exit')
""", entry],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0
    assert result.stderr == ""


def test_partial_display_initialization_is_cleaned_up(
    monkeypatch: pytest.MonkeyPatch, viewer: PygameAirlinesVisualizer,
) -> None:
    def fail(size: tuple[int, int]) -> pygame.Surface:
        assert pygame.display.get_init()
        assert pygame.font.get_init()
        raise RuntimeError("display creation failed")

    monkeypatch.setattr(pygame.display, "set_mode", fail)
    with pytest.raises(RuntimeError, match="display creation failed"):
        AirlinesWindow(viewer)
    assert not pygame.display.get_init()
    assert not pygame.font.get_init()


@pytest.mark.parametrize("close", [False, True])
def test_empty_replay_presents_initial_frame_or_closes(
    monkeypatch: pytest.MonkeyPatch, screen: pygame.Surface, close: bool,
) -> None:
    graph = build_graph([start_hub(), end_hub()], [Link("start", "goal")])
    finite_inputs(monkeypatch, [[closed()]] if close else [[]])
    window = AirlinesWindow(PygameAirlinesVisualizer(graph), screen=screen)
    presented: list[bool] = []
    monkeypatch.setattr(pygame.display, "flip", lambda: presented.append(True))
    assert window.run_loop(return_on_completion=True) is (
        PlaybackExit.CLOSED if close else PlaybackExit.COMPLETED
    )
    assert presented == ([] if close else [True])


def test_close_in_batch_that_steps_to_final_frame_wins(
    monkeypatch: pytest.MonkeyPatch, viewer: PygameAirlinesVisualizer,
    screen: pygame.Surface,
) -> None:
    window = AirlinesWindow(viewer, screen=screen)
    window._goto_turn(len(window.turn_indices) - 2)
    finite_inputs(monkeypatch, [[
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT), closed(),
    ]])

    def forbidden() -> None:
        pytest.fail("final frame was drawn despite close")

    monkeypatch.setattr(window, "draw", forbidden)
    assert window.run_loop(return_on_completion=True) is PlaybackExit.CLOSED
    assert window.current_turn_index == len(window.turn_indices) - 1
