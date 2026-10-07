from airlanes.events import (
    AgentMoved,
    AgentInTransit,
    CapacitySnapshot,
    SimulationEvent,
    TurnStarted,
)
from airlanes.model.graph import Graph
from airlanes.results import Arrival, Departure, TurnResult


def movement_tokens(result: TurnResult) -> tuple[tuple[str, str], ...]:
    """
    The movements of a turn in the assignment's format, as (aircraft,
    position) pairs in the order the outcomes happened. An aircraft that
    starts a leg is shown on its lane, one that finishes a leg in the hub it
    reached. A leg that starts and finishes in the same turn is shown once,
    by its arrival. Reroutes are not shown.
    """
    return tuple(
        (outcome.aircraft, _position(outcome))
        for outcome in _shown_outcomes(result)
    )


def _shown_outcomes(result: TurnResult) -> list[Departure | Arrival]:
    """The outcomes the assignment's format shows, in order: every arrival,
    and every departure except one whose leg also finishes in this turn."""
    arrived = {
        (outcome.aircraft, outcome.origin, outcome.destination, outcome.lane)
        for outcome in result.outcomes
        if isinstance(outcome, Arrival)
    }
    shown: list[Departure | Arrival] = []
    for outcome in result.outcomes:
        if isinstance(outcome, Arrival):
            shown.append(outcome)
        elif isinstance(outcome, Departure) and (
            outcome.aircraft,
            outcome.origin,
            outcome.destination,
            outcome.lane,
        ) not in arrived:
            shown.append(outcome)
    return shown


def _position(outcome: Departure | Arrival) -> str:
    """Where the assignment's format shows the aircraft: on the lane of a
    leg it starts, in the hub of a leg it finishes."""
    if isinstance(outcome, Departure):
        return outcome.lane
    return outcome.destination


class Visualizer:
    def __init__(self, graph: Graph, use_color: bool = False) -> None:
        self.graph = graph
        self.use_color = use_color

    def render_turn(self, result: TurnResult) -> str:
        return " ".join(
            self._format_movement(outcome)
            for outcome in _shown_outcomes(result)
        )

    def _format_movement(self, outcome: Departure | Arrival) -> str:
        """A token is colored by the hub its leg goes to, whatever the
        order in which the map declares the lane (BUG-008)."""
        movement = f"{outcome.aircraft}-{_position(outcome)}"
        if not self.use_color:
            return movement

        zone = self.graph.get_zone(outcome.destination)

        if zone and zone.color == "rainbow":
            return self._apply_rainbow_effect(movement)

        ansi_code = self._ansi_color(zone.color if zone else None)
        if ansi_code == "":
            return movement

        return f"{ansi_code}{movement}\033[0m"

    def _apply_rainbow_effect(self, text: str) -> str:
        rainbow_colors = [
            "\033[31m",
            "\033[33m",
            "\033[32m",
            "\033[36m",
            "\033[34m",
            "\033[35m",
        ]
        result = ""
        for i, char in enumerate(text):
            color = rainbow_colors[i % len(rainbow_colors)]
            result += f"{color}{char}"

        return result + "\033[0m"

    def _ansi_color(self, color: str | None) -> str:
        colors = {
            "black": "\033[30m",
            "red": "\033[31m",
            "green": "\033[32m",
            "yellow": "\033[33m",
            "blue": "\033[34m",
            "purple": "\033[35m",
            "magenta": "\033[35m",
            "cyan": "\033[36m",
            "white": "\033[37m",
            "orange": "\033[33m",
            "gold": "\033[33m",
            "brown": "\033[33m",
            "violet": "\033[35m",
            "maroon": "\033[31m",
            "darkred": "\033[31m",
            "crimson": "\033[31m",
            "rainbow": "\033[36m",
        }
        return colors.get(color or "", "")


class AirlinesVisualizer:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self._current_turn_lines: list[str] = []

    def handle(self, event: SimulationEvent) -> None:
        if isinstance(event, TurnStarted):
            self._current_turn_lines = [f"Turn {event.turn_number}"]
        elif isinstance(event, AgentInTransit):
            self._current_turn_lines.append(
                f"  {event.agent_label}: {event.origin} -> "
                f"{event.destination} via {event.connection} (in transit)"
            )
        elif isinstance(event, AgentMoved):
            label = "delivered" if event.delivered else "arrived"
            self._current_turn_lines.append(
                f"  {event.agent_label}: {event.origin} -> "
                f"{event.destination} ({label})"
            )
        else:
            self.lines.extend(self._current_turn_lines)
            self._current_turn_lines = []

    def render(self) -> list[str]:
        return self.lines


class CapacityInfoVisualizer:
    def __init__(self) -> None:
        self.blocks: dict[int, tuple[str, str, str]] = {}

    def handle(self, event: SimulationEvent) -> None:
        if not isinstance(event, CapacitySnapshot):
            return

        zones = ", ".join(
            f"{name}={used}/{self._format_capacity(capacity)}"
            for name, used, capacity in event.zone_usage
        )
        links = ", ".join(
            f"{name}={used}/{capacity}"
            for name, used, capacity in event.connection_usage
        )
        self.blocks[event.turn_number] = (
            f"Turn {event.turn_number} capacity",
            f"  zones: {zones}",
            f"  links: {links}",
        )

    def render(self) -> list[str]:
        lines: list[str] = []
        for block in self.blocks.values():
            lines.extend(block)
        return lines

    def block_for(self, turn_number: int) -> tuple[str, str, str] | None:
        return self.blocks.get(turn_number)

    def _format_capacity(self, capacity: int | float) -> str:
        if capacity == float("inf"):
            return "inf"
        return str(capacity)
