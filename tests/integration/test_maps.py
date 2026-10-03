"""Bundled maps as reference scenarios for the whole simulation.

Each map must be delivered completely without breaking any invariant.
Turn counts are compared against the documented performance targets of the
original assignment, never against the current algorithm's exact result, so
better routing never breaks these tests. Routes are not asserted.
"""

import random
from collections.abc import Iterator
from pathlib import Path

import pytest

from parser import Parser
from tests.support.simulation import (
    SimulationRun,
    check_invariants,
    run_simulation,
)

MAPS_DIR = Path(__file__).resolve().parents[2] / "maps"
MAP_FILES = sorted(MAPS_DIR.glob("*/*.txt"))

# Documented targets ("Target <= N turns"). The challenger and bonus maps
# have no target and are only required to finish.
TURN_BUDGETS = {
    "easy/01_linear_path.txt": 6,
    "easy/02_simple_fork.txt": 6,
    "easy/03_basic_capacity.txt": 8,
    "medium/01_dead_end_trap.txt": 15,
    "medium/02_circular_loop.txt": 20,
    "medium/03_priority_puzzle.txt": 12,
    "hard/01_maze_nightmare.txt": 45,
    "hard/02_capacity_hell.txt": 60,
    "hard/03_ultimate_challenge.txt": 35,
}

WEATHER_MAPS = ["bonus/germany_map.txt", "bonus/europa_map.txt"]


def map_id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def simulate(relative_path: str, weather: bool = False) -> SimulationRun:
    graph, nb_aircraft = Parser().parse(str(MAPS_DIR / relative_path))
    return run_simulation(graph, nb_aircraft, weather=weather)


@pytest.fixture
def restore_global_random() -> Iterator[None]:
    saved_state = random.getstate()
    yield
    random.setstate(saved_state)


def test_maps_are_found() -> None:
    assert MAP_FILES


def test_every_budgeted_map_exists() -> None:
    assert set(TURN_BUDGETS) <= {map_id(path) for path in MAP_FILES}


@pytest.mark.parametrize("map_file", MAP_FILES, ids=map_id)
def test_map_is_delivered_without_violations(map_file: Path) -> None:
    run = simulate(map_id(map_file))

    assert check_invariants(run) == []


@pytest.mark.parametrize(
    ("relative_path", "budget"), sorted(TURN_BUDGETS.items())
)
def test_map_meets_its_turn_budget(relative_path: str, budget: int) -> None:
    run = simulate(relative_path)

    assert run.turn_count <= budget


@pytest.mark.parametrize("map_file", MAP_FILES, ids=map_id)
def test_simulation_without_weather_is_deterministic(map_file: Path) -> None:
    first = simulate(map_id(map_file))
    second = simulate(map_id(map_file))

    assert first.output == second.output


@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("relative_path", WEATHER_MAPS)
def test_weather_keeps_invariants(
    restore_global_random: None, relative_path: str, seed: int
) -> None:
    """Weather may delay or speed up flights but must not break any rule."""
    random.seed(seed)

    run = simulate(relative_path, weather=True)

    assert check_invariants(run) == []
