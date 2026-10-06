"""Results of completed simulation turns (ADR-023, ADR-024).

A `TurnResult` records the significant things that actually happened in a
turn that completed: aircraft that started a leg, finished a leg, or changed
their route. It is not a snapshot of the world, not a complete trace of the
turn, and does not explain why something did not happen. A completed turn
in which nothing significant happened has no outcomes.

Weather and capacity are observed through events (`airlanes.events`), not
recorded here. How a result is shown is decided by the output.

Hubs, lanes, and aircraft are referred to by name, so a result stays
unchanged while the simulation goes on.
"""

from dataclasses import dataclass


class TurnOutcome:
    """Semantic base type for significant completed-turn outcomes."""


@dataclass(frozen=True)
class Departure(TurnOutcome):
    """`aircraft` started a leg from `origin` to `destination` on `lane`."""

    aircraft: str
    origin: str
    destination: str
    lane: str


@dataclass(frozen=True)
class Arrival(TurnOutcome):
    """`aircraft` finished a leg from `origin` to `destination` on `lane`.
    A leg that takes one turn starts and finishes in the same turn: its
    `Departure` comes first, then its `Arrival`."""

    aircraft: str
    origin: str
    destination: str
    lane: str


@dataclass(frozen=True)
class Reroute(TurnOutcome):
    """`aircraft`, waiting at `hub`, replaced its remaining route. Both
    routes are the remaining steps of the aircraft's plan after `hub`, up
    to the destination. A wait planned by the initial cooperative plan is a
    step that stays in the same hub, so `old_route` may repeat a hub;
    reroutes never plan waits."""

    aircraft: str
    hub: str
    old_route: tuple[str, ...]
    new_route: tuple[str, ...]


@dataclass(frozen=True)
class TurnResult:
    """Outcomes of one completed turn, in the order they happened."""

    turn_number: int
    outcomes: tuple[TurnOutcome, ...]
