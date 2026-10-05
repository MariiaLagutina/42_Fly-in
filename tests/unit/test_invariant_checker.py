"""Self-tests for the invariant checker in `tests.support.simulation`.

Simulation tests pass when the checker reports nothing, so a checker that
silently misses violations would make them meaningless. These tests feed it
hand-written event streams with one known violation each.
"""

from airlanes.model.drone import DroneState
from airlanes.events import (
    AgentInTransit,
    AgentMoved,
    AgentRerouted,
    SimulationEvent,
    TurnFinished,
    TurnStarted,
    WeatherChanged,
)
from airlanes.model.graph import Graph
from airlanes.simulation.engine import Simulator
from tests.support.graphs import Link, build_graph, end_hub, hub, start_hub
from tests.support.simulation import SimulationRun, check_invariants
from airlanes.model.transport_mode import TransportMode
from airlanes.model.zone import ZoneType


def make_graph() -> Graph:
    return build_graph(
        [
            start_hub(),
            hub("gate", capacity=1),
            hub("slow", ZoneType.RESTRICTED, capacity=2),
            hub("wall", ZoneType.BLOCKED),
            end_hub(),
        ],
        [
            Link("start", "gate"),
            Link("gate", "goal"),
            Link("start", "slow"),
            Link("slow", "goal"),
            Link("start", "wall"),
            Link("wall", "goal"),
        ],
    )


def fake_run(
    graph: Graph,
    nb_aircraft: int,
    turns: list[list[SimulationEvent]],
    delivered: bool = True,
) -> SimulationRun:
    """Wrap hand-written turns as a run; final simulator state is faked."""
    simulator = Simulator(graph, nb_aircraft)
    if delivered:
        assert graph.end_zone is not None
        for drone in simulator.drones:
            drone.state = DroneState.DELIVERED
            drone.current_zone = graph.end_zone
    events: list[SimulationEvent] = []
    for number, moves in enumerate(turns, start=1):
        events.append(TurnStarted(number))
        events.extend(moves)
        events.append(TurnFinished(number, ()))
    return SimulationRun(graph, nb_aircraft, simulator, events, [])


def moved(turn: int, label: str, origin: str, destination: str) -> AgentMoved:
    return AgentMoved(turn, label, origin, destination, destination == "goal")


def has_violation(run: SimulationRun, text: str) -> bool:
    return any(text in violation for violation in check_invariants(run))


def test_valid_run_has_no_violations() -> None:
    run = fake_run(make_graph(), 2, [
        [moved(1, "D1", "start", "gate")],
        [moved(2, "D1", "gate", "goal"), moved(2, "D2", "start", "gate")],
        [moved(3, "D2", "gate", "goal")],
    ])

    assert check_invariants(run) == []


def test_detects_hub_over_capacity() -> None:
    graph = make_graph()
    for link in graph.connections:
        link.max_link_capacity = 2
    run = fake_run(graph, 2, [
        [moved(1, "D1", "start", "gate"), moved(1, "D2", "start", "gate")],
        [moved(2, "D1", "gate", "goal"), moved(2, "D2", "gate", "goal")],
    ])

    assert has_violation(run, "hub gate holds 2")


def test_detects_lane_over_capacity() -> None:
    graph = make_graph()
    gate = graph.get_zone("gate")
    assert gate is not None
    gate.max_drones = 2
    run = fake_run(graph, 2, [
        [moved(1, "D1", "start", "gate"), moved(1, "D2", "start", "gate")],
        [moved(2, "D1", "gate", "goal")],
        [moved(3, "D2", "gate", "goal")],
    ])

    assert has_violation(run, "lane start-gate used by 2")


def test_detects_move_without_a_lane() -> None:
    run = fake_run(make_graph(), 1, [[moved(1, "D1", "start", "goal")]])

    assert has_violation(run, "without a lane")


def test_detects_entering_a_blocked_hub() -> None:
    run = fake_run(make_graph(), 1, [
        [moved(1, "D1", "start", "wall")],
        [moved(2, "D1", "wall", "goal")],
    ])

    assert has_violation(run, "entered blocked wall")


def test_detects_entering_a_restricted_hub_in_one_turn() -> None:
    run = fake_run(make_graph(), 1, [
        [moved(1, "D1", "start", "slow")],
        [moved(2, "D1", "slow", "goal")],
    ])

    assert has_violation(run, "entered slow in one turn")


def test_detects_overlong_restricted_transit() -> None:
    transit = AgentInTransit(1, "D1", "start", "start-slow", "slow")
    run = fake_run(make_graph(), 1, [
        [transit],
        [],
        [moved(3, "D1", "start", "slow")],
        [moved(4, "D1", "slow", "goal")],
    ])

    assert has_violation(run, "spent 2 extra turn(s) entering slow")


def test_detects_departure_on_a_closed_lane() -> None:
    run = fake_run(make_graph(), 1, [
        [
            WeatherChanged(1, "start-slow", "storm", False),
            AgentInTransit(1, "D1", "start", "start-slow", "slow"),
        ],
        [moved(2, "D1", "start", "slow")],
        [moved(3, "D1", "slow", "goal")],
    ])

    assert has_violation(run, "departed on closed lane start-slow")


