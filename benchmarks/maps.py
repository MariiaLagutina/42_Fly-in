"""Deterministic synthetic maps for the performance benchmark.

A map is fully determined by its parameters and seed: the same parameters
always give the same map text, so a scenario can be rebuilt from them
alone. Maps follow the strict map format (ADR-025) and are read by the real
parser before they are used.

Geometry: hubs are random points with whole-kilometre coordinates, and a
lane's distance is the rounded straight-line distance between its hubs. The
area grows with the hub count, so lanes, and the turns a leg takes, stay
about as long as maps grow.

Connectivity: a minimum spanning tree of air lanes joins every accessible
hub, so a route from start to end exists in clear weather whatever the
consecutive-road limit. More lanes then join near neighbours, shortest
first, until the target average degree is reached; only those may be roads.
Blocked hubs are extra hubs outside the tree.
"""

from dataclasses import dataclass
import math
import random
import re

# A road lane is at most this long, well within the consecutive-road limit.
ROAD_MAX_KM = 300

Point = tuple[int, int]
Pair = tuple[int, int]


@dataclass(frozen=True)
class MapSpec:
    """
    `hubs` counts the accessible hubs, start and end included; `blocked`
    hubs come on top. `degree` is the target average number of lanes per
    accessible hub; a degree the spanning tree already exceeds gives the
    tree alone. Shares are fractions of the hubs between start and end, or
    of the lanes outside the tree for `road_share`. Lanes have distances
    unless `abstract_lanes` is set; abstract lanes are never roads.
    """

    hubs: int
    degree: float = 3.0
    aircraft: int = 10
    seed: int = 1
    restricted_share: float = 0.0
    priority_share: float = 0.0
    road_share: float = 0.0
    blocked: int = 0
    max_drones: tuple[int, int] = (1, 3)
    abstract_lanes: bool = False
    spacing_km: int = 150

    def __post_init__(self) -> None:
        if self.hubs < 2:
            raise ValueError("A map needs at least a start and an end hub.")
        if self.aircraft < 1:
            raise ValueError("A map needs at least one aircraft.")
        if self.restricted_share + self.priority_share > 1:
            raise ValueError("Restricted and priority shares exceed 1.")
        low, high = self.max_drones
        if not 1 <= low <= high:
            raise ValueError("Hub capacities must be positive.")


@dataclass(frozen=True)
class _Hub:
    name: str
    point: Point
    zone: str = "normal"
    max_drones: int | None = None


@dataclass(frozen=True)
class _Lane:
    hub_a: int
    hub_b: int
    road: bool = False


def generate_map(spec: MapSpec) -> str:
    """Map text of a connected map built from `spec`."""
    rng = random.Random(spec.seed)
    side = round(spec.spacing_km * math.sqrt(spec.hubs))
    points = _unique_points(rng, spec.hubs + spec.blocked, (0, 0), side)
    accessible = points[:spec.hubs]

    start, end = _extremes(accessible)
    middle = [i for i in range(spec.hubs) if i not in (start, end)]
    hubs = [_Hub("S", accessible[start]), _Hub("E", accessible[end])]
    zones = _zone_types(rng, spec, len(middle))
    hubs += [
        _Hub(f"h{n}", accessible[i], zone, rng.randint(*spec.max_drones))
        for n, (i, zone) in enumerate(zip(middle, zones), start=1)
    ]
    # Lanes below refer to positions in `hubs`.
    position = {i: n for n, i in enumerate([start, end, *middle])}

    tree = _spanning_tree(accessible)
    target = lane_count(spec.hubs, spec.degree)
    extra = _near_pairs(accessible, target - len(tree), set(tree))
    lanes = [_Lane(position[a], position[b]) for a, b in tree]
    lanes += _maybe_roads(rng, spec, accessible, extra, position)

    for n, point in enumerate(points[spec.hubs:], start=1):
        hubs.append(_Hub(f"b{n}", point, "blocked", 1))
        blocked = len(hubs) - 1
        for i in _nearest(accessible, point, 2):
            lanes.append(_Lane(position[i], blocked))

    title = (
        f"{spec.hubs} hubs, degree {spec.degree}, {spec.aircraft} aircraft, "
        f"seed {spec.seed}"
    )
    return _render(title, spec.aircraft, hubs, lanes, spec.abstract_lanes)


