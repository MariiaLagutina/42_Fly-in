"""Dispatch board of the airlines Pygame viewer: flight statuses (BUG-011,
BUG-012).

Runs headless with SDL's dummy video driver and records the badges the
live-departures panel renders after each replayed turn.
"""

import pygame
import pytest

from airlanes.events import EventDispatcher
from airlanes.model.transport_mode import TransportMode
from airlanes.output.pygame.airlines import (
    AirlinesWindow,
    PygameAirlinesVisualizer,
)
from airlanes.simulation.engine import Simulator
from airlanes.world.weather import ScriptedWeather, WeatherCondition

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