def test_detects_an_aircraft_moving_twice_in_one_turn() -> None:
    run = fake_run(make_graph(), 1, [
        [moved(1, "D1", "start", "gate"), moved(1, "D1", "gate", "goal")],
    ])

    assert has_violation(run, "D1 moved twice")


def test_detects_undelivered_aircraft() -> None:
    run = fake_run(
        make_graph(), 2, [[moved(1, "D1", "start", "gate")]], delivered=False
    )

    assert has_violation(run, "not delivered: ['D1', 'D2']")


def test_detects_consecutive_road_over_the_budget() -> None:
    graph = build_graph(
        [start_hub(), hub("a"), end_hub()],
        [
            Link("start", "a", distance=400, mode=TransportMode.ROAD),
            Link("a", "goal", distance=400, mode=TransportMode.ROAD),
        ],
    )
    run = fake_run(graph, 1, [
        [AgentInTransit(1, "D1", "start", "start-a", "a")],
        [moved(2, "D1", "start", "a")],
        [AgentInTransit(3, "D1", "a", "a-goal", "goal")],
        [moved(4, "D1", "a", "goal")],
    ])

    assert has_violation(run, "D1 drove 800 km of consecutive road")


def test_accepts_a_reroute_at_the_current_hub() -> None:
    run = fake_run(make_graph(), 1, [
        [
            AgentRerouted(1, "D1", "start", ("gate", "goal"), "weather"),
            moved(1, "D1", "start", "gate"),
        ],
        [moved(2, "D1", "gate", "goal")],
    ])

    assert check_invariants(run) == []


def test_detects_a_reroute_in_transit() -> None:
    run = fake_run(make_graph(), 1, [
        [
            AgentInTransit(1, "D1", "start", "start-slow", "slow"),
            AgentRerouted(1, "D1", "start", ("gate", "goal"), "weather"),
        ],
        [moved(2, "D1", "start", "slow")],
        [moved(3, "D1", "slow", "goal")],
    ])

    assert has_violation(run, "D1 rerouted while in transit")


def test_detects_a_reroute_away_from_the_current_hub() -> None:
    run = fake_run(make_graph(), 1, [
        [AgentRerouted(1, "D1", "gate", ("goal",), "weather")],
        [moved(2, "D1", "start", "gate")],
        [moved(3, "D1", "gate", "goal")],
    ])

    assert has_violation(run, "D1 rerouted at gate but was at start")


def distance_lane_graph() -> Graph:
    """`start-a` is a 150 km air lane: one turn, with a departure rule."""
    return build_graph(
        [start_hub(), hub("a", capacity=2), end_hub()],
        [Link("start", "a", capacity=3, distance=150), Link("a", "goal")],
    )


def test_detects_two_departures_in_one_direction() -> None:
    run = fake_run(distance_lane_graph(), 2, [
        [moved(1, "D1", "start", "a"), moved(1, "D2", "start", "a")],
        [moved(2, "D1", "a", "goal")],
        [moved(3, "D2", "a", "goal")],
    ])

    assert has_violation(
        run, "D2 was a second departure from start on lane start-a"
    )


def test_accepts_departures_in_opposite_directions() -> None:
    run = fake_run(distance_lane_graph(), 2, [
        [moved(1, "D1", "start", "a")],
        [moved(2, "D1", "a", "start"), moved(2, "D2", "start", "a")],
        [moved(3, "D1", "start", "a"), moved(3, "D2", "a", "goal")],
        [moved(4, "D1", "a", "goal")],
    ])

    assert check_invariants(run) == []


def claim_graph(gate_capacity: int) -> Graph:
    """`start-gate` is a 450 km air lane, two turns long; `b-gate` takes one
    turn."""
    return build_graph(
        [start_hub(), hub("b"), hub("gate", capacity=gate_capacity),
         end_hub()],
        [
            Link("start", "gate", distance=450),
            Link("start", "b"),
            Link("b", "gate"),
            Link("gate", "goal"),
        ],
    )


def claim_stream() -> list[list[SimulationEvent]]:
    """D1 flies to `gate` on turns 2-3 while D2 enters `gate` on turn 2 and
    leaves it on turn 3: the hub never holds two aircraft, but on turn 2 it
    holds one and expects another."""
    return [
        [moved(1, "D2", "start", "b")],
        [
            AgentInTransit(2, "D1", "start", "start-gate", "gate"),
            moved(2, "D2", "b", "gate"),
        ],
        [moved(3, "D2", "gate", "goal"), moved(3, "D1", "start", "gate")],
        [moved(4, "D1", "gate", "goal")],
    ]


def test_detects_hub_load_over_capacity_from_aircraft_in_transit() -> None:
    run = fake_run(claim_graph(1), 2, claim_stream())

    assert has_violation(
        run, "hub gate holds 1 and 1 more are flying to it, capacity 1"
    )
    assert not has_violation(run, "hub gate holds 2")


def test_accepts_aircraft_in_transit_when_the_hub_has_room() -> None:
    run = fake_run(claim_graph(2), 2, claim_stream())

    assert check_invariants(run) == []
