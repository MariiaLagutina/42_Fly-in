import math
from dataclasses import dataclass
from typing import Literal, Optional

import pygame

from events import (
    AgentMoved,
    AgentInTransit,
    EventListener,
    SimulationEvent,
    TurnFinished,
)
from graph import Graph
from zone import Zone, ZoneType
from pygame_common import UIColors, UIConstants, load_sprite

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
    """Visualizer that builds frame-by-frame simulation data."""

    def __init__(self, graph: Graph, nb_drones: int) -> None:
        self.graph = graph
        self.nb_drones = nb_drones
        self.event_queue: list[SimulationEvent] = []

    def handle(self, event: SimulationEvent) -> None:
        """Append simulation event to queue for later visualization."""
        self.event_queue.append(event)

    def build_frames(self) -> list[StandardTurnFrame]:
        """Build frame-by-frame simulation snapshots from events."""
        if self.graph.start_zone is None:
            return []

        positions = {
            f"D{drone_id}": DroneDisplayPosition(
                "zone", self.graph.start_zone.name
            )
            for drone_id in range(1, self.nb_drones + 1)
        }
        frames = [StandardTurnFrame(0, positions.copy(), ())]

        for event in self.event_queue:
            if isinstance(event, AgentMoved):
                positions[event.agent_label] = DroneDisplayPosition(
                    "zone", event.destination
                )
            elif isinstance(event, AgentInTransit):
                positions[event.agent_label] = DroneDisplayPosition(
                    "connection", event.origin, event.destination
                )
            elif isinstance(event, TurnFinished):
                frames.append(
                    StandardTurnFrame(
                        event.turn_number, positions.copy(), event.movements
                    )
                )
        return frames


