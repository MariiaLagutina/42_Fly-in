from dataclasses import dataclass
from typing import Protocol, Union


@dataclass(frozen=True)
class TurnStarted:
    turn_number: int


@dataclass(frozen=True)
class AgentMoved:
    turn_number: int
    agent_label: str
    origin: str
    destination: str
    delivered: bool = False


@dataclass(frozen=True)
class AgentRefueling:
    turn_number: int
    agent_label: str
    origin: str
    connection: str
    destination: str


@dataclass(frozen=True)
class TurnFinished:
    turn_number: int
    movements: tuple[tuple[str, str], ...]


SimulationEvent = Union[
    TurnStarted,
    AgentMoved,
    AgentRefueling,
    TurnFinished,
]


class EventListener(Protocol):
    def handle(self, event: SimulationEvent) -> None:
        ...


class EventDispatcher:
    def __init__(self) -> None:
        self._listeners: list[EventListener] = []

    def add_listener(self, listener: EventListener) -> None:
        self._listeners.append(listener)

    def dispatch(self, event: SimulationEvent) -> None:
        for listener in self._listeners:
            listener.handle(event)
