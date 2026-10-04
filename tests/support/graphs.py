"""Small graph builders for pathfinding and simulation tests."""

from dataclasses import dataclass

from connection import Connection
from graph import Graph
from transport import TransportMode
from zone import Zone, ZoneType


@dataclass(frozen=True)
class Link:
    zone_a: str
    zone_b: str
    capacity: int = 1
    distance: int = 0
    mode: TransportMode = TransportMode.AIR


def hub(
    name: str,
    zone_type: ZoneType = ZoneType.NORMAL,
    capacity: int = 1,
) -> Zone:
    return Zone(name, 0, 0, zone_type, max_drones=capacity)


def start_hub(name: str = "start", capacity: int = 1) -> Zone:
    return Zone(name, 0, 0, max_drones=capacity, is_start=True)


def end_hub(name: str = "goal", capacity: int = 1) -> Zone:
    return Zone(name, 0, 0, max_drones=capacity, is_end=True)


def build_graph(zones: list[Zone], links: list[Link]) -> Graph:
    graph = Graph()
    for zone in zones:
        graph.add_zone(zone)
    for link in links:
        zone_a = graph.get_zone(link.zone_a)
        zone_b = graph.get_zone(link.zone_b)
        assert zone_a is not None and zone_b is not None
        connection = Connection(zone_a, zone_b, link.capacity, link.mode)
        connection.distance = link.distance
        graph.add_connection(connection)
    return graph
