"""Run the performance benchmark.

    uv run --locked python -m benchmarks.run [options]

Every scenario runs in its own process, which is killed when an execution
exceeds the timeout. Per scenario: one warm-up, then the timed repeats of
`plain` and `phases`, one `events` run and, for selected scenarios, one
`profile` run. Raw records go to `runs.jsonl` in the output directory,
with the environment in `environment.json` and profiles in `profile/`.
"""

import argparse
from collections.abc import Sequence
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
from typing import Any, TextIO

from benchmarks.isolation import ExecutionTimeout, IsolatedWorker, WorkerFailed
from benchmarks.measure import MODES, Job, Record, execute
from benchmarks.scenarios import REPO_ROOT, Scenario, all_scenarios

RESULTS_DIR = REPO_ROOT / "benchmarks" / "results"
TIMEOUT_S = 120.0
# Scenarios faster than this get more repeats.
FAST_LIMIT_NS = 1_000_000_000
FAST_REPEATS = 7
SLOW_REPEATS = 3


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    scenarios = _select(args)
    if args.list:
        for scenario in scenarios:
            print(scenario.scenario_id)
        return 0

    # Children inherit the environment: fix string hashing for every run.
    os.environ["PYTHONHASHSEED"] = args.hash_seed
    out_dir = Path(args.out) if args.out else _default_out_dir()
    (out_dir / "profile").mkdir(parents=True, exist_ok=True)
    environment = _environment(args, scenarios)
    _write_json(out_dir / "environment.json", environment)

    started = time.perf_counter()
    mismatches: list[str] = []
    errors: list[str] = []
    with open(out_dir / "runs.jsonl", "w", encoding="utf-8") as runs:
        for number, scenario in enumerate(scenarios, start=1):
            records = _run_scenario(scenario, args, runs, out_dir)
            prints = {r["fingerprint"] for r in records if "fingerprint" in r}
            if len(prints) > 1:
                mismatches.append(scenario.scenario_id)
            errors += [
                scenario.scenario_id
                for r in records if r["status"] == "error"
            ]
            print(
                f"[{number}/{len(scenarios)}] {_progress(scenario, records)}",
                flush=True,
            )

    environment["elapsed_s"] = round(time.perf_counter() - started, 1)
    _write_json(out_dir / "environment.json", environment)
    print(f"Results: {out_dir}")
    print(f"Elapsed: {environment['elapsed_s']} s")
    if mismatches:
        print("Fingerprints differ between executions: "
              + ", ".join(mismatches))
    if errors:
        print("Executions failed: " + ", ".join(sorted(set(errors))))
    return 1 if mismatches or errors else 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks.run",
        description="Measure parsing, planning and simulation time.",
    )
    parser.add_argument(
        "--experiment", action="append", default=[],
        help="Run one experiment (E1 to E5, or smoke); repeatable.",
    )
    parser.add_argument(
        "--scenario", action="append", default=[],
        help="Run one scenario by id; repeatable.",
    )
    parser.add_argument("--list", action="store_true",
                        help="List the selected scenarios and stop.")
    parser.add_argument("--out", help="Output directory.")
    parser.add_argument("--timeout", type=float, default=TIMEOUT_S,
                        help="Seconds allowed per execution.")
    parser.add_argument("--repeats", type=int,
                        help="Timed repeats per mode, instead of 7 or 3.")
    parser.add_argument("--no-warmup", action="store_true",
                        help="Skip the warm-up execution.")
    parser.add_argument(
        "--modes", default=",".join(MODES),
        help="Comma-separated modes (default: all).",
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Pilot run: one repeat, no warm-up, plain and events only. "
             "Its numbers are not results.",
    )
    parser.add_argument("--cpu", type=int,
                        help="Pin the benchmark processes to one CPU.")
    parser.add_argument("--hash-seed", default="0",
                        help="PYTHONHASHSEED of the benchmark processes.")
    args = parser.parse_args(argv)
    if args.quick:
        args.repeats = 1
        args.no_warmup = True
        args.modes = "plain,events"
    args.modes = [mode for mode in args.modes.split(",") if mode]
    unknown = sorted(set(args.modes) - set(MODES))
    if unknown:
        parser.error(f"unknown mode: {', '.join(unknown)}")
    return args


def _select(args: argparse.Namespace) -> list[Scenario]:
    scenarios = all_scenarios()
    if args.scenario:
        chosen = [s for s in scenarios if s.scenario_id in args.scenario]
        missing = set(args.scenario) - {s.scenario_id for s in chosen}
        if missing:
            raise SystemExit(f"Unknown scenario: {', '.join(sorted(missing))}")
        return chosen
    if args.experiment:
        return [s for s in scenarios if s.experiment in args.experiment]
    return [s for s in scenarios if s.experiment != "smoke"]


