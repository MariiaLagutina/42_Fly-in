"""Summarize a benchmark run: tables in `summary.md`, one row per scenario
in `summary.csv`.

    uv run --locked python -m benchmarks.summarize RESULTS_DIR

Timings come from `plain` executions only, warm-ups left out; `phases`
gives phase shares and its own overhead, `events` the workload, and
`profile` the hot functions. Spread is the median absolute deviation
(MAD); a timing whose MAD exceeds 10 % of its median is marked unstable,
never dropped. Growth exponents are least-squares slopes in log-log
space: empirical indicators, not complexity bounds.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
import csv
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any

Record = dict[str, Any]

UNSTABLE_SPREAD = 0.10
# Timings checked for stability, as (field, label).
TIMINGS = (
    ("run_ns", "run"),
    ("plan_ns", "planning"),
    ("turns_ns", "turns"),
)
# Synthetic experiments: the parameter varied, and how points are named.
SWEEPS = {
    "E2": ("hubs", "hubs"),
    "E3": ("degree", "degree"),
    "E4": ("aircraft", "aircraft"),
}


@dataclass
class Summary:
    scenario_id: str
    experiment: str
    params: dict[str, Any]
    expected: str
    status: str
    repeats: int = 0
    medians: dict[str, float] = field(default_factory=dict)
    spread: dict[str, float] = field(default_factory=dict)
    turns: int | None = None
    hubs: int | None = None
    lanes: int | None = None
    aircraft: int | None = None
    events: Record = field(default_factory=dict)
    phases: dict[str, float] = field(default_factory=dict)
    phases_run_ns: float | None = None
    profile: Record = field(default_factory=dict)
    fingerprints: set[str] = field(default_factory=set)
    executions: int = 0

    @property
    def unstable(self) -> list[str]:
        return [
            label for key, label in TIMINGS
            if self.spread.get(key, 0.0) > UNSTABLE_SPREAD
        ]

    @property
    def per_turn_ns(self) -> float | None:
        return self.medians.get("per_turn_ns")

    @property
    def overhead(self) -> float | None:
        run = self.medians.get("run_ns")
        if self.phases_run_ns is None or not run:
            return None
        return self.phases_run_ns / run - 1


def load(out_dir: Path) -> list[Record]:
    lines = (out_dir / "runs.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in lines.splitlines() if line]


def mad(values: Sequence[float]) -> float:
    centre = statistics.median(values)
    return statistics.median(abs(value - centre) for value in values)


def summarize(records: Iterable[Record]) -> list[Summary]:
    by_scenario: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        by_scenario[record["scenario_id"]].append(record)
    return [_summarize_scenario(rs) for rs in by_scenario.values()]


def _summarize_scenario(records: list[Record]) -> Summary:
    first = records[0]
    statuses = [r["status"] for r in records if not r["warmup"]]
    summary = Summary(
        scenario_id=first["scenario_id"],
        experiment=first["experiment"],
        params=first["params"],
        expected=first["expected"],
        status=_worst(statuses or [first["status"]]),
        fingerprints={r["fingerprint"] for r in records if "fingerprint" in r},
        executions=sum("fingerprint" in r for r in records),
    )
    for record in records:
        if "hubs" in record:
            summary.hubs = record["hubs"]
            summary.lanes = record["lanes"]
            summary.aircraft = record["aircraft"]
            summary.turns = record["turns"]
            break

    plain = [r for r in records
             if r["mode"] == "plain" and not r["warmup"] and "run_ns" in r]
    summary.repeats = len(plain)
    if plain:
        samples: dict[str, list[float]] = {
            key: [float(r[key]) for r in plain]
            for key in ("parse_ns", "run_ns", "plan_ns", "turns_ns",
                        "loop_other_ns")
        }
        samples["per_turn_ns"] = [
            r["turns_ns"] / r["turns"] for r in plain if r["turns"]
        ]
        samples["per_turn_p90_ns"] = [
            float(r["turn_ns_p90"]) for r in plain if r["turn_ns_p90"]
        ]
        for key, values in samples.items():
            if not values:
                continue
            centre = statistics.median(values)
            summary.medians[key] = centre
            if len(values) >= 3 and centre > 0:
                summary.spread[key] = mad(values) / centre

    phased = [r for r in records
              if r["mode"] == "phases" and not r["warmup"] and "phases" in r]
    if phased:
        summary.phases_run_ns = statistics.median(r["run_ns"] for r in phased)
        paths = sorted({path for r in phased for path in r["phases"]})
        for path in paths:
            summary.phases[path] = statistics.median(
                r["phases"].get(path, {"ns": 0})["ns"] for r in phased
            )
            summary.phases[path + "#calls"] = statistics.median(
                r["phases"].get(path, {"calls": 0})["calls"] for r in phased
            )

    for record in records:
        if record["mode"] == "events" and "departures" in record:
            summary.events = record
        if record["mode"] == "profile" and "profile_top" in record:
            summary.profile = record
    return summary


def _worst(statuses: list[str]) -> str:
    """One status for a scenario: a failure of the benchmark first."""
    for status in ("error", "timeout"):
        if status in statuses:
            return status
    return statuses[0]


def exclusive(phases: dict[str, float]) -> dict[str, float]:
    """Exclusive time of every phase: its own time minus its children's."""
    times = {p: t for p, t in phases.items() if not p.endswith("#calls")}
    result = {}
    for path, total in times.items():
        children = sum(
            t for p, t in times.items()
            if p.startswith(path + "/") and p.count("/") == path.count("/") + 1
        )
        result[path] = total - children
    return result


