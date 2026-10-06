"""End-to-end smoke test: the CLI runs a simple map to completion."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAP_FILE = REPO_ROOT / "maps" / "easy" / "01_linear_path.txt"

# The linear map has exactly one route, so the full output is the only
# correct answer and can be compared verbatim.
EXPECTED_STDOUT = (
    "D1-waypoint1\n"
    "D1-waypoint2 D2-waypoint1\n"
    "D1-goal D2-waypoint2\n"
    "D2-goal\n"
)


def test_linear_map_runs_to_completion() -> None:
    result = subprocess.run(
        [sys.executable, "main.py", str(MAP_FILE)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == EXPECTED_STDOUT


def test_package_entry_point_runs_the_same_cli() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "airlanes", str(MAP_FILE)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == EXPECTED_STDOUT
