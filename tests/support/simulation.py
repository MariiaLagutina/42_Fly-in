"""Run a simulation and check system invariants from its event stream.

The checker rebuilds where every aircraft is on every turn from `AgentMoved`
and `AgentInTransit` events alone. It deliberately does not trust the
simulator's own counters (`CapacitySnapshot`), so a counting bug in the
simulator cannot hide itself.

Rules follow the movement and occupancy rules of the original assignment:
capacities are checked at the end of each turn, after aircraft that leave a
hub have freed their place; a lane is used by every aircraft that departs on
it, crosses it, or arrives over it during the turn.

Capacity rules of the project checked on top (ADR-008, ADR-019): a hub's
load, the aircraft in it plus the aircraft flying towards it, never exceeds
its capacity, and a distance lane has at most one departure per direction
per turn.

Routing rules checked on top: no aircraft drives more consecutive road than
the routing policy allows, and an aircraft only reroutes while it waits at a
hub (ADR-010, ADR-017).
"""

from dataclasses import dataclass

from airlanes.events import (
    AgentInTransit,
    AgentMoved,
    AgentRerouted,
    EventDispatcher,
    SimulationEvent,
    TurnFinished,
    TurnStarted,
    WeatherChanged,
)
from airlanes.model.graph import Graph
from airlanes.model.transport_mode import TransportMode
from airlanes.model.zone import ZoneType
from airlanes.output.text import Visualizer, movement_tokens
from airlanes.results import Arrival, Departure, Reroute
from airlanes.routing.policy import RoutingPolicy
from airlanes.simulation.engine import Simulator
from airlanes.world.weather import WeatherProvider


class EventRecorder:
    def __init__(self) -> None:
        self.events: list[SimulationEvent] = []

    def handle(self, event: SimulationEvent) -> None:
        self.events.append(event)


@dataclass
class SimulationRun:
    graph: Graph
    nb_aircraft: int
    simulator: Simulator
    events: list[SimulationEvent]
    output: list[str]

    @property
    def turn_count(self) -> int:
        """Number of turns actually simulated, including turns without
        printed movement."""
        return max(
            (e.turn_number for e in self.events if isinstance(e, TurnStarted)),
            default=0,
        )

    def visited_zones(self, label: str) -> list[str]:
        return [
            e.destination
            for e in self.events
            if isinstance(e, AgentMoved) and e.agent_label == label
        ]


def run_simulation(
    graph: Graph,
    nb_aircraft: int,
    weather: WeatherProvider | None = None,
    policy: RoutingPolicy | None = None,
) -> SimulationRun:
    dispatcher = EventDispatcher()
    recorder = EventRecorder()
    dispatcher.add_listener(recorder)
    simulator = Simulator(
        graph, nb_aircraft, dispatcher, weather=weather, policy=policy
    )
    results = simulator.run()
    # Assignment-style output, like the CLI: a turn with nothing to show
    # prints no line.
    visualizer = Visualizer(graph)
    lines = [visualizer.render_turn(result) for result in results]
    return SimulationRun(
        graph,
        nb_aircraft,
        simulator,
        recorder.events,
        [line for line in lines if line],
    )


@dataclass(frozen=True)
class _InTransit:
    connection: str
    destination: str
    departed: int


Position = str | _InTransit


def check_invariants(run: SimulationRun) -> list[str]:
    """Return a description of every invariant violation; empty if none."""
    return _InvariantChecker(run).check()


def peak_hub_occupancy(run: SimulationRun) -> dict[str, int]:
    """Highest number of aircraft each hub held at the end of any turn."""
    checker = _InvariantChecker(run)
    checker.check()
    return checker.peak_occupancy


