"""Scenarios: a map with the start and end hubs the user chooses (ADR-029).

A scenario starts from the map file, never from an earlier run: every call
parses the file again and returns a graph that shares no object with any
other. The chosen hubs become the only start and end hubs. The map's own
start and end hubs become ordinary hubs, limited by the capacity the map
gives them, as every hub other than the start and end is. The map file is
only read.
"""

from pathlib import Path

from airlanes.mapfile import Parser
from airlanes.model.graph import Graph
from airlanes.model.zone import Zone


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
