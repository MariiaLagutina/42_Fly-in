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
| `FIXED` | Fix and regression test implemented in the linked pull request |
| `VERIFIED` | Fixed, and the regression test plus the full invariant suite pass |

An entry moves to `FIXED` only together with an actual fix and its regression
test, and to `VERIFIED` only after the regression test and the full invariant
suite pass. Both updates are made in the pull request that contains the fix
and link it, so the status is true as soon as that pull request is merged.

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
| [BUG-001](#bug-001) | Hub capacity exceeded by simultaneous multi-turn arrivals | `VERIFIED` | High | Simulation execution |
| [BUG-002](#bug-002) | Hub capacity exceeded after a rejected departure | `VERIFIED` | High | Simulation execution |
| [BUG-003](#bug-003) | Deadlock between opposite-direction aircraft on a distance lane | `VERIFIED` | Medium | Simulation execution and planning |
| [BUG-004](#bug-004) | Turns without printed movement are dropped from the output | `CONFIRMED` | Low | Simulation output |

---

## BUG-001

### Hub capacity exceeded by simultaneous multi-turn arrivals

| Field | Value |
| --- | --- |
| Status | `VERIFIED` |
| Severity | High |
| Affected area | `simulation.py`: `Simulator._apply_planned_moves`, `Simulator._finish_in_transit_drones` |
| Discovered during | Pathfinding and simulation test audit (PR #4), 2026-10-03 |
| Resolution | Fixed in PR #5: hub load counts aircraft already flying towards the hub ([ADR-008](decisions.md#adr-008)) |
| Regression test | `test_simultaneous_multi_turn_arrivals_respect_capacity` and `test_restricted_hub_with_room_for_two_is_not_overfilled` in `tests/unit/test_simulation.py`. Both fail before the fix. |
| Verification | Full invariant suite passes. Randomized audit of 6,000 small graphs: 474 hub-capacity violations before the fix, 0 after. Bundled map output unchanged. |
| Related PR | PR #5 |

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

**Fix.** A new step, `Simulator._select_feasible_moves`, validates all planned
moves before any is applied. A hub's load includes aircraft already in transit
towards it, so an arrival slot is held from the moment of departure and
arrivals can no longer overfill a hub. Each accepted move also counts towards
its destination for later moves in the same turn.

With the fix, the reproducer finishes in 8 turns, and no hub ever exceeds its
capacity.

---

## BUG-002

### Hub capacity exceeded after a rejected departure

| Field | Value |
| --- | --- |
| Status | `VERIFIED` |
| Severity | High |
| Affected area | `simulation.py`: `Simulator._execute_turn`, `Simulator._apply_planned_moves` |
| Discovered during | Pathfinding and simulation test audit (PR #4), 2026-10-03 |
| Resolution | Fixed in PR #5: a hub counts as freed only by departures that are kept ([ADR-008](decisions.md#adr-008)) |
| Regression test | `test_rejected_departure_does_not_free_its_hub` in `tests/unit/test_simulation.py`. Fails before the fix. |
| Verification | Same as [BUG-001](#bug-001). |
| Related PR | PR #5 |

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

**Fix.** `Simulator._select_feasible_moves` counts a hub as freed only by
departures that are kept. Rejecting one move can invalidate another, so the
selection repeats until no move is rejected; it only shrinks, so it always
terminates.

---

## BUG-003

### Deadlock between opposite-direction aircraft on a distance lane

| Field | Value |
| --- | --- |
| Status | `VERIFIED` |
| Severity | Medium |
| Affected area | `simulation.py`: `Simulator._plan_departures`, `Simulator._select_feasible_moves`; `pathfinder.py`: `Pathfinder.find_cooperative_path`, `Pathfinder._is_move_valid` |
| Discovered during | Pathfinding and simulation test audit (PR #4), 2026-10-03; second variant during the BUG-001/002 fix audit (PR #5); deadlocks without weather during the dynamic-routing design (PR #7) |
| Resolution | Fixed in PR #10: lanes go only to admitted departures, planner and executor share one capacity model with one departure per direction ([ADR-019](decisions.md#adr-019)), routes wait in place, and structural deadlocks are detected and resolved or reported ([ADR-020](decisions.md#adr-020)) |
| Regression tests | In `tests/unit/test_simulation.py`: `test_rejected_departure_does_not_take_the_departure_slot` and `test_rejected_departure_does_not_take_lane_capacity` (variant B); `test_aircraft_are_delivered_when_planned[bug-003-variant-a]` (variant A); `test_deadlock_after_reroutes_is_resolved_by_a_way_around` and `test_deadlock_without_a_way_around_stops_the_run` (true swaps). All of them fail on the code before PR #10. |
| Verification | Full invariant suite passes, including the new hub-load and departure-rule checks. Without weather, 10,000 random maps: 13 hangs and 7,829 late aircraft before, 0 and 0 after. With seeded weather, 3,000 random maps: 2 hangs before, 0 after. Scripted-weather fuzzing: 64 hangs in 30,000 runs before, 0 in 90,000 after. Details in [dynamic-routing.md](dynamic-routing.md#since-pr-10). |
| Related PR | PR #7 (design and evidence), PR #10 (fix) |

**Violated expected behavior.** A run either delivers every aircraft or stops
promptly with a clear error when delivery is impossible.

**Observed behavior.** Two aircraft need the same lane in opposite
directions and wait for each other forever. The run continues until the
10,000-turn safety limit raises `RuntimeError`. Two variants are
confirmed:

- **A. True swap.** Both aircraft sit in full one-slot hubs and each needs the
  other's hub. They could only move if both left in the same turn.
- **B. Wasted lane.** Only one direction is blocked. The aircraft that cannot
  move takes the lane first, and the one that could move never gets it.

**Conditions.** Weather is not required.

- **PR #5 audit:** 2 of 6,000 randomized small graphs, both with dynamic
  weather enabled.
- **PR #7 audit:** 6 of 3,000 randomized small graphs with weather off, all of
  them maps with distance lanes. Both variants occur. Method and generator
  are described in [dynamic-routing.md](dynamic-routing.md#evidence).
- **PR #10 audit:** 13 of 10,000 random maps without weather, all with
  distance lanes; weather reroutes add true swaps over lanes for one
  aircraft.
- Lanes that were road under the old "under 200 km" rule are marked
  `mode=road` in the reproducers below ([ADR-016](decisions.md#adr-016)).

**Reproducers without weather (canonical).** Save one as `repro.txt` and run
`uv run --locked python3 main.py repro.txt`. Before PR #10 the run ends with
`Error: Simulation exceeded 10000 turns.`; since PR #10 every aircraft is
delivered.

Variant A without weather. Before PR #10, D9 waited in `h2` for `h4`, and D11
in `h4` for `h2`. Both hubs have capacity 1. The planned routes parked in the
priority hub `h0` and came back:
`S → h3 → h4 → h2 → h0 → h0 → h2 → h4 → h3 → S → E`.

```txt
nb_drones: 12
start_hub: S 0 0
end_hub: E 1 0
hub: h0 2 0 [zone=priority max_drones=1]
hub: h1 3 0 [zone=blocked]
hub: h2 4 0
hub: h3 5 0 [zone=restricted max_drones=2]
hub: h4 6 0
connection: h2-h0 [distance=80km mode=road]
connection: h1-E [max_link_capacity=3 distance=700km]
connection: h4-h2 [distance=150km mode=road]
connection: h4-h3 [max_link_capacity=3 distance=700km]
connection: h3-S [distance=700km]
connection: S-E [distance=450km]
```

Variant B without weather. Before PR #10, D10 waited in `S` for `h0`, which D11
occupied, and D11 waited in `h0` for `S`. `S` has unlimited capacity, so D11
could leave, but D10 took the departure slot of lane `S-h0` first on every
turn. Both planned routes returned to the start through the priority hub `h0`:
`S → h0 → S → E` and `S → h2 → h0 → S → E`.

```txt
nb_drones: 12
start_hub: S 0 0
end_hub: E 1 0
hub: h0 2 0 [zone=priority max_drones=1]
hub: h1 3 0 [zone=restricted max_drones=2]
hub: h2 4 0
connection: h1-E [distance=450km]
connection: h2-h0 [max_link_capacity=1 distance=150km mode=road]
connection: S-h2 [distance=1200km]
connection: E-S [distance=700km]
connection: S-h0 [max_link_capacity=3 distance=450km]
```

**Reproducers with scripted weather (PR #10).** These need a weather
schedule, so they are written as tests in `tests/unit/test_simulation.py`:

- `test_rejected_departure_does_not_take_lane_capacity`: variant B through
  lane capacity instead of the departure slot.
- `test_deadlock_after_reroutes_is_resolved_by_a_way_around`: a true swap
  over a lane for one aircraft, reached through two weather reroutes. Since
  PR #10 one aircraft takes a way around.
- `test_deadlock_without_a_way_around_stops_the_run`: a true swap in which
  every way around breaks the 700 km road budget. Since PR #10 the run
  stops on turn 8 with `DeadlockError`.

**Reproducers with weather (historical).** Before PR #9 these hung. Since
PR #9 they finish after 157 and 116 turns, and since PR #10 after 13 and 18.
To run them, save a map as `repro.txt` and run it with its seed:

```python
from parser import Parser
from simulation import Simulator
from weather import RandomWeather

graph, nb_aircraft = Parser().parse("repro.txt")
weather = RandomWeather(graph, seed=SEED)  # 2287 for A, 5953 for B
Simulator(graph, nb_aircraft, weather=weather).run()
# Before PR #9: RuntimeError: Simulation exceeded 10000 turns.
```

`RandomWeather` draws in the same order as the earlier global-`random`
weather, so these seeds produce the same weather as when the bug was found.
The CLI cannot reproduce this directly, because weather is only active in the
Pygame dispatch center and is not seeded.

Variant A, seed 2287:

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
connection: h5-E [max_link_capacity=2 distance=80km mode=road]
connection: h1-E [max_link_capacity=2 distance=1200km]
connection: h3-h2 [max_link_capacity=2 distance=80km mode=road]
connection: h3-S [distance=80km mode=road]
connection: h4-h3 [max_link_capacity=3 distance=700km]
connection: S-h5 [distance=80km mode=road]
```

Variant B, seed 5953:

```txt
nb_drones: 9
start_hub: S 0 0
end_hub: E 1 0
hub: h0 2 0 [zone=blocked]
hub: h1 3 0 [zone=restricted]
hub: h2 4 0 [max_drones=3]
hub: h3 5 0 [zone=priority max_drones=3]
hub: h4 6 0 [zone=blocked max_drones=3]
connection: h2-E [max_link_capacity=3 distance=1200km]
connection: h1-S [max_link_capacity=3 distance=450km]
connection: h1-h3 [max_link_capacity=1 distance=700km]
connection: h0-S [max_link_capacity=3 distance=150km mode=road]
connection: S-E [max_link_capacity=1 distance=700km]
```

**Root cause (confirmed).** The variants have different causes.

1. **Variant B was an arbitration bug.** The executor handed out a lane's
   capacity and its one departure slot before it checked whether the move
   fit its destination hub. A rejected move kept the lane for that turn, and
   the aircraft that could leave never got it. The departure slot and lane
   capacity both cause it; the one-departure rule alone does not.
2. **Variant A in the canonical reproducer was a rule, not a physical
   deadlock.** The shared lane has capacity 3, and each aircraft's departure
   frees the hub the other needs ([ADR-008](decisions.md#adr-008)), so both
   could leave together. Only the rule of one departure per lane per turn,
   in either direction, forbade it
   ([DECISION-008](open-decisions.md#decision-008)).
3. **Plans diverged without weather.** The planner booked a hub only on the
   arrival turn and checked a two-turn lane without a distance only on the
   departure turn; the executor holds both for the whole leg. Planned
   meeting points shifted until aircraft faced each other.
4. **Routes used cycles as waiting.** The priority-hub discount made a trip
   out and back cheaper than waiting, which created the opposite traffic.
5. **True swaps over a lane for one aircraft are genuine deadlocks.** No
   legal next state exists. They appear after weather reroutes, which ignore
   other aircraft, and nothing detected them.

In short: B was incorrect arbitration; A was an incorrect rule combined with
plan divergence; and in both, as in true swaps, the simulator failed to
detect an impossible state.

**Fix.**

- Lanes go only to admitted moves (B).
- Planner and executor share one capacity model, with one departure per
  direction ([ADR-019](decisions.md#adr-019)); plans without weather now
  execute exactly (A, divergence).
- A planned route never returns to a hub it has left
  ([ADR-020](decisions.md#adr-020), [DECISION-007](open-decisions.md#decision-007)).
- Structural deadlocks are detected on the turn they form. One aircraft
  takes a way around if there is one; if a way would exist with every lane
  open, the aircraft wait; otherwise the run stops with `DeadlockError`.

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
  the simulation. The route planner is `find_cooperative_path`, and
  `find_route` handles reroutes and the reachability check. Since PR #9,
  `find_path_bfs` is not called either: the reachability check has to
  respect the consecutive-road budget, which it does not.
- `Simulator._path_cost`, `Simulator.print_results`, and
  `Simulator.print_stats` are not called.
- `SimulationConfig.UNREACHABLE_COST`, `RESERVATION_PENALTY_WEIGHT`, and
  `PRIORITY_ZONE_BASE_COST` are used only by the unused methods above.
- Resolved in PR #8: the storm/snow road penalty (`WEATHER_PENALTY_SEVERE`)
  used to be unreachable, because storm and snow closed every lane. Roads now
  stay open in storm and snow ([ADR-016](decisions.md#adr-016)), so the
  penalty applies.

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
