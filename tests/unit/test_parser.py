"""Map parser: accepted format, documented defaults, and line-numbered errors.

Only behavior that the map format promises is tested here. Lenient handling
of malformed input (unknown keys, ignored values) is deliberately left out.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from airlanes.model.graph import Graph
from parser import ParseError, Parser
from airlanes.model.transport_mode import TransportMode
from airlanes.model.zone import ZoneType

MAPS_DIR = Path(__file__).resolve().parents[2] / "maps"
MAP_FILES = sorted(MAPS_DIR.glob("*/*.txt"))

# Three valid lines; a line appended after HEADER is line 4.
HEADER = (
    "nb_drones: 2\n"
    "start_hub: start 0 0\n"
    "end_hub: goal 3 0\n"
)

MapWriter = Callable[[str], Path]


@pytest.fixture
def write_map(tmp_path: Path) -> MapWriter:
    """Write map text byte-for-byte, so CRLF line endings are preserved."""
    def _write(text: str) -> Path:
        path = tmp_path / "map.txt"
        path.write_bytes(text.encode("utf-8"))
        return path

    return _write


def parse(path: Path) -> tuple[Graph, int]:
    return Parser().parse(str(path))


# --- Valid maps ------------------------------------------------------------


def test_minimal_map(write_map: MapWriter) -> None:
    graph, nb_drones = parse(write_map(HEADER))

    assert nb_drones == 2
    assert graph.start_zone is not None
    assert graph.end_zone is not None
    assert graph.start_zone.name == "start"
    assert graph.end_zone.name == "goal"
    assert (graph.start_zone.x, graph.start_zone.y) == (0, 0)
    assert (graph.end_zone.x, graph.end_zone.y) == (3, 0)
    assert graph.start_zone.is_start and not graph.start_zone.is_end
    assert graph.end_zone.is_end and not graph.end_zone.is_start
    assert graph.connections == []


def test_hubs_and_connections_are_added(write_map: MapWriter) -> None:
    graph, _ = parse(write_map(
        HEADER
        + "hub: mid 1 2\n"
        + "connection: start-mid\n"
        + "connection: mid-goal\n"
    ))

    mid = graph.get_zone("mid")
    start = graph.get_zone("start")
    goal = graph.get_zone("goal")
    assert mid is not None and start is not None and goal is not None
    assert (mid.x, mid.y) == (1, 2)
    assert not mid.is_start and not mid.is_end
    assert graph.has_connection(start, mid)
    assert graph.has_connection(mid, goal)
    assert not graph.has_connection(start, goal)


def test_blank_lines_comments_indentation_and_crlf_are_accepted(
    write_map: MapWriter,
) -> None:
    graph, nb_drones = parse(write_map(
        "# comment\r\n"
        "\r\n"
        "  nb_drones: 3\r\n"
        "\t# indented comment\r\n"
        "\tstart_hub: start 0 0\r\n"
        "   \r\n"
        "end_hub: goal 1 0\r\n"
    ))

    assert nb_drones == 3
    assert graph.start_zone is not None
    assert graph.end_zone is not None


def test_negative_coordinates_are_accepted(write_map: MapWriter) -> None:
    graph, _ = parse(write_map(HEADER + "hub: west -2 -5\n"))

    west = graph.get_zone("west")
    assert west is not None
    assert (west.x, west.y) == (-2, -5)


def test_zone_defaults_without_metadata(write_map: MapWriter) -> None:
    graph, _ = parse(write_map(HEADER + "hub: mid 1 0\n"))

    mid = graph.get_zone("mid")
    assert mid is not None
    assert mid.zone_type is ZoneType.NORMAL
    assert mid.color is None
    assert mid.max_drones == 1
    assert mid.population == 0


def test_empty_metadata_block_uses_defaults(write_map: MapWriter) -> None:
    graph, _ = parse(write_map(HEADER + "hub: mid 1 0 []\n"))

    mid = graph.get_zone("mid")
    assert mid is not None
    assert mid.zone_type is ZoneType.NORMAL
    assert mid.max_drones == 1


@pytest.mark.parametrize("zone_type", list(ZoneType))
def test_zone_type_metadata(
    write_map: MapWriter, zone_type: ZoneType
) -> None:
    graph, _ = parse(write_map(
        HEADER + f"hub: mid 1 0 [zone={zone_type.value}]\n"
    ))

    mid = graph.get_zone("mid")
    assert mid is not None
    assert mid.zone_type is zone_type


def test_explicit_zone_metadata(write_map: MapWriter) -> None:
    graph, _ = parse(write_map(
        HEADER
        + "hub: mid 1 0 [zone=restricted color=red max_drones=4 "
        + "population=250000]\n"
    ))

    mid = graph.get_zone("mid")
    assert mid is not None
    assert mid.zone_type is ZoneType.RESTRICTED
    assert mid.color == "red"
    assert mid.max_drones == 4
    assert mid.population == 250000


def test_start_and_end_accept_metadata(write_map: MapWriter) -> None:
    graph, _ = parse(write_map(
        "nb_drones: 1\n"
        "start_hub: start 0 0 [color=green]\n"
        "end_hub: goal 1 0 [color=blue]\n"
    ))

    assert graph.start_zone is not None
    assert graph.end_zone is not None
    assert graph.start_zone.color == "green"
    assert graph.end_zone.color == "blue"


@pytest.mark.parametrize(
    ("population", "expected_capacity"),
    [
        (50000, 1),
        (100000, 1),
        (199999, 1),
        (200000, 2),
        (1899000, 18),
    ],
)
def test_population_sets_default_hub_capacity(
    write_map: MapWriter, population: int, expected_capacity: int
) -> None:
    """One slot per 100,000 inhabitants, and never less than one."""
    graph, _ = parse(write_map(
        HEADER + f"hub: city 1 0 [population={population}]\n"
    ))

    city = graph.get_zone("city")
    assert city is not None
    assert city.population == population
    assert city.max_drones == expected_capacity


def test_explicit_max_drones_overrides_population(
    write_map: MapWriter,
) -> None:
    graph, _ = parse(write_map(
        HEADER + "hub: city 1 0 [population=1899000 max_drones=2]\n"
    ))

    city = graph.get_zone("city")
    assert city is not None
    assert city.max_drones == 2


def test_connection_defaults_without_metadata(write_map: MapWriter) -> None:
    graph, _ = parse(write_map(HEADER + "connection: start-goal\n"))

    (connection,) = graph.connections
    assert connection.max_link_capacity == 1
    assert connection.distance == 0


def test_explicit_link_capacity(write_map: MapWriter) -> None:
    graph, _ = parse(write_map(
        HEADER + "connection: start-goal [max_link_capacity=3]\n"
    ))

    (connection,) = graph.connections
    assert connection.max_link_capacity == 3


@pytest.mark.parametrize(
    ("metadata", "expected_capacity"),
    [
        ("distance=1km", 1),
        ("distance=500km", 1),
        ("distance=501km", 2),
        ("distance=2000km", 2),
        ("distance=1km mode=road", 3),
        ("distance=2000km mode=road", 3),
    ],
)
def test_mode_and_distance_set_default_link_capacity(
    write_map: MapWriter, metadata: str, expected_capacity: int
) -> None:
    """Road lanes: 3. Air lanes up to 500 km: 1, longer: 2."""
    graph, _ = parse(write_map(
        HEADER + f"connection: start-goal [{metadata}]\n"
    ))

    (connection,) = graph.connections
    assert connection.max_link_capacity == expected_capacity


def test_lanes_are_air_unless_the_map_says_road(write_map: MapWriter) -> None:
    """The mode is map data: a short lane is still air, a long one can be
    road, and an abstract lane without distance is air."""
    graph, _ = parse(write_map(
        HEADER
        + "hub: a 1 0\n"
        + "connection: start-a [distance=150km]\n"
        + "connection: a-goal [distance=800km mode=road]\n"
        + "connection: start-goal\n"
    ))

    modes = {conn.name(): conn.mode for conn in graph.connections}
    assert modes == {
        "start-a": TransportMode.AIR,
        "a-goal": TransportMode.ROAD,
        "start-goal": TransportMode.AIR,
    }


def test_explicit_air_mode(write_map: MapWriter) -> None:
    graph, _ = parse(write_map(
        HEADER + "connection: start-goal [distance=150km mode=air]\n"
    ))

    (connection,) = graph.connections
    assert connection.mode is TransportMode.AIR


@pytest.mark.parametrize(
    "metadata",
    [
        pytest.param("mode=boat distance=100km", id="unknown-mode"),
        pytest.param("mode=road", id="road-without-distance"),
        pytest.param("mode=road distance=0km", id="road-with-zero-distance"),
        pytest.param("distance=far", id="non-numeric-distance"),
    ],
)
def test_invalid_transport_data_is_rejected(
    write_map: MapWriter, metadata: str
) -> None:
    with pytest.raises(ParseError) as error:
        parse(write_map(HEADER + f"connection: start-goal [{metadata}]\n"))

    assert error.value.line_number == 4


def test_explicit_link_capacity_overrides_distance(
    write_map: MapWriter,
) -> None:
    graph, _ = parse(write_map(
        HEADER
        + "connection: start-goal [distance=100km max_link_capacity=1]\n"
    ))

    (connection,) = graph.connections
    assert connection.distance == 100
    assert connection.max_link_capacity == 1


@pytest.mark.parametrize(
    "map_file", MAP_FILES, ids=lambda path: f"{path.parent.name}/{path.name}"
)
def test_included_maps_parse(map_file: Path) -> None:
    graph, nb_drones = parse(map_file)

    assert nb_drones > 0
    assert graph.start_zone is not None
    assert graph.end_zone is not None


def test_included_maps_are_found() -> None:
    """Guard against the map test above silently collecting nothing."""
    assert MAP_FILES


@pytest.mark.parametrize(
    ("relative_path", "road_lanes"),
    [("bonus/germany_map.txt", 10), ("bonus/europa_map.txt", 0)],
)
def test_bundled_maps_mark_their_road_lanes(
    relative_path: str, road_lanes: int
) -> None:
    graph, _ = parse(MAPS_DIR / relative_path)

    roads = [c for c in graph.connections if c.mode is TransportMode.ROAD]
    assert len(roads) == road_lanes


# --- Errors tied to a specific line -----------------------------------------


@pytest.mark.parametrize(
    ("text", "expected_line"),
    [
        pytest.param(HEADER + "hubs: mid 1 0\n", 4, id="unknown-line-type"),
        pytest.param(
            "nb_drones: 0\nstart_hub: start 0 0\nend_hub: goal 1 0\n",
            1,
            id="nb-drones-zero",
        ),
        pytest.param(
            "nb_drones: -1\nstart_hub: start 0 0\nend_hub: goal 1 0\n",
            1,
            id="nb-drones-negative",
        ),
        pytest.param(
            "nb_drones: two\nstart_hub: start 0 0\nend_hub: goal 1 0\n",
            1,
            id="nb-drones-not-a-number",
        ),
        pytest.param(
            "nb_drones: 2.5\nstart_hub: start 0 0\nend_hub: goal 1 0\n",
            1,
            id="nb-drones-not-an-integer",
        ),
        pytest.param(HEADER + "hub: mid 1\n", 4, id="zone-missing-token"),
        pytest.param(HEADER + "hub: mid 1 0 0\n", 4, id="zone-extra-token"),
        pytest.param(
            HEADER + "hub: mid 1.5 0\n", 4, id="zone-float-coordinate"
        ),
        pytest.param(
            HEADER + "hub: mid x 0\n", 4, id="zone-text-coordinate"
        ),
        pytest.param(
            HEADER + "hub: mid 1 0 [zone=airport]\n", 4, id="zone-type-unknown"
        ),
        pytest.param(
            HEADER + "hub: mid 1 0 [max_drones=0]\n", 4, id="max-drones-zero"
        ),
        pytest.param(
            HEADER + "hub: mid 1 0 [max_drones=-2]\n",
            4,
            id="max-drones-negative",
        ),
        pytest.param(
            HEADER + "hub: mid 1 0 [max_drones=many]\n",
            4,
            id="max-drones-not-a-number",
        ),
        pytest.param(
            HEADER + "hub: mid 1 0 [color]\n", 4, id="metadata-without-equals"
        ),
        pytest.param(
            HEADER + "hub: start 5 5\n", 4, id="duplicate-zone-name"
        ),
        pytest.param(
            "nb_drones: 1\nstart_hub: same 0 0\nend_hub: same 1 0\n",
            3,
            id="start-and-end-share-a-name",
        ),
        pytest.param(
            HEADER + "start_hub: other 5 5\n", 4, id="second-start-hub"
        ),
        pytest.param(HEADER + "end_hub: other 5 5\n", 4, id="second-end-hub"),
        pytest.param(
            HEADER + "connection: start\n", 4, id="connection-single-zone"
        ),
        pytest.param(
            HEADER + "hub: mid 1 0\nconnection: start-mid-goal\n",
            5,
            id="connection-three-zones",
        ),
        pytest.param(
            HEADER + "connection: start-nowhere\n",
            4,
            id="connection-unknown-zone",
        ),
        pytest.param(
            HEADER + "connection: start-goal\nconnection: start-goal\n",
            5,
            id="duplicate-connection",
        ),
        pytest.param(
            HEADER + "connection: start-goal\nconnection: goal-start\n",
            5,
            id="duplicate-connection-reversed",
        ),
        pytest.param(
            HEADER + "connection: start-goal [max_link_capacity=0]\n",
            4,
            id="link-capacity-zero",
        ),
        pytest.param(
            HEADER + "connection: start-goal [max_link_capacity=wide]\n",
            4,
            id="link-capacity-not-a-number",
        ),
    ],
)
def test_invalid_line_raises_parse_error_with_its_line_number(
    write_map: MapWriter, text: str, expected_line: int
) -> None:
    with pytest.raises(ParseError) as excinfo:
        parse(write_map(text))

    assert excinfo.value.line_number == expected_line


def test_line_numbers_count_blank_and_comment_lines(
    write_map: MapWriter,
) -> None:
    text = (
        "# header comment\n"
        "\n"
        "nb_drones: 2\n"
        "start_hub: start 0 0\n"
        "\n"
        "# zones\n"
        "end_hub: goal 3 0\n"
        "hub: broken\n"
    )

    with pytest.raises(ParseError) as excinfo:
        parse(write_map(text))

    assert excinfo.value.line_number == 8


# --- Errors about the file as a whole ---------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("", id="empty-file"),
        pytest.param(
            "start_hub: start 0 0\nend_hub: goal 1 0\n", id="no-nb-drones"
        ),
        pytest.param("nb_drones: 1\nend_hub: goal 1 0\n", id="no-start-hub"),
        pytest.param("nb_drones: 1\nstart_hub: start 0 0\n", id="no-end-hub"),
    ],
)
def test_missing_required_definition_raises_parse_error(
    write_map: MapWriter, text: str
) -> None:
    with pytest.raises(ParseError):
        parse(write_map(text))
