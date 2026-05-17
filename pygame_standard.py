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


class DroneSimulationWindow:
    """Main pygame window for drone simulation visualization."""

    MAP_ZONE_COLORS = {
        # Base Colors (Easy / Medium / Hard 1)
        "green": (46, 204, 113),
        "blue": (52, 152, 219),
        "red": (231, 76, 60),
        "yellow": (241, 196, 15),
        "orange": (230, 126, 34),
        "cyan": (0, 188, 212),
        # Colors (Hard 3: Ultimate)
        "purple": (155, 89, 182),
        "brown": (145, 100, 70),
        "lime": (145, 220, 35),
        "magenta": (240, 30, 240),
        "gold": (245, 190, 25),
        # Extreme Colors (Challenger: Impossible Dream)
        "black": (42, 46, 54),  # Deep black
        "maroon": (115, 35, 35),  # Burgundy
        "darkred": (145, 20, 20),  # Deep red
        "violet": (180, 120, 245),  # Violet
        "crimson": (220, 20, 60),  # Crimson/Pink
    }

    def __init__(
        self,
        visualizer: PygameStandardVisualizer,
        width: int = 1200,
        height: int = 800,
    ) -> None:
        """Initialize pygame window and layout parameters."""
        pygame.init()
        self.visualizer = visualizer
        self.frames = visualizer.build_frames()
        self.graph = visualizer.graph

        self.margin = 40
        self.history_height = 140
        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption("Fly-in UI")

        self.autoplay = True

        self.drone_sprite = pygame.image.load("drone.png").convert_alpha()
        self.drone_sprite.set_colorkey((255, 255, 255))
        self.drone_sprite = pygame.transform.scale(self.drone_sprite, (30, 30))

        self.clock = pygame.time.Clock()
        self.title_font = pygame.font.SysFont("Arial", 20, bold=True)
        self.text_font = pygame.font.SysFont("Arial", 15)
        self.node_font = pygame.font.SysFont("Arial", 13)

        self.viewport = pygame.Rect(
            self.margin,
            self.history_height + self.margin,
            width - (self.margin * 2),
            height - self.history_height - (self.margin * 2),
        )
        self.node_positions = self._calculate_adaptive_positions()

    def _calculate_adaptive_positions(self) -> dict[str, tuple[int, int]]:
        """Map graph zone coordinates to screen positions."""
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

    def _get_short_name(self, name: str) -> str:
        """Shorten names while preserving trailing numbers."""
        readable = name.replace("_", " ").title()
        if len(readable) > 11:
            # Preserve trailing digits such as "1", "5", or "12".
            suffix = ""
            main_part = readable
            while main_part and main_part[-1].isdigit():
                suffix = main_part[-1] + suffix
                main_part = main_part[:-1]

            main_part = main_part.strip()
            words = main_part.split()

            # Keep the first word and abbreviate the second one when present.
            if len(words) > 1:
                short_main = f"{words[0]} {words[1][0]}."
            else:
                short_main = main_part[:7] + ".."

            return f"{short_main}{suffix}"
        return readable

    def _get_zone_color(self, zone: Zone) -> tuple[int, int, int]:
        """Get RGB color for a zone based on its properties."""
        if zone.color == "rainbow":
            import time
            import math

            frequency = 3.5
            current_tick = time.time() * frequency
            r = int((math.sin(current_tick) + 1) * 127.5)
            g = int((math.sin(current_tick + 2) + 1) * 127.5)
            b = int((math.sin(current_tick + 4) + 1) * 127.5)
            return (r, g, b)

        if zone.color in self.MAP_ZONE_COLORS:
            return self.MAP_ZONE_COLORS[zone.color]

        if zone.is_start:
            return (39, 174, 96)
        if zone.is_end:
            return (192, 57, 43)
        if zone.zone_type == ZoneType.PRIORITY:
            return (41, 128, 185)
        if zone.zone_type == ZoneType.RESTRICTED:
            return (155, 89, 182)
        if zone.zone_type == ZoneType.BLOCKED:
            return (127, 140, 141)

        return (220, 225, 230)

    def _draw_history_bar(self, frame: StandardTurnFrame) -> None:
        """Draw turn info, status, and movement history at top."""
        total_turns = max(0, len(self.frames) - 1)
        panel_rect = pygame.Rect(
            0, 0, self.screen.get_width(), self.history_height
        )
        pygame.draw.rect(self.screen, (31, 38, 46), panel_rect)
        pygame.draw.line(
            self.screen,
            (52, 152, 219),
            (0, self.history_height),
            (self.screen.get_width(), self.history_height),
            2,
        )

        turn_str = f"Turn: {frame.turn_number} / {total_turns}"
        turn_surface = self.title_font.render(turn_str, True, (255, 255, 255))
        self.screen.blit(turn_surface, (25, 20))

        status_str = "[AUTO]" if self.autoplay else "[PAUSE]"
        status_color = (46, 204, 113) if self.autoplay else (231, 76, 60)
        status_surface = self.title_font.render(status_str, True, status_color)
        status_x = 25 + turn_surface.get_width() + 15
        self.screen.blit(status_surface, (status_x, 20))

        hint_str = "(Space: Auto/Pause | Left/Right: Step | R: Reset)"
        hint_surface = self.node_font.render(hint_str, True, (140, 152, 168))
        self.screen.blit(hint_surface, (25, 48))

        move_title = self.title_font.render("Movement:", True, (143, 211, 255))
        self.screen.blit(move_title, (25, 80))

        if not frame.movements:
            initial_surface = self.text_font.render(
                "Initial state (all drones at base)", True, (170, 183, 197)
            )
            init_x = 25 + move_title.get_width() + 15
            self.screen.blit(initial_surface, (init_x, 82))
            return

        start_x = 25 + move_title.get_width() + 15
        current_x = start_x
        current_y = 82
        line_spacing = 22
        window_max_width = self.screen.get_width() - 25

        for drone_label, destination in frame.movements:
            short_dest = self._get_short_name(destination)
            move_str = f"{drone_label}→{short_dest}"
            element_surface = self.text_font.render(
                move_str, True, (230, 237, 245)
            )

            if current_x + element_surface.get_width() > window_max_width:
                current_x = start_x
                current_y += line_spacing
                if current_y + 18 > self.history_height:
                    truncated_indicator = self.text_font.render(
                        "...", True, (143, 211, 255)
                    )
                    self.screen.blit(
                        truncated_indicator,
                        (current_x, current_y - line_spacing),
                    )
                    break

            self.screen.blit(element_surface, (current_x, current_y))
            current_x += element_surface.get_width() + 18

    def draw(self, frame: StandardTurnFrame) -> None:
        """Render graph, zones, connections and consolidated drone counts
        with dashboard UI."""
        self.screen.fill((155, 170, 185))
        self._draw_history_bar(frame)

        active_connections = set()
        for pos_info in frame.positions.values():
            if (
                pos_info.kind == "connection"
                and pos_info.second_zone is not None
            ):
                c_id = tuple(
                    sorted([pos_info.first_zone, pos_info.second_zone])
                )
                active_connections.add(c_id)

        path_counts: dict[tuple[str, str], int] = {}

        for conn in self.graph.connections:
            p1 = self.node_positions[conn.zone_a.name]
            p2 = self.node_positions[conn.zone_b.name]

            path_id = tuple(sorted([conn.zone_a.name, conn.zone_b.name]))
            if not isinstance(path_id, tuple) or len(path_id) != 2:
                raise TypeError("path_id must be a tuple of two strings")
            count = path_counts.get(path_id, 0)
            path_counts[path_id] = count + 1

            line_color = (35, 45, 55)
            thickness = 3

            if path_id in active_connections:
                line_color = (41, 128, 185)
                thickness = 5

            if count > 0:
                import math

                dx = p2[0] - p1[0]
                dy = p2[1] - p1[1]
                dist = math.hypot(dx, dy)
                if dist > 0:
                    nx = -dy / dist
                    ny = dx / dist
                    offset = count * 6
                    p1 = (
                        int(p1[0] + nx * offset),
                        int(p1[1] + ny * offset),
                    )
                    p2 = (
                        int(p2[0] + nx * offset),
                        int(p2[1] + ny * offset),
                    )

            pygame.draw.line(
                self.screen,
                (255, 255, 255),
                p1,
                p2,
                thickness + 2,
            )
            pygame.draw.line(
                self.screen,
                line_color,
                p1,
                p2,
                thickness,
            )

        is_challenger = "impossible_goal" in self.graph.zones

        row_label_indices: dict[str, int] = {}
        rows: dict[int, list[Zone]] = {}
        for zone in self.graph.zones.values():
            rows.setdefault(zone.y, []).append(zone)

        for row_zones in rows.values():
            for row_idx, zone in enumerate(
                sorted(row_zones, key=lambda item: item.x)
            ):
                row_label_indices[zone.name] = row_idx

        for zone in self.graph.zones.values():
            pos = self.node_positions[zone.name]
            color = self._get_zone_color(zone)

            pygame.draw.circle(self.screen, color, pos, 16)
            pygame.draw.circle(self.screen, (45, 55, 72), pos, 16, 2)

            short_title = self._get_short_name(zone.name)
            label = self.node_font.render(short_title, True, (45, 55, 72))

            row_idx = row_label_indices[zone.name]
            if row_idx % 2 == 0:
                y_offset = -35
                bg_y_offset = -37
            else:
                y_offset = 22
                bg_y_offset = 20

            text_bg_rect = pygame.Rect(
                pos[0] - label.get_width() // 2 - 4,
                pos[1] + bg_y_offset,
                label.get_width() + 8,
                label.get_height() + 2,
            )
            pygame.draw.rect(
                self.screen,
                (255, 255, 255),
                text_bg_rect,
                border_radius=4,
            )
            pygame.draw.rect(
                self.screen,
                (208, 215, 222),
                text_bg_rect,
                width=1,
                border_radius=4,
            )
            self.screen.blit(
                label,
                (pos[0] - label.get_width() // 2, pos[1] + y_offset),
            )

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
            # Keep labels as strings so they match the expected type.
            if not isinstance(drone_label, str):
                raise TypeError(
                    f"Expected label to be a string, "
                    f"got {type(drone_label)}"
                )
            drone_groups.setdefault(target_point, []).append(drone_label)

        for point, labels in drone_groups.items():
            count = len(labels)
            if count == 0:
                continue

            sprite_rect = self.drone_sprite.get_rect(center=point)
            self.screen.blit(self.drone_sprite, sprite_rect)

            if count > 1:
                count_str = str(count)
                count_surface = self.node_font.render(
                    count_str, True, (255, 255, 255)
                )

                badge_radius = max(8, count_surface.get_width() // 2 + 3)
                badge_pos = (point[0] + 12, point[1] - 12)

                pygame.draw.circle(
                    self.screen, (231, 76, 60), badge_pos, badge_radius
                )
                pygame.draw.circle(
                    self.screen, (255, 255, 255), badge_pos, badge_radius, 1
                )

                blit_pos = (
                    badge_pos[0] - count_surface.get_width() // 2,
                    badge_pos[1] - count_surface.get_height() // 2 - 1,
                )
                self.screen.blit(count_surface, blit_pos)

        if is_challenger:
            hint_font = pygame.font.SysFont("Arial", 13, italic=True)
            hint_surf = hint_font.render(
                "Use the move tracker above.",
                True,
                (55, 65, 80),
            )
            hint_x = (self.screen.get_width() - hint_surf.get_width()) // 2
            hint_y = self.screen.get_height() - 25
            self.screen.blit(hint_surf, (hint_x, hint_y))

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

            if self.autoplay and now - last_update >= 600:
                if current_index < len(self.frames) - 1:
                    current_index += 1
                    last_update = now
                else:
                    self.autoplay = False

            self.draw(self.frames[current_index])
            pygame.display.flip()
            self.clock.tick(60)

        pygame.quit()


def run_pygame_standard(visualizer: PygameStandardVisualizer) -> None:
    """Start pygame window with drone simulation visualization."""
    window = DroneSimulationWindow(visualizer)
    window.run_loop()