class _InvariantChecker:
    def __init__(self, run: SimulationRun) -> None:
        self.run = run
        self.graph = run.graph
        assert self.graph.start_zone is not None
        assert self.graph.end_zone is not None
        self.end_name = self.graph.end_zone.name
        self.positions: dict[str, Position] = {
            f"D{i}": self.graph.start_zone.name
            for i in range(1, run.nb_aircraft + 1)
        }
        self.connections = {c.name(): c for c in self.graph.connections}
        self.closed_lanes: set[str] = set()
        self.violations: list[str] = []
        self.turn = 0
        self.moved_this_turn: set[str] = set()
        self.lane_use: dict[str, int] = {}
        self.departures: set[tuple[str, str]] = set()
        self.peak_occupancy: dict[str, int] = {}
        self.road_km: dict[str, int] = {label: 0 for label in self.positions}
        self.max_road_km = run.simulator.policy.max_consecutive_road_km

    def fail(self, message: str) -> None:
        self.violations.append(f"turn {self.turn}: {message}")

    def check(self) -> list[str]:
        for event in self.run.events:
            if isinstance(event, TurnStarted):
                self._start_turn(event.turn_number)
            elif isinstance(event, WeatherChanged):
                if event.is_open:
                    self.closed_lanes.discard(event.connection_name)
                else:
                    self.closed_lanes.add(event.connection_name)
            elif isinstance(event, AgentRerouted):
                self._reroute(event)
            elif isinstance(event, AgentInTransit):
                self._depart(event)
            elif isinstance(event, AgentMoved):
                self._arrive(event)
            elif isinstance(event, TurnFinished):
                self._check_capacities()
        self._check_final_state()
        return self.violations

    def _start_turn(self, turn: int) -> None:
        self.turn = turn
        self.moved_this_turn = set()
        self.lane_use = {}
        self.departures = set()
        for position in self.positions.values():
            if isinstance(position, _InTransit):
                self._use_lane(position.connection)

    def _use_lane(self, name: str) -> None:
        self.lane_use[name] = self.lane_use.get(name, 0) + 1

    def _start_move(self, label: str) -> Position | None:
        if label not in self.positions:
            self.fail(f"unknown aircraft {label}")
            return None
        if label in self.moved_this_turn:
            self.fail(f"{label} moved twice")
        self.moved_this_turn.add(label)
        return self.positions[label]

    def _depart(self, event: AgentInTransit) -> None:
        label = event.agent_label
        position = self._start_move(label)
        if position is None:
            return
        if position != event.origin:
            self.fail(f"{label} departed {event.origin} but was at {position}")
        connection = self.connections.get(event.connection)
        if connection is None:
            self.fail(f"{label} used unknown lane {event.connection}")
            return
        origin = self.graph.get_zone(event.origin)
        destination = self.graph.get_zone(event.destination)
        if (
            origin is None
            or destination is None
            or not connection.connects(origin)
            or not connection.connects(destination)
        ):
            self.fail(f"{label}: lane {event.connection} does not link "
                      f"{event.origin} and {event.destination}")
            return
        if destination.zone_type is ZoneType.BLOCKED:
            self.fail(f"{label} headed into blocked {destination.name}")
        if event.connection in self.closed_lanes:
            self.fail(f"{label} departed on closed lane {event.connection}")
        self._use_lane(event.connection)
        self._take_off(label, event.connection, event.origin)
        self._drive(label, event.connection)
        self.positions[label] = _InTransit(
            event.connection, event.destination, self.turn
        )

    def _arrive(self, event: AgentMoved) -> None:
        label = event.agent_label
        position = self._start_move(label)
        if position is None:
            return
        destination = self.graph.get_zone(event.destination)
        origin = self.graph.get_zone(event.origin)
        if destination is None or origin is None:
            self.fail(f"{label} moved between unknown zones")
            return
        if destination.zone_type is ZoneType.BLOCKED:
            self.fail(f"{label} entered blocked {destination.name}")
        if event.delivered != (destination.name == self.end_name):
            self.fail(f"{label} delivered flag wrong at {destination.name}")

        if isinstance(position, _InTransit):
            self._finish_transit(label, position, event)
        else:
            self._single_turn_move(label, position, event)
        self.positions[label] = destination.name

    def _finish_transit(
        self, label: str, position: _InTransit, event: AgentMoved
    ) -> None:
        if position.destination != event.destination:
            self.fail(f"{label} arrived at {event.destination}, "
                      f"expected {position.destination}")
        connection = self.connections[position.connection]
        destination = self.graph.get_zone(event.destination)
        if connection.distance == 0 and destination is not None:
            expected = destination.movement_cost() - 1
            if self.turn - position.departed != expected:
                self.fail(f"{label} spent {self.turn - position.departed} "
                          f"extra turn(s) entering {destination.name}, "
                          f"expected {expected}")

    def _single_turn_move(
        self, label: str, position: str, event: AgentMoved
    ) -> None:
        if position != event.origin:
            self.fail(f"{label} moved from {event.origin} but was at "
                      f"{position}")
        origin = self.graph.get_zone(event.origin)
        destination = self.graph.get_zone(event.destination)
        assert origin is not None and destination is not None
        connection = self.graph.get_connection(origin, destination)
        if connection is None:
            self.fail(f"{label} moved {origin.name}->{destination.name} "
                      "without a lane")
            return
        if connection.name() in self.closed_lanes:
            self.fail(f"{label} crossed closed lane {connection.name()}")
        if connection.distance == 0 and destination.movement_cost() > 1:
            self.fail(f"{label} entered {destination.name} in one turn")
        self._use_lane(connection.name())
        self._take_off(label, connection.name(), origin.name)
        self._drive(label, connection.name())

    def _take_off(self, label: str, lane: str, origin: str) -> None:
        """A distance lane allows one departure per direction per turn."""
        if self.connections[lane].distance == 0:
            return
        if (lane, origin) in self.departures:
            self.fail(f"{label} was a second departure from {origin} on "
                      f"lane {lane} this turn")
        self.departures.add((lane, origin))

    def _drive(self, label: str, lane: str) -> None:
        """Track consecutive road distance; an air leg resets it."""
        connection = self.connections[lane]
        if connection.mode is not TransportMode.ROAD:
            self.road_km[label] = 0
            return
        self.road_km[label] += connection.distance
        if self.road_km[label] > self.max_road_km:
            self.fail(f"{label} drove {self.road_km[label]} km of "
                      f"consecutive road, limit {self.max_road_km}")

    def _reroute(self, event: AgentRerouted) -> None:
        label = event.agent_label
        position = self.positions.get(label)
        if position is None:
            self.fail(f"unknown aircraft {label} rerouted")
        elif isinstance(position, _InTransit):
            self.fail(f"{label} rerouted while in transit")
        elif position != event.hub:
            self.fail(f"{label} rerouted at {event.hub} but was at "
                      f"{position}")
        if not event.route or event.route[-1] != self.end_name:
            self.fail(f"{label} rerouted to a route that does not end at "
                      f"{self.end_name}")

    def _check_capacities(self) -> None:
        occupancy: dict[str, int] = {}
        incoming: dict[str, int] = {}
        for position in self.positions.values():
            if isinstance(position, str):
                occupancy[position] = occupancy.get(position, 0) + 1
            else:
                name = position.destination
                incoming[name] = incoming.get(name, 0) + 1
        for name, count in occupancy.items():
            self.peak_occupancy[name] = max(
                self.peak_occupancy.get(name, 0), count
            )
            zone = self.graph.get_zone(name)
            assert zone is not None
            if count > zone.effective_capacity():
                self.fail(f"hub {name} holds {count}, capacity "
                          f"{zone.effective_capacity()}")
        for name, flying in incoming.items():
            zone = self.graph.get_zone(name)
            assert zone is not None
            held = occupancy.get(name, 0)
            if held <= zone.effective_capacity() < held + flying:
                self.fail(f"hub {name} holds {held} and {flying} more are "
                          f"flying to it, capacity "
                          f"{zone.effective_capacity()}")
        for name, count in self.lane_use.items():
            capacity = self.connections[name].max_link_capacity
            if count > capacity:
                self.fail(f"lane {name} used by {count}, capacity {capacity}")

    def _check_final_state(self) -> None:
        not_delivered = sorted(
            label for label, position in self.positions.items()
            if position != self.end_name
        )
        if not_delivered:
            self.violations.append(f"not delivered: {not_delivered}")
        drones = self.run.simulator.drones
        if len(drones) != self.run.nb_aircraft:
            self.violations.append(
                f"simulator has {len(drones)} aircraft, "
                f"expected {self.run.nb_aircraft}"
            )
        for drone in drones:
            if not drone.is_delivered() or drone.current_zone.name != (
                self.end_name
            ):
                self.violations.append(
                    f"{drone.label} final state is not delivered at end"
                )


