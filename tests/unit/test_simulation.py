"""Simulation on small synthetic graphs.

Every run is checked against the full invariant set in
`tests.support.simulation`. Scenarios add one targeted assertion each.
Exact turn counts are asserted only where the rules define them: a single
aircraft on a single route, where restricted hubs and the documented
distance travel-time formula leave no room for another valid answer.
"""

import pytest

from events import AgentInTransit, AgentRerouted, WeatherChanged
from graph import Graph
from tests.support.graphs import Link, build_graph, end_hub, hub, start_hub
from tests.support.simulation import (
    check_invariants,
    peak_hub_occupancy,
    SimulationRun,
    run_simulation,
)
from transport import TransportMode
from weather import ScriptedWeather, WeatherCondition
from zone import ZoneType

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
# so these runs are deterministic. Weather penalties are provisional
# (DECISION-001) and are asserted only as "slower".


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
    graph = build_graph(
        [start_hub(), end_hub()],
        [Link("start", "goal", distance=150, mode=ROAD)],
    )
    weather = ScriptedWeather({1: {"start-goal": WeatherCondition.STORM}})

    run = run_simulation(graph, 1, weather)

    assert check_invariants(run) == []
    assert departure_turns(run) == [1]
    assert run.turn_count > 2


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


# --- Dynamic replanning (ADR-018) -------------------------------------------
# An aircraft at a hub keeps its route while it is usable, reroutes when the
# weather makes it unusable, and waits when no route is available. Weather
# comes from `ScriptedWeather`. Routes are asserted only where a single
# alternative exists.

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
    assert reroutes(run) == [AgentRerouted(1, "D1", "start", ("b", "goal"))]
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
    assert reroutes(run) == [AgentRerouted(1, "D1", "start", ("b", "goal"))]


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
    the planned route is still usable, so the aircraft keeps it."""
    graph = two_air_routes(via_a=1200, via_b=1600)
    weather = ScriptedWeather({1: {
        "start-b": WeatherCondition.TAILWIND,
        "b-goal": WeatherCondition.TAILWIND,
    }})

    run = run_simulation(graph, 1, weather)

    assert check_invariants(run) == []
    assert reroutes(run) == []
    assert run.visited_zones("D1") == ["a", "goal"]


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
    assert reroutes(run) == [AgentRerouted(1, "D1", "start", ("r", "goal"))]


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
    assert reroutes(run) == [AgentRerouted(1, "D1", "x", ("y", "goal"))]


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
