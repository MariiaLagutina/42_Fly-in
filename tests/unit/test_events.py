"""Events and dispatcher: delivery to listeners, ordering, immutability."""

import dataclasses

import pytest

from events import (
    AgentMoved,
    EventDispatcher,
    SimulationEvent,
    TurnFinished,
    TurnStarted,
)


class RecordingListener:
    def __init__(self) -> None:
        self.events: list[SimulationEvent] = []

    def handle(self, event: SimulationEvent) -> None:
        self.events.append(event)


def test_every_listener_receives_every_event() -> None:
    dispatcher = EventDispatcher()
    first = RecordingListener()
    second = RecordingListener()
    dispatcher.add_listener(first)
    dispatcher.add_listener(second)
    event = TurnStarted(1)

    dispatcher.dispatch(event)

    assert first.events == [event]
    assert second.events == [event]


def test_events_arrive_in_dispatch_order() -> None:
    dispatcher = EventDispatcher()
    listener = RecordingListener()
    dispatcher.add_listener(listener)
    events: list[SimulationEvent] = [
        TurnStarted(1),
        AgentMoved(1, "D1", "start", "mid"),
        TurnFinished(1, (("D1", "mid"),)),
    ]

    for event in events:
        dispatcher.dispatch(event)

    assert listener.events == events


def test_dispatch_without_listeners_is_harmless() -> None:
    EventDispatcher().dispatch(TurnStarted(1))


def test_events_are_immutable() -> None:
    event = TurnStarted(1)

    with pytest.raises(dataclasses.FrozenInstanceError):
        event.turn_number = 2  # type: ignore[misc]
