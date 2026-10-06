"""CLI text output for turns in which no aircraft moves (ADR-023).

Assignment-style output prints only turns with a movement. With
`--capacity-info`, every turn still has its own capacity block, matched by
turn number (BUG-005).
"""

from pathlib import Path
import re
import subprocess
import sys

from airlanes.mapfile import Parser

from tests.support.simulation import run_simulation

REPO_ROOT = Path(__file__).resolve().parents[2]
EUROPE_MAP = REPO_ROOT / "maps" / "bonus" / "europa_map.txt"

# A 900 km air leg takes 3 turns; on turn 2 the aircraft is in the air and
# nothing moves.
LONG_LEG_MAP = (
    "nb_drones: 1\n"
    "start_hub: start 0 0\n"
    "end_hub: goal 1 0\n"
    "connection: start-goal [distance=900km]\n"
)


def run_cli(*args: str) -> str:
    result = subprocess.run(
        [sys.executable, "main.py", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    return result.stdout


def write_long_leg_map(tmp_path: Path) -> str:
    map_file = tmp_path / "long_leg.txt"
    map_file.write_text(LONG_LEG_MAP)
    return str(map_file)


def test_text_output_skips_turns_without_movement(tmp_path: Path) -> None:
    stdout = run_cli(write_long_leg_map(tmp_path))

    assert stdout == "D1-start-goal\nD1-goal\n"


def test_capacity_info_follows_every_turn(tmp_path: Path) -> None:
    stdout = run_cli(write_long_leg_map(tmp_path), "--capacity-info")

    assert stdout == (
        "D1-start-goal\n"
        "Turn 1 capacity\n"
        "  zones: start=0/inf, goal=0/inf\n"
        "  links: start-goal=1/2\n"
        "Turn 2 capacity\n"
        "  zones: start=0/inf, goal=0/inf\n"
        "  links: start-goal=1/2\n"
        "D1-goal\n"
        "Turn 3 capacity\n"
        "  zones: start=0/inf, goal=1/inf\n"
        "  links: start-goal=1/2\n"
    )


def test_capacity_info_has_one_block_per_turn_in_order() -> None:
    """The Europe map has turns without movement; their blocks must not
    shift the blocks of later turns."""
    graph, nb_aircraft = Parser().parse(str(EUROPE_MAP))
    turn_count = run_simulation(graph, nb_aircraft).turn_count

    stdout = run_cli(str(EUROPE_MAP), "--capacity-info")

    headers = re.findall(r"^Turn (\d+) capacity$", stdout, re.MULTILINE)
    assert [int(number) for number in headers] == list(
        range(1, turn_count + 1)
    )
