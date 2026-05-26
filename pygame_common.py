"""
Shared pygame helpers live here only when at least two pygame visualizers
use the same concept. View-specific layout stays in the window class.
"""
import pygame
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from events import EventListener, SimulationEvent
from graph import Graph

# Shared path for assets
IMG_DIR = Path(__file__).resolve().parent / "img"

# Shared Types
PositionKind = Literal["zone", "connection"]
Point = tuple[int, int]


class PygameEventCollector(EventListener):
    """Base class for collecting simulation events for pygame visualizers."""

    def __init__(self, graph: Graph) -> None:
        self.graph = graph
        self.event_queue: list[SimulationEvent] = []

    def handle(self, event: SimulationEvent) -> None:
        self.event_queue.append(event)


@dataclass(frozen=True)
class DroneDisplayPosition:
    """Shared state tracking where a drone is rendered on the map."""
    kind: PositionKind
    first_zone: str
    second_zone: Optional[str] = None


class UIColors:
    """Centralized color palette for visualizers."""
    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)
    GREEN = (46, 204, 113)
    BLUE = (52, 152, 219)
    RED = (231, 76, 60)
    YELLOW = (241, 196, 15)
    CYAN = (0, 188, 212)
    ORANGE = (230, 126, 34)
    PURPLE = (155, 89, 182)
    BROWN = (145, 100, 70)
    LIME = (145, 220, 35)
    MAGENTA = (240, 30, 240)
    GOLD = (245, 190, 25)

    DARK_PANEL = (31, 38, 46)
    TEXT_LIGHT = (230, 237, 245)
    TEXT_MUTED = (100, 110, 120)
    ZONE_BORDER = (45, 55, 72)
    SLATE_BG = (155, 170, 185)
    HIGHLIGHT = (143, 211, 255)
    LINE_DEFAULT = (35, 45, 55)


class UIConstants:
    """Standardized dimensions, sizes, and timings."""
    FPS = 60
    STANDARD_WIDTH = 1200
    STANDARD_HEIGHT = 800
    TURN_DELAY_MS = 600
    AIRLINES_TURN_DELAY_MS = 1000

    # Shared UI drawing constraints
    HISTORY_PANEL_HEIGHT = 140
    MARGIN = 40
    BADGE_RADIUS_MIN = 8
    BADGE_OFFSET_X = 12
    BADGE_OFFSET_Y = -12
    LINE_THICKNESS_DEFAULT = 3
    LINE_THICKNESS_ACTIVE = 5
    NODE_RADIUS = 16


# Moved from pygame_standard for shared map coloring
PYGAME_ZONE_COLORS = {
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


def draw_count_badge(
    screen: pygame.Surface, font: pygame.font.Font, point: Point, count: int
) -> None:
    """Single vehicles do not need a badge; the badge only explains grouped
    drones at the same screen point."""
    if count <= 1:
        return

    count_surf = font.render(str(count), True, UIColors.WHITE)
    badge_radius = max(
        UIConstants.BADGE_RADIUS_MIN,
        count_surf.get_width() // 2 + 3,
    )
    badge_pos = (
        point[0] + UIConstants.BADGE_OFFSET_X,
        point[1] + UIConstants.BADGE_OFFSET_Y,
    )

    pygame.draw.circle(screen, UIColors.RED, badge_pos, badge_radius)
    pygame.draw.circle(screen, UIColors.WHITE, badge_pos, badge_radius, 1)

    blit_pos = (
        badge_pos[0] - count_surf.get_width() // 2,
        badge_pos[1] - count_surf.get_height() // 2 - 1,
    )
    screen.blit(count_surf, blit_pos)


def load_sprite(
    filename: str,
    size: Point,
    color_key: Optional[tuple[int, int, int]] = None,
) -> Optional[pygame.Surface]:
    """Loads an image, optionally sets a color key, and scales it."""
    try:
        sprite = pygame.image.load(IMG_DIR / filename).convert_alpha()
        if color_key is not None:
            sprite.set_colorkey(color_key)
        return pygame.transform.scale(sprite, size)
    except FileNotFoundError:
        return None


def load_outlined_sprite(
    filename: str, size: Point, final_size: Point = (32, 32)
) -> Optional[pygame.Surface]:
    """
    The outline is generated from the sprite alpha mask so map icons stay
    readable over busy backgrounds.
    """
    try:
        sprite = pygame.image.load(IMG_DIR / filename).convert_alpha()
        base_sprite = pygame.transform.scale(sprite, size)

        mask = pygame.mask.from_surface(base_sprite)
        mask_surf = mask.to_surface(
            setcolor=UIColors.WHITE, unsetcolor=(0, 0, 0, 0)
        )
        mask_surf.set_colorkey(UIColors.BLACK)

        final_surf = pygame.Surface(final_size, pygame.SRCALPHA)

        offset_x = (final_size[0] - size[0]) // 2
        offset_y = (final_size[1] - size[1]) // 2

        offsets = [
            (-1, 0), (1, 0), (0, -1), (0, 1),
            (-1, -1), (-1, 1), (1, -1), (1, 1),
        ]
        for dx, dy in offsets:
            final_surf.blit(mask_surf, (offset_x + dx, offset_y + dy))

        final_surf.blit(base_sprite, (offset_x, offset_y))
        return final_surf
    except FileNotFoundError:
        return None


def load_scaled_image(filename: str, size: Point) -> Optional[pygame.Surface]:
    """Loads and scales an image without changing color keys or alpha masks."""
    try:
        image = pygame.image.load(IMG_DIR / filename).convert_alpha()
        return pygame.transform.scale(image, size)
    except FileNotFoundError:
        return None
