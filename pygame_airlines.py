from dataclasses import dataclass
import sys
from typing import Literal, Optional

import pygame

from events import (
    AgentMoved,
    AgentRefueling,
    EventListener,
    SimulationEvent,
    WeatherChanged,
)
from graph import Graph

PositionKind = Literal["zone", "connection"]


@dataclass(frozen=True)
class DroneDisplayPosition:
    kind: PositionKind
    first_zone: str
    second_zone: Optional[str] = None


class PygameAirlinesVisualizer(EventListener):
    def __init__(self, graph: Graph) -> None:
        self.graph = graph
        self.event_queue: list[SimulationEvent] = []
        self.drone_positions: dict[str, DroneDisplayPosition] = {}
        self.connection_weather: dict[str, str] = {}

    def handle(self, event: SimulationEvent) -> None:
        self.event_queue.append(event)


def run_pygame_airlines(visualizer: PygameAirlinesVisualizer) -> None:
    pygame.init()
    width, height = 1000, 800
    screen = pygame.display.set_mode((width, height))
    pygame.display.set_caption("Fly-in: Global Logistics")
    clock = pygame.time.Clock()

    bg_image_name = "germany.png"
    for arg in sys.argv:
        if "europa" in arg.lower():
            bg_image_name = "europa.png"
    try:
        bg_image = pygame.image.load(bg_image_name)
        bg_image = pygame.transform.scale(bg_image, (width, height))
    except FileNotFoundError:
        print(f"Warning: {bg_image_name} not found! Using solid background.")
        bg_image = None

    city_font = pygame.font.SysFont("Arial", 16, bold=True)
    dashboard_font = pygame.font.SysFont("Courier", 14, bold=True)
    icons = _load_weather_icons()
    last_update_time = pygame.time.get_ticks()
    turn_delay = 500
    current_event_index = 0

    running = True
    while running:
        current_time = pygame.time.get_ticks()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                print(f"Coordinates: {event.pos[0]} {event.pos[1]}")

        if current_time - last_update_time > turn_delay:
            if current_event_index < len(visualizer.event_queue):
                sim_event = visualizer.event_queue[current_event_index]
                _apply_event(visualizer, sim_event)
                current_event_index += 1
                last_update_time = current_time

        if bg_image:
            screen.blit(bg_image, (0, 0))
        else:
            screen.fill((20, 30, 50))

        _draw_graph(screen, visualizer, icons, city_font)
        _draw_drones(screen, visualizer)
        _draw_weather_dashboard(screen, visualizer, dashboard_font)
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
    sys.exit()


def _load_weather_icons() -> dict[str, pygame.Surface]:
    icons: dict[str, pygame.Surface] = {}
    try:
        icons["storm"] = pygame.transform.scale(
            pygame.image.load("storm.png"),
            (30, 30),
        )
        icons["rain"] = pygame.transform.scale(
            pygame.image.load("rain.png"),
            (30, 30),
        )
        icons["snow"] = pygame.transform.scale(
            pygame.image.load("snow.png"),
            (30, 30),
        )
        icons["tailwind"] = pygame.transform.scale(
            pygame.image.load("sun.png"),
            (30, 30),
        )
    except FileNotFoundError:
        print("Warning: weather icons not found.")
    return icons


def _apply_event(
    visualizer: PygameAirlinesVisualizer,
    event: SimulationEvent,
) -> None:
    if isinstance(event, AgentMoved):
        visualizer.drone_positions[event.agent_label] = DroneDisplayPosition(
            "zone",
            event.destination,
        )
    elif isinstance(event, AgentRefueling):
        visualizer.drone_positions[event.agent_label] = DroneDisplayPosition(
            "connection",
            event.origin,
            event.destination,
        )
    elif isinstance(event, WeatherChanged):
        visualizer.connection_weather[event.connection_name] = event.condition


def _draw_graph(
    screen: pygame.Surface,
    visualizer: PygameAirlinesVisualizer,
    icons: dict[str, pygame.Surface],
    city_font: pygame.font.Font,
) -> None:
    for connection in visualizer.graph.connections:
        start = (connection.zone_a.x, connection.zone_a.y)
        end = (connection.zone_b.x, connection.zone_b.y)
        condition = visualizer.connection_weather.get(
            connection.name(),
            "clear",
        )
        color, thickness = _weather_style(condition)
        pygame.draw.line(screen, color, start, end, thickness)

        if condition in icons:
            mid_x = (start[0] + end[0]) // 2
            mid_y = (start[1] + end[1]) // 2
            icon_rect = icons[condition].get_rect(center=(mid_x, mid_y))
            screen.blit(icons[condition], icon_rect)

    for zone in visualizer.graph.zones.values():
        node_color = (
            (50, 255, 50)
            if zone.is_start or zone.is_end
            else (100, 200, 255)
        )
        pygame.draw.circle(screen, node_color, (zone.x, zone.y), 10)
        shadow = city_font.render(zone.name, True, (0, 0, 0))
        screen.blit(shadow, (zone.x + 11, zone.y - 14))
        text = city_font.render(zone.name, True, (255, 255, 255))
        screen.blit(text, (zone.x + 10, zone.y - 15))


def _draw_drones(
    screen: pygame.Surface,
    visualizer: PygameAirlinesVisualizer,
) -> None:
    raw_positions = {
        zone.name: (zone.x, zone.y)
        for zone in visualizer.graph.zones.values()
    }
    for position in visualizer.drone_positions.values():
        point = _display_point(position, raw_positions)
        color = (
            (255, 150, 0)
            if position.kind == "connection"
            else (255, 200, 0)
        )
        pygame.draw.circle(screen, color, point, 6)


def _draw_weather_dashboard(
    screen: pygame.Surface,
    visualizer: PygameAirlinesVisualizer,
    dashboard_font: pygame.font.Font,
) -> None:
    dashboard_surface = pygame.Surface((250, 200), pygame.SRCALPHA)
    dashboard_surface.fill((0, 0, 0, 180))
    screen.blit(dashboard_surface, (20, 20))
    title = dashboard_font.render("LIVE WEATHER ALERTS", True, (255, 200, 0))
    screen.blit(title, (30, 30))

    y_offset = 60
    for connection_name, condition in visualizer.connection_weather.items():
        if condition == "clear":
            continue
        text_color = (
            (255, 100, 100)
            if condition in ["storm", "snow"]
            else (150, 200, 255)
        )
        alert_text = dashboard_font.render(
            f"{connection_name}: {condition.upper()}",
            True,
            text_color,
        )
        screen.blit(alert_text, (30, y_offset))
        y_offset += 20
        if y_offset > 200:
            break


def _display_point(
    position: DroneDisplayPosition,
    positions: dict[str, tuple[int, int]],
) -> tuple[int, int]:
    first = positions[position.first_zone]
    if position.kind == "zone" or position.second_zone is None:
        return first
    second = positions[position.second_zone]
    return ((first[0] + second[0]) // 2, (first[1] + second[1]) // 2)


def _weather_style(condition: str) -> tuple[tuple[int, int, int], int]:
    if condition == "storm":
        return (255, 50, 50), 5
    if condition == "snow":
        return (200, 200, 255), 5
    if condition == "rain":
        return (50, 100, 255), 4
    if condition == "tailwind":
        return (50, 255, 150), 4
    return (200, 200, 200), 3
