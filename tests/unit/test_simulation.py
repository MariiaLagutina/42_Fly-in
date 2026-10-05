"""Simulation on small synthetic graphs.

Every run is checked against the full invariant set in
`tests.support.simulation`. Scenarios add one targeted assertion each.
Exact turn counts are asserted only where the rules define them: a single
aircraft on a single route, where restricted hubs and the documented
distance travel-time formula leave no room for another valid answer.
"""

import pytest

from airlanes.events import AgentInTransit, AgentRerouted, WeatherChanged
from airlanes.model.graph import Graph
from airlanes.simulation.deadlock import DeadlockError
from tests.support.graphs import Link, build_graph, end_hub, hub, start_hub
from tests.support.simulation import (
    check_invariants,
    delivery_turns,
    peak_hub_occupancy,
    planned_delivery_turns,
    SimulationRun,
    run_simulation,
)
from airlanes.model.transport_mode import TransportMode
from airlanes.world.weather import ScriptedWeather, WeatherCondition
from airlanes.model.zone import ZoneType

AIR = TransportMode.AIR
ROAD = TransportMode.ROAD


def departure_turns(run: SimulationRun) -> list[int]:
    return [e.turn_number for e in run.events if isinstance(e, AgentInTransit)]


def test_single_aircraft_on_a_linear_route() -> None:
    graph = build_graph(
        [start_hub(), hub("a"), end_hub()],
        [Link("start", "a"), Link("a", "goal")],
    )

    run = run_simulation(graph, 1)

    assert check_invariants(run) == []
    assert run.output == ["D1-a", "D1-goal"]


def test_restricted_hub_takes_two_turns_to_enter() -> None:
    graph = build_graph(
        [start_hub(), hub("slow", ZoneType.RESTRICTED), end_hub()],
        [Link("start", "slow"), Link("slow", "goal")],
    )

    run = run_simulation(graph, 1)

    assert check_invariants(run) == []
    assert run.output == ["D1-start-slow", "D1-slow", "D1-goal"]


def test_aircraft_wait_for_a_single_slot_hub() -> None:
    graph = build_graph(
        [start_hub(), hub("gate", capacity=1), end_hub()],
        [Link("start", "gate"), Link("gate", "goal")],
    )

    run = run_simulation(graph, 4)

    assert check_invariants(run) == []


@pytest.mark.parametrize("capacity", [1, 2])
def test_lane_capacity_limits_simultaneous_use(capacity: int) -> None:
    graph = build_graph(
        [start_hub(), end_hub()], [Link("start", "goal", capacity)]
    )

    run = run_simulation(graph, 5)

    assert check_invariants(run) == []


def test_aircraft_spread_over_parallel_routes() -> None:
    graph = build_graph(
        [start_hub(), hub("north"), hub("south"), end_hub()],
        [
            Link("start", "north"),
            Link("north", "goal"),
            Link("start", "south"),
            Link("south", "goal"),
        ],
    )

    run = run_simulation(graph, 4)

    assert check_invariants(run) == []


def test_blocked_hub_is_never_entered() -> None:
    graph = build_graph(
        [
            start_hub(),
            hub("wall", ZoneType.BLOCKED),
            hub("a"),
            hub("b"),
            end_hub(),
        ],
        [
            Link("start", "wall"),
            Link("wall", "goal"),
            Link("start", "a"),
            Link("a", "b"),
            Link("b", "goal"),
        ],
    )

    run = run_simulation(graph, 3)

    assert check_invariants(run) == []
    for label in ("D1", "D2", "D3"):
        assert "wall" not in run.visited_zones(label)


def test_priority_hub_is_preferred_over_an_equal_route() -> None:
    graph = build_graph(
        [
            start_hub(),
            hub("plain"),
            hub("fast", ZoneType.PRIORITY),
            end_hub(),
        ],
        [
            Link("start", "plain"),
            Link("plain", "goal"),
            Link("start", "fast"),
            Link("fast", "goal"),
        ],
    )

    run = run_simulation(graph, 1)

    assert check_invariants(run) == []
    assert run.visited_zones("D1") == ["fast", "goal"]


def test_start_and_end_hold_every_aircraft() -> None:
    """Start and end hubs ignore `max_drones`."""
    graph = build_graph(
        [start_hub(capacity=1), end_hub(capacity=1)],
        [Link("start", "goal", capacity=5)],
    )

    run = run_simulation(graph, 5)

    assert check_invariants(run) == []


