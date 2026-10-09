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
from benchmarks.measure import ENGINE_FUNCTIONS, MODES, Job, execute

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
