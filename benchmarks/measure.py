"""One benchmark execution: parse a scenario's map, run the simulator, and
measure it in one of four modes.

- `plain`: the primary timing, without events, as the command line runs by
  default. Only initial planning and each turn are timed: two clock reads
  per turn.
- `phases`: also times every phase of a turn and the route searches
  inside them. Timings are inclusive and nested: a node's path names its
  parents, and its exclusive time is its own minus its children's.
- `profile`: the run under cProfile. Its times are only used to rank
  functions and count calls, never as results.
- `events`: no timing. The run collects events and workload counts and
  checks that the scenario exercises its mechanism.

No code of `airlanes` is changed. Instrumentation wraps methods of the one
simulator instance it measures and, in `phases`, swaps three functions in
`airlanes.simulation.engine` for the run only, restoring them in `finally`.
Every mode records a fingerprint of the run's outcome, which must be the
same in every mode and repeat: proof that measuring does not change
behaviour.
"""

from collections.abc import Callable, Iterator
import contextlib
import cProfile
from dataclasses import dataclass
import gc
import hashlib
import io
import os
from pathlib import Path
import pstats
import statistics
import tempfile
import time
from typing import Any, ParamSpec, TypeVar

from airlanes.events import (
    AgentInTransit,
    AgentMoved,
    AgentRerouted,
    CapacitySnapshot,
    EventDispatcher,
    SimulationEvent,
    WeatherChanged,
)
from airlanes.mapfile import Parser
from airlanes.model.drone import DroneState
from airlanes.model.graph import Graph
from airlanes.model.transport_mode import TransportMode
from airlanes.model.zone import Zone, ZoneType
import airlanes.simulation.engine as engine
from airlanes.simulation.deadlock import DeadlockError
from airlanes.simulation.engine import Simulator
from airlanes.world.transport import travel_time
from airlanes.world.weather import WeatherCondition
from benchmarks.scenarios import Scenario, scenario_by_id

MODES = ("plain", "phases", "profile", "events")

Record = dict[str, Any]
P = ParamSpec("P")
R = TypeVar("R")

# Simulator methods timed in `phases`, and the engine functions that turns
# call by module name.
TURN_METHODS = (
    "_update_weather",
    "_count_active_connection_usage",
    "_finish_in_transit_drones",
    "_reconsider_routes",
    "_apply_planned_moves",
    "_emit_capacity_snapshot",
)
ENGINE_FUNCTIONS = (
    "plan_departures",
    "select_feasible_moves",
    "resolve_deadlock",
)
PATHFINDER_METHODS = (
    "find_cooperative_path",
    "reserve_path",
    "find_route",
    "route_travel_time",
)

# Functions reported from a profile: the most expensive by own time.
PROFILE_TOP = 25


@dataclass(frozen=True)
class Job:
    scenario_id: str
    mode: str
    # -1 marks a warm-up execution.
    repeat: int


class Timer:
    """Inclusive durations of wrapped calls, by call path."""

    def __init__(self) -> None:
        self.durations: dict[str, list[int]] = {}
        self._stack: list[str] = []

    def wrap(self, name: str, function: Callable[P, R]) -> Callable[P, R]:
        def timed(*args: P.args, **kwargs: P.kwargs) -> R:
            path = f"{self._stack[-1]}/{name}" if self._stack else name
            self._stack.append(path)
            start = time.perf_counter_ns()
            try:
                return function(*args, **kwargs)
            finally:
                elapsed = time.perf_counter_ns() - start
                self._stack.pop()
                self.durations.setdefault(path, []).append(elapsed)

        return timed

    def total(self, path: str) -> int:
        return sum(self.durations.get(path, []))


def _wrap_method(timer: Timer, owner: object, method: str, name: str) -> None:
    """Time one method of one instance; the class is left alone."""
    setattr(owner, method, timer.wrap(name, getattr(owner, method)))


