"""
Shared pygame helpers live here only when at least two pygame visualizers
use the same concept. View-specific layout stays in the window class.
"""
from dataclasses import dataclass
import pygame
from pathlib import Path
from typing import Literal, Optional

# Shared path for assets
IMG_DIR = Path(__file__).resolve().parent / "img"

# Shared Types
PositionKind = Literal["zone", "connection"]
Point = tuple[int, int]


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
    ORANGE = (230, 126, 34)
    CYAN = (0, 188, 212)
    PURPLE = (155, 89, 182)
    BROWN = (145, 100, 70)
    LIME = (145, 220, 35)
    MAGENTA = (240, 30, 240)
    GOLD = (245, 190, 25)

    SLATE_BG = (155, 170, 185)
    DARK_PANEL = (31, 38, 46)
    TEXT_LIGHT = (230, 237, 245)
    TEXT_MUTED = (140, 152, 168)
    HIGHLIGHT = (143, 211, 255)

    ZONE_BORDER = (45, 55, 72)
    LINE_DEFAULT = (35, 45, 55)


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


class UIConstants:
    """Standardized dimensions, sizes, and timings."""
    FPS = 60
    TURN_DELAY_MS = 600
    STANDARD_WIDTH = 1200
    STANDARD_HEIGHT = 800
    MARGIN = 40
    HISTORY_PANEL_HEIGHT = 140

    NODE_RADIUS = 16
    BADGE_RADIUS_MIN = 8
    BADGE_OFFSET_X = 12
    BADGE_OFFSET_Y = -12
    LINE_THICKNESS_DEFAULT = 3
    LINE_THICKNESS_ACTIVE = 5


def load_sprite(filename: str, size: tuple[int, int]) -> Optional[pygame.Surface]:
    """Loads an image, sets a white color key, and scales it."""
    try:
        sprite = pygame.image.load(IMG_DIR / filename).convert_alpha()
        sprite.set_colorkey((255, 255, 255))
        return pygame.transform.scale(sprite, size)
    except FileNotFoundError:
        return None


def draw_count_badge(
    screen: pygame.Surface, font: pygame.font.Font, point: Point, count: int
) -> None:
    """Only draw a badge for grouped drones; a single vehicle icon is already enough."""
    if count <= 1:
        return

    count_surf = font.render(str(count), True, UIColors.WHITE)
    badge_radius = max(UIConstants.BADGE_RADIUS_MIN, count_surf.get_width() // 2 + 3)
    badge_pos = (point[0] + UIConstants.BADGE_OFFSET_X, point[1] + UIConstants.BADGE_OFFSET_Y)

    pygame.draw.circle(screen, UIColors.RED, badge_pos, badge_radius)
    pygame.draw.circle(screen, UIColors.WHITE, badge_pos, badge_radius, 1)

    blit_pos = (
        badge_pos[0] - count_surf.get_width() // 2,
        badge_pos[1] - count_surf.get_height() // 2 - 1,
    )
    screen.blit(count_surf, blit_pos)
