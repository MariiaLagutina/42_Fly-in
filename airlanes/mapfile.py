import codecs
import io
import re

from airlanes.model.connection import Connection
from airlanes.model.graph import Graph
from airlanes.model.transport_mode import TransportMode
from airlanes.model.zone import Zone, ZoneType
from airlanes.world.transport import default_link_capacity

# Metadata keys each kind of declaration accepts.
ZONE_KEYS = frozenset({"zone", "color", "max_drones", "population"})
CONNECTION_KEYS = frozenset({"max_link_capacity", "distance", "mode"})


class ParseError(Exception):
    def __init__(self, line_number: int, message: str) -> None:
        super().__init__(f"Line {line_number}: {message}")
        self.line_number = line_number
        self.message = message


# Numbers are written with ASCII digits only; leading zeros are allowed.
DIGITS = re.compile(r"[0-9]+")
INTEGER = re.compile(r"-?[0-9]+")
DISTANCE = re.compile(r"([0-9]+)km")


def _positive_int(value: str, line_num: int, message: str) -> int:
    """A positive whole number in ASCII digits, or a ParseError."""
    if DIGITS.fullmatch(value) is None or int(value) <= 0:
        raise ParseError(line_num, message)
    return int(value)


class Parser:
    """
    Parses a configuration file to build the graph and
    determine the number of drones.
    """
    def parse(self, filepath: str) -> tuple[Graph, int]:
        graph = Graph()
        nb_drones = 0

        with open(filepath, "rb") as file:
            lines = self._read_lines(file.read())
            for line_num, line in enumerate(lines, start=1):
                line = line.strip()

                if not line or line.startswith("#"):
                    continue
                if line.startswith("nb_drones:"):
                    nb_drones = self._parse_nb_drones(line, line_num)
                elif line.startswith("start_hub:"):
                    zone = self._parse_zone(line, line_num, is_start=True)
                    self._validate_new_zone(graph, zone, line_num)
                    if graph.start_zone is not None:
                        raise ParseError(
                            line_num, "Start zone already defined."
                        )
                    graph.add_zone(zone)
                elif line.startswith("end_hub:"):
                    zone = self._parse_zone(line, line_num, is_end=True)
                    self._validate_new_zone(graph, zone, line_num)
                    if graph.end_zone is not None:
                        raise ParseError(line_num, "End zone already defined.")
                    graph.add_zone(zone)
                elif line.startswith("hub:"):
                    zone = self._parse_zone(line, line_num)
                    self._validate_new_zone(graph, zone, line_num)
                    graph.add_zone(zone)
                elif line.startswith("connection:"):
                    conn = self._parse_connection(line, line_num, graph)
                    graph.add_connection(conn)
                else:
                    raise ParseError(line_num, "Unknown line format.")

        if nb_drones <= 0:
            raise ParseError(0, "Number of drones not defined.")
        if graph.start_zone is None:
            raise ParseError(0, "Start zone not defined.")
        if graph.end_zone is None:
            raise ParseError(0, "End zone not defined.")

        return graph, nb_drones

    @staticmethod
    def _read_lines(data: bytes) -> list[str]:
        """
        The lines of a map file. A map is UTF-8, optionally with a byte
        order mark at the start of the file. Lines end with LF, CRLF or a
        solitary CR, as in text mode.
        """
        if data.startswith(codecs.BOM_UTF8):
            data = data[len(codecs.BOM_UTF8):]
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            # Everything before the first invalid byte is valid UTF-8.
            before = Parser._split_lines(data[:exc.start].decode("utf-8"))
            line_num = len(before)
            if not before or before[-1].endswith("\n"):
                line_num += 1
            raise ParseError(line_num, "Map file is not valid UTF-8.") from exc
        return Parser._split_lines(text)

    @staticmethod
    def _split_lines(text: str) -> list[str]:
        """Split as text mode does: CRLF and a solitary CR become LF."""
        return io.StringIO(text, newline=None).readlines()

    def _validate_new_zone(
        self, graph: Graph, zone: Zone, line_num: int
    ) -> None:
        if graph.get_zone(zone.name) is not None:
            raise ParseError(line_num, f"Duplicate zone name: {zone.name}.")

    def _parse_nb_drones(self, line: str, line_num: int) -> int:
        parts = line.split(":", 1)
        if len(parts) != 2:
            raise ParseError(line_num, "Invalid nb_drones format.")

        return _positive_int(
            parts[1].strip(), line_num, "nb_drones must be positive integer."
        )

    def _parse_zone(
        self,
        line: str,
        line_num: int,
        is_start: bool = False,
        is_end: bool = False,
    ) -> Zone:
        """Parse a zone definition line and return a Zone object."""
        metadata, line = self._parse_metadata(line, line_num, ZONE_KEYS)
        parts = line.split()

        if len(parts) != 4:
            raise ParseError(line_num, "Invalid zone format.")

        name = parts[1]
        if not all(INTEGER.fullmatch(part) for part in parts[2:]):
            raise ParseError(line_num, "Zone coordinates must be integers.")
        x = int(parts[2])
        y = int(parts[3])

        zone_type_str = metadata.get("zone", "normal")
        try:
            zone_type = ZoneType(zone_type_str)
        except ValueError as exc:
            raise ParseError(
                line_num, f"Invalid zone type: {zone_type_str}."
            ) from exc

        color = metadata.get("color")
        explicit_max_drones = "max_drones" in metadata
        max_drones = _positive_int(
            metadata.get("max_drones", "1"),
            line_num,
            "max_drones must be positive integer.",
        )

        population = 0
        if "population" in metadata:
            population = _positive_int(
                metadata["population"],
                line_num,
                "population must be positive integer.",
            )
            if not explicit_max_drones:
                max_drones = max(1, population // 100000)

        zone = Zone(
            name=name,
            x=x,
            y=y,
            zone_type=zone_type,
            color=color,
            max_drones=max_drones,
            is_start=is_start,
            is_end=is_end,
        )
        zone.population = population

        return zone

    def _parse_connection(
        self, line: str, line_num: int, graph: Graph
    ) -> Connection:
        """Parse a connection definition line and return a Connection object"""
        metadata, line = self._parse_metadata(
            line, line_num, CONNECTION_KEYS
        )
        parts = line.split(":", 1)

        if len(parts) != 2:
            raise ParseError(line_num, "Invalid connection format.")

        zone_names = parts[1].strip().split("-")
        if len(zone_names) != 2:
            raise ParseError(line_num, "Connection must be zoneA-zoneB.")

        zone_a_name, zone_b_name = zone_names
        zone_a = graph.get_zone(zone_a_name)
        zone_b = graph.get_zone(zone_b_name)

        if not zone_a or not zone_b:
            raise ParseError(line_num, "Connected zones not found.")

        if graph.has_connection(zone_a, zone_b):
            raise ParseError(
                line_num,
                f"Duplicate connection: {zone_a_name}-{zone_b_name}.",
            )

        explicit_max_link_capacity = "max_link_capacity" in metadata
        capacity = _positive_int(
            metadata.get("max_link_capacity", "1"),
            line_num,
            "max_link_capacity must be positive integer.",
        )

        mode_str = metadata.get("mode", TransportMode.AIR.value)
        try:
            mode = TransportMode(mode_str)
        except ValueError as exc:
            raise ParseError(
                line_num, f"Invalid transport mode: {mode_str}."
            ) from exc

        distance = 0
        if "distance" in metadata:
            km = DISTANCE.fullmatch(metadata["distance"])
            if km is None:
                raise ParseError(
                    line_num, "distance must be a whole number of km."
                )
            distance = int(km.group(1))
            if distance <= 0:
                raise ParseError(
                    line_num,
                    "distance must be positive; a lane without a distance "
                    "omits it.",
                )

        if mode is TransportMode.ROAD and distance <= 0:
            raise ParseError(
                line_num, "A road connection needs a positive distance."
            )

        if not explicit_max_link_capacity:
            capacity = default_link_capacity(mode, distance)

        connection = Connection(zone_a, zone_b, capacity, mode)
        connection.distance = distance

        return connection

    def _parse_metadata(
        self, line: str, line_num: int, keys: frozenset[str]
    ) -> tuple[dict[str, str], str]:
        """
        Extract metadata from a line and return it along
        with the line without metadata.

        A declaration has at most one metadata block, with each of `keys`
        at most once and never empty. Text after the block is not part of
        the declaration and is ignored, unless it contains a bracket: that
        is a second block, or a broken one.
        """
        metadata: dict[str, str] = {}
        match = re.search(r"\[(.*?)\]", line)

        if match is None:
            if "[" in line:
                raise ParseError(line_num, "Unclosed metadata block.")
            return metadata, line

        tail = line[match.end():]
        if "[" in tail or "]" in tail:
            raise ParseError(line_num, "Only one metadata block is allowed.")

        for item in match.group(1).split():
            if "=" not in item:
                raise ParseError(line_num, f"Invalid metadata: {item}.")
            key, value = item.split("=", 1)
            if key not in keys:
                raise ParseError(line_num, f"Unknown metadata key: {key}.")
            if key in metadata:
                raise ParseError(line_num, f"Repeated metadata key: {key}.")
            if not value:
                raise ParseError(line_num, f"Missing value for {key}.")
            metadata[key] = value

        line_without_metadata = line[: match.start()].strip()
        return metadata, line_without_metadata
