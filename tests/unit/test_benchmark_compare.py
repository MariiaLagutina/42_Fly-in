"""Comparison of two benchmark runs: gaps and behaviour changes are
problems, never silently ignored. No timing is asserted."""

import json
from pathlib import Path
import shutil
from typing import Any

import pytest

from benchmarks import compare, run

SMOKE = "smoke/tiny"


@pytest.fixture(scope="module")
def smoke_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("before")
    status = run.main(["--experiment", "smoke", "--repeats", "3",
                       "--out", str(out_dir)])
    assert status == 0
    return out_dir


def copy_run(source: Path, target: Path) -> Path:
    shutil.copytree(source, target)
    return target


def records(out_dir: Path) -> list[dict[str, Any]]:
    lines = (out_dir / "runs.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def rewrite(out_dir: Path, rows: list[dict[str, Any]]) -> None:
    (out_dir / "runs.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )


def environment(out_dir: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (out_dir / "environment.json").read_text()
    )
    return data


def set_environment(out_dir: Path, **changes: Any) -> None:
    data = environment(out_dir)
    data.update(changes)
    for key, value in changes.items():
        if value is None:
            del data[key]
    (out_dir / "environment.json").write_text(json.dumps(data))


def test_identical_runs_compare_cleanly(
    smoke_run: Path, tmp_path: Path
) -> None:
    after = copy_run(smoke_run, tmp_path / "after")

    assert compare.compare(smoke_run, after, partial=True) == []
    report = (after / "compare.md").read_text()
    assert "## Problems\n\nNone." in report
    assert SMOKE in report


def test_a_partial_run_needs_the_partial_flag(
    smoke_run: Path, tmp_path: Path
) -> None:
    after = copy_run(smoke_run, tmp_path / "after")

    problems = compare.compare(smoke_run, after, partial=False)

    assert "before: does not cover the whole matrix" in problems
    assert "after: does not cover the whole matrix" in problems


def test_a_changed_fingerprint_is_a_problem(
    smoke_run: Path, tmp_path: Path
) -> None:
    after = copy_run(smoke_run, tmp_path / "after")
    rows = records(after)
    for row in rows:
        if "fingerprint" in row:
            row["fingerprint"] = "changed"
    rewrite(after, rows)

    assert compare.compare(smoke_run, after, partial=True) == [
        f"{SMOKE}: outcome fingerprints differ"
    ]


def test_a_changed_events_field_is_a_problem(
    smoke_run: Path, tmp_path: Path
) -> None:
    after = copy_run(smoke_run, tmp_path / "after")
    rows = records(after)
    for row in rows:
        if row["mode"] == "events":
            row["departures"] += 1
    rewrite(after, rows)

    assert compare.compare(smoke_run, after, partial=True) == [
        f"{SMOKE}: events fields differ: departures"
    ]


def test_missing_data_is_a_problem(smoke_run: Path, tmp_path: Path) -> None:
    after = copy_run(smoke_run, tmp_path / "after")
    rows = [row for row in records(after)
            if row["mode"] not in ("phases", "profile")
            and (row["mode"], row["repeat"]) != ("plain", 1)]
    for row in rows:
        if (row["mode"], row["repeat"]) == ("plain", 2):
            del row["plan_ns"]
    rewrite(after, rows)

    problems = compare.compare(smoke_run, after, partial=True)

    assert f"after: {SMOKE} has 2 plain repeats, needs 3" in problems
    assert f"after: {SMOKE} plain repeat 2 lacks plan_ns" in problems
    assert f"after: {SMOKE} has no phases execution" in problems
    assert f"after: {SMOKE} has no profile execution" in problems


def test_a_missing_scenario_is_a_problem(
    smoke_run: Path, tmp_path: Path
) -> None:
    after = copy_run(smoke_run, tmp_path / "after")
    rewrite(after, [])

    problems = compare.compare(smoke_run, after, partial=True)

    assert f"after: {SMOKE} has no records" in problems
    assert f"scenario sets differ: {SMOKE}" in problems


def test_an_unexpected_status_or_timeout_is_a_problem(
    smoke_run: Path, tmp_path: Path
) -> None:
    after = copy_run(smoke_run, tmp_path / "after")
    rows = records(after)
    for row in rows:
        row["status"] = "deadlock"
    rows[-1]["status"] = "timeout"
    rewrite(after, rows)

    problems = compare.compare(smoke_run, after, partial=True)

    assert f"after: {SMOKE}: expected ok, got deadlock" in problems
    assert any("ended in timeout" in p for p in problems)


def test_an_unfinished_run_or_other_configuration_is_a_problem(
    smoke_run: Path, tmp_path: Path
) -> None:
    after = copy_run(smoke_run, tmp_path / "after")
    set_environment(after, elapsed_s=None, pinned_cpu=5,
                    cpu_governor="performance")

    problems = compare.compare(smoke_run, after, partial=True)

    assert "after: the run did not finish" in problems
    assert "configuration differs: pinned_cpu None -> 5" in problems
    report = (after / "compare.md").read_text()
    assert "cpu_governor: " in report


def test_the_command_exits_with_one_on_a_problem(
    smoke_run: Path, tmp_path: Path
) -> None:
    after = copy_run(smoke_run, tmp_path / "after")
    assert compare.main([str(smoke_run), str(after), "--partial"]) == 0
    rewrite(after, [])
    assert compare.main([str(smoke_run), str(after), "--partial"]) == 1