def generate_bottleneck_map(
    cluster_hubs: int,
    aircraft: int,
    seed: int,
    gate_blocked: bool = False,
    degree: float = 3.0,
    spacing_km: int = 150,
) -> str:
    """
    Two clusters of `cluster_hubs` hubs, joined only through the gate hub
    `G`, which holds one aircraft. Start is in the left cluster, end in the
    right one, so every route passes the gate. A blocked gate leaves no
    route at all.
    """
    rng = random.Random(seed)
    side = round(spacing_km * math.sqrt(cluster_hubs))
    gap = 2 * spacing_km
    left = _unique_points(rng, cluster_hubs, (0, 0), side)
    right = _unique_points(rng, cluster_hubs, (side + gap, 0), side)
    gate: Point = (side + gap // 2, side // 2)

    start, _ = _extremes(left)
    _, end = _extremes(right)
    left_middle = [i for i in range(cluster_hubs) if i != start]
    right_middle = [i for i in range(cluster_hubs) if i != end]
    hubs = [_Hub("S", left[start]), _Hub("E", right[end])]
    hubs.append(_Hub("G", gate, "blocked" if gate_blocked else "normal", 1))
    left_position = {start: 0}
    right_position = {end: 1}
    for points, middle, position in (
        (left, left_middle, left_position),
        (right, right_middle, right_position),
    ):
        for i in middle:
            position[i] = len(hubs)
            name = f"h{len(hubs) - 2}"
            hubs.append(_Hub(name, points[i], "normal", rng.randint(1, 3)))

    lanes: list[_Lane] = []
    for points, position in ((left, left_position), (right, right_position)):
        tree = _spanning_tree(points)
        target = lane_count(cluster_hubs, degree)
        extra = _near_pairs(points, target - len(tree), set(tree))
        lanes += [_Lane(position[a], position[b]) for a, b in tree + extra]
        (nearest,) = _nearest(points, gate, 1)
        lanes.append(_Lane(position[nearest], 2))

    title = (
        f"bottleneck, 2 x {cluster_hubs} hubs, {aircraft} aircraft, "
        f"seed {seed}" + (", gate blocked" if gate_blocked else "")
    )
    return _render(title, aircraft, hubs, lanes, False)


def lane_count(hubs: int, degree: float) -> int:
    """Lanes among `hubs` accessible hubs for the target average degree: at
    least the spanning tree, at most one lane per pair of hubs."""
    return min(hubs * (hubs - 1) // 2, max(hubs - 1, round(hubs * degree / 2)))


def with_aircraft(text: str, aircraft: int) -> str:
    """The same map with another aircraft count. The map file itself is
    not changed."""
    changed, count = re.subn(
        r"^nb_drones:[^\n]*$", f"nb_drones: {aircraft}", text,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError("The map must declare nb_drones exactly once.")
    return changed


def _unique_points(
    rng: random.Random, count: int, origin: Point, side: int
) -> list[Point]:
    """`count` distinct random points in a square, in generation order."""
    seen: set[Point] = set()
    points: list[Point] = []
    while len(points) < count:
        point = (
            origin[0] + rng.randint(0, side),
            origin[1] + rng.randint(0, side),
        )
        if point not in seen:
            seen.add(point)
            points.append(point)
    return points


def _extremes(points: list[Point]) -> tuple[int, int]:
    """The westernmost and easternmost points, ties broken by position."""
    order = sorted(range(len(points)), key=lambda i: (points[i], i))
    return order[0], order[-1]


def _zone_types(
    rng: random.Random, spec: MapSpec, count: int
) -> list[str]:
    positions = list(range(count))
    restricted = set(
        rng.sample(positions, round(spec.restricted_share * count))
    )
    rest = [i for i in positions if i not in restricted]
    priority = set(rng.sample(rest, round(spec.priority_share * count)))
    return [
        "restricted" if i in restricted
        else "priority" if i in priority
        else "normal"
        for i in positions
    ]


def _distance2(a: Point, b: Point) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _spanning_tree(points: list[Point]) -> list[Pair]:
    """Minimum spanning tree by straight-line distance (Prim), with ties
    broken by position so the result is deterministic."""
    count = len(points)
    in_tree = [False] * count
    best = [math.inf] * count
    parent = [-1] * count
    best[0] = 0
    edges: list[Pair] = []
    for _ in range(count):
        u = min(
            (i for i in range(count) if not in_tree[i]),
            key=lambda i: (best[i], i),
        )
        in_tree[u] = True
        if parent[u] >= 0:
            edges.append((min(parent[u], u), max(parent[u], u)))
        for v in range(count):
            if not in_tree[v]:
                d = _distance2(points[u], points[v])
                if d < best[v]:
                    best[v] = d
                    parent[v] = u
    return edges


def _nearest(points: list[Point], point: Point, count: int) -> list[int]:
    order = sorted(
        range(len(points)), key=lambda i: (_distance2(points[i], point), i)
    )
    return order[:count]


def _near_pairs(
    points: list[Point], count: int, existing: set[Pair]
) -> list[Pair]:
    """`count` new pairs among near neighbours, shortest first."""
    if count <= 0:
        return []
    # Enough near neighbours per hub for the lanes still needed on average.
    per_hub = math.ceil(2 * count / len(points))
    neighbours = min(len(points) - 1, max(8, per_hub + 6))
    candidates: set[Pair] = set()
    for i, point in enumerate(points):
        for j in _nearest(points, point, neighbours + 1):
            if j != i:
                candidates.add((min(i, j), max(i, j)))
    ordered = sorted(
        candidates - existing,
        key=lambda pair: (_distance2(points[pair[0]], points[pair[1]]), pair),
    )
    if len(ordered) < count:
        raise ValueError("Not enough near neighbours for this degree.")
    return ordered[:count]


def _maybe_roads(
    rng: random.Random,
    spec: MapSpec,
    points: list[Point],
    pairs: list[Pair],
    position: dict[int, int],
) -> list[_Lane]:
    """Lanes outside the tree; a short one is a road with `road_share`."""
    lanes: list[_Lane] = []
    for a, b in pairs:
        short = math.dist(points[a], points[b]) <= ROAD_MAX_KM
        road = (
            not spec.abstract_lanes
            and short
            and rng.random() < spec.road_share
        )
        lanes.append(_Lane(position[a], position[b], road))
    return lanes


def _render(
    title: str,
    aircraft: int,
    hubs: list[_Hub],
    lanes: list[_Lane],
    abstract_lanes: bool,
) -> str:
    lines = [
        f"# Synthetic benchmark map: {title}",
        f"nb_drones: {aircraft}",
        "start_hub: {} {} {}".format(hubs[0].name, *hubs[0].point),
        "end_hub: {} {} {}".format(hubs[1].name, *hubs[1].point),
    ]
    for hub in hubs[2:]:
        metadata = f"max_drones={hub.max_drones}"
        if hub.zone != "normal":
            metadata = f"zone={hub.zone} {metadata}"
        lines.append("hub: {} {} {} [{}]".format(
            hub.name, *hub.point, metadata
        ))
    for lane in sorted(
        lanes, key=lambda lane: sorted((lane.hub_a, lane.hub_b))
    ):
        a, b = sorted((lane.hub_a, lane.hub_b))
        name = f"{hubs[a].name}-{hubs[b].name}"
        if abstract_lanes:
            lines.append(f"connection: {name}")
            continue
        distance = max(1, round(math.dist(hubs[a].point, hubs[b].point)))
        metadata = f"distance={distance}km"
        if lane.road:
            metadata += " mode=road"
        lines.append(f"connection: {name} [{metadata}]")
    return "\n".join(lines) + "\n"
