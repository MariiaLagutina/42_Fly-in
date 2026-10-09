# Performance Benchmark

How long Maria's Airlanes takes to parse a map, plan the initial routes and
run the simulation, how that grows with the map and the traffic, and where
the time goes. This is Stage 8A. It measures and changes nothing under
`airlanes/`; whether an optimization is justified is decided from these
results, separately (Stage 8B).

The benchmark measures **run time only**. Route quality (turn counts,
delivery order, reroute choices) is not judged here; the turn counts in
the tables only describe the workload.

Earlier measurements in [dynamic-routing.md](dynamic-routing.md) were
taken while designing dynamic routing and stay as they are; this document
does not update them.

## Contents

- [Running it](#running-it)
- [Method](#method)
- [Scenarios](#scenarios)
- [Results](#results)
- [Where the time goes](#where-the-time-goes)
- [Variability and reliability](#variability-and-reliability)
- [Behaviour equivalence](#behaviour-equivalence)
- [Analysis](#analysis)
- [Conclusion for Stage 8B](#conclusion-for-stage-8b)
- [Limitations](#limitations)

## Running it

```sh
make benchmark                                    # the full matrix
make benchmark ARGS="--experiment E2"             # one experiment
make benchmark ARGS="--scenario E5/bottleneck"    # one scenario
make benchmark ARGS="--quick"                     # pilot: 1 repeat, no numbers to publish
uv run --locked python -m benchmarks.run --list   # list scenario ids
uv run --locked python -m benchmarks.summarize benchmarks/results/<run>
```

The results below come from

```sh
make benchmark ARGS="--cpu 3"
```

on commit `28b3c99`, the third benchmark commit. The summary tables were
regenerated from the same raw records after `f507ef8`, which only changes
how the phase table is presented. The full matrix took **1450 s (24 min
10 s)** of wall-clock time.

Raw records stay local, in the ignored `benchmarks/results/<UTC time>-<commit>/`:
`environment.json`, `runs.jsonl` (one line per execution), `profile/*.txt`,
`summary.md` and `summary.csv`. The benchmark is never part of `make
check` or CI, and nothing asserts on timings. Its code is still linted by
flake8 and `mypy --strict`; it is left out of coverage. The normal test
suite checks the generator (`tests/unit/test_benchmark_maps.py`) and the
benchmark's correctness and output structure
(`tests/unit/test_benchmark_runner.py`), never its speed.

## Method

### Environment

| | |
|---|---|
| CPU | Intel Core i7-10850H, 6 cores / 12 threads, up to 5.1 GHz |
| Frequency | governor `powersave`, turbo on (`no_turbo = 0`); not changed for the run |
| Pinning | benchmark processes pinned to CPU 3 (`--cpu 3`) |
| OS | Linux 7.0.0-34, glibc 2.43 |
| Python | CPython 3.14.4 (GCC 15.2.0), dependencies from `uv.lock` |
| Hashing | `PYTHONHASHSEED=0` in every benchmark process |

A laptop with frequency scaling and turbo is a noisy machine. The numbers
are meant for comparing scenarios and growth on this machine, not as
absolute figures; their spread is reported below.

### Isolation and timeout

Each scenario runs in its own process, started with `spawn` so it shares
no state with the runner. The runner waits at most 120 s for each
execution; if no result arrives, it kills the process and records
`timeout`. The timeout is enforced, not checked after the fact. No
execution timed out.

### Repeats and statistics

Per scenario: one warm-up execution (recorded, excluded from the
statistics), then 7 timed repeats if the warm-up took less than 1 s and 3
otherwise, in `plain` and again in `phases`; then one `events` execution
and, for the profiled scenarios, one `profile` execution. Before every
measured section the runner calls `gc.collect()`; the collector otherwise
stays on, as in normal use. Times are `time.perf_counter_ns()`.

Every execution parses the map file again, creates a new `Simulator`, and
creates its weather source anew from the same seed, so repeats are
identical runs.

A scenario's value is the median of its repeats. Spread is the median
absolute deviation (MAD). A timing whose MAD exceeds 10 % of its median is
marked **unstable**; it is reported, not dropped. Synthetic experiments
have three map seeds per point; a point's value is the median of its
seeds' medians, and the seed range is shown.

### Modes

Modes are never mixed: each table states which mode it comes from.

- **`plain`**: the primary timing. The simulator runs without an event
  dispatcher, as the command line does by default. Only two methods of the
  measured instance are wrapped: initial planning (`_assign_paths`) and
  each turn (`_execute_turn`), two clock reads per turn.
- **`phases`**: also wraps every phase of a turn, the three engine
  functions a turn calls (`plan_departures`, `select_feasible_moves`,
  `resolve_deadlock`, swapped in `airlanes.simulation.engine` for the run
  only and restored in `finally`), and the route searches of the
  pathfinder.
- **`profile`**: one run under `cProfile`. Profiling inflates time, so
  these numbers only rank functions; call counts are exact.
- **`events`**: no timing. Collects events and workload: planned route
  length, departures, aircraft-turns spent waiting at a hub, reroutes by
  reason, lane closures, and the mechanism evidence of stress scenarios.

### What the timings mean

| Timing | Meaning |
|---|---|
| Parse | `Parser().parse`, file read included |
| Run | `Simulator.run()` as a whole |
| Plan | initial cooperative planning (`_assign_paths`), once per run |
| Turn loop | sum of all completed turns (`_execute_turn`) |
| Per turn | turn loop / completed turns |
| Loop other | run − plan − all turns: the delivery check and keeping each turn's result |

Run − plan is not labelled turn execution: it is split into the turn loop
and the small rest, which is recorded. A turn interrupted by an error
(`DeadlockError`) is timed separately and not counted as a completed turn.

Phase timings are **inclusive** and **nested**. Each timing is recorded
under its call path, for example `turn/reconsider_routes/find_route`. A
path's time includes every path below it; its exclusive time is its own
minus its children's. Turn phases never call each other, so their
inclusive shares of a turn do not overlap. Nested route searches are
reported inside the phase that calls them and never added on top.

### Measuring overhead

`phases` against `plain`, median run time: for the 48 scenarios that run
100 ms or longer, the median overhead is **1 %** (range −6 % to +11 %).
Over all 100 scenarios it is 2 % (range −11 % to +53 %); the extremes are
runs below 2 ms, where a few microseconds of wrapping is a large share.
Primary results use `plain` only.

## Scenarios

Each scenario has a stable id and is rebuilt from code: a bundled map, or
generator parameters and a seed. 100 scenarios in five experiments, each
answering one question; no full cross product.

| Experiment | Question | Scenarios |
|---|---|---|
| E1 bundled maps | What do the bundled maps cost, and what does weather add? | 12 maps × {no weather, `RandomWeather` seeds 0, 1, 2} = 48 |
| E2 graph size | How does time grow with hubs at a fixed lane density? | hubs {25, 50, 100, 200, 400}, degree 3, 10 aircraft, seeds {1, 2, 3} = 15 |
| E3 lane density | How does time grow with lanes at a fixed hub count? | 100 hubs, degree {2.5, 3, 4, 6}, 10 aircraft, seeds {1, 2, 3} = 12 |
| E4 aircraft | How does time grow with aircraft on one graph? | 100 hubs, degree 3, aircraft {1, 5, 10, 25, 50, 100}, seeds {1, 2, 3} = 18 |
| E5 stress | How do specific mechanisms behave under load? | 7 scenarios, below |

E5:

| Scenario | Built to exercise |
|---|---|
| `E5/bottleneck` | two generated clusters of 30 hubs joined only through gate hub `G` (capacity 1); 50 aircraft |
| `E5/restricted` | 50 hubs, all restricted, lanes without distance, so every leg into a hub takes 2 turns; 25 aircraft |
| `E5/weather-waves` | Europe map with four scripted storm waves, each closing 40 % of the air lanes for 3 turns |
| `E5/challenger-a50`, `-a100` | challenger map with 50 and 100 aircraft; the variant is built in memory, the map file is unchanged |
| `E5/disconnected` | the bottleneck map with the gate blocked: no route; expected status `no_route` |
| `E5/deadlock` | the road-budget trap from the simulation tests with its snow: expected status `deadlock` |

### Synthetic maps

`benchmarks/maps.py` builds maps from parameters and a seed; the same
parameters always give the same text. An earlier throwaway generator was
audited and not reused: its hubs lay on one line, its distances were
unrelated to coordinates, it did not guarantee connectivity, and size was
not a parameter.

- Hubs are random points with whole-kilometre coordinates; the area grows
  with the hub count, so lanes stay about as long as maps grow. Start and
  end are the westernmost and easternmost hubs.
- Lane distance is the rounded straight-line distance.
- A minimum spanning tree of air lanes connects every accessible hub, so a
  route exists in clear weather under any consecutive-road limit. More
  lanes join near neighbours, shortest first, up to the target average
  degree. Only those may be roads (20 % of the short ones in E2 to E4, as
  the bonus maps mix roads in); roads are at most 300 km.
- Intermediate hubs hold 1 to 3 aircraft. Blocked hubs, when requested,
  are extra hubs outside the tree.

Validation (tests in `tests/unit/test_benchmark_maps.py`): byte-identical
output for the same parameters, different output for another seed;
acceptance by the strict parser; lane count and average degree; distances
matching coordinates; roads within 300 km; a route under the simulation's
own routing rules, also with no road allowed at all; every route of the
bottleneck map passing the gate, and none with the gate blocked;
`with_aircraft` changing only the `nb_drones` line.

### Matrix changes after the pilot

A one-repeat pilot of the whole matrix (`--quick`, 297 s) ran before the
measurement. The longest execution was 25.6 s (`E2/h400-s3`), well under
the timeout, so no scenario was cut or shrunk. The one change from the
reviewed design: E3 includes degree 3, the same maps as E2 at 100 hubs,
so that E3 has its own baseline point.

## Results

All timings: `plain` mode, medians. Every scenario finished with the
status it was built for: 98 `ok`, `E5/disconnected` `no_route`,
`E5/deadlock` `deadlock`. No execution timed out or failed.

### Runs that did not complete

Reported apart; they are not part of any growth analysis.

| Scenario | Status | Completed turns | Run ms |
|---|---|---|---|
| `E5/disconnected` | `no_route`, raised by initial planning | 0 | 0.32 |
| `E5/deadlock` | `deadlock` (`DeadlockError` on turn 8) | 7 | 0.75 |

### E1: bundled maps

No weather, and the range over weather seeds 0, 1, 2:

| Map | Hubs | Lanes | Aircraft | Turns, clear | Run ms, clear | Plan ms | Turns with weather | Run ms with weather | Per turn ms, clear → weather |
|---|---|---|---|---|---|---|---|---|---|
| easy/01 linear path | 4 | 3 | 2 | 4 | 0.32 | 0.17 | 4 | 0.30–0.40 | 0.03 → 0.03 |
| easy/02 simple fork | 5 | 5 | 3 | 5 | 0.50 | 0.33 | 5 | 0.50–0.64 | 0.03 → 0.03–0.06 |
| easy/03 basic capacity | 4 | 3 | 4 | 6 | 0.55 | 0.32 | 6–21 | 0.53–1.06 | 0.03 → 0.03 |
| medium/01 dead-end trap | 6 | 5 | 5 | 8 | 1.10 | 0.80 | 8–22 | 1.11–1.75 | 0.03 → 0.04 |
| medium/02 circular loop | 7 | 7 | 6 | 16 | 1.78 | 1.33 | 22–31 | 2.6–5.0 | 0.03 → 0.06–0.11 |
| medium/03 priority puzzle | 8 | 8 | 4 | 7 | 1.15 | 0.90 | 7–9 | 1.18–1.46 | 0.03 → 0.04–0.07 |
| hard/01 maze nightmare | 17 | 20 | 8 | 14 | 8.0 | 7.2 | 14–22 | 9.9–12.2 | 0.05 → 0.17–0.23 |
| hard/02 capacity hell | 15 | 18 | 12 | 18 | 10.0 | 9.0 | 22–44 | 14.4–19.3 | 0.05 → 0.23–0.31 |
| hard/03 ultimate challenge | 31 | 37 | 15 | 26 | 61.8 | 59.4 | 46–57 | 127–136 | 0.09 → 1.2–1.6 |
| challenger/01 impossible dream | 54 | 70 | 25 | 43 | 483 | 477 | 78–106 | 615–921 | 0.16 → 2.2–4.5 |
| bonus/europa | 24 | 36 | 15 | 34 | 79.8 | 77.6 | 48–59 | 86–99 | 0.07 → 0.37–0.53 |
| bonus/germany | 16 | 25 | 10 | 14 | 8.7 | 7.9 | 14–15 | 9.6–10.2 | 0.05 → 0.15–0.18 |

Parsing a bundled map takes about a millisecond at most (largest median
1.05 ms, challenger); at 400 synthetic hubs it takes 19 ms, still about
0.1 % of the run. Without weather, initial planning is 70 % to 99 % of
the run on every map above the easy ones. Weather does not change
planning: the initial plan is made before the first weather is observed.
It makes turns more expensive, 3× to 28× per turn on the larger maps, and
adds turns. On challenger and hard/03 the turns then take about half of
the run: 0.2–0.5 s at most.

### E2: graph size

100 hubs ≈ 150 lanes; 10 aircraft; medians over 3 seeds.

| Hubs | Lanes | Turns | Planned hops | Run ms | Run ms, seed range | Plan ms | Plan ms / aircraft | Turn loop ms | Per turn ms |
|---|---|---|---|---|---|---|---|---|---|
| 25 | 38 | 16 | 7.2 | 26.6 | 10.0–34.4 | 25.0 | 2.5 | 1.09 | 0.068 |
| 50 | 75 | 21 | 12.0 | 86.9 | 74.2–107 | 84.6 | 8.5 | 2.01 | 0.095 |
| 100 | 150 | 31 | 21.1 | 710 | 575–734 | 703 | 70 | 5.01 | 0.15 |
| 200 | 300 | 42 | 32.9 | 2676 | 1689–3156 | 2664 | 266 | 12.7 | 0.29 |
| 400 | 600 | 54 | 44.3 | 13907 | 11261–26674 | 13882 | 1388 | 26.0 | 0.48 |

Log-log slope against hubs: run 2.30, planning 2.32, turn loop 1.18, per
turn 0.73, turns 0.45. Routes get longer with the graph (planned hops
grow about as hubs^0.65), so part of the growth is more work per aircraft,
not only a slower step.

### E3: lane density

100 hubs, 10 aircraft; medians over 3 seeds.

| Degree | Lanes | Turns | Planned hops | Run ms | Run ms, seed range | Plan ms | Turn loop ms | Per turn ms |
|---|---|---|---|---|---|---|---|---|
| 2.5 | 125 | 33 | 24.0 | 544 | 333–592 | 540 | 4.68 | 0.14 |
| 3 | 150 | 31 | 21.1 | 726 | 528–749 | 720 | 4.89 | 0.15 |
| 4 | 200 | 25 | 16.2 | 1116 | 666–1161 | 1111 | 4.33 | 0.17 |
| 6 | 300 | 22 | 14.4 | 2918 | 1335–3358 | 2913 | 5.41 | 0.25 |

Log-log slope against lanes: run 1.91, planning 1.92, per turn 0.65,
turns −0.49. More lanes make routes shorter and runs end sooner, yet
planning grows almost with the square of the lane count.

### E4: aircraft

100 hubs, 150 lanes; medians over 3 seeds.

| Aircraft | Turns | Run ms | Run ms, seed range | Plan ms | Plan ms / aircraft | Turn loop ms | Per turn ms | Waiting aircraft-turns |
|---|---|---|---|---|---|---|---|---|
| 1 | 21 | 60.2 | 45.5–79.7 | 58.0 | 58.0 | 1.85 | 0.088 | 0 |
| 5 | 26 | 332 | 256–358 | 328 | 65.7 | 3.14 | 0.13 | 8 |
| 10 | 31 | 670 | 509–761 | 665 | 66.5 | 4.64 | 0.14 | 43 |
| 25 | 46 | 2049 | 1460–2181 | 2039 | 81.6 | 9.12 | 0.20 | 298 |
| 50 | 71 | 5068 | 3752–5620 | 5045 | 101 | 20.3 | 0.29 | 1223 |
| 100 | 121 | 11928 | 11001–16944 | 11888 | 119 | 37.6 | 0.31 | 4948 |

Log-log slope against aircraft: run 1.15, planning 1.16, planning per
aircraft 0.16, turn loop 0.67, per turn 0.29. Planning is one search per
aircraft, so it is close to linear in aircraft; each search gets
somewhat dearer as the reservation tables fill and routes wait longer.

### E5: stress scenarios

| Scenario | Status | Aircraft | Turns | Run ms | Plan ms | Per turn ms | Waiting aircraft-turns | Mechanism evidence (from `events`) |
|---|---|---|---|---|---|---|---|---|
| `bottleneck` | ok | 50 | 119 | 3226 | 3206 | 0.16 | 2446 | gate `G` full on 50 turns; all 50 aircraft passed it |
| `restricted` | ok | 25 | 71 | 356 | 349 | 0.10 | 600 | 275 two-turn legs into restricted hubs |
| `weather-waves` | ok | 15 | 46 | 80.5 | 68.2 | 0.27 | 184 | 56 lane closures, 18 weather reroutes |
| `challenger-a50` | ok | 50 | 68 | 1062 | 1050 | 0.18 | 1225 | – |
| `challenger-a100` | ok | 100 | 120 | 2519 | 2490 | 0.23 | 4951 | – |
| `disconnected` | no_route | 50 | 0 | 0.32 | – | – | – | no route at planning |
| `deadlock` | deadlock | 2 | 7 | 0.75 | – | – | – | `DeadlockError` on turn 8, as in the simulation tests |

Each stress scenario exercised what it was built for. Heavy waiting
(thousands of aircraft-turns at hubs) costs little per turn: 0.16–0.23 ms.

## Where the time goes

### Phases

From `phases` executions. Plan and turns are shares of the run.

| Scenario | Plan | Turns | Cooperative search / plan | Largest turn phases (share of turn time) |
|---|---|---|---|---|
| challenger, clear | 99 % | 1 % | 99 % | `plan_departures` 28 %, `update_weather` 24 % |
| challenger, seed 0 | 53 % | 47 % | 99 % | `reconsider_routes` 93 % |
| hard/03, seed 0 | 50 % | 48 % | 98 % | `reconsider_routes` 90 % |
| europa, seed 0 | 68 % | 33 % | 99 % | `reconsider_routes` 82 % |
| `E2/h400-s1` | 100 % | 0 % | 100 % | `update_weather` 52 %, `plan_departures` 34 % |
| `E4/a100-s1` | 100 % | 0 % | 100 % | `plan_departures` 34 %, `update_weather` 20 % |
| `E5/weather-waves` | 83 % | 16 % | 99 % | `reconsider_routes` 71 % |

Inside planning, almost all the time is `find_cooperative_path`; its
initial reachability check (`find_route`) and `reserve_path` are 1–3 %.
Inside a turn in weather, `reconsider_routes` dominates, mostly through
`find_route` and `route_travel_time`.

Inclusive phase detail of three profiled scenarios:

| Path | challenger, clear | `E2/h400-s1` | `E4/a100-s1` |
|---|---|---|---|
| `plan` | 451 ms | 11824 ms | 12288 ms |
| `plan/find_cooperative_path` | 448 ms, 25 calls | 11804 ms, 10 calls | 12259 ms, 100 calls |
| `…/find_cooperative_path/find_route` | 10.7 ms | 158 ms | 158 ms |
| `plan/reserve_path` | 3.0 ms | 19.4 ms | 27.0 ms |
| `turn` (all turns) | 6.2 ms, 43 turns | 28.9 ms, 54 turns | 42.8 ms, 124 turns |

### Profiles

cProfile own time, as a share of the profiled run, with exact call counts:

| Function | challenger, clear | `E2/h400-s1` | `E4/a100-s1` | `E5/weather-waves` |
|---|---|---|---|---|
| `Graph.get_connection` | 29 %, 85 512 calls | 41 %, 371 574 | 35 %, 1 261 314 | 22 %, 20 572 |
| `Connection.connects` | 26 %, 4 328 690 | 36 %, 153 726 081 | 31 %, 131 375 307 | 19 %, 559 394 |
| `Graph.get_neighbors` | 14 %, 18 000 | 15 %, 64 859 | 13 %, 222 156 | 8 %, 2 971 |
| `Pathfinder.find_cooperative_path` (own) | 12 % | 3 % | 8 % | 12 % |
| `Pathfinder._is_move_valid` | 5 % | 1 % | 3 % | 8 % |
| **Graph lookups together** | **69 %** | **92 %** | **79 %** | **49 %** |

`Graph.get_connection` and `Graph.get_neighbors` scan every lane of the map
on every call (`Connection.connects` is the comparison inside the scan); on
`E2/h400-s1` the scans call it 154 million times. The
cooperative search calls `get_neighbors` once per expanded state and
`get_connection` up to three times per candidate move (move cost,
`_is_move_valid`, road distance), so the cost of one expansion grows with
the lane count. That matches the measurements: planning grows about with
lanes² at a fixed hub count (E3) and about with hubs^2.3 at a fixed
density (E2), where routes also get longer.

## Variability and reliability

- 299 timings had at least three repeats. 37 exceed MAD / median > 10 %
  and are marked unstable in the raw summary.
- Almost all of them are runs below 2 ms (small E1 maps), or the turn-loop
  timing of synthetic scenarios, where the turn loop is 1–2 % of a run
  dominated by planning. The largest is 22 % (planning on easy/01, seed 2,
  0.22 ms; turn loop on easy/02, seed 2, 0.22 ms).
- No run or planning timing at 100 ms or more is unstable. Over all
  scenarios, run-time MAD / median has a median of 3 % and a maximum of
  16 %.
- The unstable timings do not support any conclusion below. The growth
  exponents rest on planning and run timings that are stable.
- The seed ranges are much wider than the repeat spread: for example
  11.3–26.7 s at 400 hubs. They are differences between maps, not noise.

## Behaviour equivalence

- 1420 executions of 100 scenarios across `plain`, `phases`, `profile` and
  `events`, warm-ups included, each recorded a fingerprint: a SHA-256
  digest of the final status, its error message and every completed
  `TurnResult`. Within every scenario, all fingerprints are identical.
  Instrumentation, profiling and event collection did not change any
  outcome, and repeats with a fresh weather source from the same seed
  replay the same run.
- No file under `airlanes/` changed. The CLI output, text snapshot and
  Pygame frame digests of the test corpus are unchanged (see the pull
  request).

## Analysis

Criteria for an optimization candidate, all required:

1. A reproducible hotspot.
2. An impact on total time or scaling well above the noise.
3. A cause in the code.
4. A testable hypothesis.

| Criterion | Finding |
|---|---|
| Reproducible | The same three graph lookups lead every profile; planning is ≥ 90 % of the run in every synthetic scenario and on every larger bundled map in clear weather, over all seeds and repeats. |
| Significant | Total time is dominated by planning wherever runs are slow: 0.48 s on challenger, 3.2 s on the bottleneck, 12–14 s at 400 hubs or 100 aircraft. Effects are many times the 3 % median spread. Planning grows about with hubs^2.3 and lanes^1.9. |
| Cause in the code | `get_connection` and `get_neighbors` scan the whole lane list on every call. They are called per expanded state and per candidate move: 154 million `connects` calls on `E2/h400-s1`. |
| Hypothesis | An adjacency index makes both lookups proportional to a hub's degree instead of the lane count. This removes most of the 69–92 % profiled share and the extra lane factor from the growth, without changing which connection or neighbour order is returned. |

Turn execution is not a candidate. In clear weather a turn costs
0.03–0.5 ms. In weather, `reconsider_routes` dominates turns, but turns
are at most about half of a run of 0.6–0.9 s on the largest bundled map,
and its `find_route` scans lanes in the same way.

## Conclusion for Stage 8B

The measurements justify exactly one targeted optimization: **an
adjacency index in `Graph` for `get_connection` and `get_neighbors`**.

- **Expected benefit.** Profiling puts 69–92 % of the planning-dominated
  runs in these lookups and the scans inside them. A lookup proportional
  to a hub's degree (about 3–6 here) instead of the lane count (70–600)
  should cut planning time several-fold on the larger maps. It should also
  lower the E2 and E3 growth exponents by roughly one power of the lane
  count. The exact gain must come from re-running this benchmark, not
  from this estimate.
- **Behaviour.** Behaviour must stay identical. The same connection for
  every pair of hubs: the first matching lane in map order. The same
  neighbour order, which the cooperative search's tie-breaking depends
  on. The index must stay current when `add_connection` is called. To
  prove it: the fingerprints of all 100 scenarios, the CLI, text and
  Pygame digests, and the full test suite must be unchanged.
- **Risks.**
  - Graphs built in code, as in the tests, can hold duplicate lanes that
    the parser rejects; the index must keep lane order to return the same
    one.
  - `get_connection(a, a)` today returns the first lane that touches
    `a`; the index must keep that or prove that no caller relies on it.
  - Anything that changes a connection's ends after it is added would
    leave the index stale.
  - Out of scope: `find_route` scans `graph.connections` directly and
    would not benefit without a routing change.
  - Out of scope: the cooperative search's own costs, such as path
    copying and `next_zone in path`.

If Stage 8B is not approved, nothing here requires action: the bundled
maps run in under a second.

## Limitations

- One machine, with frequency scaling and turbo left on; absolute times
  will differ elsewhere.
- Synthetic maps are random geometric graphs, not real networks; E1 covers
  the hand-made maps.
- `cProfile` inflates call-heavy code; its shares rank functions and are
  confirmed by phase timings, but they are not the shares of an
  unprofiled run.
- Growth exponents are least-squares slopes over three to six points:
  empirical indicators for this range, not complexity bounds.
- Weather scenarios use seeded random or scripted weather only.
