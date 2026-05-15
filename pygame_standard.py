from dataclasses import dataclass
from typing import Literal, Optional

import pygame

from events import (
    AgentMoved,
    AgentRefueling,
    EventListener,
    SimulationEvent,
    TurnFinished,
)
from graph import Graph
from zone import Zone, ZoneType

PositionKind = Literal["zone", "connection"]


@dataclass(frozen=True)
class DroneDisplayPosition:
    kind: PositionKind
    first_zone: str
    second_zone: Optional[str] = None


@dataclass(frozen=True)
class StandardTurnFrame:
    turn_number: int
    positions: dict[str, DroneDisplayPosition]
    movements: tuple[tuple[str, str], ...]


class PygameStandardVisualizer(EventListener):
    def __init__(self, graph: Graph, nb_drones: int) -> None:
        self.graph = graph
        self.nb_drones = nb_drones
        self.event_queue: list[SimulationEvent] = []

    def handle(self, event: SimulationEvent) -> None:
        self.event_queue.append(event)

    def build_frames(self) -> list[StandardTurnFrame]:
        if self.graph.start_zone is None:
            return []

        positions = {
            f"D{drone_id}": DroneDisplayPosition(
                "zone",
                self.graph.start_zone.name,
            )
            for drone_id in range(1, self.nb_drones + 1)
        }
        frames = [StandardTurnFrame(0, positions.copy(), ())]

        for event in self.event_queue:
            if isinstance(event, AgentMoved):
                positions[event.agent_label] = DroneDisplayPosition(
                    "zone",
                    event.destination,
                )
            elif isinstance(event, AgentRefueling):
                positions[event.agent_label] = DroneDisplayPosition(
                    "connection",
                    event.origin,
                    event.destination,
                )
            elif isinstance(event, TurnFinished):
                frames.append(
                    StandardTurnFrame(
                        event.turn_number,
                        positions.copy(),
                        event.movements,
                    )
                )

        return frames


def run_pygame_standard(visualizer: PygameStandardVisualizer) -> None:
    pygame.init()
    margin = 35
    history_height = 130
    positions = _build_positions(visualizer.graph)
    content_width, content_height = _content_size(positions)
    width = max(1100, content_width + (margin * 2) + 120)
    height = max(700, content_height + history_height + (margin * 2) + 80)
    screen = pygame.display.set_mode((width, height))
    pygame.display.set_caption("Fly-in")
    clock = pygame.time.Clock()
    title_font = pygame.font.SysFont("Arial", 24, bold=True)
    text_font = pygame.font.SysFont("Arial", 17)
    small_font = pygame.font.SysFont("Arial", 15)

    frames = visualizer.build_frames()
    current_index = 0
    autoplay = True
    last_update_time = pygame.time.get_ticks()
    turn_delay = 650
    graph_rect = pygame.Rect(
        margin,
        history_height + margin,
        width - (margin * 2),
        height - history_height - (margin * 2),
    )
    offset_x, offset_y = _center_positions(positions, graph_rect)
    positions = _offset_positions(positions, offset_x, offset_y)

    running = True
    while running:
        current_time = pygame.time.get_ticks()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_a:
                    autoplay = False
                    current_index = max(0, current_index - 1)
                elif event.key == pygame.K_d:
                    autoplay = False
                    current_index = min(len(frames) - 1, current_index + 1)
                elif event.key == pygame.K_SPACE:
                    autoplay = not autoplay

        if autoplay and current_time - last_update_time >= turn_delay:
            if current_index < len(frames) - 1:
                current_index += 1
                last_update_time = current_time
            else:
                autoplay = False

        screen.fill((244, 247, 250))
        _draw_history_bar(
            screen,
            frames[current_index],
            len(frames) - 1,
            width,
            history_height,
            title_font,
            text_font,
        )
        _draw_graph(screen, visualizer.graph, positions, small_font)
        _draw_drones(screen, frames[current_index], positions)
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()


def _build_positions(graph: Graph) -> dict[str, tuple[int, int]]:
    zones = list(graph.zones.values())
    if not zones:
        return {}

    min_x = min(zone.x for zone in zones)
    min_y = min(zone.y for zone in zones)
    horizontal_gap = 96
    vertical_gap = 110
    return {
        zone.name: (
            60 + (zone.x - min_x) * horizontal_gap,
            60 + (zone.y - min_y) * vertical_gap,
        )
        for zone in zones
    }


def _content_size(positions: dict[str, tuple[int, int]]) -> tuple[int, int]:
    if not positions:
        return 0, 0
    xs = [position[0] for position in positions.values()]
    ys = [position[1] for position in positions.values()]
    return max(xs) - min(xs), max(ys) - min(ys)