def planned_delivery_turns(
    graph: Graph, nb_aircraft: int
) -> dict[str, int]:
    """Plan routes the way the simulator does before its first turn and
    return the turn on which each aircraft's plan delivers it."""
    simulator = Simulator(graph, nb_aircraft)
    simulator._assign_paths()
    assert graph.start_zone is not None
    planned: dict[str, int] = {}
    for drone in simulator.drones:
        turn, here = 0, graph.start_zone
        for zone in drone.path:
            turn += simulator.pathfinder._calculate_move_cost(here, zone)
            here = zone
        planned[drone.label] = turn
    return planned


def delivery_turns(run: SimulationRun) -> dict[str, int]:
    """The turn on which each aircraft was delivered."""
    return {
        event.agent_label: event.turn_number
        for event in run.events
        if isinstance(event, AgentMoved) and event.delivered
    }


def committed_hub_load_by_turn(
    run: SimulationRun,
) -> dict[int, dict[str, int]]:
    """
    The committed load of every hub at the end of every turn, rebuilt from
    movement events alone: the aircraft in the hub plus the aircraft flying
    towards it (ADR-008). Delivered aircraft no longer count.
    """
    start = run.graph.start_zone
    assert start is not None
    # A hub name, or the destination of a leg in progress.
    positions: dict[str, str | _InTransit] = {
        f"D{number}": start.name for number in range(1, run.nb_aircraft + 1)
    }
    loads: dict[int, dict[str, int]] = {}
    for event in run.events:
        if isinstance(event, AgentInTransit):
            positions[event.agent_label] = _InTransit(
                event.connection, event.destination, event.turn_number
            )
        elif isinstance(event, AgentMoved):
            if event.delivered:
                positions.pop(event.agent_label)
            else:
                positions[event.agent_label] = event.destination
        elif isinstance(event, TurnFinished):
            load: dict[str, int] = {}
            for position in positions.values():
                hub = (
                    position
                    if isinstance(position, str)
                    else position.destination
                )
                load[hub] = load.get(hub, 0) + 1
            loads[event.turn_number] = load
    return loads


