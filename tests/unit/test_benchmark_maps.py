"""Synthetic maps of the performance benchmark.

A benchmark scenario must be reproducible from its parameters and seed, be
accepted by the strict parser, and have a route under the simulation's own
transport and routing rules. These tests check the generator, not timing.
"""

import math
from pathlib import Path

import pytest

from airlanes.mapfile import Parser
from airlanes.model.graph import Graph
from airlanes.model.transport_mode import TransportMode
from airlanes.model.zone import ZoneType
from airlanes.routing.pathfinder import Pathfinder
from airlanes.routing.policy import RoutingPolicy
from airlanes.world.weather import WeatherState
from benchmarks.maps import (
    ROAD_MAX_KM,
    MapSpec,
    generate_bottleneck_map,
    generate_map,
    lane_count,
    with_aircraft,
)

MAPS_DIR = Path(__file__).resolve().parents[2] / "maps"

SPECS = [
    MapSpec(2),
    MapSpec(25, seed=2),
    MapSpec(100, degree=2.5, seed=3),
    MapSpec(100, degree=6, road_share=0.2),
    MapSpec(60, road_share=1.0, blocked=5, seed=4),
    MapSpec(40, restricted_share=0.5, priority_share=0.3, seed=5),
    MapSpec(50, restricted_share=1.0, abstract_lanes=True, aircraft=25),
]
SPEC_IDS = [
    f"{s.hubs}h-d{s.degree}-r{s.road_share}-b{s.blocked}-s{s.seed}"
    + ("-abstract" if s.abstract_lanes else "")
    for s in SPECS
]


def parse(tmp_path: Path, text: str) -> tuple[Graph, int]:
    path = tmp_path / "map.txt"
    path.write_text(text)
    return Parser().parse(str(path))


def has_route(graph: Graph, policy: RoutingPolicy | None = None) -> bool:
    assert graph.start_zone is not None and graph.end_zone is not None
    return Pathfinder(graph, policy).find_route(
        graph.start_zone, graph.end_zone, WeatherState()
    ) is not None


@pytest.mark.parametrize("spec", SPECS, ids=SPEC_IDS)
def test_the_same_spec_gives_the_same_map(spec: MapSpec) -> None:
    assert generate_map(spec) == generate_map(spec)


def test_another_seed_gives_another_map() -> None:
    assert generate_map(MapSpec(50, seed=1)) != generate_map(
        MapSpec(50, seed=2)
    )


@pytest.mark.parametrize("spec", SPECS, ids=SPEC_IDS)
def test_maps_follow_the_strict_format_and_their_spec(
    tmp_path: Path, spec: MapSpec
) -> None:
    graph, nb_aircraft = parse(tmp_path, generate_map(spec))

    assert nb_aircraft == spec.aircraft
    assert len(graph.zones) == spec.hubs + spec.blocked
    lanes = [frozenset((c.zone_a.name, c.zone_b.name))
             for c in graph.connections]
    assert len(set(lanes)) == len(lanes)
    # Each blocked hub brings two lanes of its own.
    accessible_lanes = len(lanes) - 2 * spec.blocked
    assert accessible_lanes == lane_count(spec.hubs, spec.degree)
    if spec.hubs > 2:
        assert 2 * accessible_lanes / spec.hubs == pytest.approx(
            spec.degree, abs=0.05
        )

    middle = [z for z in graph.zones.values()
              if not z.is_start and not z.is_end
              and z.zone_type is not ZoneType.BLOCKED]
    restricted = [z for z in middle if z.zone_type is ZoneType.RESTRICTED]
    priority = [z for z in middle if z.zone_type is ZoneType.PRIORITY]
    assert len(restricted) == round(spec.restricted_share * len(middle))
    assert len(priority) == round(spec.priority_share * len(middle))
    low, high = spec.max_drones
    assert all(low <= z.max_drones <= high for z in middle)


@pytest.mark.parametrize("spec", SPECS, ids=SPEC_IDS)
def test_lane_distances_follow_the_hub_coordinates(
    tmp_path: Path, spec: MapSpec
) -> None:
    graph, _ = parse(tmp_path, generate_map(spec))

    for connection in graph.connections:
        a, b = connection.zone_a, connection.zone_b
        if spec.abstract_lanes:
            assert connection.distance == 0
            continue
        assert connection.distance == max(
            1, round(math.dist((a.x, a.y), (b.x, b.y)))
        )
        if connection.mode is TransportMode.ROAD:
            assert connection.distance <= ROAD_MAX_KM


@pytest.mark.parametrize("spec", SPECS, ids=SPEC_IDS)
def test_air_lanes_alone_reach_the_end_hub(
    tmp_path: Path, spec: MapSpec
) -> None:
    """With no road allowed at all, a route still exists: the spanning tree
    is made of air lanes and avoids blocked hubs. So the routing policy's
    road limit can never disconnect a generated map."""
    graph, _ = parse(tmp_path, generate_map(spec))

    assert has_route(graph)
    assert has_route(graph, RoutingPolicy(max_consecutive_road_km=0))


def test_blocked_hubs_are_extra_hubs_off_the_tree(tmp_path: Path) -> None:
    graph, _ = parse(tmp_path, generate_map(MapSpec(30, blocked=4)))

    blocked = [z for z in graph.zones.values()
               if z.zone_type is ZoneType.BLOCKED]
    assert sorted(z.name for z in blocked) == ["b1", "b2", "b3", "b4"]
    for zone in blocked:
        neighbours = [c for c in graph.connections if c.connects(zone)]
        assert len(neighbours) == 2


def test_every_route_of_the_bottleneck_map_passes_the_gate(
    tmp_path: Path,
) -> None:
    graph, nb_aircraft = parse(tmp_path, generate_bottleneck_map(20, 30, 1))
    assert graph.start_zone is not None and graph.end_zone is not None
    pathfinder = Pathfinder(graph)

    gate = graph.get_zone("G")
    assert gate is not None and gate.max_drones == 1
    assert nb_aircraft == 30
    route = pathfinder.find_route(
        graph.start_zone, graph.end_zone, WeatherState()
    )
    assert route is not None and gate in route
    assert pathfinder.find_route(
        graph.start_zone, graph.end_zone, WeatherState(),
        avoid=frozenset({"G"}),
    ) is None


def test_a_blocked_gate_disconnects_the_bottleneck_map(
    tmp_path: Path,
) -> None:
    graph, _ = parse(
        tmp_path, generate_bottleneck_map(20, 30, 1, gate_blocked=True)
    )

    assert not has_route(graph)


def test_with_aircraft_changes_only_the_aircraft_count() -> None:
    path = MAPS_DIR / "challenger" / "01_the_impossible_dream.txt"
    original = path.read_text()

    changed = with_aircraft(original, 100)

    assert path.read_text() == original
    differences = [
        (old, new)
        for old, new in zip(original.splitlines(), changed.splitlines())
        if old != new
    ]
    assert differences == [("nb_drones: 25", "nb_drones: 100")]


def test_with_aircraft_needs_one_aircraft_declaration() -> None:
    with pytest.raises(ValueError):
        with_aircraft("start_hub: S 0 0\n", 5)
