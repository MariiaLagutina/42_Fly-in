"""The performance benchmark itself: correctness and output structure.

These tests never check how fast anything runs. They check that every
measuring mode sees the same simulation outcome, that instrumentation
leaves the engine as it found it, that phase timings nest without double
counting, and that the timeout really stops a call.
"""

import json
from pathlib import Path
import time

import pytest

import airlanes.simulation.engine as engine
from airlanes.simulation.engine import Simulator
from benchmarks import run
from benchmarks.isolation import ExecutionTimeout, IsolatedWorker, WorkerFailed
from benchmarks.measure import ENGINE_FUNCTIONS, MODES, Job, Record, execute
from benchmarks.scenarios import scenario_by_id

SMOKE = "smoke/tiny"
COMMON_KEYS = {
    "scenario_id", "experiment", "mode", "repeat", "warmup", "params",
    "weather", "expected", "status", "error", "fingerprint", "turns",
    "hubs", "lanes", "aircraft", "parse_ns",
}
TIMED_KEYS = {
    "setup_ns", "run_ns", "plan_ns", "turns_ns", "interrupted_turn_ns",
    "loop_other_ns", "turn_ns_p50", "turn_ns_p90", "turn_ns_max",
}


def test_every_mode_sees_the_same_outcome() -> None:
    records = {mode: execute(Job(SMOKE, mode, 0)) for mode in MODES}

    assert {r["status"] for r in records.values()} == {"ok"}
    assert len({r["fingerprint"] for r in records.values()}) == 1
    for record in records.values():
        assert COMMON_KEYS <= record.keys()
    assert TIMED_KEYS <= records["plain"].keys()
    assert TIMED_KEYS | {"phases"} <= records["phases"].keys()
    assert {"profile_top", "profile_text"} <= records["profile"].keys()
    assert {"departures", "waiting_aircraft_turns", "planned_makespan"} <= (
        records["events"].keys()
    )


def test_repeats_see_the_same_weather() -> None:
    """The smoke scenario has random weather; each execution creates its
    weather anew from the same seed."""
    first = execute(Job(SMOKE, "plain", 0))
    second = execute(Job(SMOKE, "plain", 1))

    assert first["fingerprint"] == second["fingerprint"]


def test_phase_timing_leaves_the_engine_unchanged() -> None:
    functions = {name: getattr(engine, name) for name in ENGINE_FUNCTIONS}
    methods = dict(vars(Simulator))

    execute(Job(SMOKE, "phases", 0))

    assert {name: getattr(engine, name) for name in ENGINE_FUNCTIONS} == (
        functions
    )
    assert dict(vars(Simulator)) == methods


def test_phase_timings_nest_without_double_counting() -> None:
    record = execute(Job(SMOKE, "phases", 0))
    phases = record["phases"]

    for parent in ("plan", "turn"):
        children = [
            timing["ns"]
            for path, timing in phases.items()
            if path.startswith(f"{parent}/") and path.count("/") == 1
        ]
        assert children
        assert sum(children) <= phases[parent]["ns"]
    assert phases["turn"]["calls"] == record["turns"]
    assert record["run_ns"] == (
        record["plan_ns"] + record["turns_ns"]
        + record["interrupted_turn_ns"] + record["loop_other_ns"]
    )


@pytest.mark.parametrize(
    ("scenario_id", "status"),
    [("E5/disconnected", "no_route"), ("E5/deadlock", "deadlock")],
)
def test_failed_runs_keep_their_status(scenario_id: str, status: str) -> None:
    plain = execute(Job(scenario_id, "plain", 0))
    events = execute(Job(scenario_id, "events", 0))

    assert plain["status"] == events["status"] == status
    assert plain["expected"] == status
    assert plain["fingerprint"] == events["fingerprint"]


@pytest.mark.parametrize("scenario_id", ["E5/restricted", "E5/weather-waves"])
def test_stress_scenarios_exercise_their_mechanism(scenario_id: str) -> None:
    record = execute(Job(scenario_id, "events", 0))

    assert record["status"] == "ok"
    assert record["mechanism_ok"] is True


def test_a_call_that_runs_too_long_is_killed() -> None:
    with IsolatedWorker(timeout=0.5) as worker:
        start = time.monotonic()
        with pytest.raises(ExecutionTimeout):
            worker.call(time.sleep, 30)
        assert time.monotonic() - start < 10
        # The next call starts a new process.
        assert worker.call(abs, -3) == 3


