"""Compare two benchmark runs: behaviour first, then time.

    uv run --locked python -m benchmarks.compare BEFORE AFTER [--partial]

The runs must be comparable and complete. The same scenarios (the whole
matrix unless `--partial`), the same configuration, every scenario with
its expected status and no timeout or error, every required measurement
present, and the same behaviour. Every successful execution, warm-ups
included, must carry a valid fingerprint and the fields of its mode; the
fingerprints of a scenario must be one and the same in both runs, and the
non-timing `events` fields equal. Missing data is never taken as a match,
even when both runs lack it. Any gap is a problem; the comparison exits
with 1 and lists them.

Timing: per scenario, the ratio of `plain` medians before / after (above
1 is faster). A change counts as real only when it exceeds three times
the sum of both runs' median absolute deviations. Growth exponents of E2
to E4 are recomputed for both runs. The report goes to `compare.md` in
the AFTER directory.
"""

import argparse
from collections import defaultdict
from collections.abc import Sequence
import json
from pathlib import Path
import re
import statistics
import sys
from typing import Any

from benchmarks.run import scenario_problems
from benchmarks.scenarios import all_scenarios, scenario_by_id
from benchmarks.summarize import Summary, load, slope, summarize

Record = dict[str, Any]

# Configuration that must match for timings to be comparable.
SAME_CONFIG = (
    "python", "implementation", "cpu", "pinned_cpu", "hash_seed",
    "timeout_s", "repeats", "warmup", "modes",
)
# Noted when they differ, as they may shift absolute times.
NOTED_ENVIRONMENT = ("cpu_governor", "intel_no_turbo", "platform")
TIMINGS = (
    ("run_ns", "Run"),
    ("plan_ns", "Plan"),
    ("turns_ns", "Turn loop"),
    ("per_turn_ns", "Per turn"),
    ("parse_ns", "Parse"),
)
# What every record needs, and what each mode adds. Fields in `*_VALUES`
# must be present and not null; fields in `*_KEYS` must be present, as null
# is a valid value (no route has no planned route, a run without turns no
# turn percentile, a scenario without a mechanism no mechanism result).
BASE_FIELDS = (
    "scenario_id", "experiment", "mode", "repeat", "warmup", "params",
    "expected", "status",
)
TIMED_VALUES = (
    "parse_ns", "run_ns", "plan_ns", "turns_ns", "loop_other_ns", "turns",
)
TIMED_KEYS = ("turn_ns_p90",)
EVENTS_VALUES = (
    "turns", "departures", "waiting_aircraft_turns", "reroutes_weather",
    "reroutes_deadlock", "weather_changes", "lane_closures",
)
EVENTS_KEYS = (
    "planned_hops_mean", "planned_hops_max", "planned_makespan",
    "mechanism", "mechanism_ok",
)
PROFILE_VALUES = ("turns", "profile_total_s", "profile_top")
FINGERPRINT = re.compile(r"[0-9a-f]{64}")
SWEEPS = {"E2": "hubs", "E3": "lanes", "E4": "aircraft"}


class Run:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.environment: Record = json.loads(
            (out_dir / "environment.json").read_text(encoding="utf-8")
        )
        self.records = load(out_dir)
        # Records without the fields every record has cannot be placed;
        # they are only counted as problems.
        self.unplaced = [
            r for r in self.records
            if any(field not in r for field in BASE_FIELDS)
        ]
        placed = [r for r in self.records if r not in self.unplaced]
        self.by_scenario: dict[str, list[Record]] = defaultdict(list)
        for record in placed:
            self.by_scenario[record["scenario_id"]].append(record)
        # Incomplete records are reported as problems and kept out of the
        # summaries.
        self.summaries = {
            s.scenario_id: s
            for s in summarize(r for r in placed if not record_gaps(r))
        }


