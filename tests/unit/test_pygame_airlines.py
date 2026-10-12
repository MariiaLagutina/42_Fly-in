"""Airlines Pygame viewer: the window title, the map view and the original
drawing of other maps (ADR-028), flight statuses on the dispatch board
(BUG-011, BUG-012) and the ATC hub report (ADR-026).

Runs headless with SDL's dummy video driver. The board tests record the
badges the live-departures panel renders after each replayed turn.
"""

import hashlib
from pathlib import Path
import sys
from typing import Any, Optional

import pygame
import pytest

from airlanes import cli
from airlanes.events import CapacitySnapshot, EventDispatcher
from airlanes.mapfile import Parser
from airlanes.model.transport_mode import TransportMode
from airlanes.output.pygame import airlines
from airlanes.output.pygame.airlines import (
    AirlinesWindow,
    PygameAirlinesVisualizer,
    MapView,
    view_for,
)
from airlanes.simulation.engine import Simulator
from airlanes.world.weather import (
    RandomWeather,
    ScriptedWeather,
    WeatherCondition,
)

from tests.support.graphs import Link, build_graph, end_hub, hub, start_hub


class RecordingFont:
    def __init__(self, font: pygame.font.Font) -> None:
        self.font = font
        self.texts: list[str] = []

    def render(
        self, text: str, antialias: bool, color: tuple[int, int, int]
    ) -> pygame.Surface:
        self.texts.append(text)
        return self.font.render(text, antialias, color)


def board_statuses(
    monkeypatch: pytest.MonkeyPatch,
    links: list[Link],
    weather: ScriptedWeather,
) -> list[list[str]]:
    """The status badges on the board after each turn, from turn 1."""
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    graph = build_graph([start_hub(), hub("a"), end_hub()], links)
    viewer = PygameAirlinesVisualizer(graph)
    dispatcher = EventDispatcher()
    dispatcher.add_listener(viewer)
    Simulator(graph, 1, dispatcher, weather=weather).run()

    window = AirlinesWindow(viewer)
    try:
        font = window.badge_font
        statuses = []
        for turn in range(1, len(window.turn_indices)):
            window._goto_turn(turn)
            recorder = RecordingFont(font)
            monkeypatch.setattr(window, "badge_font", recorder)
            window._draw_live_departures(0)
            # The other badge on a card is the aircraft label, "(D1)".
            statuses.append(
                [text for text in recorder.texts if not text.startswith("(")]
            )
    finally:
        pygame.quit()
    return statuses


@pytest.mark.parametrize(
    ("mode", "distance", "status"),
    [
        pytest.param(TransportMode.AIR, 900, "EN ROUTE", id="air"),
        pytest.param(TransportMode.ROAD, 300, "DRIVING", id="road"),
    ],
)
def test_weather_after_departure_does_not_change_the_status_of_a_leg(
    monkeypatch: pytest.MonkeyPatch,
    mode: TransportMode,
    distance: int,
    status: str,
) -> None:
    """Both legs take 3 turns. The storm starts on turn 2, after departure;
    travel time is fixed at departure, so the leg is not delayed."""
    statuses = board_statuses(
        monkeypatch,
        [Link("start", "goal", distance=distance, mode=mode)],
        ScriptedWeather({2: {"start-goal": WeatherCondition.STORM}}),
    )

    assert statuses == [[status], [status], []]


