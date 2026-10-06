"""Weather sources and the weather state they produce.

A `WeatherProvider` supplies the weather for each turn as a `WeatherState`:
a snapshot of the current, observed condition of each connection. It is not
a forecast. The simulator decides what a condition means for each transport
mode (see `airlanes.world.transport`); providers only describe the weather.
"""

from collections.abc import Iterable, Mapping
from enum import Enum
import random
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from airlanes.model.graph import Graph


class WeatherCondition(Enum):
    CLEAR = "clear"
    RAIN = "rain"
    SNOW = "snow"
    STORM = "storm"
    TAILWIND = "tailwind"


class WeatherState:
    """Current weather per connection name; a missing connection is clear."""

    def __init__(
        self, conditions: Mapping[str, WeatherCondition] | None = None
    ) -> None:
        self._conditions = MappingProxyType(
            {
                name: condition
                for name, condition in (conditions or {}).items()
                if condition is not WeatherCondition.CLEAR
            }
        )

    def condition_of(self, connection_name: str) -> WeatherCondition:
        return self._conditions.get(connection_name, WeatherCondition.CLEAR)

    @property
    def connection_names(self) -> Iterable[str]:
        """Connections with a condition other than clear."""
        return self._conditions.keys()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, WeatherState):
            return NotImplemented
        return self._conditions == other._conditions

    def __repr__(self) -> str:
        return f"WeatherState({dict(self._conditions)})"


class WeatherProvider(Protocol):
    def weather_for_turn(self, turn_number: int) -> WeatherState:
        ...


class NoWeather:
    """Every connection is always clear."""

    def weather_for_turn(self, turn_number: int) -> WeatherState:
        return WeatherState()


class RandomWeather:
    """Random weather from its own generator, reproducible from a seed.

    Each turn, every affected connection clears with `clear_chance`, then
    every clear connection changes with `storm_chance` to one of rain, snow,
    storm, or tailwind. Without a seed the generator is seeded from the
    operating system, so runs differ.
    """

    _CHANGES = [
        WeatherCondition.SNOW,
        WeatherCondition.STORM,
        WeatherCondition.TAILWIND,
        WeatherCondition.RAIN,
    ]

    def __init__(
        self,
        graph: "Graph",
        seed: int | None = None,
        storm_chance: float = 0.05,
        clear_chance: float = 0.20,
    ) -> None:
        self._connection_names = [conn.name() for conn in graph.connections]
        self._rng = random.Random(seed)
        self.storm_chance = storm_chance
        self.clear_chance = clear_chance
        self._conditions: dict[str, WeatherCondition] = {}
        self._affected: list[str] = []

    def weather_for_turn(self, turn_number: int) -> WeatherState:
        for name in self._affected[:]:
            if self._rng.random() < self.clear_chance:
                del self._conditions[name]
                self._affected.remove(name)

        if self.storm_chance > 0:
            for name in self._connection_names:
                if (
                    name not in self._conditions
                    and self._rng.random() < self.storm_chance
                ):
                    self._conditions[name] = self._rng.choice(self._CHANGES)
                    self._affected.append(name)

        return WeatherState(self._conditions)


class ScriptedWeather:
    """Weather that follows a fixed schedule, for deterministic tests.

    `schedule` maps a turn number to the connections whose condition changes
    on that turn. A condition stays until the schedule changes it again;
    `WeatherCondition.CLEAR` clears a connection.
    """

    def __init__(
        self, schedule: Mapping[int, Mapping[str, WeatherCondition]]
    ) -> None:
        self._schedule = {
            turn: dict(changes) for turn, changes in schedule.items()
        }
        self._conditions: dict[str, WeatherCondition] = {}
        self._applied_until = 0

    def weather_for_turn(self, turn_number: int) -> WeatherState:
        for turn in range(self._applied_until + 1, turn_number + 1):
            self._conditions.update(self._schedule.get(turn, {}))
        self._applied_until = max(self._applied_until, turn_number)
        return WeatherState(self._conditions)