@pytest.mark.parametrize(
    "graph",
    [
        pytest.param(
            build_graph([start_hub(), hub("a"), end_hub()],
                        [Link("start", "a")]),
            id="disconnected",
        ),
        pytest.param(
            build_graph(
                [start_hub(), hub("wall", ZoneType.BLOCKED), end_hub()],
                [Link("start", "wall"), Link("wall", "goal")],
            ),
            id="only-through-blocked",
        ),
    ],
)
def test_missing_route_fails_before_the_first_turn(graph: Graph) -> None:
    with pytest.raises(RuntimeError):
        run_simulation(graph, 2)


# --- Distance-based travel time and weather ---------------------------------
# Road legs travel at 100 km/h, air legs at 400 km/h, rounded up to whole
# turns; the mode comes from the map. Weather comes from `ScriptedWeather`,
# so these runs are deterministic. Weather travel times follow the transport
# rules (DECISION-001): rain adds one turn to a road leg, storm and snow two.


@pytest.mark.parametrize(
    ("mode", "distance", "expected_turns"),
    [
        pytest.param(ROAD, 100, 1, id="road-100km"),
        pytest.param(ROAD, 150, 2, id="road-150km"),
        pytest.param(ROAD, 250, 3, id="road-250km"),
        pytest.param(AIR, 150, 1, id="air-150km"),
        pytest.param(AIR, 450, 2, id="air-450km"),
        pytest.param(AIR, 900, 3, id="air-900km"),
    ],
)
def test_mode_and_distance_set_travel_time(
    mode: TransportMode, distance: int, expected_turns: int
) -> None:
    graph = build_graph(
        [start_hub(), end_hub()],
        [Link("start", "goal", distance=distance, mode=mode)],
    )

    run = run_simulation(graph, 1)

    assert check_invariants(run) == []
    assert run.turn_count == expected_turns


def test_aircraft_waits_while_its_air_lane_is_closed() -> None:
    graph = build_graph(
        [start_hub(), end_hub()], [Link("start", "goal", distance=450)]
    )
    weather = ScriptedWeather({
        1: {"start-goal": WeatherCondition.STORM},
        4: {"start-goal": WeatherCondition.CLEAR},
    })

    run = run_simulation(graph, 1, weather)

    assert check_invariants(run) == []
    assert departure_turns(run) == [4]
    assert run.turn_count == 5


def test_road_stays_open_but_slower_in_a_storm() -> None:
    """150 km of road takes 2 turns, plus 2 in a storm. With no other route
    the aircraft reconsiders, keeps its route, and drives."""
    graph = build_graph(
        [start_hub(), end_hub()],
        [Link("start", "goal", distance=150, mode=ROAD)],
    )
    weather = ScriptedWeather({1: {"start-goal": WeatherCondition.STORM}})

    run = run_simulation(graph, 1, weather)

    assert check_invariants(run) == []
    assert departure_turns(run) == [1]
    assert not any(isinstance(e, AgentRerouted) for e in run.events)
    assert run.turn_count == 4


def test_weather_events_report_each_change_once() -> None:
    graph = build_graph(
        [start_hub(), hub("a"), end_hub()],
        [
            Link("start", "a", distance=450),
            Link("a", "goal", distance=150, mode=ROAD),
        ],
    )
    weather = ScriptedWeather({
        1: {
            "start-a": WeatherCondition.STORM,
            "a-goal": WeatherCondition.STORM,
        },
        2: {"start-a": WeatherCondition.STORM},
        3: {"start-a": WeatherCondition.CLEAR},
    })

    run = run_simulation(graph, 1, weather)

    assert [
        (e.turn_number, e.connection_name, e.condition, e.is_open)
        for e in run.events
        if isinstance(e, WeatherChanged)
    ] == [
        (1, "start-a", "storm", False),
        (1, "a-goal", "storm", True),
        (3, "start-a", "clear", True),
    ]


def test_weather_cannot_describe_a_connection_the_map_lacks() -> None:
    graph = build_graph(
        [start_hub(), end_hub()], [Link("start", "goal", distance=450)]
    )
    weather = ScriptedWeather({1: {"start-nowhere": WeatherCondition.STORM}})

    with pytest.raises(ValueError):
        run_simulation(graph, 1, weather)