@contextlib.contextmanager
def _timed_engine_functions(timer: Timer) -> Iterator[None]:
    originals = {name: getattr(engine, name) for name in ENGINE_FUNCTIONS}
    try:
        for name, function in originals.items():
            setattr(engine, name, timer.wrap(name, function))
        yield
    finally:
        for name, function in originals.items():
            setattr(engine, name, function)


def _status(simulator: Simulator) -> tuple[str, str | None]:
    """Run the simulation; how it ended, and the error if it failed."""
    try:
        simulator.run()
    except DeadlockError as exc:
        return "deadlock", str(exc)
    except RuntimeError as exc:
        message = str(exc)
        if message.startswith("No valid route"):
            return "no_route", message
        if message.startswith("Simulation exceeded"):
            return "turn_limit", message
        raise
    return "ok", None


def fingerprint(status: str, error: str | None, simulator: Simulator) -> str:
    """Digest of how the run ended and of every completed turn."""
    outcome = repr((status, error, tuple(simulator.turns)))
    return hashlib.sha256(outcome.encode()).hexdigest()


def _percentile(values: list[int], share: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def execute(job: Job) -> Record:
    """Measure one execution of a scenario; see the module docstring."""
    if job.mode not in MODES:
        raise ValueError(f"Unknown mode: {job.mode}")
    scenario = scenario_by_id(job.scenario_id)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "map.txt"
        path.write_text(scenario.map_text(), encoding="utf-8")
        gc.collect()
        start = time.perf_counter_ns()
        graph, nb_aircraft = Parser().parse(str(path))
        parse_ns = time.perf_counter_ns() - start

    record: Record = {
        "scenario_id": scenario.scenario_id,
        "experiment": scenario.experiment,
        "mode": job.mode,
        "repeat": job.repeat,
        "warmup": job.repeat < 0,
        "params": scenario.params,
        "weather": scenario.weather.label,
        "expected": scenario.expected,
        "hubs": len(graph.zones),
        "accessible_hubs": sum(
            zone.zone_type is not ZoneType.BLOCKED
            for zone in graph.zones.values()
        ),
        "lanes": len(graph.connections),
        "road_lanes": sum(
            connection.mode is TransportMode.ROAD
            for connection in graph.connections
        ),
        "aircraft": nb_aircraft,
        "parse_ns": parse_ns,
        "hash_seed": os.environ.get("PYTHONHASHSEED"),
    }
    if job.mode == "events":
        record.update(_measure_events(scenario, graph, nb_aircraft))
    elif job.mode == "profile":
        record.update(_measure_profile(scenario, graph, nb_aircraft))
    else:
        record.update(
            _measure_time(scenario, graph, nb_aircraft, job.mode == "phases")
        )
    return record


def _measure_time(
    scenario: Scenario, graph: Graph, nb_aircraft: int, phases: bool
) -> Record:
    timer = Timer()
    gc.collect()
    start = time.perf_counter_ns()
    simulator = Simulator(
        graph, nb_aircraft, weather=scenario.weather.provider(graph)
    )
    setup_ns = time.perf_counter_ns() - start
    _wrap_method(timer, simulator, "_assign_paths", "plan")
    _wrap_method(timer, simulator, "_execute_turn", "turn")
    if phases:
        for method in TURN_METHODS:
            _wrap_method(timer, simulator, method, method.lstrip("_"))
        for method in PATHFINDER_METHODS:
            _wrap_method(timer, simulator.pathfinder, method, method)

    with (
        _timed_engine_functions(timer) if phases else contextlib.nullcontext()
    ):
        gc.collect()
        start = time.perf_counter_ns()
        status, error = _status(simulator)
        run_ns = time.perf_counter_ns() - start

    turns = len(simulator.turns)
    turn_ns = timer.durations.get("turn", [])
    # A turn interrupted by an error is timed but not kept (ADR-023).
    completed = turn_ns[:turns]
    record: Record = {
        "status": status,
        "error": error,
        "turns": turns,
        "fingerprint": fingerprint(status, error, simulator),
        "setup_ns": setup_ns,
        "run_ns": run_ns,
        "plan_ns": timer.total("plan"),
        "turns_ns": sum(completed),
        "interrupted_turn_ns": sum(turn_ns[turns:]),
        # What `run()` does besides planning and turns: the delivery check
        # and keeping each turn's result.
        "loop_other_ns": run_ns - timer.total("plan") - sum(turn_ns),
        "turn_ns_p50": _percentile(completed, 0.5) if completed else None,
        "turn_ns_p90": _percentile(completed, 0.9) if completed else None,
        "turn_ns_max": max(completed) if completed else None,
    }
    if phases:
        record["phases"] = {
            path: {"ns": sum(values), "calls": len(values)}
            for path, values in sorted(timer.durations.items())
        }
    return record


def _measure_profile(
    scenario: Scenario, graph: Graph, nb_aircraft: int
) -> Record:
    simulator = Simulator(
        graph, nb_aircraft, weather=scenario.weather.provider(graph)
    )
    profiler = cProfile.Profile()
    gc.collect()
    profiler.enable()
    try:
        status, error = _status(simulator)
    finally:
        profiler.disable()

    stats = pstats.Stats(profiler)
    total_s = stats.total_tt  # type: ignore[attr-defined]
    rows = []
    for (filename, line, function), entry in stats.stats.items():  # type: ignore[attr-defined]  # noqa: E501
        _primitive, calls, own_s, cumulative_s, _callers = entry
        rows.append({
            "function": f"{_short_path(filename)}:{line}({function})",
            "calls": calls,
            "own_s": own_s,
            "cumulative_s": cumulative_s,
        })
    rows.sort(key=lambda row: row["own_s"], reverse=True)

    text = io.StringIO()
    for key in ("tottime", "cumulative"):
        report = pstats.Stats(profiler, stream=text)
        report.strip_dirs().sort_stats(key).print_stats(PROFILE_TOP)
    return {
        "status": status,
        "error": error,
        "turns": len(simulator.turns),
        "fingerprint": fingerprint(status, error, simulator),
        "profile_total_s": total_s,
        "profile_top": rows[:PROFILE_TOP],
        "profile_text": text.getvalue(),
    }


def _short_path(filename: str) -> str:
    marker = f"{os.sep}airlanes{os.sep}"
    if marker in filename:
        return "airlanes/" + filename.split(marker, 1)[1]
    return Path(filename).name


class _Recorder:
    def __init__(self) -> None:
        self.events: list[SimulationEvent] = []

    def handle(self, event: SimulationEvent) -> None:
        self.events.append(event)


def _measure_events(
    scenario: Scenario, graph: Graph, nb_aircraft: int
) -> Record:
    recorder = _Recorder()
    dispatcher = EventDispatcher()
    dispatcher.add_listener(recorder)
    simulator = Simulator(
        graph,
        nb_aircraft,
        dispatcher,
        weather=scenario.weather.provider(graph),
    )
    planned: list[list[Zone]] = []
    at_hubs: list[int] = []
    departures: list[int] = []

    assign_paths = simulator._assign_paths
    execute_turn = simulator._execute_turn
    apply_moves = simulator._apply_planned_moves

    def watched_assign_paths() -> None:
        assign_paths()
        planned.extend(list(drone.path) for drone in simulator.drones)

    def watched_execute_turn(turn_number: int) -> Any:
        at_hubs.append(sum(
            not drone.is_delivered()
            and drone.state != DroneState.IN_TRANSIT
            for drone in simulator.drones
        ))
        return execute_turn(turn_number)

    def watched_apply_moves(*args: Any) -> None:
        departures.append(len(args[3]))
        apply_moves(*args)

    setattr(simulator, "_assign_paths", watched_assign_paths)
    setattr(simulator, "_execute_turn", watched_execute_turn)
    setattr(simulator, "_apply_planned_moves", watched_apply_moves)
    status, error = _status(simulator)

    events = recorder.events
    reroutes = [e for e in events if isinstance(e, AgentRerouted)]
    weather_changes = [e for e in events if isinstance(e, WeatherChanged)]
    start = graph.start_zone
    assert start is not None
    hops = [_hops(start, path) for path in planned]
    planned_turns = [_planned_turns(graph, start, path) for path in planned]
    workload: Record = {
        "status": status,
        "error": error,
        "turns": len(simulator.turns),
        "fingerprint": fingerprint(status, error, simulator),
        "planned_hops_mean": statistics.fmean(hops) if hops else None,
        "planned_hops_max": max(hops) if hops else None,
        "planned_makespan": max(planned_turns) if planned_turns else None,
        "departures": sum(departures),
        # Aircraft-turns spent at a hub without departing, planned waits
        # included; turns interrupted by an error are left out.
        "waiting_aircraft_turns": sum(
            at_hub - departed
            for at_hub, departed in zip(at_hubs, departures)
        ),
        "reroutes_weather": sum(e.reason == "weather" for e in reroutes),
        "reroutes_deadlock": sum(e.reason == "deadlock" for e in reroutes),
        "weather_changes": len(weather_changes),
        "lane_closures": sum(not e.is_open for e in weather_changes),
    }
    workload.update(_mechanism(scenario, graph, events, nb_aircraft))
    return workload


def _hops(start: Zone, path: list[Zone]) -> int:
    hops = 0
    current = start
    for zone in path:
        if zone is not current:
            hops += 1
            current = zone
    return hops


def _planned_turns(graph: Graph, start: Zone, path: list[Zone]) -> int:
    """Turns of the initial plan in clear weather; a planned wait takes
    one turn."""
    turns = 0
    current = start
    for zone in path:
        if zone is current:
            turns += 1
            continue
        connection = graph.get_connection(current, zone)
        assert connection is not None
        turns += travel_time(connection, zone, WeatherCondition.CLEAR)
        current = zone
    return turns


def _mechanism(
    scenario: Scenario,
    graph: Graph,
    events: list[SimulationEvent],
    nb_aircraft: int,
) -> Record:
    """Evidence that a stress scenario exercises what it is built for."""
    if scenario.mechanism == "bottleneck":
        full_turns = sum(
            1
            for e in events
            if isinstance(e, CapacitySnapshot)
            for name, load, capacity in e.hub_load
            if name == "G" and load >= capacity
        )
        through_gate = {
            e.agent_label
            for e in events
            if isinstance(e, AgentMoved) and e.destination == "G"
        }
        return {
            "mechanism": "bottleneck",
            "gate_full_turns": full_turns,
            "aircraft_through_gate": len(through_gate),
            "mechanism_ok": full_turns > 0
            and len(through_gate) == nb_aircraft,
        }
    if scenario.mechanism == "restricted":
        restricted = {
            zone.name
            for zone in graph.zones.values()
            if zone.zone_type is ZoneType.RESTRICTED
        }
        legs = sum(
            isinstance(e, AgentInTransit) and e.destination in restricted
            for e in events
        )
        return {
            "mechanism": "restricted",
            "two_turn_legs_into_restricted": legs,
            "mechanism_ok": legs > 0,
        }
    if scenario.mechanism == "weather":
        reroutes = sum(
            isinstance(e, AgentRerouted) and e.reason == "weather"
            for e in events
        )
        closures = sum(
            isinstance(e, WeatherChanged) and not e.is_open for e in events
        )
        return {
            "mechanism": "weather",
            "mechanism_ok": reroutes > 0 and closures > 0,
        }
    return {"mechanism": None, "mechanism_ok": None}