def slope(points: Sequence[tuple[float, float]]) -> float | None:
    """Least-squares slope of log(y) against log(x)."""
    usable = [(math.log(x), math.log(y)) for x, y in points if x > 0 and y > 0]
    if len(usable) < 2:
        return None
    mean_x = statistics.fmean(x for x, _ in usable)
    mean_y = statistics.fmean(y for _, y in usable)
    var = sum((x - mean_x) ** 2 for x, _ in usable)
    if var == 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in usable) / var


def _ms(value: float | None) -> str:
    if value is None:
        return "–"
    ms = value / 1e6
    if ms >= 100:
        return f"{ms:.0f}"
    if ms >= 10:
        return f"{ms:.1f}"
    if ms >= 0.1:
        return f"{ms:.2f}"
    return f"{ms:.3f}"


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{100 * value:.0f} %"


def _num(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "–"
    return f"{value:.{digits}f}"


def _table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _flag(summary: Summary) -> str:
    return ", ".join(summary.unstable) or "–"


def _plan_per_aircraft(summary: Summary) -> float | None:
    plan = summary.medians.get("plan_ns")
    if plan is None or not summary.aircraft:
        return None
    return plan / summary.aircraft


def _statuses_section(summaries: list[Summary]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for summary in summaries:
        counts[summary.status] += 1
    rows = [
        (s.scenario_id, s.expected, s.status, _num(s.turns))
        for s in summaries if s.status != "ok" or s.expected != "ok"
    ]
    unexpected = [s.scenario_id for s in summaries if s.status != s.expected]
    text = "## Statuses\n\n" + ", ".join(
        f"{status}: {count}" for status, count in sorted(counts.items())
    ) + "\n\n"
    if rows:
        text += "Runs that did not complete, reported apart from the "
        text += "completed ones:\n\n"
        text += _table(["Scenario", "Expected", "Status", "Turns"], rows)
        text += "\n\n"
    text += "Unexpected statuses: " + (", ".join(unexpected) or "none")
    return text + "\n"


def _bundled_section(summaries: list[Summary]) -> str:
    rows = []
    for s in summaries:
        rows.append((
            s.params.get("map", s.scenario_id), s.params.get("weather", ""),
            s.status, _num(s.hubs), _num(s.lanes), _num(s.aircraft),
            _num(s.turns), _ms(s.medians.get("run_ns")),
            _ms(s.medians.get("plan_ns")), _ms(s.per_turn_ns),
            _num(s.events.get("reroutes_weather")),
            _num(s.events.get("reroutes_deadlock")), _flag(s),
        ))
    table = _table(
        ["Map", "Weather", "Status", "Hubs", "Lanes", "Aircraft", "Turns",
         "Run ms", "Plan ms", "Per turn ms", "Weather reroutes",
         "Deadlock reroutes", "Unstable"],
        rows,
    )

    by_map: dict[str, dict[str, Summary]] = defaultdict(dict)
    for s in summaries:
        by_map[str(s.params.get("map"))][str(s.params.get("weather"))] = s
    weather_rows = []
    for name, runs in by_map.items():
        clear = runs.get("none")
        seeded = [s for w, s in runs.items() if w != "none"]
        if clear is None or not seeded or "run_ns" not in clear.medians:
            continue
        ratios = [
            s.medians["per_turn_ns"] / clear.medians["per_turn_ns"]
            for s in seeded
            if "per_turn_ns" in s.medians and clear.medians.get("per_turn_ns")
        ]
        turn_counts = [s.turns for s in seeded if s.turns is not None]
        weather_rows.append((
            name, _num(clear.turns),
            f"{min(turn_counts)}–{max(turn_counts)}" if turn_counts else "–",
            _ms(clear.per_turn_ns),
            f"{min(ratios):.2f}–{max(ratios):.2f}" if ratios else "–",
        ))
    weather = _table(
        ["Map", "Turns, clear", "Turns, weather seeds",
         "Per turn ms, clear", "Per turn with weather / clear"],
        weather_rows,
    )
    return (
        "## E1 bundled maps\n\n" + table
        + "\n\nWeather against clear weather, per map:\n\n" + weather + "\n"
    )


def _point_rows(
    summaries: list[Summary], key: str
) -> list[tuple[float, list[Summary]]]:
    points: dict[float, list[Summary]] = defaultdict(list)
    for s in summaries:
        if s.status == "ok" and "run_ns" in s.medians:
            points[float(s.params[key])].append(s)
    return sorted(points.items())


def _median_of(
    group: list[Summary], value: Callable[[Summary], float | None]
) -> float | None:
    values = [v for v in (value(s) for s in group) if v is not None]
    return statistics.median(values) if values else None


def _sweep_section(
    experiment: str, summaries: list[Summary]
) -> tuple[str, list[str]]:
    key, label = SWEEPS[experiment]
    points = _point_rows(summaries, key)
    rows = []
    series: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for value, group in points:
        lanes = _median_of(group, lambda s: s.lanes)
        x = lanes if experiment == "E3" and lanes else value
        measures: dict[str, Callable[[Summary], float | None]] = {
            "run": lambda s: s.medians.get("run_ns"),
            "planning": lambda s: s.medians.get("plan_ns"),
            "planning per aircraft": _plan_per_aircraft,
            "turn loop": lambda s: s.medians.get("turns_ns"),
            "per turn": lambda s: s.per_turn_ns,
            "turns": lambda s: s.turns,
        }
        medians = {name: _median_of(group, f) for name, f in measures.items()}
        for name, median in medians.items():
            if median:
                series[name].append((x, median))
        runs = [s.medians["run_ns"] for s in group]
        rows.append((
            _num(value, 1 if experiment == "E3" else 0), _num(lanes),
            str(len(group)), _num(medians["turns"]),
            _num(_median_of(group, lambda s: s.events.get(
                "planned_hops_mean")), 1),
            _ms(medians["run"]), f"{_ms(min(runs))}–{_ms(max(runs))}",
            _ms(medians["planning"]), _ms(medians["planning per aircraft"]),
            _ms(medians["turn loop"]), _ms(medians["per turn"]),
            _num(_median_of(group, lambda s: s.events.get(
                "waiting_aircraft_turns"))),
            ", ".join(sorted({u for s in group for u in s.unstable})) or "–",
        ))
    table = _table(
        [label.capitalize(), "Lanes", "Seeds", "Turns", "Planned hops",
         "Run ms", "Run ms, seed range", "Plan ms", "Plan ms / aircraft",
         "Turn loop ms", "Per turn ms", "Waiting aircraft-turns",
         "Unstable"],
        rows,
    )
    x_label = "lanes" if experiment == "E3" else label
    slopes = [
        f"- {name}: {_num(slope(points_), 2)}"
        for name, points_ in series.items()
    ]
    text = (
        f"Medians over seeds; each seed's value is the median of its "
        f"repeats.\n\n{table}\n\nGrowth exponent against {x_label} "
        f"(log-log slope of the medians):\n\n" + "\n".join(slopes) + "\n"
    )
    return text, slopes


def _stress_section(summaries: list[Summary]) -> str:
    rows = []
    for s in summaries:
        evidence = []
        for name in ("gate_full_turns", "aircraft_through_gate",
                     "two_turn_legs_into_restricted", "reroutes_weather",
                     "reroutes_deadlock", "lane_closures"):
            if s.events.get(name):
                evidence.append(f"{name.replace('_', ' ')} "
                                f"{s.events[name]}")
        ok = s.events.get("mechanism_ok")
        rows.append((
            s.scenario_id, f"{s.status} ({s.expected})", _num(s.aircraft),
            _num(s.turns), _ms(s.medians.get("run_ns")),
            _ms(s.medians.get("plan_ns")), _ms(s.per_turn_ns),
            _num(s.events.get("waiting_aircraft_turns")),
            ("yes" if ok else "NO") if ok is not None else "–",
            "; ".join(evidence) or "–", _flag(s),
        ))
    return "## E5 stress scenarios\n\n" + _table(
        ["Scenario", "Status (expected)", "Aircraft", "Turns", "Run ms",
         "Plan ms", "Per turn ms", "Waiting aircraft-turns",
         "Mechanism exercised", "Evidence", "Unstable"],
        rows,
    ) + "\n"


def _phase_section(summaries: list[Summary]) -> str:
    rows = []
    for s in summaries:
        if not s.phases:
            continue
        own = exclusive(s.phases)
        run = s.phases_run_ns or 0
        turns = s.phases.get("turn", 0)
        if not run:
            continue
        turn_phases = sorted(
            ((p.split("/", 1)[1], t) for p, t in own.items()
             if p.startswith("turn/") and p.count("/") == 1),
            key=lambda item: item[1], reverse=True,
        )
        top = "; ".join(
            f"{name} {_pct(t / turns)}" for name, t in turn_phases[:3]
            if turns
        )
        coop = s.phases.get("plan/find_cooperative_path", 0)
        plan = s.phases.get("plan", 0)
        rows.append((
            s.scenario_id, _pct(plan / run), _pct(turns / run),
            _pct(coop / plan) if plan else "–",
            _pct(own.get("turn", 0) / turns) if turns else "–",
            top or "–", _pct(s.overhead),
        ))
    return (
        "## Phases\n\nFrom `phases` executions. Plan and turns are shares of "
        "the run; the cooperative search is a share of planning; turn "
        "phases are exclusive shares of the turn time, nested route "
        "searches included in the phase that calls them. Overhead compares "
        "the median `phases` run with the median `plain` run.\n\n"
        + _table(
            ["Scenario", "Plan", "Turns", "Cooperative search / plan",
             "Turn, outside phases", "Top turn phases", "Overhead"],
            rows,
        ) + "\n"
    )


def _nested_section(summaries: list[Summary]) -> str:
    rows = []
    for s in summaries:
        if not s.phases or not s.profile:
            continue
        for path in sorted(p for p in s.phases if not p.endswith("#calls")):
            rows.append((
                s.scenario_id, path, _ms(s.phases[path]),
                _num(s.phases.get(path + "#calls")),
            ))
    return (
        "## Phase detail of the profiled scenarios\n\nInclusive times; a "
        "path includes every path below it.\n\n"
        + _table(["Scenario", "Path", "Inclusive ms", "Calls"], rows) + "\n"
    )


def _profile_section(summaries: list[Summary]) -> str:
    parts = ["## Profiles\n\ncProfile times are inflated by profiling and "
             "only rank functions; call counts are exact."]
    for s in summaries:
        if not s.profile:
            continue
        total = s.profile["profile_total_s"]
        rows = [
            (row["function"], str(row["calls"]), f"{row['own_s']:.3f}",
             _pct(row["own_s"] / total) if total else "–",
             f"{row['cumulative_s']:.3f}")
            for row in s.profile["profile_top"][:12]
        ]
        parts.append(
            f"### {s.scenario_id}\n\nProfiled total {total:.2f} s.\n\n"
            + _table(["Function", "Calls", "Own s", "Own share",
                      "Cumulative s"], rows)
        )
    return "\n\n".join(parts) + "\n"


def _stability_section(summaries: list[Summary]) -> str:
    rows = []
    checked = 0
    for s in summaries:
        for key, label in TIMINGS:
            if key in s.spread:
                checked += 1
                if s.spread[key] > UNSTABLE_SPREAD:
                    rows.append((s.scenario_id, label, _pct(s.spread[key]),
                                 _ms(s.medians.get(key)), str(s.repeats)))
    text = (
        f"## Variability\n\n{checked} timings with at least 3 repeats; "
        f"{len(rows)} have MAD / median above "
        f"{100 * UNSTABLE_SPREAD:.0f} % and are marked unstable.\n\n"
    )
    if rows:
        text += _table(["Scenario", "Timing", "MAD / median", "Median ms",
                        "Repeats"], rows) + "\n"
    spreads = sorted(s.spread["run_ns"] for s in summaries
                     if "run_ns" in s.spread)
    if spreads:
        text += (
            f"\nRun-time MAD / median over all scenarios: median "
            f"{_pct(statistics.median(spreads))}, max {_pct(spreads[-1])}.\n"
        )
    return text


def _equivalence_section(summaries: list[Summary]) -> str:
    differing = [s.scenario_id for s in summaries if len(s.fingerprints) > 1]
    executions = sum(s.executions for s in summaries)
    return (
        "## Behaviour equivalence\n\n"
        f"{executions} executions of {len(summaries)} scenarios across "
        "plain, phases, profile and events modes, warm-ups included. "
        "Scenarios whose outcome fingerprints differ: "
        + (", ".join(differing) or "none") + ".\n"
    )


def _overhead_section(summaries: list[Summary]) -> str:
    values = sorted(s.overhead for s in summaries if s.overhead is not None)
    if not values:
        return ""
    return (
        "## Phase instrumentation overhead\n\n"
        f"Median `phases` run / median `plain` run − 1, over "
        f"{len(values)} scenarios: median {_pct(statistics.median(values))}, "
        f"range {_pct(values[0])} to {_pct(values[-1])}.\n"
    )


def render(summaries: list[Summary], environment: Record) -> str:
    by_experiment: dict[str, list[Summary]] = defaultdict(list)
    for summary in summaries:
        by_experiment[summary.experiment].append(summary)
    sections = [
        "# Benchmark summary\n\n"
        f"Commit `{environment.get('commit', '?')}`, Python "
        f"{str(environment.get('python', '?')).split()[0]}, "
        f"{environment.get('cpu', '?')}, governor "
        f"{environment.get('cpu_governor', '?')}, PYTHONHASHSEED "
        f"{environment.get('hash_seed', '?')}, elapsed "
        f"{environment.get('elapsed_s', '?')} s.\n",
        _statuses_section(summaries),
        _equivalence_section(summaries),
        _stability_section(summaries),
        _overhead_section(summaries),
    ]
    if by_experiment.get("E1"):
        sections.append(_bundled_section(by_experiment["E1"]))
    for experiment in SWEEPS:
        if by_experiment.get(experiment):
            text, _ = _sweep_section(experiment, by_experiment[experiment])
            sections.append(f"## {experiment}\n\n{text}")
    if by_experiment.get("E5"):
        sections.append(_stress_section(by_experiment["E5"]))
    sections += [
        _phase_section(summaries),
        _nested_section(summaries),
        _profile_section(summaries),
    ]
    return "\n".join(section for section in sections if section)


CSV_FIELDS = (
    "scenario_id", "experiment", "expected", "status", "hubs", "lanes",
    "aircraft", "turns", "repeats", "parse_ms", "run_ms", "plan_ms",
    "turns_ms", "per_turn_ms", "run_spread", "unstable", "phases_overhead",
    "planned_hops_mean", "waiting_aircraft_turns", "reroutes_weather",
    "reroutes_deadlock", "mechanism_ok", "fingerprints",
)


def _csv_row(s: Summary) -> dict[str, Any]:
    def ms(key: str) -> float | None:
        value = s.medians.get(key)
        return None if value is None else round(value / 1e6, 4)

    return {
        "scenario_id": s.scenario_id, "experiment": s.experiment,
        "expected": s.expected, "status": s.status, "hubs": s.hubs,
        "lanes": s.lanes, "aircraft": s.aircraft, "turns": s.turns,
        "repeats": s.repeats, "parse_ms": ms("parse_ns"),
        "run_ms": ms("run_ns"), "plan_ms": ms("plan_ns"),
        "turns_ms": ms("turns_ns"), "per_turn_ms": ms("per_turn_ns"),
        "run_spread": s.spread.get("run_ns"),
        "unstable": " ".join(s.unstable),
        "phases_overhead": s.overhead,
        "planned_hops_mean": s.events.get("planned_hops_mean"),
        "waiting_aircraft_turns": s.events.get("waiting_aircraft_turns"),
        "reroutes_weather": s.events.get("reroutes_weather"),
        "reroutes_deadlock": s.events.get("reroutes_deadlock"),
        "mechanism_ok": s.events.get("mechanism_ok"),
        "fingerprints": len(s.fingerprints),
    }


def write_summary(out_dir: Path) -> list[Summary]:
    summaries = summarize(load(out_dir))
    environment = json.loads(
        (out_dir / "environment.json").read_text(encoding="utf-8")
    )
    (out_dir / "summary.md").write_text(
        render(summaries, environment), encoding="utf-8"
    )
    with open(out_dir / "summary.csv", "w", newline="",
              encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for summary in summaries:
            writer.writerow(_csv_row(summary))
    return summaries


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m benchmarks.summarize RESULTS_DIR",
              file=sys.stderr)
        return 2
    out_dir = Path(args[0])
    write_summary(out_dir)
    print(out_dir / "summary.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