# --- Dynamic replanning (ADR-018, ADR-021) ----------------------------------
# An aircraft at a hub reconsiders its route when the weather makes it slower
# than in clear weather, a closed leg being infinitely slow. It switches only
# to a strictly faster route, and waits when a closed route has no
# alternative. Weather comes from `ScriptedWeather`. Routes are asserted only
# where a single alternative exists.

STORM = WeatherCondition.STORM
CLEAR = WeatherCondition.CLEAR


def reroutes(run: SimulationRun) -> list[AgentRerouted]:
    return [e for e in run.events if isinstance(e, AgentRerouted)]


def two_air_routes(
    via_a: int = 450, via_b: int = 900
) -> Graph:
    """start -> a -> goal is faster than start -> b -> goal."""
    return build_graph(
        [start_hub(), hub("a"), hub("b"), end_hub()],
        [
            Link("start", "a", distance=via_a),
            Link("a", "goal", distance=via_a),
            Link("start", "b", distance=via_b),
            Link("b", "goal", distance=via_b),
        ],
    )


def test_closed_first_leg_on_turn_one_causes_a_reroute() -> None:
    weather = ScriptedWeather({1: {"start-a": STORM}})

    run = run_simulation(two_air_routes(), 1, weather)

    assert check_invariants(run) == []
    assert reroutes(run) == [
        AgentRerouted(1, "D1", "start", ("b", "goal"), "weather")
    ]
    assert departure_turns(run)[0] == 1


def test_aircraft_waits_while_no_route_is_usable() -> None:
    weather = ScriptedWeather({
        1: {"start-a": STORM, "start-b": STORM},
        4: {"start-a": CLEAR, "start-b": CLEAR},
    })

    run = run_simulation(two_air_routes(), 1, weather)

    assert check_invariants(run) == []
    assert reroutes(run) == []
    assert departure_turns(run)[0] == 4
    assert run.visited_zones("D1") == ["a", "goal"]


def test_unusable_later_leg_causes_a_reroute_before_departure() -> None:
    weather = ScriptedWeather({1: {"a-goal": STORM}})

    run = run_simulation(two_air_routes(), 1, weather)

    assert check_invariants(run) == []
    assert reroutes(run) == [
        AgentRerouted(1, "D1", "start", ("b", "goal"), "weather")
    ]


def test_aircraft_in_transit_finishes_its_leg_before_rerouting() -> None:
    """The lane ahead closes while the aircraft flies to `a`. It decides at
    `a`, on the first turn after it arrives there (turn 3)."""
    weather = ScriptedWeather({2: {"a-goal": STORM}})

    run = run_simulation(two_air_routes(), 1, weather)

    assert check_invariants(run) == []
    first = reroutes(run)[0]
    assert (first.turn_number, first.hub) == (3, "a")
    assert "a-goal" not in {
        e.connection for e in run.events if isinstance(e, AgentInTransit)
    }


def test_usable_route_is_kept_when_another_becomes_faster() -> None:
    """A tailwind makes the route via `b` faster than the planned one, but
    the planned route is not slowed, so the aircraft does not reconsider."""
    graph = two_air_routes(via_a=1200, via_b=1600)
    weather = ScriptedWeather({1: {
        "start-b": WeatherCondition.TAILWIND,
        "b-goal": WeatherCondition.TAILWIND,
    }})

    run = run_simulation(graph, 1, weather)

    assert check_invariants(run) == []
    assert reroutes(run) == []
    assert run.visited_zones("D1") == ["a", "goal"]


RAIN = WeatherCondition.RAIN
TAILWIND = WeatherCondition.TAILWIND


def road_or_air() -> Graph:
    """start -> a by 150 km of road (2 turns), then 300 km of air (1 turn),
    is faster than start -> b by 900 km of air (3 turns), then 300 km of
    air (1 turn)."""
    return build_graph(
        [start_hub(), hub("a"), hub("b"), end_hub()],
        [
            Link("start", "a", distance=150, mode=ROAD),
            Link("a", "goal", distance=300),
            Link("start", "b", distance=900),
            Link("b", "goal", distance=300),
        ],
    )


