"""
Lane styling of the geographic dispatch-center view (Airlines). The
standard turn viewer keeps its own lane drawing.

A lane's width and the depth of its colour show its capacity; the colour
family shows its weather; a dashed lane is closed. Widths stop at 5 px, so
the 7+ capacity class differs from 4-6 by a deeper shade only.
"""
from dataclasses import dataclass
import math
from typing import Iterator, Sequence

import pygame

from airlanes.output.pygame.common import Point

RGB = tuple[int, int, int]
FloatPoint = tuple[float, float]

# Lane width by capacity class: 1, 2-3, 4-6 and 7+.
CAPACITY_WIDTHS = (3, 4, 5, 5)

# One shade per capacity class, lightest first, within each weather colour
# family. Snow stays pale and rain deep so the two blues never meet, and
# clear and tailwind avoid the lightness of the Germany land background.
WEATHER_SHADES: dict[str, tuple[RGB, RGB, RGB, RGB]] = {
    "clear": ((189, 194, 199), (167, 173, 180), (84, 92, 99), (68, 74, 80)),
    "storm": ((230, 72, 55), (213, 44, 26), (182, 37, 22), (154, 32, 19)),
    "snow": (
        (214, 239, 255), (184, 227, 255), (158, 217, 255), (138, 209, 255)
    ),
    "rain": ((47, 150, 218), (34, 128, 191), (28, 107, 160), (24, 90, 134)),
    "tailwind": (
        (159, 233, 191), (118, 224, 163), (28, 125, 69), (23, 100, 55)
    ),
}

# A thin dark edge keeps pale lanes visible on light land and dark lanes
# visible against similar country colours.
OUTLINE_COLOR: RGB = (18, 24, 34)
OUTLINE_WIDTH = 1

# A closed lane is dashed: weather has closed it to new departures.
DASH_LENGTH = 10
DASH_GAP = 7

# Distance between the centre lines of parallel lanes.
PARALLEL_SPACING = 7


def capacity_class(capacity: int) -> int:
    """Index of the capacity class: 0 for 1, 1 for 2-3, 2 for 4-6, 3 for
    7 and more."""
    if capacity <= 1:
        return 0
    if capacity <= 3:
        return 1
    if capacity <= 6:
        return 2
    return 3


def lane_width(capacity: int) -> int:
    return CAPACITY_WIDTHS[capacity_class(capacity)]


def lane_color(condition: str, capacity: int) -> RGB:
    """Colour of a lane: the weather family, at the depth of its capacity
    class. An unknown condition is drawn as clear."""
    shades = WEATHER_SHADES.get(condition, WEATHER_SHADES["clear"])
    return shades[capacity_class(capacity)]


@dataclass(frozen=True)
class LaneStroke:
    start: FloatPoint
    end: FloatPoint
    color: RGB
    width: int
    closed: bool = False


def parallel_offsets(count: int) -> list[float]:
    """Perpendicular offsets of `count` lanes between the same two hubs,
    symmetric around the line between the hub centres. A single lane has
    no offset."""
    middle = (count - 1) / 2
    return [(index - middle) * PARALLEL_SPACING for index in range(count)]


def offset_line(
    start: Point, end: Point, offset: float
) -> tuple[FloatPoint, FloatPoint]:
    """The line from `start` to `end`, moved `offset` pixels to its left."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length == 0 or offset == 0:
        return (float(start[0]), float(start[1])), (
            float(end[0]), float(end[1])
        )
    nx = -dy / length * offset
    ny = dx / length * offset
    return (start[0] + nx, start[1] + ny), (end[0] + nx, end[1] + ny)


def dash_segments(
    start: FloatPoint, end: FloatPoint
) -> Iterator[tuple[FloatPoint, FloatPoint]]:
    """The dashes of a closed lane, from `start` towards `end`."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    position = 0.0
    while position < length:
        stop = min(length, position + DASH_LENGTH)
        yield (
            (start[0] + dx * position / length,
             start[1] + dy * position / length),
            (start[0] + dx * stop / length, start[1] + dy * stop / length),
        )
        position += DASH_LENGTH + DASH_GAP


def _segments(
    stroke: LaneStroke,
) -> list[tuple[FloatPoint, FloatPoint]]:
    if stroke.closed:
        return list(dash_segments(stroke.start, stroke.end))
    return [(stroke.start, stroke.end)]


def draw_lanes(
    surface: pygame.surface.Surface, strokes: Sequence[LaneStroke]
) -> None:
    """
    Wide lanes first, so a narrow lane stays visible where it crosses a
    wide one. Every outline goes down before any lane colour, so outlines
    never cut across a lane at a crossing.
    """
    ordered = sorted(strokes, key=lambda stroke: -stroke.width)
    pieces = [(stroke, _segments(stroke)) for stroke in ordered]
    for stroke, segments in pieces:
        for start, end in segments:
            pygame.draw.line(
                surface, OUTLINE_COLOR, start, end,
                stroke.width + 2 * OUTLINE_WIDTH,
            )
    for stroke, segments in pieces:
        for start, end in segments:
            pygame.draw.line(surface, stroke.color, start, end, stroke.width)
