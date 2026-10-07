"""Exit status and error reporting of the command line (BUG-006).

A run exits with 0 on success and 1 when the map cannot be used or the
simulation fails; the error goes to stderr. Most cases call `main()` in
process; the subprocess tests check that both entry points pass the status
on to the shell.
"""

from pathlib import Path
import subprocess
import sys

import pytest

from airlanes.cli import EXIT_ERROR, EXIT_OK, main

REPO_ROOT = Path(__file__).resolve().parents[2]
LINEAR_MAP = REPO_ROOT / "maps" / "easy" / "01_linear_path.txt"

# `a` is not connected to the goal, so there is no route.
NO_ROUTE_MAP = (
    "nb_drones: 1\n"
    "start_hub: start 0 0\n"
    "end_hub: goal 1 0\n"
    "hub: a 2 0\n"
    "connection: start-a\n"
)


def run_main(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["main.py", *args])
    return main()


def write(tmp_path: Path, text: str) -> str:
    map_file = tmp_path / "map.txt"
    map_file.write_text(text)
    return str(map_file)


def test_a_successful_run_exits_with_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_main(monkeypatch, str(LINEAR_MAP)) == EXIT_OK
    assert capsys.readouterr().err == ""


def test_a_missing_map_file_exits_with_an_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    missing = str(tmp_path / "missing.txt")

    assert run_main(monkeypatch, missing) == EXIT_ERROR
    assert capsys.readouterr().err == f"File not found: {missing}\n"


def test_a_directory_is_reported_as_an_unreadable_map(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """A directory used to end in an `IsADirectoryError` traceback
    (BUG-007)."""
    assert run_main(monkeypatch, str(tmp_path)) == EXIT_ERROR
    # The reason after the path is the operating system's message.
    error = capsys.readouterr().err
    assert error.startswith(f"Cannot read map file: {tmp_path}: ")
    assert error.count("\n") == 1


def test_an_invalid_map_exits_with_an_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    map_file = write(tmp_path, "nb_drones: 0\n")

    assert run_main(monkeypatch, map_file) == EXIT_ERROR
    assert capsys.readouterr().err == (
        "Error parsing input file: "
        "Line 1: nb_drones must be positive integer.\n"
    )


def test_a_map_that_is_not_utf8_exits_with_a_parse_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Invalid UTF-8 used to end in a `UnicodeDecodeError` traceback
    (BUG-013)."""
    map_file = tmp_path / "map.txt"
    map_file.write_bytes(b"nb_drones: 1\nstart_hub: caf\xe9 0 0\n")

    assert run_main(monkeypatch, str(map_file)) == EXIT_ERROR
    assert capsys.readouterr().err == (
        "Error parsing input file: Line 2: Map file is not valid UTF-8.\n"
    )


def test_a_failed_simulation_exits_with_an_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """No route is one of the simulation errors the command line reports;
    `DeadlockError` and the turn limit take the same path."""
    map_file = write(tmp_path, NO_ROUTE_MAP)

    assert run_main(monkeypatch, map_file) == EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "Error: No valid route found between start and end zones.\n"
    )


@pytest.mark.parametrize(
    "entry_point",
    [
        pytest.param(["main.py"], id="main.py"),
        pytest.param(["-m", "airlanes"], id="python-m-airlanes"),
    ],
)
def test_entry_points_pass_the_exit_status_on(
    entry_point: list[str], tmp_path: Path
) -> None:
    result = subprocess.run(
        [sys.executable, *entry_point, write(tmp_path, NO_ROUTE_MAP)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == EXIT_ERROR
    assert result.stdout == ""
    assert result.stderr == (
        "Error: No valid route found between start and end zones.\n"
    )
