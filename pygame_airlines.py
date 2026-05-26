import random
import string
import sys
import math
import pygame
from typing import Optional, TypedDict

from events import (
    AgentMoved,
    AgentInTransit,
    SimulationEvent,
    WeatherChanged,
    TurnStarted,
)
from connection import Connection
from pygame_common import (
    PygameEventCollector,
    DroneDisplayPosition,
    UIColors,
    UIConstants,
    draw_count_badge,
    load_outlined_sprite,
    load_scaled_image,
    IMG_DIR,
    Point,
)
from zone import Zone


class FlightInfo(TypedDict):
    flight: str
    origin: str
    dest: str
    status: str


class PygameAirlinesVisualizer(PygameEventCollector):
    """Collects simulation events for airlines visualization."""
    pass


class AirlinesWindow:
    """Main window for the airlines visualization and control panel."""

    # Airlines-specific dark theme colors stay local to this view.
    COLOR_SIDEBAR_BG = (25, 32, 42)
    COLOR_SIDEBAR_BORDER = (55, 68, 85)
    COLOR_CARD_BG = (35, 45, 60)
    COLOR_PANEL_BG = (40, 50, 65)
    COLOR_OVERLAY_BG = (20, 30, 50, 200)
    COLOR_OVERLAY_BORDER = (80, 95, 115)
    COLOR_MUTED_DARK = (100, 110, 120)

    def __init__(self, visualizer: PygameAirlinesVisualizer) -> None:
        self.visualizer = visualizer
        self.graph = visualizer.graph

        self._setup_layout()
        self._setup_pygame()
        self._load_assets()
        self.start_hub_name = self._find_start_hub_name()
        self._initialize_flight_data()
        self._build_turn_indices()
        self._setup_playback_state()

        self._goto_turn(0)

    def _setup_layout(self) -> None:
        self.map_width = 1000
        self.sidebar_width = 350
        self.width = self.map_width + self.sidebar_width
        self.height = UIConstants.STANDARD_HEIGHT

    def _setup_pygame(self) -> None:
        pygame.init()
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("Fly-in: Global Logistics")
        self.clock = pygame.time.Clock()

        self.city_font = pygame.font.SysFont("Arial", 16, bold=True)
        self.dashboard_font = pygame.font.SysFont("Courier", 13, bold=True)
        self.badge_font = pygame.font.SysFont("Arial", 12, bold=True)

    def _load_assets(self) -> None:
        self.bg_image = self._load_background()
        self.drone_sprite = load_outlined_sprite("drone.png", (26, 26))
        self.car_sprite = load_outlined_sprite("car.png", (25, 25))
        self.icons = self._load_weather_icons()

    def _find_start_hub_name(self) -> Optional[str]:
        return next(
            (
                z.name
                for z in self.graph.zones.values()
                if getattr(z, "is_start", False)
            ),
            None,
        )

    def _initialize_flight_data(self) -> None:
        self.flight_data: dict[str, FlightInfo] = {}
        for event in self.visualizer.event_queue:
            if hasattr(event, "agent_label"):
                self._get_flight_info(event.agent_label)

    def _build_turn_indices(self) -> None:
        """Let the UI seek by turn without replaying the simulator."""
        self.turn_indices = [
            i
            for i, e in enumerate(self.visualizer.event_queue)
            if isinstance(e, TurnStarted)
        ]
        if not self.turn_indices or self.turn_indices[0] != 0:
            self.turn_indices.insert(0, 0)
        self.turn_indices.append(len(self.visualizer.event_queue))
        self.turn_indices = sorted(list(set(self.turn_indices)))

    def _setup_playback_state(self) -> None:
        self.current_turn_index = 0
        self.current_event_index = 0
        self.is_playing = True
        self.turn_delay = UIConstants.AIRLINES_TURN_DELAY_MS
        self.last_update_time = pygame.time.get_ticks()

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
            return UIColors.GREEN
        elif population < 3500000:
            return UIColors.YELLOW
        else:
            return UIColors.RED

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

    def _load_weather_icons(self) -> dict[str, pygame.Surface]:
        icons = {}
        files = [
            ("storm", "storm.png"),
            ("rain", "rain.png"),
            ("snow", "snow.png"),
            ("tailwind", "sun.png"),
        ]
        for cond, file in files:
            surf = load_scaled_image(file, (30, 30))
            if surf:
                icons[cond] = surf
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

        elif isinstance(event, AgentInTransit):
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
            return UIColors.RED, 4
        if condition == "snow":
            return UIColors.HIGHLIGHT, 4
        if condition == "rain":
            return UIColors.BLUE, 4
        if condition == "tailwind":
            return UIColors.GREEN, 4
        return UIColors.TEXT_MUTED, 3

    def _draw_weather_icon(
        self, connection: Connection, condition: str
    ) -> None:
        if condition in self.icons:
            start = (connection.zone_a.x, connection.zone_a.y)
            end = (connection.zone_b.x, connection.zone_b.y)
            mid_x = (start[0] + end[0]) // 2
            mid_y = (start[1] + end[1]) // 2
            icon_rect = self.icons[condition].get_rect(center=(mid_x, mid_y))
            self.screen.blit(self.icons[condition], icon_rect)

    def _draw_weather_connections(self) -> None:
        for connection in self.graph.connections:
            start = (connection.zone_a.x, connection.zone_a.y)
            end = (connection.zone_b.x, connection.zone_b.y)
            condition = self.connection_weather.get(connection.name(), "clear")
            color, thickness = self._weather_style(condition)
            pygame.draw.line(self.screen, color, start, end, thickness)
            self._draw_weather_icon(connection, condition)

    def _draw_city_name(self, zone: Zone) -> None:
        shadow = self.city_font.render(zone.name, True, UIColors.BLACK)
        self.screen.blit(shadow, (zone.x + 11, zone.y - 14))
        text = self.city_font.render(zone.name, True, UIColors.WHITE)
        self.screen.blit(text, (zone.x + 10, zone.y - 15))

    def _draw_population_label(self, zone: Zone) -> None:
        pop = getattr(zone, "population", 500000)
        if pop == 0:
            pop = 500000

        pop_str = self._format_population(pop)

        # Border text for readability
        border_text = self.badge_font.render(pop_str, True, UIColors.WHITE)
        self.screen.blit(border_text, (zone.x + 9, zone.y + 4))
        self.screen.blit(border_text, (zone.x + 11, zone.y + 4))
        self.screen.blit(border_text, (zone.x + 10, zone.y + 3))
        self.screen.blit(border_text, (zone.x + 10, zone.y + 5))

        # Main text
        pop_text = self.badge_font.render(pop_str, True, (64, 64, 64))
        self.screen.blit(pop_text, (zone.x + 10, zone.y + 4))

    def _draw_city(self, zone: Zone) -> None:
        """
        Airlines mode uses the map coordinates directly; standard mode rescales
        coordinates into a viewport.
        """
        pop = getattr(zone, "population", 500000)
        if pop == 0:
            pop = 500000

        node_color = self._get_city_color(pop)

        pygame.draw.circle(self.screen, node_color, (zone.x, zone.y), 10)
        pygame.draw.circle(
            self.screen, UIColors.WHITE, (zone.x, zone.y), 10, 1
        )

        self._draw_city_name(zone)
        self._draw_population_label(zone)

    def _draw_map(self) -> None:
        self._draw_weather_connections()

        for zone in self.graph.zones.values():
            self._draw_city(zone)

    def _zone_points(self) -> dict[str, Point]:
        return {z.name: (z.x, z.y) for z in self.graph.zones.values()}

    def _resolve_drone_point(
        self, pos: DroneDisplayPosition, raw_positions: dict[str, Point]
    ) -> Optional[Point]:
        first = raw_positions.get(pos.first_zone)
        if first is None:
            return None

        if pos.kind == "zone" or pos.second_zone is None:
            return first

        second = raw_positions.get(pos.second_zone)
        if second is None:
            return None

        return ((first[0] + second[0]) // 2, (first[1] + second[1]) // 2)

    def _is_road_segment(self, first_zone: str, second_zone: str) -> bool:
        """
        Transport type is presentation logic here; simulation still uses the
        same connection and movement events.
        """
        zone_a = self.graph.get_zone(first_zone)
        zone_b = self.graph.get_zone(second_zone)
        if zone_a and zone_b:
            conn = self.graph.get_connection(zone_a, zone_b)
            if conn and 0 < conn.distance < 200:
                return True
        return False

    def _group_vehicles_by_point(self) -> dict[tuple[Point, bool], list[str]]:
        raw_positions = self._zone_points()
        groups: dict[tuple[Point, bool], list[str]] = {}

        for label, pos in self.drone_positions.items():
            point = self._resolve_drone_point(pos, raw_positions)
            if point is None:
                continue

            is_car = False
            if pos.kind == "connection" and pos.second_zone:
                is_car = self._is_road_segment(pos.first_zone, pos.second_zone)

            groups.setdefault((point, is_car), []).append(label)

        return groups

    def _draw_vehicle_group(
        self, point: Point, is_car: bool, labels: list[str]
    ) -> None:
        sprite_to_draw = self.car_sprite if is_car else self.drone_sprite

        if sprite_to_draw:
            sprite_rect = sprite_to_draw.get_rect(center=point)
            self.screen.blit(sprite_to_draw, sprite_rect)
        else:
            fallback_color = UIColors.BLUE if is_car else UIColors.YELLOW
            pygame.draw.circle(self.screen, fallback_color, point, 8)

        draw_count_badge(self.screen, self.badge_font, point, len(labels))

    def _draw_drones(self) -> None:
        drone_groups = self._group_vehicles_by_point()

        for (point, is_car), labels in drone_groups.items():
            self._draw_vehicle_group(point, is_car, labels)

    def _draw_map_controls(self) -> None:
        overlay_rect = pygame.Rect(20, self.height - 75, 410, 55)

        overlay_surf = pygame.Surface(
            (overlay_rect.width, overlay_rect.height), pygame.SRCALPHA
        )
        overlay_surf.fill(self.COLOR_OVERLAY_BG)
        self.screen.blit(overlay_surf, overlay_rect.topleft)
        pygame.draw.rect(
            self.screen,
            self.COLOR_OVERLAY_BORDER,
            overlay_rect,
            width=1,
            border_radius=4,
        )

        status_color = UIColors.GREEN if self.is_playing else UIColors.RED
        status_text = "AUTO" if self.is_playing else "PAUSE"
        status_surf = self.dashboard_font.render(
            status_text, True, status_color
        )
        self.screen.blit(status_surf, (35, self.height - 56))

        pygame.draw.line(
            self.screen,
            self.COLOR_OVERLAY_BORDER,
            (115, self.height - 65),
            (115, self.height - 30),
            1,
        )

        controls_1 = self.dashboard_font.render(
            "[SPACE] Play/Pause    [R] Reset", True, UIColors.TEXT_LIGHT
        )
        controls_2 = self.dashboard_font.render(
            "[<] Prev Turn         [>] Next Turn", True, UIColors.TEXT_LIGHT
        )
        self.screen.blit(controls_1, (135, self.height - 66))
        self.screen.blit(controls_2, (135, self.height - 46))

    def _draw_sidebar_background(self) -> None:
        sb_x = self.map_width
        pygame.draw.rect(
            self.screen,
            self.COLOR_SIDEBAR_BG,
            (sb_x, 0, self.sidebar_width, self.height),
        )
        pygame.draw.line(
            self.screen,
            self.COLOR_SIDEBAR_BORDER,
            (sb_x, 0),
            (sb_x, self.height),
            2,
        )

    def _draw_sidebar_header(self) -> int:
        sb_x = self.map_width
        y = 25
        title = self.city_font.render(
            "DISPATCH CENTER", True, UIColors.TEXT_LIGHT
        )
        self.screen.blit(title, (sb_x + 20, y))
        y += 40

        pygame.draw.rect(
            self.screen,
            self.COLOR_PANEL_BG,
            (sb_x + 15, y, self.sidebar_width - 30, 35),
            border_radius=6,
        )
        turn_text = self.city_font.render(
            f"CURRENT TURN: {self.current_turn}", True, UIColors.YELLOW
        )
        self.screen.blit(turn_text, (sb_x + 25, y + 8))
        return y + 55

    def _draw_weather_alerts(self, y: int) -> int:
        if not self.connection_weather:
            return y

        sb_x = self.map_width
        w_title = self.dashboard_font.render(
            "WEATHER ALERTS", True, UIColors.RED
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
        return y + 15

    def _determine_flight_status(
        self, info: FlightInfo
    ) -> tuple[str, tuple[int, int, int]]:
        """
        Status text is presentation-only. The real route state comes from
        replayed simulation events.
        """
        if info["status"] != "En Route":
            return "LANDED", UIColors.YELLOW

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
                        return "ROAD DELAY", UIColors.RED
                    return "DRIVING", UIColors.BLUE
                else:
                    if current_weather in ("storm", "snow"):
                        return "DELAYED", UIColors.RED

        return "EN ROUTE", UIColors.GREEN

    def _draw_departure_card(
        self,
        y: int,
        drone_label: str,
        info: FlightInfo,
        status_str: str,
        status_color: tuple[int, int, int],
    ) -> None:
        sb_x = self.map_width
        f_num = info["flight"]
        route = f"{info['origin']} -> {info['dest']}"

        card_rect = pygame.Rect(sb_x + 15, y, self.sidebar_width - 30, 50)
        pygame.draw.rect(
            self.screen, self.COLOR_CARD_BG, card_rect, border_radius=4
        )

        flight_surf = self.city_font.render(f_num, True, UIColors.WHITE)
        self.screen.blit(flight_surf, (sb_x + 25, y + 7))

        drone_id_surf = self.badge_font.render(
            f"({drone_label})", True, UIColors.TEXT_MUTED
        )
        self.screen.blit(
            drone_id_surf, (sb_x + 30 + flight_surf.get_width(), y + 10)
        )

        status_surf = self.badge_font.render(status_str, True, status_color)
        self.screen.blit(
            status_surf,
            (
                sb_x + self.sidebar_width - 25 - status_surf.get_width(),
                y + 10,
            ),
        )

        route_surf = self.dashboard_font.render(
            route, True, UIColors.TEXT_MUTED
        )
        self.screen.blit(route_surf, (sb_x + 25, y + 28))

    def _draw_live_departures(self, y: int) -> None:
        sb_x = self.map_width
        f_title = self.city_font.render("LIVE DEPARTURES", True, UIColors.CYAN)
        self.screen.blit(f_title, (sb_x + 20, y))
        pygame.draw.line(
            self.screen,
            UIColors.CYAN,
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

            status_str, status_color = self._determine_flight_status(info)
            self._draw_departure_card(
                y, drone_label, info, status_str, status_color
            )

            y += 60
            if y > self.height - 60:
                more_surf = self.dashboard_font.render(
                    "... tracking more flights", True, self.COLOR_MUTED_DARK
                )
                self.screen.blit(more_surf, (sb_x + 25, y))
                break

    def _draw_sidebar(self) -> None:
        self._draw_sidebar_background()
        y = self._draw_sidebar_header()
        y = self._draw_weather_alerts(y)
        self._draw_live_departures(y)

    def run_loop(self) -> None:
        running = True
        while running:
            current_time = pygame.time.get_ticks()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    occupancy: dict[str, int] = {}
                    for pos_info in self.drone_positions.values():
                        if pos_info.kind == "zone":
                            occupancy[pos_info.first_zone] = (
                                occupancy.get(pos_info.first_zone, 0) + 1
                            )

                    click_x, click_y = event.pos
                    for zone in self.graph.zones.values():
                        distance = math.hypot(
                            zone.x - click_x,
                            zone.y - click_y,
                        )

                        if distance <= 15:
                            current_pop = occupancy.get(zone.name, 0)
                            max_cap = zone.effective_capacity()
                            max_cap_str = (
                                "INF"
                                if max_cap == float("inf")
                                else str(max_cap)
                            )

                            print(f"\n[ATC HUB REPORT: {zone.name.upper()}]")
                            print(
                                "  -> Regional Population: "
                                f"{getattr(zone, 'population', 'N/A')}"
                            )
                            print(
                                "  -> Logistics Type:      "
                                f"{zone.zone_type.value.upper()}"
                            )
                            print(
                                "  -> Traffic Load:        "
                                f"{current_pop} / {max_cap_str} drones"
                            )
                            break
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

            self.screen.fill(self.COLOR_OVERLAY_BG)

            if self.bg_image:
                self.screen.blit(self.bg_image, (0, 0))

            self._draw_map()
            self._draw_drones()
            self._draw_map_controls()
            self._draw_sidebar()

            pygame.display.flip()
            self.clock.tick(UIConstants.FPS)

        pygame.quit()
        sys.exit()


def run_pygame_airlines(visualizer: PygameAirlinesVisualizer) -> None:
    window = AirlinesWindow(visualizer)
    window.run_loop()
