from dataclasses import dataclass
from typing import Literal, Protocol


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
class AgentInTransit:
    turn_number: int
    agent_label: str
    origin: str
    connection: str
    destination: str


# Why an aircraft rerouted: weather made its route unusable (ADR-018), or
# it was part of a structural deadlock and took a way around it (ADR-020).
RerouteReason = Literal["weather", "deadlock"]


@dataclass(frozen=True)
class AgentRerouted:
    """An aircraft at `hub` replaced its remaining route with `route`, the
    hubs it now plans to visit up to its destination."""

    turn_number: int
    agent_label: str
    hub: str
    route: tuple[str, ...]
    reason: RerouteReason


@dataclass(frozen=True)
class TurnFinished:
    turn_number: int
    movements: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class CapacitySnapshot:
    turn_number: int
    zone_usage: tuple[tuple[str, int, int | float], ...]
    connection_usage: tuple[tuple[str, int, int], ...]


@dataclass(frozen=True)
class WeatherChanged:
    turn_number: int
    connection_name: str
    condition: str
    is_open: bool


SimulationEvent = (
    TurnStarted
    | AgentMoved
    | AgentInTransit
    | AgentRerouted
    | TurnFinished
    | CapacitySnapshot
    | WeatherChanged
)


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