def test_weather_reroute_marks_the_first_leg_of_the_new_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A storm closes the 800 km air lane on turn 1. The aircraft is
    rerouted by road through `a` and departs in the same turn; each road
    leg takes 2 turns. Only the first one is a consequence of the reroute."""
    road = TransportMode.ROAD
    statuses = board_statuses(
        monkeypatch,
        [
            Link("start", "goal", distance=800),
            Link("start", "a", distance=150, mode=road),
            Link("a", "goal", distance=150, mode=road),
        ],
        ScriptedWeather({1: {"start-goal": WeatherCondition.STORM}}),
    )

    assert statuses == [["WEATHER REROUTE"], ["ARRIVED"], ["DRIVING"], []]


@pytest.mark.parametrize(
    ("first_leg", "statuses"),
    [
        pytest.param(
            Link("start", "a", distance=800),
            [["EN ROUTE"], ["LANDED"], ["EN ROUTE"], []],
            id="air-then-air",
        ),
        pytest.param(
            Link("start", "a", distance=150, mode=TransportMode.ROAD),
            [["DRIVING"], ["ARRIVED"], ["EN ROUTE"], []],
            id="road-then-air",
        ),
    ],
)
def test_an_aircraft_at_a_hub_is_described_by_the_leg_it_completed(
    monkeypatch: pytest.MonkeyPatch,
    first_leg: Link,
    statuses: list[list[str]],
) -> None:
    """Each leg takes 2 turns; the second one is an 800 km air leg. On turn
    2 the aircraft waits at `a` after the first leg (BUG-012)."""
    assert board_statuses(
        monkeypatch,
        [first_leg, Link("a", "goal", distance=800)],
        ScriptedWeather({}),
    ) == statuses


# --- ATC hub report (ADR-026) ------------------------------------------------


def airlines_window(
    monkeypatch: pytest.MonkeyPatch, links: list[Link], nb_aircraft: int
) -> tuple[AirlinesWindow, list[CapacitySnapshot]]:
    """A window over a finished run through hub `b`, and the run's capacity
    snapshots in turn order."""
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    graph = build_graph(
        [start_hub(), hub("b", capacity=3), end_hub()], links
    )
    viewer = PygameAirlinesVisualizer(graph)
    dispatcher = EventDispatcher()
    dispatcher.add_listener(viewer)
    Simulator(graph, nb_aircraft, dispatcher).run()
    snapshots = [
        event
        for event in viewer.event_queue
        if isinstance(event, CapacitySnapshot)
    ]
    return AirlinesWindow(viewer), snapshots


def hub_load_line(window: AirlinesWindow, name: str) -> str:
    zone = window.graph.get_zone(name)
    assert zone is not None
    report = window._hub_report(zone)
    assert report[0] == f"[ATC HUB REPORT: {name.upper()}]"
    return report[-1]


def test_hub_report_counts_an_aircraft_flying_to_the_hub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On turn 1 the aircraft is on its way to `b`: nobody is in the hub,
    but it holds one of its slots."""
    window, _snapshots = airlines_window(
        monkeypatch,
        [Link("start", "b", distance=900), Link("b", "goal")],
        nb_aircraft=1,
    )
    try:
        window._goto_turn(1)
        assert window.drone_positions["D1"].kind == "connection"
        assert hub_load_line(window, "b") == (
            "  -> Hub Load:            1 / 3 aircraft"
        )
    finally:
        pygame.quit()


