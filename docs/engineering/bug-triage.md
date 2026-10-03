# Bug Triage

Registry of confirmed defects in Maria's Airlanes. Each entry keeps a stable ID,
so issues, commits, and pull requests can refer to it.

Questions where the correct behavior is not decided yet live in
[open-decisions.md](open-decisions.md), not here. Accepted engineering decisions
are in [decisions.md](decisions.md).

## How to use this registry

### Statuses

| Status | Meaning |
| --- | --- |
| `OPEN` | Reported, not yet reproduced |
| `CONFIRMED` | Reproduced; no fix scheduled |
| `PLANNED` | Fix scheduled for a specific upcoming pull request |
| `IN PROGRESS` | Fix being implemented |
| `FIXED` | Fix merged; regression test added |
| `VERIFIED` | Fixed, and the regression test plus the full invariant suite pass on `main` |

An entry moves to `FIXED` only after the fix is merged, and to `VERIFIED` only
after its regression test and the invariant suite pass. Both updates link the
pull request.

### Severity

| Severity | Meaning |
| --- | --- |
| High | Silently breaks a core simulation rule; output looks valid but is wrong |
| Medium | Run fails or hangs under specific conditions |
| Low | Reporting or presentation is wrong; simulation itself is correct |

### Reproducing

Reproducers are map files. Save one as `repro.txt` and run
`uv run --locked python3 main.py repro.txt`. The invariant checker in
`tests/support/simulation.py` (`run_simulation` + `check_invariants`) reports
the violation precisely.

## Summary