class DroneSimulationWindow:
    """Main pygame window for standard drone simulation visualization."""

    MAP_ZONE_COLORS = {
        "green": UIColors.GREEN,
        "blue": UIColors.BLUE,
        "red": UIColors.RED,
        "yellow": UIColors.YELLOW,
        "orange": UIColors.ORANGE,
        "cyan": UIColors.CYAN,
        "purple": UIColors.PURPLE,
        "brown": UIColors.BROWN,
        "lime": UIColors.LIME,
        "magenta": UIColors.MAGENTA,
        "gold": UIColors.GOLD,
        "black": (42, 46, 54),
        "maroon": (115, 35, 35),
        "darkred": (145, 20, 20),
        "violet": (180, 120, 245),
        "crimson": (220, 20, 60),
    }

    def __init__(
        self,
        visualizer: PygameStandardVisualizer,
        width: int = UIConstants.STANDARD_WIDTH,
        height: int = UIConstants.STANDARD_HEIGHT,
    ) -> None:
        """Initialize pygame window and layout parameters."""
        pygame.init()
        self.visualizer = visualizer
        self.frames = visualizer.build_frames()
        self.graph = visualizer.graph
        self.autoplay = True

        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption("Fly-in UI: Standard Mode")

        self.drone_sprite = load_sprite("drone.png", (30, 30))
        self.clock = pygame.time.Clock()

        self.title_font = pygame.font.SysFont("Arial", 20, bold=True)
        self.text_font = pygame.font.SysFont("Arial", 15)
        self.node_font = pygame.font.SysFont("Arial", 13)

        margin = UIConstants.MARGIN
        panel_h = UIConstants.HISTORY_PANEL_HEIGHT
        self.viewport = pygame.Rect(
            margin,
            panel_h + margin,
            width - (margin * 2),
            height - panel_h - (margin * 2),
        )
        self.node_positions = self._calculate_adaptive_positions()

    def _calculate_adaptive_positions(self) -> dict[str, tuple[int, int]]:
        """Map graph zone coordinates to screen positions based on viewport."""
        zones = list(self.graph.zones.values())
        if not zones:
            return {}

        xs = [z.x for z in zones]
        ys = [z.y for z in zones]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        range_x = (max_x - min_x) if max_x != min_x else 1
        range_y = (max_y - min_y) if max_y != min_y else 1

        positions = {}
        for zone in zones:
            norm_x = (zone.x - min_x) / range_x
            norm_y = (zone.y - min_y) / range_y
            screen_x = int(
                self.viewport.left + (norm_x * (self.viewport.width - 60)) + 30
            )
            screen_y = int(
                self.viewport.top + (norm_y * (self.viewport.height - 60)) + 30
            )
            positions[zone.name] = (screen_x, screen_y)

        return positions

    def _get_zone_color(self, zone: Zone) -> tuple[int, int, int]:
        """Get RGB color for a zone based on its properties."""
        if zone.color in self.MAP_ZONE_COLORS:
            return self.MAP_ZONE_COLORS[zone.color]
        if zone.is_start:
            return UIColors.GREEN
        if zone.is_end:
            return UIColors.RED
        if zone.zone_type == ZoneType.PRIORITY:
            return UIColors.BLUE
        if zone.zone_type == ZoneType.RESTRICTED:
            return UIColors.PURPLE
        if zone.zone_type == ZoneType.BLOCKED:
            return UIColors.BLACK
        return UIColors.WHITE

    def draw(self, frame: StandardTurnFrame) -> None:
        """Render the complete simulation frame."""
        self.screen.fill(UIColors.SLATE_BG)

        self._draw_history_bar(frame)

        active_conns, path_counts = self._analyze_frame_connections(frame)
        self._draw_connections(active_conns, path_counts)

        self._draw_zones()
        self._draw_drones(frame)

    def _analyze_frame_connections(
        self, frame: StandardTurnFrame
    ) -> tuple[set[tuple[str, str]], dict[tuple[str, str], int]]:
        """Extracts which lines are active and paths sharing a line."""
        active_connections: set[tuple[str, str]] = set()
        for pos_info in frame.positions.values():
            if pos_info.kind == "connection" and pos_info.second_zone:
                c_id = tuple(
                    sorted([pos_info.first_zone, pos_info.second_zone])
                )
                if len(c_id) == 2:
                    active_connections.add((c_id[0], c_id[1]))

        path_counts: dict[tuple[str, str], int] = {}
        for conn in self.graph.connections:
            path_id_list = sorted([conn.zone_a.name, conn.zone_b.name])
            path_id = (path_id_list[0], path_id_list[1])
            path_counts[path_id] = path_counts.get(path_id, 0) + 1

        return active_connections, path_counts

    def _draw_connections(
        self,
        active_connections: set[tuple[str, str]],
        path_counts: dict[tuple[str, str], int],
    ) -> None:
        """Renders lines connecting the zones."""
        for conn in self.graph.connections:
            p1 = self.node_positions[conn.zone_a.name]
            p2 = self.node_positions[conn.zone_b.name]
            path_id_list = sorted([conn.zone_a.name, conn.zone_b.name])
            path_id = (path_id_list[0], path_id_list[1])
            count = path_counts.get(path_id, 1)

            line_color = UIColors.LINE_DEFAULT
            thickness = UIConstants.LINE_THICKNESS_DEFAULT

            if path_id in active_connections:
                line_color = UIColors.BLUE
                thickness = UIConstants.LINE_THICKNESS_ACTIVE

            if count > 1:
                dx, dy = p2[0] - p1[0], p2[1] - p1[1]
                dist = math.hypot(dx, dy)
                if dist > 0:
                    offset = count * 6
                    p1 = (
                        int(p1[0] - (dy / dist) * offset),
                        int(p1[1] + (dx / dist) * offset),
                    )
                    p2 = (
                        int(p2[0] - (dy / dist) * offset),
                        int(p2[1] + (dx / dist) * offset),
                    )

            pygame.draw.line(
                self.screen, UIColors.WHITE, p1, p2, thickness + 2
            )
            pygame.draw.line(self.screen, line_color, p1, p2, thickness)

    def _draw_zones(self) -> None:
        """Renders the circular nodes and their labels."""
        for zone in self.graph.zones.values():
            pos = self.node_positions[zone.name]
            color = self._get_zone_color(zone)

            pygame.draw.circle(
                self.screen, color, pos, UIConstants.NODE_RADIUS
            )
            pygame.draw.circle(
                self.screen,
                UIColors.ZONE_BORDER,
                pos,
                UIConstants.NODE_RADIUS,
                2,
            )

            label = self.node_font.render(
                zone.name[:10], True, UIColors.ZONE_BORDER
            )
            text_bg_rect = pygame.Rect(
                pos[0] - label.get_width() // 2 - 4,
                pos[1] + 20,
                label.get_width() + 8,
                label.get_height() + 2,
            )
            pygame.draw.rect(
                self.screen, UIColors.WHITE, text_bg_rect, border_radius=4
            )
            self.screen.blit(
                label, (pos[0] - label.get_width() // 2, pos[1] + 22)
            )

    def _draw_drones(self, frame: StandardTurnFrame) -> None:
        """Renders drones and grouped count badges on the map."""
        drone_groups: dict[tuple[int, int], list[str]] = {}

        for drone_label, pos_info in frame.positions.items():
            p_start = self.node_positions[pos_info.first_zone]
            if pos_info.kind == "zone" or pos_info.second_zone is None:
                target_point = p_start
            else:
                p_end = self.node_positions[pos_info.second_zone]
                target_point = (
                    (p_start[0] + p_end[0]) // 2,
                    (p_start[1] + p_end[1]) // 2,
                )

            drone_groups.setdefault(target_point, []).append(drone_label)

        for point, labels in drone_groups.items():
            if getattr(self, "drone_sprite", None):
                sprite_rect = self.drone_sprite.get_rect(center=point)
                self.screen.blit(self.drone_sprite, sprite_rect)

            count = len(labels)
            if count > 1:
                count_surface = self.node_font.render(
                    str(count), True, UIColors.WHITE
                )
                badge_radius = max(
                    UIConstants.BADGE_RADIUS_MIN,
                    count_surface.get_width() // 2 + 3,
                )
                badge_pos = (point[0] + 12, point[1] - 12)

                pygame.draw.circle(
                    self.screen, UIColors.RED, badge_pos, badge_radius
                )
                pygame.draw.circle(
                    self.screen, UIColors.WHITE, badge_pos, badge_radius, 1
                )

                blit_pos = (
                    badge_pos[0] - count_surface.get_width() // 2,
                    badge_pos[1] - count_surface.get_height() // 2 - 1,
                )
                self.screen.blit(count_surface, blit_pos)

    def _draw_history_bar(self, frame: StandardTurnFrame) -> None:
        """Draws the top panel showing turn status and movement logs."""
        panel_rect = pygame.Rect(
            0, 0, self.screen.get_width(), UIConstants.HISTORY_PANEL_HEIGHT
        )
        pygame.draw.rect(self.screen, UIColors.DARK_PANEL, panel_rect)
        pygame.draw.line(
            self.screen,
            UIColors.BLUE,
            (0, UIConstants.HISTORY_PANEL_HEIGHT),
            (self.screen.get_width(), UIConstants.HISTORY_PANEL_HEIGHT),
            2,
        )

        total_frames = max(0, len(self.frames) - 1)
        turn_str = f"Turn: {frame.turn_number} / {total_frames}"
        turn_surf = self.title_font.render(turn_str, True, UIColors.WHITE)
        self.screen.blit(turn_surf, (25, 20))

        status_str, status_color = (
            ("[AUTO]", UIColors.GREEN)
            if self.autoplay
            else ("[PAUSE]", UIColors.RED)
        )
        status_surf = self.title_font.render(status_str, True, status_color)
        self.screen.blit(status_surf, (200, 20))

        hint_str = "(Space: Auto/Pause | Left/Right: Step | R: Reset)"
        hint_surf = self.node_font.render(hint_str, True, UIColors.TEXT_MUTED)
        self.screen.blit(hint_surf, (25, 48))

        move_title = self.title_font.render(
            "Movement:", True, UIColors.HIGHLIGHT
        )
        self.screen.blit(move_title, (25, 80))

        current_x, current_y = 135, 82
        for drone_label, dest in frame.movements:
            move_str = f"{drone_label}→{dest[:7]}"
            surf = self.text_font.render(move_str, True, UIColors.TEXT_LIGHT)

            if current_x + surf.get_width() > self.screen.get_width() - 25:
                current_x = 135
                current_y += 22
                if current_y + 18 > UIConstants.HISTORY_PANEL_HEIGHT:
                    break

            self.screen.blit(surf, (current_x, current_y))
            current_x += surf.get_width() + 18

    def run_loop(self) -> None:
        """Main event loop for simulation playback."""
        current_index = 0
        last_update = pygame.time.get_ticks()
        running = True

        while running:
            now = pygame.time.get_ticks()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_LEFT:
                        self.autoplay = False
                        current_index = max(0, current_index - 1)
                    elif event.key == pygame.K_RIGHT:
                        self.autoplay = False
                        current_index = min(
                            len(self.frames) - 1, current_index + 1
                        )
                    elif event.key == pygame.K_SPACE:
                        self.autoplay = not self.autoplay
                    elif event.key == pygame.K_r:
                        self.autoplay = False
                        current_index = 0

            if (
                self.autoplay
                and now - last_update >= UIConstants.TURN_DELAY_MS
            ):
                if current_index < len(self.frames) - 1:
                    current_index += 1
                    last_update = now
                else:
                    self.autoplay = False

            self.draw(self.frames[current_index])
            pygame.display.flip()
            self.clock.tick(UIConstants.FPS)

        pygame.quit()


def run_pygame_standard(visualizer: PygameStandardVisualizer) -> None:
    """Start pygame window with drone simulation visualization."""
    window = DroneSimulationWindow(visualizer)
    window.run_loop()
