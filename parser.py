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
        pass

    def _parse_zone(
        self,
        line: str,
        line_num: int,
        is_start: bool = False,
        is_end: bool = False,
    ) -> Zone:
        pass

    def _parse_connection(
        self, line: str, line_num: int, graph: Graph
    ) -> Connection:
        pass