| ID | Title | Status | Severity | Area |
| --- | --- | --- | --- | --- |
| [BUG-001](#bug-001) | Hub capacity exceeded by simultaneous multi-turn arrivals | `PLANNED` | High | Simulation execution |
| [BUG-002](#bug-002) | Hub capacity exceeded after a rejected departure | `PLANNED` | High | Simulation execution |
| [BUG-003](#bug-003) | Deadlock when two aircraft swap hubs over a distance lane | `CONFIRMED` | Medium | Simulation execution |
| [BUG-004](#bug-004) | Turns without printed movement are dropped from the output | `CONFIRMED` | Low | Simulation output |

---

## BUG-001

### Hub capacity exceeded by simultaneous multi-turn arrivals

| Field | Value |
| --- | --- |
| Status | `PLANNED` |
| Severity | High |
| Affected area | `simulation.py`: `Simulator._apply_planned_moves`, `Simulator._finish_in_transit_drones` |
| Discovered during | Pathfinding and simulation test audit (PR #4), 2026-10-03 |
| Planned resolution | Dedicated bugfix pull request right after PR #4 |
| Regression test | Not yet. Planned in the bugfix PR. The invariant checker already detects this reproducer. |
| Related PR | — |

**Violated invariant.** A hub never holds more aircraft than its `max_drones`
at the end of a turn. An aircraft on a multi-turn leg cannot wait on the
connection, so the destination must have room when it arrives.

**Observed behavior.** Several aircraft depart in the same turn on multi-turn
legs (for example into a restricted hub) towards the same hub. On arrival the
hub holds more aircraft than its capacity.

**Reproducer.**

```txt
nb_drones: 3
start_hub: start 0 0
end_hub: goal 3 0
hub: gate 1 0
hub: slow 2 0 [zone=restricted]
connection: start-gate
connection: gate-slow [max_link_capacity=2]
connection: slow-goal [max_link_capacity=2]
```

```txt
D1-gate
D1-gate-slow D2-gate
D1-slow D3-gate
D1-goal D2-gate-slow D3-gate-slow
D2-slow D3-slow
D2-goal D3-goal
```

On turn 4, D2 and D3 both depart towards `slow` (capacity 1). On turn 5 both
arrive, so `slow` holds 2. Turn 3 of the same run shows [BUG-002](#bug-002).

**Root cause (confirmed).**

1. In `_apply_planned_moves`, a move that takes more than one turn `continue`s
   before `incoming_counts` is updated, so later departures towards the same
   hub do not see it as incoming.
2. The capacity check for a multi-turn move uses the destination's occupancy
   at departure, not at arrival.
3. `_finish_in_transit_drones` places arriving aircraft without any capacity
   check.

---

## BUG-002

### Hub capacity exceeded after a rejected departure

| Field | Value |
| --- | --- |
| Status | `PLANNED` |
| Severity | High |
| Affected area | `simulation.py`: `Simulator._execute_turn`, `Simulator._apply_planned_moves` |
| Discovered during | Pathfinding and simulation test audit (PR #4), 2026-10-03 |
| Planned resolution | Same bugfix pull request as BUG-001 |
| Regression test | Not yet. Planned in the bugfix PR. The invariant checker already detects this reproducer. |
| Related PR | — |

**Violated invariant.** A hub never holds more aircraft than its `max_drones`.
A place counts as freed only by an aircraft that actually leaves.

**Observed behavior.** An aircraft plans to leave a hub, but its move is then
rejected because its destination is full. Its hub is still treated as freed,
and another aircraft moves in.

**Reproducer.** The [BUG-001](#bug-001) map. On turn 3, D2 plans
`gate → slow`, but `slow` is full (D1 arrives there), so D2 stays in `gate`.
D3 moves `start → gate` in the same turn, so `gate` (capacity 1) holds 2.

**Root cause (confirmed).** `_execute_turn` computes `outgoing_counts` from all
*planned* departures before any of them is validated. `_apply_planned_moves`
subtracts these counts when checking a destination, including departures that
are rejected later in the same loop.

---

## BUG-003

### Deadlock when two aircraft swap hubs over a distance lane

| Field | Value |
| --- | --- |
| Status | `CONFIRMED` |
| Severity | Medium |
| Affected area | `simulation.py`: `Simulator._plan_departures`, `Simulator._apply_planned_moves` |
| Discovered during | Pathfinding and simulation test audit (PR #4), 2026-10-03 |
| Planned resolution | Not scheduled. The fix depends on [DECISION-002](open-decisions.md#decision-002). |
| Regression test | Not yet |
| Related PR | — |

**Violated expected behavior.** A run either delivers every aircraft or stops
promptly with a clear error when delivery is impossible.

**Observed behavior.** Two aircraft, each in a full one-slot hub, need to swap
places over the same distance-based lane. Only one departure per turn is
allowed on such a lane, and the other hub is never freed, so neither moves.
The run continues until the 10,000-turn safety limit raises `RuntimeError`.

**Conditions.** Seen once in 3,000 randomized small graphs, only with dynamic
weather enabled: weather delays push execution away from the original plan.
This map plus `random.seed(2287)` reproduces it when the simulator runs with
`enable_dynamic_weather=True`:

```txt
nb_drones: 8
start_hub: S 0 0
end_hub: E 1 0
hub: h0 2 0 [max_drones=2]
hub: h1 3 0 [zone=restricted max_drones=3]
hub: h2 4 0 [zone=restricted max_drones=3]
hub: h3 5 0
hub: h4 6 0 [zone=priority]
hub: h5 7 0 [zone=blocked max_drones=2]
connection: h2-h5 [max_link_capacity=2 distance=450km]
connection: E-S [distance=1200km]
connection: h5-E [max_link_capacity=2 distance=80km]
connection: h1-E [max_link_capacity=2 distance=1200km]
connection: h3-h2 [max_link_capacity=2 distance=80km]
connection: h3-S [distance=80km]
connection: h4-h3 [max_link_capacity=3 distance=700km]
connection: S-h5 [distance=80km]
```

```python
import random
from parser import Parser
from simulation import Simulator

graph, nb_aircraft = Parser().parse("repro.txt")
random.seed(2287)
Simulator(graph, nb_aircraft, enable_dynamic_weather=True).run()
# RuntimeError: Simulation exceeded 10000 turns.
```

The CLI cannot reproduce this directly, because weather is only active in the
Pygame dispatch center and is not seeded.

**Root cause (confirmed).** D4 waits in `h4` for `h3`, and D5 waits in `h3`
for `h4`. Both hubs have capacity 1 and share one distance lane. A swap needs
both to leave in the same turn, but `_plan_departures` allows one departure
per distance lane per turn, and a single departure is rejected because the
other hub is still full. Routes are never re-planned, so the state repeats
forever.

---

## BUG-004

### Turns without printed movement are dropped from the output

| Field | Value |
| --- | --- |
| Status | `CONFIRMED` |
| Severity | Low |
| Affected area | `simulation.py`: `Simulator.run` |
| Discovered during | Pathfinding and simulation test audit (PR #4), 2026-10-03 |
| Planned resolution | Not scheduled. The output format for such turns depends on [DECISION-003](open-decisions.md#decision-003). |
| Regression test | Not yet |
| Related PR | — |

**Violated expected behavior.** Each simulated turn is represented by one
output line, so the number of lines equals the number of turns.

**Observed behavior.** A turn in which no aircraft starts or completes a move
(for example, every aircraft is mid-way through a long air leg) produces no
line. The printed turn count is lower than the real one. `Simulator.run()`
returns the same reduced list, so `len(run())` also undercounts.

**Reproducer.**

```txt
nb_drones: 1
start_hub: start 0 0
end_hub: goal 1 0
connection: start-goal [distance=900km]
```

The 900 km air leg takes 3 turns, but the output has 2 lines:

```txt
D1-start-goal
D1-goal
```

The bundled Europe map prints 33 lines for 34 turns, and up to 56 lines for
79 turns with weather enabled.

**Root cause (confirmed).** `Simulator.run` appends a turn only
`if turn.movements`.

---

## Technical debt

These are not runtime bugs: the code below is never executed by the
simulation. It is recorded so it can be removed or used deliberately later.

### TD-001 — Unused pathfinding and simulation code

| Field | Value |
| --- | --- |
| Status | `CONFIRMED` |
| Discovered during | Pathfinding and simulation test audit (PR #4), 2026-10-03 |

- `Pathfinder.find_path_dijkstra`, `Pathfinder.find_multiple_paths`,
  `Pathfinder._pathfinding_cost`, and `Pathfinder.heuristic` are not called by
  the simulation. The route planner is `find_cooperative_path`;
  `find_path_bfs` is used only as a reachability check.
- `Simulator._path_cost`, `Simulator.print_results`, and
  `Simulator.print_stats` are not called.
- `SimulationConfig.UNREACHABLE_COST`, `RESERVATION_PENALTY_WEIGHT`, and
  `PRIORITY_ZONE_BASE_COST` are used only by the unused methods above.
- The storm/snow road penalty in `Pathfinder._calculate_move_cost`
  (`WEATHER_PENALTY_SEVERE`) is unreachable: storm and snow always close the
  lane, and no aircraft departs on a closed lane. Routes are planned before
  any weather exists.

These methods are intentionally not covered by tests.

### TD-002 — Unused model state

| Field | Value |
| --- | --- |
| Status | `CONFIRMED` |
| Discovered during | Core unit test audit (PR #3), 2026-10-03 |

- `Connection.current_drones` is never updated, so `Connection.has_capacity()`
  always reflects zero usage. Link capacity is enforced by the simulator.
- `Zone.reservations` is always 0. Only the unused
  `Pathfinder._pathfinding_cost` reads it.
- `DroneState.MOVING` is never assigned.
