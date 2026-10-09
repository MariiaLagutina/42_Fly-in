"""Capacity snapshots: committed hub load and lane usage (ADR-026).

A hub's load is the aircraft in it plus the aircraft flying towards it,
immediately after the turn: the load departures are admitted against
(ADR-008). A lane's usage is what lane admission counted during the turn,
including aircraft that finished their leg in it (ADR-019). Start and end
hubs have no capacity limit and are not reported.
"""

from dataclasses import fields
from pathlib import Path

import pytest

from airlanes.events import CapacitySnapshot, EventDispatcher
from airlanes.mapfile import Parser
from airlanes.model.drone import DroneState
from airlanes.model.graph import Graph
from airlanes.simulation.engine import Simulator
from airlanes.world.weather import (
    RandomWeather,
    ScriptedWeather,
    WeatherCondition,
)

from tests.support.simulation import (
    EventRecorder,
    committed_hub_load_by_turn,
    run_simulation,
)

MAPS_DIR = Path(__file__).resolve().parents[2] / "maps"
MAP_FILES = sorted(MAPS_DIR.glob("*/*.txt"))

# A 900 km air leg into `b` takes 3 turns; `b` holds one aircraft, and the
# leg from `b` to the goal takes one turn.
ONE_SLOT_HUB = (
    "start_hub: start 0 0\n"
    "hub: b 1 0 [max_drones=1]\n"
    "end_hub: goal 2 0\n"
    "connection: start-b [distance=900km max_link_capacity=2]\n"
    "connection: b-goal\n"
)

# `b` holds three aircraft; `b-goal` is the only way on.
THREE_SLOT_HUB = (
    "nb_drones: 5\n"
    "start_hub: start 0 0\n"
    "hub: b 1 0 [max_drones=3]\n"
    "end_hub: goal 2 0\n"
    "connection: start-b\n"
    "connection: b-goal\n"
)


def parse(tmp_path: Path, text: str) -> tuple[Graph, int]:
    path = tmp_path / "map.txt"
    path.write_text(text)
    return Parser().parse(str(path))


def snapshots(
    graph: Graph,
    nb_aircraft: int,
    weather: ScriptedWeather | None = None,
) -> dict[int, CapacitySnapshot]:
    run = run_simulation(graph, nb_aircraft, weather)
    return {
        event.turn_number: event
        for event in run.events
        if isinstance(event, CapacitySnapshot)
    }


def hub_load(snapshot: CapacitySnapshot) -> dict[str, tuple[int, int]]:
    return {name: (load, cap) for name, load, cap in snapshot.hub_load}


def lane_usage(snapshot: CapacitySnapshot) -> dict[str, tuple[int, int]]:
    return {
        name: (used, cap) for name, used, cap in snapshot.connection_usage
    }


def test_an_aircraft_flying_to_a_hub_holds_its_slot(tmp_path: Path) -> None:
    """Turns 1 and 2: nobody is in `b`, but the aircraft flying to it holds
    the only slot. Turn 4: its departure releases the slot."""
    by_turn = snapshots(*parse(tmp_path, "nb_drones: 1\n" + ONE_SLOT_HUB))

    assert [hub_load(by_turn[turn])["b"] for turn in (1, 2, 3, 4)] == [
        (1, 1), (1, 1), (1, 1), (0, 1),
    ]


def test_a_released_slot_is_taken_by_an_aircraft_admitted_towards_it(
    tmp_path: Path,
) -> None:
    """Turn 4: D1 leaves `b` for the goal and D2 departs towards `b`. The
    hub is empty, but its slot is committed again."""
    graph, nb_aircraft = parse(tmp_path, "nb_drones: 2\n" + ONE_SLOT_HUB)
    run = run_simulation(graph, nb_aircraft)
    by_turn = {
        event.turn_number: event
        for event in run.events
        if isinstance(event, CapacitySnapshot)
    }

    assert run.visited_zones("D1") == ["b", "goal"]
    assert hub_load(by_turn[4])["b"] == (1, 1)
    assert [hub_load(by_turn[turn])["b"] for turn in (5, 6, 7)] == [
        (1, 1), (1, 1), (0, 1),
    ]


def test_a_waiting_aircraft_keeps_its_slot(tmp_path: Path) -> None:
    """A storm closes `b-goal` while the aircraft waits in `b`: the slot
    stays committed, since no departure frees it."""
    weather = ScriptedWeather({
        3: {"b-goal": WeatherCondition.STORM},
        6: {"b-goal": WeatherCondition.CLEAR},
    })
    by_turn = snapshots(
        *parse(tmp_path, "nb_drones: 1\n" + ONE_SLOT_HUB), weather
    )

    assert [hub_load(by_turn[turn])["b"] for turn in (3, 4, 5, 6)] == [
        (1, 1), (1, 1), (1, 1), (0, 1),
    ]