def _center_positions(
    positions: dict[str, tuple[int, int]],
    viewport: pygame.Rect,
) -> tuple[int, int]:
    if not positions:
        return viewport.left, viewport.top
    xs = [position[0] for position in positions.values()]
    ys = [position[1] for position in positions.values()]
    content_width = max(xs) - min(xs)
    content_height = max(ys) - min(ys)
    offset_x = viewport.left - min(xs) + (viewport.width - content_width) // 2
    offset_y = viewport.top - min(ys) + (viewport.height - content_height) // 2
    return offset_x, offset_y


def _offset_positions(
    positions: dict[str, tuple[int, int]],
    offset_x: int,
    offset_y: int,
) -> dict[str, tuple[int, int]]:
    return {
        name: (position[0] + offset_x, position[1] + offset_y)
        for name, position in positions.items()
    }


def _draw_graph(
    screen: pygame.Surface,
    graph: Graph,
    positions: dict[str, tuple[int, int]],
    font: pygame.font.Font,
) -> None:
    for connection in graph.connections:
        start = positions[connection.zone_a.name]
        end = positions[connection.zone_b.name]
        pygame.draw.line(screen, (145, 157, 171), start, end, 3)

    for zone in graph.zones.values():
        position = positions[zone.name]
        color = _zone_color(zone)
        pygame.draw.circle(screen, color, position, 14)
        pygame.draw.circle(screen, (34, 45, 58), position, 14, 2)
        label = font.render(_short_zone_name(zone.name), True, (34, 45, 58))
        screen.blit(label, (position[0] + 16, position[1] - 22))


def _draw_drones(
    screen: pygame.Surface,
    frame: StandardTurnFrame,
    positions: dict[str, tuple[int, int]],
) -> None:
    grouped: dict[tuple[int, int], list[str]] = {}
    for drone_label, position in frame.positions.items():
        point = _display_point(position, positions)
        grouped.setdefault(point, []).append(drone_label)

    for point, labels in grouped.items():
        for index, _label in enumerate(labels):
            offset_x = ((index % 3) - 1) * 12
            offset_y = (index // 3) * 12 - 6
            center = (point[0] + offset_x, point[1] + offset_y)
            pygame.draw.circle(screen, (246, 174, 45), center, 7)
            pygame.draw.circle(screen, (125, 77, 0), center, 7, 1)


def _draw_history_bar(
    screen: pygame.Surface,
    frame: StandardTurnFrame,
    total_turns: int,
    width: int,
    height: int,
    title_font: pygame.font.Font,
    text_font: pygame.font.Font,
) -> None:
    panel = pygame.Rect(0, 0, width, height)
    pygame.draw.rect(screen, (32, 42, 54), panel)
    title = title_font.render(
        f"Turn {frame.turn_number} / {total_turns}",
        True,
        (255, 255, 255),
    )
    screen.blit(title, (28, 24))

    heading = text_font.render("Movements", True, (143, 211, 255))
    screen.blit(heading, (28, 74))
    if not frame.movements:
        line = text_font.render("Initial state", True, (220, 226, 232))
        screen.blit(line, (160, 74))
        return

    x = 160
    y = 74
    for drone_label, destination in frame.movements:
        line = text_font.render(
            f"{drone_label} -> {_short_zone_name(destination)}",
            True,
            (220, 226, 232),
        )
        if x + line.get_width() > width - 28:
            x = 160
            y += 28
        screen.blit(line, (x, y))
        x += line.get_width() + 28


def _display_point(
    position: DroneDisplayPosition,
    positions: dict[str, tuple[int, int]],
) -> tuple[int, int]:
    first = positions[position.first_zone]
    if position.kind == "zone" or position.second_zone is None:
        return first
    second = positions[position.second_zone]
    return ((first[0] + second[0]) // 2, (first[1] + second[1]) // 2)


def _zone_color(zone: Zone) -> tuple[int, int, int]:
    if zone.is_start:
        return (68, 177, 106)
    if zone.is_end:
        return (224, 91, 91)
    if zone.zone_type == ZoneType.PRIORITY:
        return (77, 151, 230)
    if zone.zone_type == ZoneType.RESTRICTED:
        return (171, 107, 214)
    if zone.zone_type == ZoneType.BLOCKED:
        return (104, 113, 122)
    return (243, 195, 74)


def _short_zone_name(name: str) -> str:
    if len(name) <= 12:
        return name

    parts = name.split("_")
    if len(parts) == 1:
        return name[:11] + "."

    shortened_parts = [parts[0]]
    for part in parts[1:]:
        if part[-1:].isdigit():
            shortened_parts.append(part[0] + part[-1])
        else:
            shortened_parts.append(part[0])
    shortened = "_".join(shortened_parts)
    if len(shortened) <= 12:
        return shortened
    return shortened[:11] + "."