def test_slowed_road_is_replaced_by_a_faster_air_route() -> None:
    """A storm makes the road route 5 turns, the air route takes 4."""
    weather = ScriptedWeather({1: {"start-a": STORM}})

    run = run_simulation(road_or_air(), 1, weather)

    assert check_invariants(run) == []
    assert reroutes(run) == [
        AgentRerouted(1, "D1", "start", ("b", "goal"), "weather")
    ]
    assert delivery_turns(run) == {"D1": 4}


def test_slowed_route_is_kept_on_a_tie() -> None:
    """Rain makes the road route 4 turns, as long as the air route."""
    weather = ScriptedWeather({1: {"start-a": RAIN}})

    run = run_simulation(road_or_air(), 1, weather)

    assert check_invariants(run) == []
    assert reroutes(run) == []
    assert run.visited_zones("D1") == ["a", "goal"]


def test_slowed_later_leg_is_reconsidered_before_departure() -> None:
    """The storm is on the second leg of the planned route. The current
    weather is costed for the whole route, so the aircraft switches before
    it leaves: road 2 + air 3 = 5 turns against air 3 + air 1 = 4."""
    graph = build_graph(
        [start_hub(), hub("a"), hub("b"), end_hub()],
        [
            Link("start", "a", distance=300),
            Link("a", "goal", distance=150, mode=ROAD),
            Link("start", "b", distance=300),
            Link("b", "goal", distance=1000),
        ],
    )
    weather = ScriptedWeather({1: {"a-goal": STORM}})

    run = run_simulation(graph, 1, weather)

    assert check_invariants(run) == []
    assert reroutes(run) == [
        AgentRerouted(1, "D1", "start", ("b", "goal"), "weather")
    ]


def test_tailwind_counts_once_a_slowdown_triggers_reconsideration() -> None:
    """Rain alone would tie (4 against 4 turns), but the search uses the
    whole current weather: a tailwind makes the air route 3 turns."""
    weather = ScriptedWeather({1: {"start-a": RAIN, "start-b": TAILWIND}})

    run = run_simulation(road_or_air(), 1, weather)

    assert check_invariants(run) == []
    assert reroutes(run) == [
        AgentRerouted(1, "D1", "start", ("b", "goal"), "weather")
    ]
    assert delivery_turns(run) == {"D1": 3}


def test_travel_time_is_fixed_when_the_leg_starts() -> None:
    """The storm clears on turn 2, but a road leg started in it keeps the
    storm's travel time, so switching to the air route on turn 1 is not a
    bet on the weather: 4 turns instead of 5."""
    weather = ScriptedWeather({1: {"start-a": STORM}, 2: {"start-a": CLEAR}})

    run = run_simulation(road_or_air(), 1, weather)

    assert check_invariants(run) == []
    assert delivery_turns(run) == {"D1": 4}


def air_with_road_fallback(road_km: int) -> Graph:
    """A direct air lane and a two-leg road through `r`."""
    return build_graph(
        [start_hub(), hub("r"), end_hub()],
        [
            Link("start", "goal", distance=450),
            Link("start", "r", distance=road_km, mode=ROAD),
            Link("r", "goal", distance=road_km, mode=ROAD),
        ],
    )


def test_road_becomes_the_fallback_when_air_closes() -> None:
    weather = ScriptedWeather({1: {"start-goal": STORM}})

    run = run_simulation(air_with_road_fallback(150), 1, weather)

    assert check_invariants(run) == []
    assert reroutes(run) == [
        AgentRerouted(1, "D1", "start", ("r", "goal"), "weather")
    ]


def test_road_over_the_budget_is_not_a_fallback() -> None:
    """400 + 400 km of road exceeds the 700 km budget, so the aircraft
    waits for the air lane instead."""
    weather = ScriptedWeather({
        1: {"start-goal": STORM}, 3: {"start-goal": CLEAR},
    })

    run = run_simulation(air_with_road_fallback(400), 1, weather)

    assert check_invariants(run) == []
    assert reroutes(run) == []
    assert departure_turns(run) == [3]


def test_road_already_driven_counts_when_rerouting() -> None:
    """After 500 km of road to `x`, the 300 km road detour would make 800 km
    of consecutive road, so the aircraft waits for the air lane."""
    graph = build_graph(
        [start_hub(), hub("x"), hub("y"), end_hub()],
        [
            Link("start", "x", distance=500, mode=ROAD),
            Link("x", "goal", distance=450),
            Link("x", "y", distance=300, mode=ROAD),
            Link("y", "goal", distance=450),
        ],
    )
    weather = ScriptedWeather({2: {"x-goal": STORM}, 9: {"x-goal": CLEAR}})

    run = run_simulation(graph, 1, weather)

    assert check_invariants(run) == []
    assert departure_turns(run)[0] == 1
    assert reroutes(run) == []
    assert run.visited_zones("D1") == ["x", "goal"]