def test_committed_load_counts_aircraft_in_and_towards_a_hub(
    tmp_path: Path,
) -> None:
    """Two aircraft in `b` and one flying to it fill its three slots; after
    an exchange, so do one in `b` and two flying to it."""
    graph, nb_aircraft = parse(tmp_path, THREE_SLOT_HUB)
    recorder = EventRecorder()
    dispatcher = EventDispatcher()
    dispatcher.add_listener(recorder)
    simulator = Simulator(graph, nb_aircraft, dispatcher)
    b = graph.get_zone("b")
    assert b is not None

    def in_hub(drone_index: int, hub_name: str) -> None:
        zone = graph.get_zone(hub_name)
        assert zone is not None
        drone = simulator.drones[drone_index]
        drone.current_zone = zone
        drone.state = (
            DroneState.DELIVERED if zone.is_end else DroneState.WAITING
        )

    def flying_to_b(drone_index: int) -> None:
        drone = simulator.drones[drone_index]
        drone.state = DroneState.IN_TRANSIT
        drone.transit_target = b
        drone.transit_connection_name = "start-b"
        drone.transit_turns_left = 1

    in_hub(0, "b")
    in_hub(1, "b")
    flying_to_b(2)
    simulator._emit_capacity_snapshot(1, {})

    in_hub(0, "goal")
    in_hub(1, "goal")
    in_hub(2, "b")
    simulator._emit_capacity_snapshot(2, {})

    flying_to_b(3)
    flying_to_b(4)
    simulator._emit_capacity_snapshot(3, {})

    loads = [
        hub_load(event)["b"]
        for event in recorder.events
        if isinstance(event, CapacitySnapshot)
    ]
    assert loads == [(3, 3), (1, 3), (3, 3)]


def test_start_and_end_hubs_are_not_reported(tmp_path: Path) -> None:
    by_turn = snapshots(*parse(tmp_path, "nb_drones: 2\n" + ONE_SLOT_HUB))

    assert all(
        [name for name, _load, _cap in snapshot.hub_load] == ["b"]
        for snapshot in by_turn.values()
    )


def test_snapshot_lists_capacity_hubs_and_every_lane_in_map_order(
    tmp_path: Path,
) -> None:
    graph, nb_aircraft = parse(
        tmp_path,
        "nb_drones: 1\n"
        "start_hub: start 0 0\n"
        "hub: z 1 0 [max_drones=2]\n"
        "end_hub: goal 3 0\n"
        "hub: a 2 0 [population=400000]\n"
        "connection: start-z\n"
        "connection: z-a\n"
        "connection: a-goal [max_link_capacity=3]\n",
    )
    snapshot = snapshots(graph, nb_aircraft)[1]

    assert [field.name for field in fields(CapacitySnapshot)] == [
        "turn_number", "hub_load", "connection_usage",
    ]
    assert [(name, cap) for name, _load, cap in snapshot.hub_load] == [
        ("z", 2), ("a", 4),
    ]
    assert all(type(cap) is int for _name, _load, cap in snapshot.hub_load)
    assert [(name, cap) for name, _used, cap in snapshot.connection_usage] == [
        ("start-z", 1), ("z-a", 1), ("a-goal", 3),
    ]


def test_lane_usage_counts_the_turn_in_which_a_leg_finishes(
    tmp_path: Path,
) -> None:
    """The multi-turn leg still uses `start-b` on turn 3, when it arrives;
    the one-turn leg uses `b-goal` on turn 4, when it starts and arrives."""
    by_turn = snapshots(*parse(tmp_path, "nb_drones: 1\n" + ONE_SLOT_HUB))

    assert [lane_usage(by_turn[turn]) for turn in (1, 2, 3, 4)] == [
        {"start-b": (1, 2), "b-goal": (0, 1)},
        {"start-b": (1, 2), "b-goal": (0, 1)},
        {"start-b": (1, 2), "b-goal": (0, 1)},
        {"start-b": (0, 2), "b-goal": (1, 1)},
    ]


@pytest.mark.parametrize("seed", [None, 0, 1])
@pytest.mark.parametrize(
    "map_file", MAP_FILES, ids=[path.stem for path in MAP_FILES]
)
def test_hub_load_matches_the_load_rebuilt_from_events(
    map_file: Path, seed: int | None
) -> None:
    """The snapshot agrees with the committed load rebuilt from movement
    events alone, and never exceeds a hub's capacity (ADR-004)."""
    graph, nb_aircraft = Parser().parse(str(map_file))
    weather = RandomWeather(graph, seed=seed) if seed is not None else None
    run = run_simulation(graph, nb_aircraft, weather)
    rebuilt = committed_hub_load_by_turn(run)

    snapshots_seen = 0
    for event in run.events:
        if not isinstance(event, CapacitySnapshot):
            continue
        snapshots_seen += 1
        expected = rebuilt[event.turn_number]
        for name, load, capacity in event.hub_load:
            assert load == expected.get(name, 0), (event.turn_number, name)
            assert load <= capacity, (event.turn_number, name)
    assert snapshots_seen == run.turn_count
