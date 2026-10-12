"""Scenarios: a map with the start and end hubs the user chooses (ADR-029).

A scenario starts from the map file, never from an earlier run: every call
parses the file again and returns a graph that shares no object with any
other. The chosen hubs become the only start and end hubs. The map's own
start and end hubs become ordinary hubs, limited by the capacity the map
gives them, as every hub other than the start and end is. The map file is
only read.

The number of vehicles is one count for the whole fleet, chosen by the user
rather than taken from the map.
"""

from pathlib import Path

from airlanes.mapfile import INTEGER, Parser
from airlanes.model.graph import Graph
from airlanes.model.zone import Zone

# The vehicle count of a scenario: the default, used for empty or invalid
# input, and the range any other count is clamped to.
DEFAULT_VEHICLE_COUNT = 10
MIN_VEHICLE_COUNT = 1
MAX_VEHICLE_COUNT = 100


class ScenarioError(ValueError):
    """The chosen start or end hub cannot be used on this map."""


def load_scenario_graph(
    map_path: str | Path, start: str, end: str
) -> Graph:
    """
    A new graph of the map, with `start` and `end` as its only start and
    end hubs. Errors of the map file itself propagate from the parser.
    """
    graph, _nb_aircraft = Parser().parse(str(map_path))
    start_zone = _terminal(graph, start)
    end_zone = _terminal(graph, end)
    if start_zone is end_zone:
        raise ScenarioError("Start and end hubs must be different.")

    # The flags and the graph's references change together, so they always
    # name the same hubs.
    for zone in graph.zones.values():
        zone.is_start = zone is start_zone
        zone.is_end = zone is end_zone
    graph.start_zone = start_zone
    graph.end_zone = end_zone
    return graph


def normalize_vehicle_count(value: str) -> int:
    """
    The vehicle count that `value` asks for, within the allowed range.

    Surrounding whitespace is ignored. A count is written in ASCII digits,
    optionally after a `-`, as integers are in a map file. A count below
    the range becomes its minimum, one above it its maximum, and anything
    else, empty input included, the default. Input of any length works.
    """
    text = value.strip()
    if INTEGER.fullmatch(text) is None:
        return DEFAULT_VEHICLE_COUNT
    # A negative count, or zero written as "-0", is below the range.
    if text.startswith("-"):
        return MIN_VEHICLE_COUNT
    # A count with more significant digits than the maximum is above the
    # range. Deciding that from its length keeps a long input away from
    # `int`, which refuses strings longer than Python's conversion limit.
    digits = text.lstrip("0")
    if len(digits) > len(str(MAX_VEHICLE_COUNT)):
        return MAX_VEHICLE_COUNT
    return max(MIN_VEHICLE_COUNT, min(MAX_VEHICLE_COUNT, int(digits or "0")))


def _terminal(graph: Graph, name: str) -> Zone:
    """The hub that may become a start or end hub, or a ScenarioError."""
    zone = graph.get_zone(name)
    if zone is None:
        raise ScenarioError(f"Unknown hub: {name}.")
    if not zone.is_accessible():
        raise ScenarioError(
            f"A start or end hub cannot be blocked: {name}."
        )
    return zone