def test_fresh_road_budget_allows_the_same_detour() -> None:
    """Control for the test above: starting at `x` with no road driven,
    the same detour is within the budget and is taken."""
    graph = build_graph(
        [start_hub("x"), hub("y"), end_hub()],
        [
            Link("x", "goal", distance=450),
            Link("x", "y", distance=300, mode=ROAD),
            Link("y", "goal", distance=450),
        ],
    )
    weather = ScriptedWeather({1: {"x-goal": STORM}})

    run = run_simulation(graph, 1, weather)

    assert check_invariants(run) == []
    assert reroutes(run) == [
        AgentRerouted(1, "D1", "x", ("y", "goal"), "weather")
    ]


# --- Regression: hub capacity (BUG-001, BUG-002) ----------------------------
# Three aircraft pass a one-slot `gate` and then a one-slot restricted hub
# `slow`. Before the fix, an aircraft whose departure from `gate` was
# rejected still counted as having left it, so a second aircraft moved in
# (BUG-002); and two aircraft departing towards `slow` in the same turn did
# not see each other as incoming, so both arrived (BUG-001). Each test checks
# one hub, so each bug is detected independently of the other.


def build_gate_and_restricted_hub() -> Graph:
    return build_graph(
        [
            start_hub(),
            hub("gate"),
            hub("slow", ZoneType.RESTRICTED),
            end_hub(),
        ],
        [
            Link("start", "gate"),
            Link("gate", "slow", capacity=2),
            Link("slow", "goal", capacity=2),
        ],
    )


def test_rejected_departure_does_not_free_its_hub() -> None:
    """BUG-002: `gate` never holds more than its single slot."""
    run = run_simulation(build_gate_and_restricted_hub(), 3)

    assert peak_hub_occupancy(run)["gate"] <= 1


def test_simultaneous_multi_turn_arrivals_respect_capacity() -> None:
    """BUG-001: `slow` never holds more than its single slot."""
    run = run_simulation(build_gate_and_restricted_hub(), 3)

    assert peak_hub_occupancy(run)["slow"] <= 1


def test_restricted_hub_with_room_for_two_is_not_overfilled() -> None:
    """BUG-001 with a larger hub: six aircraft, a restricted hub for two."""
    graph = build_graph(
        [
            start_hub(),
            hub("slow", ZoneType.RESTRICTED, capacity=2),
            hub("side", ZoneType.PRIORITY, capacity=3),
            end_hub(),
        ],
        [
            Link("slow", "goal", capacity=2),
            Link("start", "side", capacity=2),
            Link("slow", "start", capacity=3),
        ],
    )

    run = run_simulation(graph, 6)

    assert peak_hub_occupancy(run)["slow"] <= 2


# --- Regression: departure arbitration (BUG-003 variant B) ------------------
# A lane is handed out only to a move that can also enter its destination
# hub. Before the fix, an aircraft that could not enter its hub still took
# the lane first, every turn, and an aircraft that could leave never got it.
# Both runs hung until the 10,000-turn limit.


def test_rejected_departure_does_not_take_the_departure_slot() -> None:
    """Canonical BUG-003 variant B. D10 in `S` waits for `h0`, which D11
    occupies; D11 in `h0` could leave for `S`, but D10 took the lane's one
    departure slot first on every turn."""
    graph = build_graph(
        [
            start_hub("S"),
            end_hub("E"),
            hub("h0", ZoneType.PRIORITY),
            hub("h1", ZoneType.RESTRICTED, capacity=2),
            hub("h2"),
        ],
        [
            Link("h1", "E", distance=450),
            Link("h2", "h0", distance=150, mode=ROAD),
            Link("S", "h2", capacity=2, distance=1200),
            Link("E", "S", capacity=2, distance=700),
            Link("S", "h0", capacity=3, distance=450),
        ],
    )

    run = run_simulation(graph, 12)

    assert check_invariants(run) == []


