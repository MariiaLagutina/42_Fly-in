import random
import string
import sys
from dataclasses import dataclass
from typing import Literal, Optional, TypedDict

import pygame

from events import (
    AgentMoved,
    AgentRefueling,
    EventListener,
    SimulationEvent,
    WeatherChanged,
    TurnStarted,
)
from graph import Graph

PositionKind = Literal["zone", "connection"]
Point = tuple[int, int]


class FlightInfo(TypedDict):
    flight: str
    origin: str
    dest: str
    status: str


@dataclass(frozen=True)
class DroneDisplayPosition:
    kind: PositionKind
    first_zone: str
    second_zone: Optional[str] = None


class PygameAirlinesVisualizer(EventListener):
    """Collects simulation events for airlines visualization."""
    def __init__(self, graph: Graph) -> None:
        self.graph = graph
        self.event_queue: list[SimulationEvent] = []

    def handle(self, event: SimulationEvent) -> None:
        self.event_queue.append(event)


class AirlinesWindow:
    """Fully OOP Main window for Airlines visualization with Control Panel."""

    def __init__(self, visualizer: PygameAirlinesVisualizer) -> None:
        pygame.init()
        self.visualizer = visualizer
        self.graph = visualizer.graph

        # Настройки Layout: 1000px для карты, 350px под сайдбар диспетчера
        self.map_width = 1000
        self.sidebar_width = 350
        self.width = self.map_width + self.sidebar_width
        self.height = 800

        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("Fly-in: Global Logistics")
        self.clock = pygame.time.Clock()

        # Шрифты
        self.city_font = pygame.font.SysFont("Arial", 16, bold=True)
        self.dashboard_font = pygame.font.SysFont("Courier", 13, bold=True)
        self.badge_font = pygame.font.SysFont("Arial", 12, bold=True)

        # Ассеты
        self.bg_image = self._load_background()
        self.drone_sprite = self._load_drone_sprite()
        self.icons = self._load_weather_icons()

        # Состояния и отслеживание
        self.drone_positions: dict[str, DroneDisplayPosition] = {}
        self.connection_weather: dict[str, str] = {}
        self.flight_data: dict[str, FlightInfo] = {}

        self.city_populations = self._generate_populations()

        self.current_turn = 0
        self.current_event_index = 0
        self.last_update_time = pygame.time.get_ticks()
        self.turn_delay = 500

    def _generate_populations(self) -> dict[str, int]:
        """Generate consistent random populations based on city names."""
        pops: dict[str, int] = {}
        for zone in self.graph.zones.values():
            # Сид по имени города, чтобы при перезапуске население не менялось
            random.seed(zone.name)
            # Население: от 100 тысяч до 8 миллионов человек
            pops[zone.name] = random.randint(100000, 8000000)
        random.seed()
        return pops

    def _get_city_color(self, population: int) -> tuple[int, int, int]:
        """Return city node color based on population size."""
        if population < 1000000:
            return (46, 204, 113)
        elif population < 3500000:
            return (241, 196, 15)
        else:
            return (231, 76, 60)

    def _format_population(self, population: int) -> str:
        """Format population for display (e.g., 2.5M or 450K)."""
        if population >= 1000000:
            return f"{population/1000000:.1f}M"
        return f"{population//1000}K"

    def _load_background(self) -> Optional[pygame.Surface]:
        bg_image_name = "germany.png"
        for arg in sys.argv:
            if "europa" in arg.lower():
                bg_image_name = "europa.png"
        try:
            bg = pygame.image.load(bg_image_name)
            return pygame.transform.scale(bg, (self.map_width, self.height))
        except FileNotFoundError:
            return None

    def _load_drone_sprite(self) -> Optional[pygame.Surface]:
        try:
            sprite = pygame.image.load("drone.png").convert_alpha()
            sprite.set_colorkey((255, 255, 255))
            return pygame.transform.scale(sprite, (30, 30))
        except FileNotFoundError:
            return None

    def _load_weather_icons(self) -> dict[str, pygame.Surface]:
        icons = {}
        try:
            files = [
                ("storm", "storm.png"),
                ("rain", "rain.png"),
                ("snow", "snow.png"),
                ("tailwind", "sun.png"),
            ]
            for cond, file in files:
                surf = pygame.image.load(file).convert_alpha()
                icons[cond] = pygame.transform.scale(surf, (30, 30))
        except FileNotFoundError:
            pass
        return icons

    def _get_flight_info(self, drone_label: str) -> FlightInfo:
        """Generate or retrieve consistent flight info for a drone."""
        if drone_label not in self.flight_data:
            letter = random.choice(string.ascii_uppercase)
            num = random.randint(100, 999)
            self.flight_data[drone_label] = {
                "flight": f"{letter}{num}",
                "origin": "Base",
                "dest": "Base",
                "status": "Idle",
            }
        return self.flight_data[drone_label]

    def _apply_event(self, event: SimulationEvent) -> None:
        """Process simulation logic and update tracking dicts."""
        if isinstance(event, TurnStarted):
            self.current_turn = event.turn_number
        elif isinstance(event, AgentMoved):
            self.drone_positions[event.agent_label] = DroneDisplayPosition(
                "zone",
                event.destination,
            )
            info = self._get_flight_info(event.agent_label)
            info["origin"] = getattr(event, "origin", info["origin"])
            info["dest"] = event.destination
            info["status"] = (
                "Delivered" if getattr(event, "delivered", False) else "Landed"
            )

        elif isinstance(event, AgentRefueling):
            self.drone_positions[event.agent_label] = DroneDisplayPosition(
                "connection",
                event.origin,
                event.destination,
            )
            info = self._get_flight_info(event.agent_label)
            info["origin"] = event.origin
            info["dest"] = event.destination
            info["status"] = "En Route"
        elif isinstance(event, WeatherChanged):
            self.connection_weather[event.connection_name] = event.condition

    def _weather_style(
        self,
        condition: str,
    ) -> tuple[tuple[int, int, int], int]:
        if condition == "storm":
            return (231, 76, 60), 5
        if condition == "snow":
            return (173, 216, 230), 5
        if condition == "rain":
            return (52, 152, 219), 4
        if condition == "tailwind":
            return (46, 204, 113), 4
        return (100, 110, 120), 3

    def _draw_map(self) -> None:
        for connection in self.graph.connections:
            start = (connection.zone_a.x, connection.zone_a.y)
            end = (connection.zone_b.x, connection.zone_b.y)
            condition = self.connection_weather.get(connection.name(), "clear")
            color, thickness = self._weather_style(condition)
            pygame.draw.line(self.screen, color, start, end, thickness)

            if condition in self.icons:
                mid_x = (start[0] + end[0]) // 2
                mid_y = (start[1] + end[1]) // 2
                icon_rect = self.icons[condition].get_rect(
                    center=(mid_x, mid_y)
                )
                self.screen.blit(self.icons[condition], icon_rect)

        for zone in self.graph.zones.values():
            pop = self.city_populations[zone.name]
            node_color = self._get_city_color(pop)

            pygame.draw.circle(self.screen, node_color, (zone.x, zone.y), 10)
            pygame.draw.circle(
                self.screen,
                (255, 255, 255),
                (zone.x, zone.y),
                10,
                1,
            )

            shadow = self.city_font.render(zone.name, True, (0, 0, 0))
            self.screen.blit(shadow, (zone.x + 11, zone.y - 14))
            text = self.city_font.render(zone.name, True, (255, 255, 255))
            self.screen.blit(text, (zone.x + 10, zone.y - 15))

            pop_text = self.badge_font.render(
                self._format_population(pop),
                True,
                (230, 230, 230),
            )
            self.screen.blit(pop_text, (zone.x + 10, zone.y + 4))

    def _draw_drones(self) -> None:
        raw_positions: dict[str, Point] = {
            z.name: (z.x, z.y) for z in self.graph.zones.values()
        }
        drone_groups: dict[Point, list[str]] = {}

        for label, pos in self.drone_positions.items():
            first = raw_positions.get(pos.first_zone)
            if first is None:
                continue

            if pos.kind == "zone" or pos.second_zone is None:
                point = first
            else:
                second = raw_positions.get(pos.second_zone)
                if second is None:
                    continue
                point = (
                    (first[0] + second[0]) // 2,
                    (first[1] + second[1]) // 2,
                )

            drone_groups.setdefault(point, []).append(label)

        for point, labels in drone_groups.items():
            if self.drone_sprite:
                sprite_rect = self.drone_sprite.get_rect(center=point)
                self.screen.blit(self.drone_sprite, sprite_rect)
            else:
                pygame.draw.circle(self.screen, (255, 200, 0), point, 8)

            if len(labels) > 1:
                count_surf = self.badge_font.render(
                    str(len(labels)),
                    True,
                    (255, 255, 255),
                )
                badge_r = max(8, count_surf.get_width() // 2 + 3)
                badge_pos = (point[0] + 12, point[1] - 12)

                pygame.draw.circle(
                    self.screen,
                    (231, 76, 60),
                    badge_pos,
                    badge_r,
                )
                pygame.draw.circle(
                    self.screen,
                    (255, 255, 255),
                    badge_pos,
                    badge_r,
                    1,
                )

                blit_pos = (
                    badge_pos[0] - count_surf.get_width() // 2,
                    badge_pos[1] - count_surf.get_height() // 2 - 1,
                )
                self.screen.blit(count_surf, blit_pos)

    def _draw_sidebar(self) -> None:
        sb_x = self.map_width

        pygame.draw.rect(
            self.screen,
            (25, 32, 42),
            (sb_x, 0, self.sidebar_width, self.height),
        )
        pygame.draw.line(
            self.screen,
            (55, 68, 85),
            (sb_x, 0),
            (sb_x, self.height),
            2,
        )

        y = 25
        title = self.city_font.render("DISPATCH CENTER", True, (218, 225, 232))
        self.screen.blit(title, (sb_x + 20, y))
        y += 40

        pygame.draw.rect(
            self.screen,
            (40, 50, 65),
            (sb_x + 15, y, self.sidebar_width - 30, 35),
            border_radius=6,
        )
        turn_text = self.city_font.render(
            f"CURRENT TURN: {self.current_turn}",
            True,
            (255, 200, 0),
        )
        self.screen.blit(turn_text, (sb_x + 25, y + 8))
        y += 55

        if self.connection_weather:
            w_title = self.dashboard_font.render(
                "WEATHER ALERTS",
                True,
                (255, 100, 100),
            )
            self.screen.blit(w_title, (sb_x + 20, y))
            y += 20
            for conn, cond in self.connection_weather.items():
                if cond != "clear":
                    c_text = self.dashboard_font.render(
                        f"* {conn}: {cond.upper()}",
                        True,
                        (150, 200, 255),
                    )
                    self.screen.blit(c_text, (sb_x + 25, y))
                    y += 18
            y += 15

        f_title = self.city_font.render("LIVE DEPARTURES", True, (0, 188, 212))
        self.screen.blit(f_title, (sb_x + 20, y))
        pygame.draw.line(
            self.screen,
            (0, 188, 212),
            (sb_x + 20, y + 20),
            (sb_x + self.sidebar_width - 20, y + 20),
        )
        y += 30

        for drone_label, info in sorted(self.flight_data.items()):
            if info["status"] == "Delivered":
                continue

            f_num = info["flight"]
            route = f"{info['origin']} -> {info['dest']}"

            card_rect = pygame.Rect(sb_x + 15, y, self.sidebar_width - 30, 50)
            pygame.draw.rect(
                self.screen,
                (35, 45, 60),
                card_rect,
                border_radius=4,
            )

            flight_surf = self.city_font.render(f_num, True, (255, 255, 255))
            self.screen.blit(flight_surf, (sb_x + 25, y + 7))

            drone_id_surf = self.badge_font.render(
                f"({drone_label})",
                True,
                (150, 160, 175),
            )
            self.screen.blit(
                drone_id_surf,
                (sb_x + 30 + flight_surf.get_width(), y + 10),
            )

            route_surf = self.dashboard_font.render(
                route,
                True,
                (170, 185, 200),
            )
            self.screen.blit(route_surf, (sb_x + 25, y + 28))

            y += 60
            if y > self.height - 60:
                more_surf = self.dashboard_font.render(
                    "... tracking more flights",
                    True,
                    (100, 110, 120),
                )
                self.screen.blit(more_surf, (sb_x + 25, y))
                break

    def run_loop(self) -> None:
        running = True
        while running:
            current_time = pygame.time.get_ticks()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

            if current_time - self.last_update_time > self.turn_delay:
                if self.current_event_index < len(self.visualizer.event_queue):
                    sim_event = self.visualizer.event_queue[
                        self.current_event_index
                    ]
                    self._apply_event(sim_event)
                    self.current_event_index += 1
                    self.last_update_time = current_time

            self.screen.fill((20, 30, 50))

            if self.bg_image:
                self.screen.blit(self.bg_image, (0, 0))

            self._draw_map()
            self._draw_drones()
            self._draw_sidebar()

            pygame.display.flip()
            self.clock.tick(60)

        pygame.quit()
        sys.exit()


def run_pygame_airlines(visualizer: PygameAirlinesVisualizer) -> None:
    window = AirlinesWindow(visualizer)
    window.run_loop()