def record_gaps(record: Record) -> list[str]:
    """
    What a placed record lacks. A successful execution of any mode, warm-up
    included, needs a valid fingerprint and the measurements of its mode;
    a timeout or error has neither and is reported by `scenario_problems`.
    """
    if record["status"] in ("timeout", "error"):
        return []
    gaps = []
    fingerprint = record.get("fingerprint")
    if not isinstance(fingerprint, str) or not FINGERPRINT.fullmatch(
        fingerprint
    ):
        gaps.append("a valid fingerprint")
    values: tuple[str, ...] = ()
    keys: tuple[str, ...] = ()
    if record["mode"] in ("plain", "phases"):
        values, keys = TIMED_VALUES, TIMED_KEYS
        if record["mode"] == "phases":
            values += ("phases",)
    elif record["mode"] == "events":
        values, keys = EVENTS_VALUES, EVENTS_KEYS
    elif record["mode"] == "profile":
        values = PROFILE_VALUES
    gaps += [f for f in values if record.get(f) is None]
    gaps += [f for f in keys if f not in record]
    return gaps


def run_problems(run: Run, label: str, partial: bool) -> list[str]:
    """Gaps that make one run unusable for a comparison."""
    problems = []
    declared = run.environment.get("scenarios", [])
    if not partial:
        matrix = [s.scenario_id for s in all_scenarios()
                  if s.experiment != "smoke"]
        if sorted(declared) != sorted(matrix):
            problems.append(f"{label}: does not cover the whole matrix")
    missing = [sid for sid in declared if sid not in run.by_scenario]
    problems += [f"{label}: {sid} has no records" for sid in missing]
    unknown = sorted(set(run.by_scenario) - set(declared))
    problems += [f"{label}: {sid} was not declared" for sid in unknown]
    if "elapsed_s" not in run.environment:
        problems.append(f"{label}: the run did not finish")
    if run.unplaced:
        problems.append(
            f"{label}: {len(run.unplaced)} records lack "
            f"{', '.join(BASE_FIELDS)}"
        )

    modes = run.environment.get("modes", [])
    # `repeats` is a number only when the run fixed it with --repeats.
    configured = run.environment.get("repeats")
    minimum = min(3, configured) if isinstance(configured, int) else 3
    for sid, records in sorted(run.by_scenario.items()):
        try:
            scenario = scenario_by_id(sid)
        except KeyError:
            problems.append(f"{label}: {sid} is not a known scenario")
            continue
        problems += [f"{label}: {p}"
                     for p in scenario_problems(scenario, records)]
        for record in records:
            gaps = record_gaps(record)
            if gaps:
                problems.append(
                    f"{label}: {sid} {record['mode']} execution "
                    f"{record['repeat']} lacks {', '.join(gaps)}"
                )
        plain = [r for r in records
                 if r["mode"] == "plain" and not r["warmup"]
                 and r["status"] not in ("timeout", "error")
                 and not record_gaps(r)]
        if "plain" in modes and len(plain) < minimum:
            problems.append(
                f"{label}: {sid} has {len(plain)} complete plain repeats, "
                f"needs {minimum}"
            )
        for mode in ("phases", "events"):
            if mode in modes and not any(
                r["mode"] == mode and not r["warmup"] for r in records
            ):
                problems.append(f"{label}: {sid} has no {mode} execution")
        if "profile" in modes and scenario.profile and not any(
            r["mode"] == "profile" for r in records
        ):
            problems.append(f"{label}: {sid} has no profile execution")
    return problems