def test_rejected_departure_does_not_take_lane_capacity() -> None:
    """The same mechanism through lane capacity. After a reroute, D3 in
    `h2` waits for `h4`, which D5 occupies, and D5 in `h4` wants `h2`, which
    has room. Lane `h4-h2` holds one aircraft; D3 used to take it first."""
    graph = build_graph(
        [
            start_hub("S"),
            end_hub("E"),
            hub("h1", ZoneType.PRIORITY),
            hub("h2", capacity=3),
            hub("h3", ZoneType.PRIORITY, capacity=3),
            hub("h4"),
            hub("h5"),
        ],
        [
            Link("E", "h5"),
            Link("S", "h4"),
            Link("h1", "h5"),
            Link("h4", "h2"),
            Link("h5", "h4"),
            Link("h3", "h5"),
            Link("h2", "h3", capacity=2),
            Link("h3", "h1"),
            Link("S", "h2"),
        ],
    )
    weather = ScriptedWeather({3: {"h3-h5": STORM}, 7: {"h3-h5": CLEAR}})

    run = run_simulation(graph, 5, weather)

    assert check_invariants(run) == []


# --- One capacity model for planner and executor (ADR-019) ------------------
# The planner holds a hub from the turn a leg towards it departs, holds a
# lane on every turn of a leg, and allows one departure per direction per
# turn on a distance lane, exactly as the executor does. Without weather,
# plans therefore execute exactly. Before, the planner booked a hub only on
# the arrival turn, so the executor delayed planned departures, the planned
# meeting points shifted, and some runs hung (BUG-003).


def canonical_variant_a() -> Graph:
    """Canonical BUG-003 variant A. The old plans parked aircraft in the
    priority hub `h0` and brought them back, so D9 in `h2` and D11 in `h4`
    ended up waiting for each other's hub on lane `h4-h2`."""
    return build_graph(
        [
            start_hub("S"),
            end_hub("E"),
            hub("h0", ZoneType.PRIORITY),
            hub("h1", ZoneType.BLOCKED),
            hub("h2"),
            hub("h3", ZoneType.RESTRICTED, capacity=2),
            hub("h4"),
        ],
        [
            Link("h2", "h0", capacity=3, distance=80, mode=ROAD),
            Link("h1", "E", capacity=3, distance=700),
            Link("h4", "h2", capacity=3, distance=150, mode=ROAD),
            Link("h4", "h3", capacity=3, distance=700),
            Link("h3", "S", capacity=2, distance=700),
            Link("S", "E", distance=450),
        ],
    )


def restricted_hub_queue() -> Graph:
    """Five aircraft through a one-slot restricted hub."""
    return build_graph(
        [start_hub(), hub("slow", ZoneType.RESTRICTED), end_hub()],
        [Link("start", "slow", capacity=2), Link("slow", "goal")],
    )


def zero_distance_lane_into_restricted_hub() -> Graph:
    """A two-turn lane without a distance: the planner used to check the
    lane only on the departure turn."""
    return build_graph(
        [
            start_hub("S"),
            end_hub("E"),
            hub("h0", ZoneType.PRIORITY),
            hub("h1", capacity=3),
            hub("h2", ZoneType.PRIORITY),
            hub("h3", ZoneType.RESTRICTED, capacity=3),
            hub("h4", ZoneType.BLOCKED),
        ],
        [
            Link("h4", "h3", capacity=3),
            Link("E", "h2", capacity=2),
            Link("E", "h0"),
            Link("h2", "h1"),
            Link("E", "h3"),
            Link("h0", "h1"),
            Link("S", "h3", capacity=2),
            Link("h3", "h1", capacity=3),
        ],
    )


@pytest.mark.parametrize(
    ("graph", "nb_aircraft"),
    [
        pytest.param(canonical_variant_a(), 12, id="bug-003-variant-a"),
        pytest.param(restricted_hub_queue(), 5, id="restricted-hub-queue"),
        pytest.param(
            zero_distance_lane_into_restricted_hub(), 10,
            id="zero-distance-lane",
        ),
    ],
)
def test_aircraft_are_delivered_when_planned(
    graph: Graph, nb_aircraft: int
) -> None:
    planned = planned_delivery_turns(graph, nb_aircraft)

    run = run_simulation(graph, nb_aircraft)

    assert check_invariants(run) == []
    assert delivery_turns(run) == planned


# --- Waiting happens in place (ADR-014, DECISION-007) -----------------------