def check_outcomes_against_events(run: SimulationRun) -> list[str]:
    """
    Compare the turn results with the event stream of the same run and
    return every disagreement; empty if none (ADR-024, DECISION-012).

    Both describe the same facts until the event contract is decided, so
    they must agree turn by turn and in order:

    - `AgentInTransit` is a `Departure`. `AgentMoved` after it is the
      `Arrival` of that leg; any other `AgentMoved` is a one-turn leg, a
      `Departure` followed by an `Arrival`.
    - `AgentRerouted` is a `Reroute` at the same hub with the same new
      route; events do not carry the old route, so it is only checked to
      differ from the new one.
    - The assignment tokens of each result equal `TurnFinished.movements`.
    """
    problems: list[str] = []
    finished = {
        event.turn_number: event.movements
        for event in run.events
        if isinstance(event, TurnFinished)
    }
    results = run.simulator.turns
    if [result.turn_number for result in results] != sorted(finished):
        problems.append("results and TurnFinished cover different turns")

    expected: dict[int, list[object]] = {}
    lanes_in_flight: dict[str, str] = {}
    for event in run.events:
        here = expected.setdefault(event.turn_number, [])
        if isinstance(event, AgentInTransit):
            lanes_in_flight[event.agent_label] = event.connection
            here.append(
                Departure(
                    event.agent_label,
                    event.origin,
                    event.destination,
                    event.connection,
                )
            )
        elif isinstance(event, AgentMoved):
            lane = lanes_in_flight.pop(event.agent_label, None)
            leg = (
                event.agent_label,
                event.origin,
                event.destination,
                lane or _lane_between(run.graph, event.origin,
                                      event.destination),
            )
            if lane is None:
                here.append(Departure(*leg))
            here.append(Arrival(*leg))
        elif isinstance(event, AgentRerouted):
            here.append((event.agent_label, event.hub, event.route))

    for result in results:
        actual: list[object] = []
        for outcome in result.outcomes:
            if isinstance(outcome, Reroute):
                if outcome.old_route == outcome.new_route:
                    problems.append(
                        f"turn {result.turn_number}: {outcome.aircraft} "
                        "reroute keeps its route"
                    )
                actual.append(
                    (outcome.aircraft, outcome.hub, outcome.new_route)
                )
            else:
                actual.append(outcome)
        if actual != expected.get(result.turn_number, []):
            problems.append(
                f"turn {result.turn_number}: outcomes {actual} do not match "
                f"events {expected.get(result.turn_number, [])}"
            )
        tokens = movement_tokens(result)
        if tokens != finished.get(result.turn_number):
            problems.append(
                f"turn {result.turn_number}: tokens {tokens} differ from "
                f"TurnFinished {finished.get(result.turn_number)}"
            )
    return problems


def _lane_between(graph: Graph, origin: str, destination: str) -> str:
    connection = graph.get_connection(
        graph.zones[origin], graph.zones[destination]
    )
    assert connection is not None
    return connection.name()
