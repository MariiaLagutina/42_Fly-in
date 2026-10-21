"""Scenarios: a map with the start and end hubs the user chooses (ADR-029).

A scenario starts from the map file, never from an earlier run: every call
parses the file again and returns a graph that shares no object with any
other. The chosen hubs become the only start and end hubs. The map's own
start and end hubs become ordinary hubs, limited by the capacity the map
gives them, as every hub other than the start and end is. The map file is
only read.

The number of vehicles is one count for the whole fleet, chosen by the user
rather than taken from the map.

A routing mode is the user's choice of which of the map's lanes routing may
use. It becomes the run's routing policy; it changes no lane of the graph
and is not a property of a vehicle. A map offers the modes its own lanes
allow. That says nothing about a route between two particular hubs.

Running a scenario builds everything a run uses anew: the graph, the
weather, the event dispatcher and the simulator. How the run ended is told
apart by the type of the simulator's exception, never by its message.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from airlanes.events import EventDispatcher, EventListener
from airlanes.mapfile import INTEGER, Parser
from airlanes.model.graph import Graph
from airlanes.model.transport_mode import TransportMode
from airlanes.model.zone import Zone
from airlanes.results import TurnResult
from airlanes.routing.policy import RoutingPolicy
from airlanes.simulation.deadlock import DeadlockError
from airlanes.simulation.engine import NoRouteError, Simulator, TurnLimitError
from airlanes.world.weather import RandomWeather

# The vehicle count of a scenario: the default, used for empty or invalid
# input, and the range any other count is clamped to.
DEFAULT_VEHICLE_COUNT = 10
MIN_VEHICLE_COUNT = 1
MAX_VEHICLE_COUNT = 100


class ScenarioError(ValueError):
    """The chosen hubs, vehicle count or routing mode cannot be used for a
    scenario."""


class RoutingMode(Enum):
    """
    Which lanes routing may use in a scenario (ADR-029), in the order the
    application presents them. Unlike `TransportMode`, which is how one
    lane travels, a routing mode applies to the whole run.
    """

    MIXED = "Mixed"
    ROAD_ONLY = "Road only"
    AIR_ONLY = "Air only"


def routing_policy(mode: RoutingMode) -> RoutingPolicy:
    """
    The routing policy of a mode. Mixed is the default policy, as the CLI
    runs: every mode, 700 km of consecutive road. Road only has no road
    limit; for Air only, which drives no road, the limit has no effect.
    """
    match mode:
        case RoutingMode.MIXED:
            return RoutingPolicy()
        case RoutingMode.ROAD_ONLY:
            return RoutingPolicy(None, frozenset({TransportMode.ROAD}))
        case RoutingMode.AIR_ONLY:
            return RoutingPolicy(
                transport_modes=frozenset({TransportMode.AIR})
            )


def available_routing_modes(graph: Graph) -> tuple[RoutingMode, ...]:
    """
    The routing modes the map's lanes allow, in presentation order. Mixed
    needs lanes of both modes, Road only a road lane and Air only an air
    lane. A graph without lanes allows none. Whether a mode has a route
    between two particular hubs is not checked here.
    """
    modes = {connection.mode for connection in graph.connections}
    return tuple(
        mode for mode in RoutingMode
        if routing_policy(mode).transport_modes <= modes
    )


class ScenarioStatus(Enum):
    """How a scenario run ended."""

    DELIVERED = "delivered"
    NO_ROUTE = "no route"
    DEADLOCK = "deadlock"
    TURN_LIMIT = "turn limit"


@dataclass(frozen=True)
class ScenarioResult:
    """
    The outcome of one scenario run. `turns` are the turns that completed,
    in order: all of them when every vehicle was delivered, those before
    the failure otherwise, and none without a route. `message` describes
    the outcome for the user.
    """

    status: ScenarioStatus
    turns: tuple[TurnResult, ...]
    delivered: int
    vehicles: int
    message: str


def load_scenario_graph(
    map_path: str | Path, start: str, end: str
) -> Graph:
    """
    A new graph of the map, with `start` and `end` as its only start and
    end hubs. Errors of the map file itself propagate from the parser.
    """
    graph, _nb_aircraft = Parser().parse(str(map_path))
    start_zone = _terminal(graph, start)
    end_zone = _terminal(graph, end)
    if start_zone is end_zone:
        raise ScenarioError("Start and end hubs must be different.")

    # The flags and the graph's references change together, so they always
    # name the same hubs.
    for zone in graph.zones.values():
        zone.is_start = zone is start_zone
        zone.is_end = zone is end_zone
    graph.start_zone = start_zone
    graph.end_zone = end_zone
    return graph


def run_scenario(
    map_path: str | Path,
    start: str,
    end: str,
    vehicles: int,
    weather_seed: int | None = None,
    listeners: Iterable[EventListener] = (),
    mode: RoutingMode | None = None,
) -> ScenarioResult:
    """
    Run `vehicles` vehicles from `start` to `end` on a fresh graph of the
    map, under random weather, and report how the run ended.

    Without a seed, every run has new weather; with one, runs of the same
    scenario are identical. `listeners` receive the run's events. The
    vehicle count must already be a whole number in the allowed range;
    `normalize_vehicle_count` turns user input into one.

    With a `mode`, routing follows that mode's policy, and a mode the map
    does not offer is a ScenarioError: the mode is never changed here.
    Without one, the run uses the default policy, as before modes existed.
    """
    _check_vehicle_count(vehicles)
    graph = load_scenario_graph(map_path, start, end)
    policy = None
    if mode is not None:
        _check_mode(graph, mode)
        policy = routing_policy(mode)
    dispatcher = EventDispatcher()
    for listener in listeners:
        dispatcher.add_listener(listener)
    simulator = Simulator(
        graph,
        vehicles,
        dispatcher,
        weather=RandomWeather(graph, seed=weather_seed),
        policy=policy,
    )

    try:
        simulator.run()
    except NoRouteError:
        status = ScenarioStatus.NO_ROUTE
        message = f"No route from {start} to {end}."
    except DeadlockError as error:
        status = ScenarioStatus.DEADLOCK
        message = (
            f"Deadlock on turn {error.turn_number} at "
            f"{', '.join(error.hubs)}."
        )
    except TurnLimitError:
        status = ScenarioStatus.TURN_LIMIT
        message = f"Stopped after {len(simulator.turns)} turns."
    else:
        status = ScenarioStatus.DELIVERED
        message = f"Delivered in {len(simulator.turns)} turns."

    delivered = sum(drone.is_delivered() for drone in simulator.drones)
    noun = "vehicle" if vehicles == 1 else "vehicles"
    return ScenarioResult(
        status,
        tuple(simulator.turns),
        delivered,
        vehicles,
        f"{message} {delivered} of {vehicles} {noun} reached {end}.",
    )


def _check_vehicle_count(vehicles: int) -> None:
    # A bool is an int in Python, but never a vehicle count.
    if (
        isinstance(vehicles, bool)
        or not isinstance(vehicles, int)
        or not MIN_VEHICLE_COUNT <= vehicles <= MAX_VEHICLE_COUNT
    ):
        raise ScenarioError(
            f"The vehicle count must be a whole number from "
            f"{MIN_VEHICLE_COUNT} to {MAX_VEHICLE_COUNT}: {vehicles!r}."
        )


def _check_mode(graph: Graph, mode: RoutingMode) -> None:
    available = available_routing_modes(graph)
    if mode not in available:
        offered = ", ".join(m.value for m in available) or "none"
        raise ScenarioError(
            f"{mode.value} is not available on this map. "
            f"Available modes: {offered}."
        )


def normalize_vehicle_count(value: str) -> int:
    """
    The vehicle count that `value` asks for, within the allowed range.

    Surrounding whitespace is ignored. A count is written in ASCII digits,
    optionally after a `-`, as integers are in a map file. A count below
    the range becomes its minimum, one above it its maximum, and anything
    else, empty input included, the default. Input of any length works.
    """
    text = value.strip()
    if INTEGER.fullmatch(text) is None:
        return DEFAULT_VEHICLE_COUNT
    # A negative count, or zero written as "-0", is below the range.
    if text.startswith("-"):
        return MIN_VEHICLE_COUNT
    # A count with more significant digits than the maximum is above the
    # range. Deciding that from its length keeps a long input away from
    # `int`, which refuses strings longer than Python's conversion limit.
    digits = text.lstrip("0")
    if len(digits) > len(str(MAX_VEHICLE_COUNT)):
        return MAX_VEHICLE_COUNT
    return max(MIN_VEHICLE_COUNT, min(MAX_VEHICLE_COUNT, int(digits or "0")))


def _terminal(graph: Graph, name: str) -> Zone:
    """The hub that may become a start or end hub, or a ScenarioError."""
    zone = graph.get_zone(name)
    if zone is None:
        raise ScenarioError(f"Unknown hub: {name}.")
    if not zone.is_accessible():
        raise ScenarioError(
            f"A start or end hub cannot be blocked: {name}."
        )
    return zone
