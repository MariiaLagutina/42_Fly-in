import re
from zone import Zone, ZoneType
from connection import Connection
from graph import Graph


class ParseError(Exception):
    def __init__(self, line_number: int, message: str) -> None:
        super().__init__(f"Line {line_number}: {message}")
        self.line_number = line_number
        self.message = message


class Parser:
    """
    Parses a configuration file to build the graph and
    determine the number of drones.
    """
    def parse(self, filepath: str) -> tuple[Graph, int]:
        graph = Graph()
        nb_drones = 0

        with open(filepath, "r") as file:
            for line_num, line in enumerate(file, start=1):
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

    def _validate_new_zone(
        self, graph: Graph, zone: Zone, line_num: int
    ) -> None:
        if graph.get_zone(zone.name) is not None:
            raise ParseError(line_num, f"Duplicate zone name: {zone.name}.")

    def _parse_nb_drones(self, line: str, line_num: int) -> int:
        parts = line.split(":", 1)
        if len(parts) != 2:
            raise ParseError(line_num, "Invalid nb_drones format.")

        value = parts[1].strip()
        if not value.isdigit() or int(value) <= 0:
            raise ParseError(line_num, "nb_drones must be positive integer.")

        return int(value)

    def _parse_zone(
        self,
        line: str,
        line_num: int,
        is_start: bool = False,
        is_end: bool = False,
    ) -> Zone:
        """Parse a zone definition line and return a Zone object."""
        metadata, line = self._parse_metadata(line, line_num)
        parts = line.split()

        if len(parts) != 4:
            raise ParseError(line_num, "Invalid zone format.")

        name = parts[1]
        try:
            x = int(parts[2])
            y = int(parts[3])
        except ValueError as exc:
            raise ParseError(
                line_num, "Zone coordinates must be integers."
            ) from exc

        zone_type_str = metadata.get("zone", "normal")
        try:
            zone_type = ZoneType(zone_type_str)
        except ValueError as exc:
            raise ParseError(
                line_num, f"Invalid zone type: {zone_type_str}."
            ) from exc

        color = metadata.get("color")
        explicit_max_drones = "max_drones" in metadata
        max_drones_str = metadata.get("max_drones", "1")

        if not max_drones_str.isdigit() or int(max_drones_str) <= 0:
            raise ParseError(line_num, "max_drones must be positive integer.")
        max_drones = int(max_drones_str)

        population = 0
        if "population" in metadata:
            pop_str = metadata["population"]
            if pop_str.isdigit():
                population = int(pop_str)
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
        zone.explicit_max_drones = explicit_max_drones

        return zone

    def _parse_connection(
        self, line: str, line_num: int, graph: Graph
    ) -> Connection:
        """Parse a connection definition line and return a Connection object"""
        metadata, line = self._parse_metadata(line, line_num)
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
        capacity_str = metadata.get("max_link_capacity", "1")

        if not capacity_str.isdigit() or int(capacity_str) <= 0:
            raise ParseError(
                line_num, "max_link_capacity must be positive integer."
            )
        capacity = int(capacity_str)

        distance = 0
        if "distance" in metadata:
            dist_str = metadata["distance"].replace("km", "").strip()
            if dist_str.isdigit():
                distance = int(dist_str)
                if not explicit_max_link_capacity:
                    if distance > 500:
                        capacity = 2
                    elif 0 < distance < 200:
                        capacity = 3
                    else:
                        capacity = 1

        connection = Connection(zone_a, zone_b, capacity)
        connection.distance = distance
        connection.explicit_max_link_capacity = explicit_max_link_capacity

        return connection

    def _parse_metadata(
        self, line: str, line_num: int
    ) -> tuple[dict[str, str], str]:
        """
        Extract metadata from a line and return it along
        with the line without metadata.
        """
        metadata: dict[str, str] = {}
        match = re.search(r"\[(.*?)\]", line)

        if match is None:
            return metadata, line

        for item in match.group(1).split():
            if "=" not in item:
                raise ParseError(line_num, f"Invalid metadata: {item}.")
            key, value = item.split("=", 1)
            metadata[key] = value

        line_without_metadata = line[: match.start()].strip()
        return metadata, line_without_metadata