def pair_problems(before: Run, after: Run) -> tuple[list[str], list[str]]:
    """Problems that make the two runs incomparable or show a change of
    behaviour, and environment differences worth noting."""
    problems = []
    for key in SAME_CONFIG:
        if before.environment.get(key) != after.environment.get(key):
            problems.append(
                f"configuration differs: {key} "
                f"{before.environment.get(key)!r} -> "
                f"{after.environment.get(key)!r}"
            )
    notes = [
        f"{key}: {before.environment.get(key)!r} -> "
        f"{after.environment.get(key)!r}"
        for key in NOTED_ENVIRONMENT
        if before.environment.get(key) != after.environment.get(key)
    ]
    if set(before.by_scenario) != set(after.by_scenario):
        only = sorted(set(before.by_scenario) ^ set(after.by_scenario))
        problems.append("scenario sets differ: " + ", ".join(only))

    for sid in sorted(set(before.by_scenario) & set(after.by_scenario)):
        prints = {
            r["fingerprint"]
            for r in before.by_scenario[sid] + after.by_scenario[sid]
            if isinstance(r.get("fingerprint"), str)
        }
        if not prints:
            problems.append(f"{sid}: no fingerprint to compare")
        elif len(prints) > 1:
            problems.append(f"{sid}: outcome fingerprints differ")
        events_before = _events(before.by_scenario[sid])
        events_after = _events(after.by_scenario[sid])
        if events_before != events_after:
            changed = sorted(
                key for key in set(events_before) | set(events_after)
                if events_before.get(key) != events_after.get(key)
            )
            problems.append(
                f"{sid}: events fields differ: {', '.join(changed)}"
            )
    return problems, notes


def _events(records: list[Record]) -> Record:
    """Non-timing fields of the events execution; the fingerprint is
    compared on its own."""
    for record in records:
        if record["mode"] == "events" and not record["warmup"]:
            return {
                key: value for key, value in record.items()
                if not key.endswith("_ns")
                and key not in ("repeat", "fingerprint")
            }
    return {}


def _absolute_spread(summary: Summary, key: str) -> float:
    return summary.spread.get(key, 0.0) * summary.medians.get(key, 0.0)


def ratio(before: Summary, after: Summary, key: str) -> tuple[
    float | None, bool
]:
    """Before / after median, and whether the change exceeds the noise."""
    old = before.medians.get(key)
    new = after.medians.get(key)
    if not old or not new:
        return None, False
    noise = 3 * (_absolute_spread(before, key) + _absolute_spread(after, key))
    return old / new, abs(old - new) > noise


def _times(value: float | None, real: bool) -> str:
    if value is None:
        return "–"
    return f"{value:.2f}×" + ("" if real else " ~")


def _ms(value: float | None) -> str:
    if value is None:
        return "–"
    ms = value / 1e6
    return f"{ms:.0f}" if ms >= 100 else f"{ms:.2f}" if ms < 10 \
        else f"{ms:.1f}"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _scenario_rows(before: Run, after: Run, ids: list[str]) -> list[
    list[str]
]:
    rows = []
    for sid in ids:
        old, new = before.summaries[sid], after.summaries[sid]
        row = [sid, new.status]
        row += [_ms(old.medians.get("run_ns")),
                _ms(new.medians.get("run_ns"))]
        for key, _label in TIMINGS:
            row.append(_times(*ratio(old, new, key)))
        unstable = sorted(set(old.unstable) | set(new.unstable))
        row.append(", ".join(unstable) or "–")
        rows.append(row)
    return rows


def _experiment_rows(before: Run, after: Run) -> list[list[str]]:
    by_experiment: dict[str, list[str]] = defaultdict(list)
    for sid in after.summaries:
        if sid in before.summaries:
            by_experiment[after.summaries[sid].experiment].append(sid)
    rows = []
    for experiment, ids in sorted(by_experiment.items()):
        for key, label in TIMINGS:
            values = []
            real = 0
            for sid in ids:
                value, significant = ratio(
                    before.summaries[sid], after.summaries[sid], key
                )
                if value is not None:
                    values.append(value)
                    real += significant
            if values:
                rows.append([
                    experiment, label, str(len(values)),
                    f"{statistics.median(values):.2f}×",
                    f"{min(values):.2f}×–{max(values):.2f}×",
                    f"{real} / {len(values)}",
                ])
    return rows


def _series(
    run: Run, experiment: str, key: str
) -> list[tuple[float, float]]:
    """Medians over seeds of one timing, per sweep point."""
    points: dict[float, list[Summary]] = defaultdict(list)
    for summary in run.summaries.values():
        if summary.experiment != experiment or summary.status != "ok":
            continue
        param = SWEEPS[experiment]
        x = summary.lanes if param == "lanes" else summary.params[param]
        if key in summary.medians and x:
            points[float(x)].append(summary)
    return [
        (x, statistics.median(s.medians[key] for s in group))
        for x, group in sorted(points.items())
    ]