def test_hub_report_follows_the_replayed_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward, backward, and back to the start, the report shows the
    snapshot of the selected turn, never a later or stale one."""
    window, snapshots = airlines_window(
        monkeypatch,
        [Link("start", "b", capacity=3), Link("b", "goal", distance=900)],
        nb_aircraft=3,
    )
    try:
        loads = [snapshot.hub_load[0][1] for snapshot in snapshots]
        assert len(set(loads)) > 1
        last_turn = len(window.turn_indices) - 1
        assert last_turn == len(snapshots)

        before_turn_1 = "  -> Hub Load:            — (no turn completed yet)"
        assert hub_load_line(window, "b") == before_turn_1

        order = list(range(1, last_turn + 1))
        for turn in order + order[::-1]:
            window._goto_turn(turn)
            assert hub_load_line(window, "b") == (
                f"  -> Hub Load:            {loads[turn - 1]} / 3 aircraft"
            ), turn

        window._goto_turn(last_turn)
        window._goto_turn(0)
        assert hub_load_line(window, "b") == before_turn_1
    finally:
        pygame.quit()


@pytest.mark.parametrize("name", ["start", "goal"])
def test_hub_report_of_start_and_end_hubs_has_no_capacity(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    window, _snapshots = airlines_window(
        monkeypatch,
        [Link("start", "b", distance=900), Link("b", "goal")],
        nb_aircraft=1,
    )
    try:
        window._goto_turn(2)
        zone = window.graph.get_zone(name)
        assert zone is not None
        assert window._hub_report(zone) == [
            f"[ATC HUB REPORT: {name.upper()}]",
            "  -> Regional Population: 0",
            "  -> Logistics Type:      NORMAL",
            "  -> Hub Load:            not applicable (unlimited capacity)",
        ]
    finally:
        pygame.quit()


def test_the_window_is_titled_after_the_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    airlines_window(monkeypatch, [Link("start", "b"), Link("b", "goal")], 1)
    try:
        title, _icon_title = pygame.display.get_caption()
    finally:
        pygame.quit()

    assert title == "Mariia's Airlanes — Dispatch Center"


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("map_path", "view"),
    [
        pytest.param(
            "maps/bonus/europa_map.txt", MapView("europa.png"), id="europe"
        ),
        pytest.param(
            "/elsewhere/germany_map.txt", MapView("germany.png"),
            id="germany",
        ),
        pytest.param(
            "maps/challenger/01_the_impossible_dream.txt", None, id="other"
        ),
        pytest.param("maps/europa_notes/map.txt", None, id="name-only"),
    ],
)
def test_the_view_is_chosen_by_map_file_name(
    map_path: str, view: Optional[MapView]
) -> None:
    assert view_for(map_path) == view


def test_the_view_does_not_depend_on_the_command_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The window used to pick Europe when "europa" appeared in sys.argv
    # and Germany for every other map.
    monkeypatch.setattr(sys, "argv", ["main.py", "europa_map.txt"])
    window, _ = airlines_window(
        monkeypatch, [Link("start", "b"), Link("b", "goal")], 1
    )
    pygame.quit()

    assert window.view is None
    assert window.bg_image is None


def test_a_geographic_view_fills_the_map_area_with_its_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    graph = build_graph([start_hub(), end_hub()], [Link("start", "goal")])
    window = AirlinesWindow(
        PygameAirlinesVisualizer(graph), MapView("germany.png")
    )
    pygame.quit()

    assert window.bg_image is not None
    assert window.bg_image.get_size() == (window.map_width, window.height)


def test_the_cli_passes_the_view_of_the_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[Optional[MapView]] = []

    def record(
        visualizer: PygameAirlinesVisualizer,
        view: Optional[MapView] = None,
    ) -> None:
        opened.append(view)

    monkeypatch.setattr(airlines, "run_pygame_airlines", record)
    map_file = REPO_ROOT / "maps" / "bonus" / "germany_map.txt"
    monkeypatch.setattr(
        sys, "argv", ["main.py", str(map_file), "--pygame-airlines"]
    )

    assert cli.main() == cli.EXIT_OK
    assert opened == [MapView("germany.png")]


# The dispatch center's lanes and cities on the original challenge maps,
# with seeded weather, as drawn before the geographic lane styling (Stage
# 9b base, 3cc1360). Only Germany and Europe have a geographic view.
ORIGINAL_MAP_DRAWING = {
    "easy/01_linear_path.txt":
        "bcdebb3a43498a1d22b8c1e79d6c3d28cb12bbd1524259870a5b6013c1d9ea10",
    "easy/02_simple_fork.txt":
        "f7e97798989307541d32a3eb9023490d983f881e3527ee673c1d73ad8f3ec728",
    "easy/03_basic_capacity.txt":
        "dbd0edd9fc63050300e081e852eed18b6c174c6ca08f91837d747478046ac5ee",
    "medium/01_dead_end_trap.txt":
        "1354f9522e9697c06e33cc2d55f41761395a2630e96d107e8cdcb2dd1dbc3459",
    "medium/02_circular_loop.txt":
        "ab05ec4f2461c79c498aa749f1c505c6f668a519f8cf2c9e6828dc8aa29d390f",
    "medium/03_priority_puzzle.txt":
        "ea2a5d237f5ce1b5dc90abd8aea0be6aac3f248f92e5199d5394eb640194a009",
    "hard/01_maze_nightmare.txt":
        "8b1b1f3c836f9e9484d6f7befa7a6e3d7b388d570b37f9bf8b075bc1f110216d",
    "hard/02_capacity_hell.txt":
        "fcfde412aae79e39a4e5bba48c36484cf9656e174d761b1bb873f9f0bd68f786",
    "hard/03_ultimate_challenge.txt":
        "aadf1a7510f154494d1d6f32fdb128a5564818b6ec0d56353124481e1ccb0f09",
    "challenger/01_the_impossible_dream.txt":
        "5da9f4f86a1adc62fa17c2c52c1952df501698bd48f719fc32a26246b43a395a",
}


def map_drawing_fingerprint(
    monkeypatch: pytest.MonkeyPatch, map_name: str
) -> str:
    """SHA-256 of every line and circle the dispatch center draws for the
    map area over all turns, with weather seed 0: lane geometry, colours
    and widths, and cities. Text is left out, as fonts differ between
    machines."""
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
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
    viewer = PygameAirlinesVisualizer(graph)
    dispatcher = EventDispatcher()
    dispatcher.add_listener(viewer)
    weather = RandomWeather(graph, seed=0)
    Simulator(graph, nb_aircraft, dispatcher, weather=weather).run()
    window = AirlinesWindow(viewer)
    digest = hashlib.sha256()
    try:
        for turn in range(len(window.turn_indices)):
            window._goto_turn(turn)
            calls.clear()
            window._draw_map()
            digest.update(repr(calls).encode())
    finally:
        pygame.quit()
    return digest.hexdigest()


@pytest.mark.parametrize("map_name", sorted(ORIGINAL_MAP_DRAWING))
def test_the_original_maps_keep_their_dispatch_center_lanes(
    monkeypatch: pytest.MonkeyPatch, map_name: str
) -> None:
    fingerprint = map_drawing_fingerprint(monkeypatch, map_name)

    assert fingerprint == ORIGINAL_MAP_DRAWING[map_name]
