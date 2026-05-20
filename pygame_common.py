import pygame
from pathlib import Path
from typing import Optional

IMG_DIR = Path(__file__).resolve().parent / "img"


class UIColors:
    """Centralized color palette for visualizers."""

    # Base Colors
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

    # UI Theme Colors
    SLATE_BG = (155, 170, 185)
    DARK_PANEL = (31, 38, 46)
    TEXT_LIGHT = (230, 237, 245)
    TEXT_MUTED = (140, 152, 168)
    HIGHLIGHT = (143, 211, 255)

    # Zone & Line specific
    ZONE_BORDER = (45, 55, 72)
    LINE_DEFAULT = (35, 45, 55)


class UIConstants:
    """Standardized dimensions, sizes, and timings."""

    FPS = 60
    TURN_DELAY_MS = 600
    STANDARD_WIDTH = 1200
    STANDARD_HEIGHT = 800
    MARGIN = 40
    HISTORY_PANEL_HEIGHT = 140

    # Drawing sizes
    NODE_RADIUS = 16
    BADGE_RADIUS_MIN = 8
    LINE_THICKNESS_DEFAULT = 3
    LINE_THICKNESS_ACTIVE = 5


def load_sprite(
    filename: str, size: tuple[int, int]
) -> Optional[pygame.Surface]:
    """Loads an image, sets a white color key, and scales it."""
    try:
        sprite = pygame.image.load(IMG_DIR / filename).convert_alpha()
        sprite.set_colorkey((255, 255, 255))
        return pygame.transform.scale(sprite, size)
    except FileNotFoundError:
        return None
