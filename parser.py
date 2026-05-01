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
                    graph.add_zone(zone)
                elif line.startswith("end_hub:"):
                    zone = self._parse_zone(line, line_num, is_end=True)
                    graph.add_zone(zone)
                elif line.startswith("hub:"):
                    zone = self._parse_zone(line, line_num)
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
                line_num,
                "Zone coordinates must be integers.",
            ) from exc

        zone_type_str = metadata.get("zone", "normal")
        try:
            zone_type = ZoneType(zone_type_str)
        except ValueError as exc:
            raise ParseError(
                line_num,
                f"Invalid zone type: {zone_type_str}.",
            ) from exc

        color = metadata.get("color")
        max_drones_str = metadata.get("max_drones", "1")
        if not max_drones_str.isdigit() or int(max_drones_str) <= 0:
            raise ParseError(line_num, "max_drones must be positive integer.")
        max_drones = int(max_drones_str)

        return Zone(
            name=name,
            x=x,
            y=y,
            zone_type=zone_type,
            color=color,
            max_drones=max_drones,
            is_start=is_start,
            is_end=is_end,
        )

    def _parse_connection(
        self, line: str, line_num: int, graph: Graph
    ) -> Connection:
        metadata, line = self._parse_metadata(line, line_num)
        parts = line.split(":", 1)

        if len(parts) != 2:
            raise ParseError(
                line_num,
                "Invalid connection format.",
            )

        zone_names = parts[1].strip().split("-")
        if len(zone_names) != 2:
            raise ParseError(line_num, "Connection must be zoneA-zoneB.")

        zone_a_name, zone_b_name = zone_names
        zone_a = graph.get_zone(zone_a_name)
        zone_b = graph.get_zone(zone_b_name)

        if not zone_a:
            raise ParseError(line_num, f"Zone '{zone_a_name}' not found.")
        if not zone_b:
            raise ParseError(line_num, f"Zone '{zone_b_name}' not found.")

        capacity_str = metadata.get("max_link_capacity", "1")
        if not capacity_str.isdigit() or int(capacity_str) <= 0:
            raise ParseError(
                line_num,
                "max_link_capacity must be positive integer.",
            )
        capacity = int(capacity_str)

        return Connection(zone_a, zone_b, capacity)

    def _parse_metadata(
        self, line: str, line_num: int
    ) -> tuple[dict[str, str], str]:
        metadata: dict[str, str] = {}
        match = re.search(r"\[(.*?)\]", line)

        if match is None:
            return metadata, line

        for item in match.group(1).split():
            if "=" not in item:
                raise ParseError(line_num, f"Invalid metadata: {item}.")
            key, value = item.split("=", 1)
            metadata[key] = value

        line_without_metadata = line[:match.start()].strip()
        return metadata, line_without_metadata
