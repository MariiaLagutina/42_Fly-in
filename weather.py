import random

from connection import Connection
from events import EventDispatcher, WeatherChanged
from graph import Graph


class WeatherSystem:
    def __init__(
        self,
        graph: Graph,
        dispatcher: EventDispatcher | None = None,
    ) -> None:
        self.graph = graph
        self.dispatcher = dispatcher
        self.active_storms: list[Connection] = []
        self.storm_chance = 0.05  # 5% chance per connection each turn

    def update_weather(self, turn_number: int) -> None:
        for conn in self.active_storms[:]:
            if random.random() < 0.20:
                conn.set_weather("clear", is_open=True)
                self.active_storms.remove(conn)
                self._emit_weather(turn_number, conn)

        for conn in self.graph.connections:
            if (
                conn.weather_condition == "clear"
                and random.random() < self.storm_chance
            ):
                condition = random.choice(
                    ["snow", "storm", "tailwind", "rain"]
                )

                if condition in ["snow", "storm"]:
                    conn.set_weather(condition, is_open=False)
                else:
                    conn.set_weather(condition, is_open=True)

                self.active_storms.append(conn)
                self._emit_weather(turn_number, conn)

    def _emit_weather(self, turn_number: int, conn: Connection) -> None:
        if self.dispatcher:
            self.dispatcher.dispatch(
                WeatherChanged(
                    turn_number,
                    conn.name(),
                    conn.weather_condition,
                    conn.is_open,
                )
            )