def test_an_error_in_the_worker_is_reported() -> None:
    with IsolatedWorker(timeout=30) as worker:
        with pytest.raises(WorkerFailed, match="ValueError"):
            worker.call(int, "not a number")


def test_the_runner_writes_raw_records(tmp_path: Path) -> None:
    status = run.main(
        ["--experiment", "smoke", "--repeats", "1", "--out", str(tmp_path)]
    )

    assert status == 0
    environment = json.loads((tmp_path / "environment.json").read_text())
    assert {"commit", "python", "cpu", "hash_seed", "elapsed_s"} <= (
        environment.keys()
    )
    records = [
        json.loads(line)
        for line in (tmp_path / "runs.jsonl").read_text().splitlines()
    ]
    assert [(r["mode"], r["repeat"]) for r in records] == [
        ("plain", -1), ("plain", 0), ("phases", 0), ("events", 0),
        ("profile", 0),
    ]
    assert all("profile_text" not in r for r in records)
    assert (tmp_path / "profile" / "smoke_tiny.txt").exists()
    summary = (tmp_path / "summary.md").read_text()
    assert "Scenarios whose outcome fingerprints differ: none." in summary
    rows = (tmp_path / "summary.csv").read_text().splitlines()
    assert rows[0].startswith("scenario_id,experiment,")
    assert rows[1].startswith("smoke/tiny,smoke,ok,ok,")


def outcome(status: str, fingerprint: str = "f1", repeat: int = 0) -> Record:
    record: Record = {"mode": "plain", "repeat": repeat, "status": status}
    if status not in ("timeout", "error"):
        record["fingerprint"] = fingerprint
    return record


def test_a_scenario_ending_as_built_is_no_problem() -> None:
    """Missing routes and deadlocks are successful cases when the scenario
    is built for them."""
    for scenario_id, status in (
        (SMOKE, "ok"),
        ("E5/disconnected", "no_route"),
        ("E5/deadlock", "deadlock"),
    ):
        scenario = scenario_by_id(scenario_id)
        records = [outcome(status, repeat=r) for r in (-1, 0, 1)]
        assert run.scenario_problems(scenario, records) == []


def test_an_unexpected_status_is_a_problem_even_when_consistent() -> None:
    records = [outcome("deadlock", repeat=r) for r in (-1, 0, 1)]

    assert run.scenario_problems(scenario_by_id(SMOKE), records) == [
        "smoke/tiny: expected ok, got deadlock"
    ]


def test_an_expected_failure_that_does_not_happen_is_a_problem() -> None:
    problems = run.scenario_problems(
        scenario_by_id("E5/deadlock"), [outcome("ok")]
    )

    assert problems == ["E5/deadlock: expected deadlock, got ok"]


@pytest.mark.parametrize("status", ["timeout", "error"])
def test_a_timeout_or_error_is_a_problem(status: str) -> None:
    records = [outcome("ok", repeat=-1), outcome(status)]

    assert run.scenario_problems(scenario_by_id(SMOKE), records) == [
        f"smoke/tiny: plain execution 0 ended in {status}"
    ]


def test_differing_fingerprints_are_a_problem() -> None:
    records = [outcome("ok", "f1"), outcome("ok", "f2", repeat=1)]

    assert run.scenario_problems(scenario_by_id(SMOKE), records) == [
        "smoke/tiny: outcome fingerprints differ"
    ]


def test_the_runner_fails_when_an_execution_times_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No execution can start a process and answer within a millisecond:
    the first one times out, the scenario stops, and the run fails."""
    status = run.main([
        "--scenario", SMOKE, "--timeout", "0.001", "--out", str(tmp_path),
    ])

    assert status == 1
    records = [
        json.loads(line)
        for line in (tmp_path / "runs.jsonl").read_text().splitlines()
    ]
    assert [(r["mode"], r["status"]) for r in records] == [
        ("plain", "timeout")
    ]
    assert "Problem: smoke/tiny: plain execution -1 ended in timeout" in (
        capsys.readouterr().out
    )


def test_the_runner_accepts_an_expected_deadlock(tmp_path: Path) -> None:
    status = run.main([
        "--scenario", "E5/deadlock", "--repeats", "1", "--out", str(tmp_path),
    ])

    assert status == 0