def _run_scenario(
    scenario: Scenario,
    args: argparse.Namespace,
    runs: TextIO,
    out_dir: Path,
) -> list[Record]:
    """All executions of one scenario, in one worker process. A timeout
    ends the scenario: its other executions would time out as well."""
    records: list[Record] = []

    def run(mode: str, repeat: int) -> Record:
        try:
            record = worker.call(execute, Job(scenario.scenario_id, mode,
                                              repeat))
        except ExecutionTimeout as exc:
            record = _failure(scenario, mode, repeat, "timeout", str(exc))
        except WorkerFailed as exc:
            record = _failure(scenario, mode, repeat, "error", str(exc))
        profile_text = record.pop("profile_text", None)
        if profile_text is not None:
            name = re.sub(r"[^A-Za-z0-9_.-]+", "_", scenario.scenario_id)
            (out_dir / "profile" / f"{name}.txt").write_text(
                profile_text, encoding="utf-8"
            )
        runs.write(json.dumps(record, sort_keys=True) + "\n")
        runs.flush()
        records.append(record)
        return record

    with IsolatedWorker(args.timeout, args.cpu) as worker:
        repeats = args.repeats
        timed = [m for m in ("plain", "phases") if m in args.modes]
        if timed and not args.no_warmup:
            warmup = run(timed[0], -1)
            if warmup["status"] in ("timeout", "error"):
                return records
            if repeats is None:
                spent = warmup["parse_ns"] + warmup["run_ns"]
                repeats = (
                    FAST_REPEATS if spent < FAST_LIMIT_NS else SLOW_REPEATS
                )
        for mode in timed:
            for repeat in range(repeats or SLOW_REPEATS):
                if run(mode, repeat)["status"] in ("timeout", "error"):
                    return records
        if "events" in args.modes:
            if run("events", 0)["status"] in ("timeout", "error"):
                return records
        if "profile" in args.modes and scenario.profile:
            run("profile", 0)
    return records


def _failure(
    scenario: Scenario, mode: str, repeat: int, status: str, error: str
) -> Record:
    return {
        "scenario_id": scenario.scenario_id,
        "experiment": scenario.experiment,
        "mode": mode,
        "repeat": repeat,
        "warmup": repeat < 0,
        "params": scenario.params,
        "weather": scenario.weather.label,
        "expected": scenario.expected,
        "status": status,
        "error": error,
    }


def _progress(scenario: Scenario, records: list[Record]) -> str:
    plain = [r for r in records if r["mode"] == "plain" and not r["warmup"]
             and "run_ns" in r]
    statuses = sorted({r["status"] for r in records})
    text = f"{scenario.scenario_id}: {'/'.join(statuses)}"
    if plain:
        runs = sorted(r["run_ns"] for r in plain)
        text += (f", run median {runs[len(runs) // 2] / 1e6:.1f} ms"
                 f" over {len(runs)} repeats")
    return text


def _default_out_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return RESULTS_DIR / f"{stamp}-{_git('rev-parse', '--short', 'HEAD')}"


def _git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _cpu_model() -> str | None:
    info = _read("/proc/cpuinfo") or ""
    for line in info.splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return platform.processor() or None


def _environment(
    args: argparse.Namespace, scenarios: list[Scenario]
) -> dict[str, Any]:
    return {
        "started_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "commit": _git("rev-parse", "HEAD"),
        "uncommitted_changes": bool(
            _git("status", "--porcelain", "--", "airlanes", "benchmarks",
                 "maps")
        ),
        "python": sys.version,
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "cpu": _cpu_model(),
        "cpu_count": os.cpu_count(),
        "cpu_governor": _read(
            "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
        ),
        "intel_no_turbo": _read(
            "/sys/devices/system/cpu/intel_pstate/no_turbo"
        ),
        "pinned_cpu": args.cpu,
        "hash_seed": args.hash_seed,
        "timeout_s": args.timeout,
        "repeats": args.repeats or f"{FAST_REPEATS} if under "
        f"{FAST_LIMIT_NS / 1e9:g} s, else {SLOW_REPEATS}",
        "warmup": not args.no_warmup,
        "modes": args.modes,
        "quick": args.quick,
        "argv": sys.argv[1:],
        "scenarios": [scenario.scenario_id for scenario in scenarios],
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
