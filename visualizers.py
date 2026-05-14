from events import (
    AgentMoved,
    AgentRefueling,
    CapacitySnapshot,
    SimulationEvent,
    TurnStarted,
)
from graph import Graph
from simulation import SimulationTurn


class Visualizer:
    def __init__(self, graph: Graph, use_color: bool = False) -> None:
        self.graph = graph
        self.use_color = use_color

    def render_turn(self, turn: SimulationTurn) -> str:
        return " ".join(
            self._format_movement(drone_label, destination)
            for drone_label, destination in turn.movements
        )

    def _format_movement(self, drone_label: str, destination: str) -> str:
        movement = f"{drone_label}-{destination}"
        if not self.use_color:
            return movement

        zone = self.graph.get_zone(destination)
        if zone is None and "-" in destination:
            zone = self.graph.get_zone(destination.split("-")[-1])

        if zone and zone.color == "rainbow":
            return self._apply_rainbow_effect(movement)

        ansi_code = self._ansi_color(zone.color if zone else None)
        if ansi_code == "":
            return movement

        return f"{ansi_code}{movement}\033[0m"

    def _apply_rainbow_effect(self, text: str) -> str:
        rainbow_colors = [
            "\033[31m", "\033[33m", "\033[32m",
            "\033[36m", "\033[34m", "\033[35m"
        ]
        result = ""
        for i, char in enumerate(text):
            color = rainbow_colors[i % len(rainbow_colors)]
            result += f"{color}{char}"

        return result + "\033[0m"

    def _ansi_color(self, color: str | None) -> str:
        colors = {
            "black": "\033[30m", "red": "\033[31m", "green": "\033[32m",
            "yellow": "\033[33m", "blue": "\033[34m", "purple": "\033[35m",
            "magenta": "\033[35m", "cyan": "\033[36m", "white": "\033[37m",
            "orange": "\033[33m", "gold": "\033[33m", "brown": "\033[33m",
            "violet": "\033[35m", "maroon": "\033[31m", "darkred": "\033[31m",
            "crimson": "\033[31m", "rainbow": "\033[36m",
        }
        return colors.get(color or "", "")


class AirlinesVisualizer:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self._current_turn_lines: list[str] = []

    def handle(self, event: SimulationEvent) -> None:
        if isinstance(event, TurnStarted):
            self._current_turn_lines = [f"Turn {event.turn_number}"]
        elif isinstance(event, AgentRefueling):
            self._current_turn_lines.append(
                f"  {event.agent_label}: {event.origin} -> "
                f"{event.destination} via {event.connection} "
                "(mid-air refueling)"
            )
        elif isinstance(event, AgentMoved):
            label = "landed" if event.delivered else "arrived"
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
        self.blocks: list[tuple[str, str, str]] = []

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
        self.blocks.append(
            (
                f"Turn {event.turn_number} capacity",
                f"  zones: {zones}",
                f"  links: {links}",
            )
        )

    def render(self) -> list[str]:
        lines: list[str] = []
        for block in self.blocks:
            lines.extend(block)
        return lines

    def render_blocks(self) -> list[tuple[str, str, str]]:
        return self.blocks

    def _format_capacity(self, capacity: int | float) -> str:
        if capacity == float("inf"):
            return "inf"
        return str(capacity)