def _growth_rows(before: Run, after: Run) -> list[list[str]]:
    rows = []
    for experiment, param in SWEEPS.items():
        for key, label in (("run_ns", "Run"), ("plan_ns", "Plan"),
                           ("per_turn_ns", "Per turn")):
            old = slope(_series(before, experiment, key))
            new = slope(_series(after, experiment, key))
            if old is None and new is None:
                continue
            rows.append([
                experiment, param, label,
                "–" if old is None else f"{old:.2f}",
                "–" if new is None else f"{new:.2f}",
            ])
    return rows


def _profile_section(before: Run, after: Run) -> str:
    parts = []
    for sid, new in sorted(after.summaries.items()):
        old = before.summaries.get(sid)
        if not new.profile or old is None or not old.profile:
            continue
        rows = []
        for label, summary in (("before", old), ("after", new)):
            total = summary.profile["profile_total_s"]
            for row in summary.profile["profile_top"][:6]:
                share = row["own_s"] / total if total else 0
                rows.append([label, row["function"], str(row["calls"]),
                             f"{100 * share:.0f} %"])
        parts.append(
            f"### {sid}\n\nProfiled total "
            f"{old.profile['profile_total_s']:.2f} s before, "
            f"{new.profile['profile_total_s']:.2f} s after.\n\n"
            + _table(["Run", "Function", "Calls", "Own share"], rows)
        )
    return "\n\n".join(parts)


def render(
    before: Run, after: Run, problems: list[str], notes: list[str]
) -> str:
    ids = sorted(set(before.summaries) & set(after.summaries))
    text = [
        "# Benchmark comparison\n",
        f"Before: `{before.out_dir.name}`, commit "
        f"`{before.environment.get('commit', '?')}`. After: "
        f"`{after.out_dir.name}`, commit "
        f"`{after.environment.get('commit', '?')}`.\n",
        "## Problems\n\n" + ("\n".join(f"- {p}" for p in problems)
                             or "None.") + "\n",
        "## Environment differences\n\n"
        + ("\n".join(f"- {n}" for n in notes) or "None.") + "\n",
        "## Speed-up by experiment\n\nBefore / after of `plain` medians; "
        "the last column counts scenarios whose change exceeds 3 × the "
        "sum of both MADs.\n\n"
        + _table(["Experiment", "Timing", "Scenarios", "Median",
                  "Range", "Beyond noise"],
                 _experiment_rows(before, after)) + "\n",
        "## Growth exponents\n\nLog-log slope of the medians over seeds, "
        "before and after.\n\n"
        + _table(["Experiment", "Against", "Timing", "Before", "After"],
                 _growth_rows(before, after)) + "\n",
        "## Scenarios\n\nSpeed-ups marked `~` are within noise.\n\n"
        + _table(["Scenario", "Status", "Run ms before", "Run ms after"]
                 + [label for _key, label in TIMINGS] + ["Unstable"],
                 _scenario_rows(before, after, ids)) + "\n",
    ]
    profiles = _profile_section(before, after)
    if profiles:
        text.append("## Profiles\n\ncProfile shares rank functions only.\n\n"
                    + profiles + "\n")
    return "\n".join(text)


def compare(before_dir: Path, after_dir: Path, partial: bool) -> list[str]:
    before = Run(before_dir)
    after = Run(after_dir)
    problems = run_problems(before, "before", partial)
    problems += run_problems(after, "after", partial)
    more, notes = pair_problems(before, after)
    problems += more
    (after_dir / "compare.md").write_text(
        render(before, after, problems, notes), encoding="utf-8"
    )
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks.compare",
        description="Compare two benchmark runs.",
    )
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument(
        "--partial", action="store_true",
        help="Allow runs of a subset of the matrix; both need the same.",
    )
    args = parser.parse_args(argv)
    problems = compare(args.before, args.after, args.partial)
    print(args.after / "compare.md")
    for problem in problems:
        print(f"Problem: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