def test_aircraft_waits_in_place_instead_of_a_detour() -> None:
    """With one lane to the goal, the third aircraft used to fly to the
    priority hub `p` and back to pass time. It now waits at the start and
    is delivered on the same turn."""
    graph = build_graph(
        [start_hub(), hub("p", ZoneType.PRIORITY), end_hub()],
        [Link("start", "goal"), Link("start", "p")],
    )

    run = run_simulation(graph, 3)

    assert check_invariants(run) == []
    assert run.visited_zones("D3") == ["goal"]
    assert delivery_turns(run) == {"D1": 1, "D2": 2, "D3": 3}


# --- Structural deadlocks (ADR-020, BUG-003) --------------------------------
# Aircraft that block each other for good are detected on the turn it
# happens. One of them takes a way around if there is one now; if there is
# one only once the weather clears, they wait; otherwise the run stops with
# DeadlockError instead of running into the 10,000-turn limit.


def deadlock_reroutes(run: SimulationRun) -> list[AgentRerouted]:
    return [e for e in reroutes(run) if e.reason == "deadlock"]


def lane_for_one_between_full_hubs() -> Graph:
    """`h2` and `h3` hold one aircraft each and share a lane for one."""
    return build_graph(
        [start_hub("S"), end_hub("E"), hub("h2"),
         hub("h3", ZoneType.RESTRICTED)],
        [
            Link("h3", "h2"),
            Link("h3", "S"),
            Link("h2", "E"),
            Link("E", "h3"),
        ],
    )


def test_deadlock_after_reroutes_is_resolved_by_a_way_around() -> None:
    """Weather reroutes D2 into `h2` heading for `h3`, while D3 in `h3`
    heads for `h2`: they can never swap over a lane for one. The way around
    for D2, lane `h2-E`, is closed on turn 6, so the aircraft wait for the
    weather; on turn 7 it opens and D2 takes it."""
    weather = ScriptedWeather({
        1: {"E-h3": STORM}, 4: {"E-h3": CLEAR},
        6: {"h2-E": STORM}, 7: {"h2-E": CLEAR},
    })

    run = run_simulation(lane_for_one_between_full_hubs(), 3, weather)

    assert check_invariants(run) == []
    assert deadlock_reroutes(run) == [
        AgentRerouted(7, "D2", "h2", ("E",), "deadlock")
    ]


def road_budget_trap() -> Graph:
    """Roads around the air lane `h0-h2` are too long to drive after the
    road an aircraft has already driven."""
    return build_graph(
        [start_hub("S"), end_hub("E"), hub("h0"), hub("h1"), hub("h2")],
        [
            Link("h0", "S", capacity=3, distance=400, mode=ROAD),
            Link("h2", "h1", capacity=3, distance=250, mode=ROAD),
            Link("E", "h2", capacity=3, distance=300, mode=ROAD),
            Link("h0", "E", distance=450, mode=ROAD),
            Link("S", "h1", distance=400, mode=ROAD),
            Link("E", "h1"),
            Link("h0", "h2"),
        ],
    )


def test_deadlock_without_a_way_around_stops_the_run() -> None:
    """Snow closes D1's lane `E-h1`, so D1 reroutes through `h2` and `h0`
    while D2 waits in `h0` for `h2`. Each holds the hub the other needs, the
    lane between them holds one aircraft, and every way around breaks the
    700 km road budget, whatever the weather."""
    weather = ScriptedWeather({4: {"E-h1": WeatherCondition.SNOW}})

    with pytest.raises(DeadlockError) as error:
        run_simulation(road_budget_trap(), 2, weather)

    assert error.value.turn_number == 8
    assert error.value.aircraft == ("D1", "D2")
    assert error.value.hubs == ("h0", "h2")


def test_waiting_for_weather_is_not_a_deadlock() -> None:
    """D1 waits in `a` for its closed lane and D2 waits for `a`: a chain of
    waiting that ends at the weather, not a deadlock."""
    graph = build_graph(
        [start_hub(), hub("a"), end_hub()],
        [Link("start", "a"), Link("a", "goal", distance=450)],
    )
    weather = ScriptedWeather({2: {"a-goal": STORM}, 30: {"a-goal": CLEAR}})

    run = run_simulation(graph, 2, weather)

    assert check_invariants(run) == []
    assert deadlock_reroutes(run) == []
    assert run.turn_count > 30
