import random
import string
import sys
import pygame
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, TypedDict

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
IMG_DIR = Path(__file__).resolve().parent / "img"


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
    """Main window for the airlines visualization and control panel."""

    def __init__(self, visualizer: PygameAirlinesVisualizer) -> None:
        pygame.init()
        self.visualizer = visualizer
        self.graph = visualizer.graph

        self.map_width = 1000
        self.sidebar_width = 350
        self.width = self.map_width + self.sidebar_width
        self.height = 800

        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("Fly-in: Global Logistics")
        self.clock = pygame.time.Clock()

        self.city_font = pygame.font.SysFont("Arial", 16, bold=True)
        self.dashboard_font = pygame.font.SysFont("Courier", 13, bold=True)
        self.badge_font = pygame.font.SysFont("Arial", 12, bold=True)

        self.bg_image = self._load_background()
        self.drone_sprite = self._load_drone_sprite()
        self.car_sprite = self._load_car_sprite()
        self.icons = self._load_weather_icons()

        self.start_hub_name = next(
            (
                z.name
                for z in self.graph.zones.values()
                if getattr(z, "is_start", False)
            ),
            None,
        )

        self.flight_data: dict[str, FlightInfo] = {}
        for event in self.visualizer.event_queue:
            if hasattr(event, "agent_label"):
                self._get_flight_info(event.agent_label)

        self.turn_indices = [
            i
            for i, e in enumerate(self.visualizer.event_queue)
            if isinstance(e, TurnStarted)
        ]
        if not self.turn_indices or self.turn_indices[0] != 0:
            self.turn_indices.insert(0, 0)
        self.turn_indices.append(len(self.visualizer.event_queue))
        self.turn_indices = sorted(list(set(self.turn_indices)))

        self.current_turn_index = 0
        self.current_event_index = 0
        self.is_playing = True
        self.turn_delay = 1000
        self.last_update_time = pygame.time.get_ticks()

        self._goto_turn(0)

    def _reset_state(self) -> None:
        self.current_turn = 0
        self.drone_positions: dict[str, DroneDisplayPosition] = {}
        self.connection_weather: dict[str, str] = {}

        if self.start_hub_name:
            for label, info in self.flight_data.items():
                self.drone_positions[label] = DroneDisplayPosition(
                    "zone", self.start_hub_name
                )
                info["origin"] = self.start_hub_name
                info["dest"] = self.start_hub_name
                info["status"] = "Idle"

    def _goto_turn(self, turn_idx: int) -> None:
        self.current_turn_index = max(
            0, min(turn_idx, len(self.turn_indices) - 1)
        )
        target_event_idx = self.turn_indices[self.current_turn_index]

        self._reset_state()
        for i in range(target_event_idx):
            self._apply_event(self.visualizer.event_queue[i])

        self.current_event_index = target_event_idx

    def _get_city_color(self, population: int) -> tuple[int, int, int]:
        if population < 1000000:
            return (46, 204, 113)
        elif population < 3500000:
            return (241, 196, 15)
        else:
            return (231, 76, 60)

    def _format_population(self, population: int) -> str:
        if population >= 1000000:
            return f"{population/1000000:.1f}M"
        return f"{population//1000}K"

    def _load_background(self) -> Optional[pygame.Surface]:
        bg_image_name = "germany.png"
        for arg in sys.argv:
            if "europa" in arg.lower():
                bg_image_name = "europa.png"
        try:
            bg = pygame.image.load(IMG_DIR / bg_image_name)
            return pygame.transform.scale(bg, (self.map_width, self.height))
        except FileNotFoundError:
            return None

    def _load_drone_sprite(self) -> Optional[pygame.Surface]:
        try:
            sprite = pygame.image.load(IMG_DIR / "drone.png").convert_alpha()
            base_size = (26, 26)
            base_sprite = pygame.transform.scale(sprite, base_size)

            mask = pygame.mask.from_surface(base_sprite)
            mask_surf = mask.to_surface(
                setcolor=(255, 255, 255), unsetcolor=(0, 0, 0, 0)
            )
            mask_surf.set_colorkey((0, 0, 0))

            final_surf = pygame.Surface((32, 32), pygame.SRCALPHA)

            offsets = [
                (-1, 0),
                (1, 0),
                (0, -1),
                (0, 1),
                (-1, -1),
                (-1, 1),
                (1, -1),
                (1, 1),
            ]
            for dx, dy in offsets:
                final_surf.blit(mask_surf, (dx + 3, dy + 3))

            final_surf.blit(base_sprite, (3, 3))
            return final_surf
        except FileNotFoundError:
            return None

    def _load_car_sprite(self) -> Optional[pygame.Surface]:
        try:
            # Add a programmatic 1 px white border around the car icon.
            sprite = pygame.image.load(IMG_DIR / "car.png").convert_alpha()
            base_size = (25, 25)
            base_sprite = pygame.transform.scale(sprite, base_size)

            mask = pygame.mask.from_surface(base_sprite)
            mask_surf = mask.to_surface(
                setcolor=(255, 255, 255), unsetcolor=(0, 0, 0, 0)
            )
            mask_surf.set_colorkey((0, 0, 0))

            final_surf = pygame.Surface((32, 32), pygame.SRCALPHA)

            offsets = [
                (-1, 0),
                (1, 0),
                (0, -1),
                (0, 1),
                (-1, -1),
                (-1, 1),
                (1, -1),
                (1, 1),
            ]
            for dx, dy in offsets:
                final_surf.blit(mask_surf, (dx + 3, dy + 3))

            final_surf.blit(base_sprite, (3, 3))
            return final_surf
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
                surf = pygame.image.load(IMG_DIR / file).convert_alpha()
                icons[cond] = pygame.transform.scale(surf, (30, 30))
        except FileNotFoundError:
            pass
        return icons

    def _get_flight_info(self, drone_label: str) -> FlightInfo:
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
        self, condition: str
    ) -> tuple[tuple[int, int, int], int]:
        if condition == "storm":
            return (231, 76, 60), 4
        if condition == "snow":
            return (135, 215, 240), 4
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
            pop = getattr(zone, "population", 500000)
            if pop == 0:
                pop = 500000

            node_color = self._get_city_color(pop)

            pygame.draw.circle(self.screen, node_color, (zone.x, zone.y), 10)
            pygame.draw.circle(
                self.screen, (255, 255, 255), (zone.x, zone.y), 10, 1
            )

            shadow = self.city_font.render(zone.name, True, (0, 0, 0))
            self.screen.blit(shadow, (zone.x + 11, zone.y - 14))
            text = self.city_font.render(zone.name, True, (255, 255, 255))
            self.screen.blit(text, (zone.x + 10, zone.y - 15))

            pop_str = self._format_population(pop)
            border_text = self.badge_font.render(
                pop_str, True, (255, 255, 255)
            )
            self.screen.blit(border_text, (zone.x + 9, zone.y + 4))
            self.screen.blit(border_text, (zone.x + 11, zone.y + 4))
            self.screen.blit(border_text, (zone.x + 10, zone.y + 3))
            self.screen.blit(border_text, (zone.x + 10, zone.y + 5))

            pop_text = self.badge_font.render(pop_str, True, (64, 64, 64))
            self.screen.blit(pop_text, (zone.x + 10, zone.y + 4))

    def _draw_drones(self) -> None:
        raw_positions: dict[str, Point] = {
            z.name: (z.x, z.y) for z in self.graph.zones.values()
        }
        # Group positions to avoid collisions between transport modes.
        drone_groups: dict[tuple[Point, bool], list[str]] = {}

        for label, pos in self.drone_positions.items():
            first = raw_positions.get(pos.first_zone)
            if first is None:
                continue

            if pos.kind == "zone" or pos.second_zone is None:
                point = first
                is_car = False
            else:
                second = raw_positions.get(pos.second_zone)
                if second is None:
                    continue
                point = (
                    (first[0] + second[0]) // 2,
                    (first[1] + second[1]) // 2,
                )

                # Check whether this route segment should use the car layer.
                is_car = False
                zone_a = self.graph.get_zone(pos.first_zone)
                zone_b = self.graph.get_zone(pos.second_zone)
                if zone_a and zone_b:
                    conn = self.graph.get_connection(zone_a, zone_b)
                    if conn and 0 < conn.distance < 200:
                        is_car = True

            drone_groups.setdefault((point, is_car), []).append(label)

        for (point, is_car), labels in drone_groups.items():
            sprite_to_draw = self.car_sprite if is_car else self.drone_sprite

            if sprite_to_draw:
                sprite_rect = sprite_to_draw.get_rect(center=point)
                self.screen.blit(sprite_to_draw, sprite_rect)
            else:
                fallback_color = (52, 152, 219) if is_car else (255, 200, 0)
                pygame.draw.circle(self.screen, fallback_color, point, 8)

            if len(labels) > 1:
                count_surf = self.badge_font.render(
                    str(len(labels)), True, (255, 255, 255)
                )
                badge_r = max(8, count_surf.get_width() // 2 + 3)
                badge_pos = (point[0] + 12, point[1] - 12)

                pygame.draw.circle(
                    self.screen, (231, 76, 60), badge_pos, badge_r
                )
                pygame.draw.circle(
                    self.screen, (255, 255, 255), badge_pos, badge_r, 1
                )

                blit_pos = (
                    badge_pos[0] - count_surf.get_width() // 2,
                    badge_pos[1] - count_surf.get_height() // 2 - 1,
                )
                self.screen.blit(count_surf, blit_pos)

    def _draw_map_controls(self) -> None:
        overlay_rect = pygame.Rect(20, self.height - 75, 410, 55)

        overlay_surf = pygame.Surface(
            (overlay_rect.width, overlay_rect.height), pygame.SRCALPHA
        )
        overlay_surf.fill((20, 30, 50, 200))
        self.screen.blit(overlay_surf, overlay_rect.topleft)
        pygame.draw.rect(
            self.screen,
            (80, 95, 115),
            overlay_rect,
            width=1,
            border_radius=4,
        )

        status_color = (
            (46, 204, 113) if self.is_playing else (231, 76, 60)
        )
        status_text = "AUTO" if self.is_playing else "PAUSE"
        status_surf = self.dashboard_font.render(
            status_text, True, status_color
        )
        self.screen.blit(status_surf, (35, self.height - 56))

        pygame.draw.line(
            self.screen,
            (80, 95, 115),
            (115, self.height - 65),
            (115, self.height - 30),
            1,
        )

        controls_1 = self.dashboard_font.render(
            "[SPACE] Play/Pause    [R] Reset", True, (210, 220, 230)
        )
        controls_2 = self.dashboard_font.render(
            "[<] Prev Turn         [>] Next Turn", True, (210, 220, 230)
        )
        self.screen.blit(controls_1, (135, self.height - 66))
        self.screen.blit(controls_2, (135, self.height - 46))

    def _draw_sidebar(self) -> None:
        sb_x = self.map_width

        pygame.draw.rect(
            self.screen,
            (25, 32, 42),
            (sb_x, 0, self.sidebar_width, self.height),
        )
        pygame.draw.line(
            self.screen, (55, 68, 85), (sb_x, 0), (sb_x, self.height), 2
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
            f"CURRENT TURN: {self.current_turn}", True, (255, 200, 0)
        )
        self.screen.blit(turn_text, (sb_x + 25, y + 8))
        y += 55

        if self.connection_weather:
            w_title = self.dashboard_font.render(
                "WEATHER ALERTS", True, (255, 100, 100)
            )
            self.screen.blit(w_title, (sb_x + 20, y))
            y += 20
            for conn_name, cond in self.connection_weather.items():
                if cond != "clear":
                    w_color, _ = self._weather_style(cond)
                    c_text = self.dashboard_font.render(
                        f"{conn_name}: {cond.upper()}", True, w_color
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
            if (
                info["status"] in ("Idle", "Delivered")
                or info["origin"] == info["dest"]
            ):
                continue

            f_num = info["flight"]
            route = f"{info['origin']} -> {info['dest']}"

            status_str = "EN ROUTE"
            status_color = (46, 204, 113)

            if info["status"] == "En Route":
                zone_a = self.graph.get_zone(info["origin"])
                zone_b = self.graph.get_zone(info["dest"])
                if zone_a and zone_b:
                    conn = self.graph.get_connection(zone_a, zone_b)
                    if conn:
                        current_weather = self.connection_weather.get(
                            conn.name(), "clear"
                        )

                        if conn.distance < 200:
                            if current_weather in ("storm", "snow"):
                                status_str = "ROAD DELAY"
                                status_color = (231, 76, 60)
                            else:
                                status_str = "DRIVING"
                                status_color = (52, 152, 219)
                        else:
                            if current_weather in ("storm", "snow"):
                                status_str = "DELAYED"
                                status_color = (231, 76, 60)
            else:
                status_str = "LANDED"
                status_color = (241, 196, 15)

            card_rect = pygame.Rect(
                sb_x + 15, y, self.sidebar_width - 30, 50
            )
            pygame.draw.rect(
                self.screen, (35, 45, 60), card_rect, border_radius=4
            )

            flight_surf = self.city_font.render(f_num, True, (255, 255, 255))
            self.screen.blit(flight_surf, (sb_x + 25, y + 7))

            drone_id_surf = self.badge_font.render(
                f"({drone_label})", True, (150, 160, 175)
            )
            self.screen.blit(
                drone_id_surf, (sb_x + 30 + flight_surf.get_width(), y + 10)
            )

            status_surf = self.badge_font.render(
                status_str, True, status_color
            )
            self.screen.blit(
                status_surf,
                (
                    sb_x + self.sidebar_width - 25 - status_surf.get_width(),
                    y + 10,
                ),
            )

            route_surf = self.dashboard_font.render(
                route, True, (170, 185, 200)
            )
            self.screen.blit(route_surf, (sb_x + 25, y + 28))

            y += 60
            if y > self.height - 60:
                more_surf = self.dashboard_font.render(
                    "... tracking more flights", True, (100, 110, 120)
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
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    print(f"Coordinates: {event.pos[0]} {event.pos[1]}")
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE:
                        self.is_playing = not self.is_playing
                    elif event.key == pygame.K_RIGHT:
                        self.is_playing = False
                        self._goto_turn(self.current_turn_index + 1)
                    elif event.key == pygame.K_LEFT:
                        self.is_playing = False
                        self._goto_turn(self.current_turn_index - 1)
                    elif event.key == pygame.K_r:
                        self.is_playing = False
                        self._goto_turn(0)

            if (
                self.is_playing
                and current_time - self.last_update_time > self.turn_delay
            ):
                if self.current_turn_index < len(self.turn_indices) - 1:
                    self._goto_turn(self.current_turn_index + 1)
                    self.last_update_time = current_time
                else:
                    self.is_playing = False

            self.screen.fill((20, 30, 50))

            if self.bg_image:
                self.screen.blit(self.bg_image, (0, 0))

            self._draw_map()
            self._draw_drones()
            self._draw_map_controls()
            self._draw_sidebar()

            pygame.display.flip()
            self.clock.tick(60)

        pygame.quit()
        sys.exit()


def run_pygame_airlines(visualizer: PygameAirlinesVisualizer) -> None:
    window = AirlinesWindow(visualizer)
    window.run_loop()
