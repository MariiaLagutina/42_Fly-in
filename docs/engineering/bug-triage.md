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

### Module names in older entries

Entries keep the file and method names that existed when they were
recorded. The Architecture refactor ([ADR-022](decisions.md#adr-022)) moved
the code into the `airlanes/` package:

| In older entries | Now |
| --- | --- |
| `simulation.py` | `airlanes/simulation/engine.py`, with departure selection in `departures.py` and deadlock handling in `deadlock.py` |
| `Simulator._plan_departures`, `Simulator._select_feasible_moves` | `plan_departures`, `select_feasible_moves` in `airlanes/simulation/departures.py` |
| `pathfinder.py`, `routing_policy.py` | `airlanes/routing/pathfinder.py`, `airlanes/routing/policy.py` |
| `parser.py` | `airlanes/mapfile.py` |
| `weather.py`, `transport.py` | `airlanes/world/` (`TransportMode` in `airlanes/model/transport_mode.py`) |
| `graph.py`, `zone.py`, `connection.py`, `drone.py` | `airlanes/model/` |
| `events.py`, `config.py` | `airlanes/events.py`, `airlanes/config.py` |
| `visualizers.py`, `pygame_*.py` | `airlanes/output/text.py`, `airlanes/output/pygame/` |
| `main.py` | `airlanes/cli.py`; `main.py` still runs it |

## Summary

| ID | Title | Status | Severity | Area |
| --- | --- | --- | --- | --- |
| [BUG-001](#bug-001) | Hub capacity exceeded by simultaneous multi-turn arrivals | `VERIFIED` | High | Simulation execution |
| [BUG-002](#bug-002) | Hub capacity exceeded after a rejected departure | `VERIFIED` | High | Simulation execution |
| [BUG-003](#bug-003) | Deadlock between opposite-direction aircraft on a distance lane | `VERIFIED` | Medium | Simulation execution and planning |
| [BUG-004](#bug-004) | Turns without movement are dropped from the simulation result | `VERIFIED` | Low | Simulation output |
| [BUG-005](#bug-005) | Capacity blocks are attached to the wrong turns after a turn without movement | `VERIFIED` | Low | Command-line output |
| [BUG-006](#bug-006) | The command line exits with status 0 after an error | `VERIFIED` | Medium | Command line |
| [BUG-007](#bug-007) | Some invalid input ends in a traceback instead of an error message | `VERIFIED` | Medium | Map parser and command line |
| [BUG-008](#bug-008) | `--visual` colors a departure on a reverse-declared lane like its origin | `VERIFIED` | Low | Command-line output |
| [BUG-009](#bug-009) | The flight log calls every multi-turn departure "mid-air refueling" | `VERIFIED` | Low | Command-line output |
| [BUG-010](#bug-010) | The standard Pygame viewer calls a later turn without movement the initial state | `VERIFIED` | Low | Pygame output |

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
To run them, save a map as `repro.txt` and this script as `repro.py` in the
repository root, set the map's seed, and run
`uv run --locked python3 repro.py`:

```python
from airlanes.mapfile import Parser
from airlanes.simulation.engine import Simulator
from airlanes.world.weather import RandomWeather

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

### Turns without movement are dropped from the simulation result

| Field | Value |
| --- | --- |
| Status | `VERIFIED` |
| Severity | Low |
| Affected area | `simulation.py`: `Simulator.run` |
| Discovered during | Pathfinding and simulation test audit (PR #4), 2026-10-03; reframed during the Output & event audit, 2026-10-06 |
| Resolution | Fixed in PR #14: the simulation result keeps every completed turn, and the output decides what to print ([ADR-023](decisions.md#adr-023)) |
| Regression tests | `test_every_completed_turn_is_in_the_result` in `tests/unit/test_simulation.py`, and `test_result_keeps_every_turn` for every bundled map in `tests/integration/test_maps.py`. The first, and the Europe case of the second, fail before the fix. |
| Verification | Full invariant suite passes. Event streams, simulation fingerprints, the Pygame frames, and the assignment-style text output are unchanged for the bundled maps with and without weather and for 60,000 generated maps. In every run, including the three that end in `DeadlockError`, the kept turns are exactly the turns that finished. |
| Related PR | PR #14 |

**Violated expected behavior.** Every completed turn is part of the
simulation result, whether or not an aircraft moves in it.

**Observed behavior.** A turn in which no aircraft starts or completes a move
(for example, every aircraft is mid-way through a long air leg) was left out
of the list returned by `Simulator.run()`, so `len(run())` undercounted the
turns, and every output that used the list lost the turn.

This entry used to expect one printed line per turn. The assignment-style
text output prints only turns with a movement, and whether other turns
should be printed is a separate question,
[DECISION-003](open-decisions.md#decision-003).

**Reproducer.**

```txt
nb_drones: 1
start_hub: start 0 0
end_hub: goal 1 0
connection: start-goal [distance=900km]
```

The 900 km air leg takes 3 turns, but `Simulator.run()` returned 2: turns 1
and 3. Turn 2, in which the aircraft is in the air, was missing.

The bundled Europe map kept 33 of 34 turns, and up to 56 of 79 turns with
weather enabled.

**Root cause (confirmed).** `Simulator.run` appended a turn only
`if turn.movements`.

**Fix.** `Simulator.run` keeps every completed turn. The command line and
the test helper that models the assignment-style output print only turns
with a movement, so that output is unchanged.

---

## BUG-005

### Capacity blocks are attached to the wrong turns after a turn without movement

| Field | Value |
| --- | --- |
| Status | `VERIFIED` |
| Severity | Low |
| Affected area | `airlanes/cli.py`: `main`; `airlanes/output/text.py`: `CapacityInfoVisualizer` |
| Discovered during | Output & event audit, 2026-10-06 |
| Resolution | Fixed in PR #14: capacity blocks are found by turn number, and every completed turn is in the result ([ADR-023](decisions.md#adr-023)) |
| Regression tests | `test_capacity_info_follows_every_turn` and `test_capacity_info_has_one_block_per_turn_in_order` in `tests/integration/test_cli_output.py`. Both fail before the fix. |
| Verification | Full invariant suite passes. Command-line output is unchanged in every mode except `--capacity-info` on the Europe map, the only bundled map with a turn without movement when weather is off. |
| Related PR | PR #14 |

**Violated expected behavior.** With `--capacity-info`, every turn has its
own capacity block, in turn order, including turns without a printed
movement. A turn's movement line comes before its block.

**Observed behavior.** The command line paired the printed turns with the
capacity blocks by position. The printed turns left out turns without
movement ([BUG-004](#bug-004)), but the blocks did not, so after the first
such turn every line got the block of an earlier turn, and the last
blocks were never printed. The simulation itself was correct; the numbers
shown for the turns were not.

**Reproducer.** The map of [BUG-004](#bug-004), run with
`--capacity-info`, printed:

```txt
D1-start-goal
Turn 1 capacity
  zones: start=0/inf, goal=0/inf
  links: start-goal=1/2
D1-goal
Turn 2 capacity
  zones: start=0/inf, goal=0/inf
  links: start-goal=1/2
```

`D1-goal` happens on turn 3 but got the block of turn 2, and the block of
turn 3 was lost. On the bundled Europe map without weather, turn 4 has no
movement: 30 of the 33 printed lines got the block of the previous turn,
and `Turn 34 capacity` was never printed.

**Root cause (confirmed).** `main` printed `render_blocks()[index]` after
the `index`-th turn of the shortened turn list.

**Fix.** `CapacityInfoVisualizer` keeps its blocks by turn number, and
`block_for(turn_number)` replaces `render_blocks()`. The command line goes
through every completed turn and prints its movement line, if it has one,
then its block. A turn without movement prints only its block.

---

## BUG-006

### The command line exits with status 0 after an error

| Field | Value |
| --- | --- |
| Status | `VERIFIED` |
| Severity | Medium |
| Affected area | `airlanes/cli.py`: `main`; `main.py`; `airlanes/__main__.py` |
| Discovered during | Bugs & Cleanup audit, 2026-10-06 |
| Resolution | Fixed in PR #16: `main()` returns the exit status, and every entry point passes it to `sys.exit` |
| Regression tests | `tests/integration/test_cli_errors.py`: one test per handled error, and `test_entry_points_pass_the_exit_status_on` for `main.py` and `python -m airlanes`. They fail before the fix. |
| Verification | Full suite passes. Every bundled map still exits with 0 in every text mode, with byte-identical stdout and stderr. |
| Related PR | PR #16 |

**Violated expected behavior.** A run that fails exits with a non-zero
status, so a script or a CI job can tell it from a successful one.

**Observed behavior.** For a missing file, a map that cannot be parsed, a
map without a route, `DeadlockError`, or the 10,000-turn limit, the command
line printed the error to stderr and exited with status 0. Only invalid
arguments, handled by `argparse`, exited with 2.

**Reproducer.**

```txt
nb_drones: 1
start_hub: start 0 0
end_hub: goal 1 0
hub: a 2 0
connection: start-a
```

`main.py repro.txt` printed
`Error: No valid route found between start and end zones.` and exited
with 0.

**Root cause (confirmed).** `main()` returned `None` after printing each
error, and the entry points ignored it.

**Fix.** `main()` returns 0 on success and 1 for every error it handles;
`main.py`, `python -m airlanes`, and `airlanes/cli.py` itself call
`sys.exit(main())`. Messages are unchanged.

---

## BUG-007

### Some invalid input ends in a traceback instead of an error message

| Field | Value |
| --- | --- |
| Status | `VERIFIED` |
| Severity | Medium |
| Affected area | `airlanes/mapfile.py`: numeric fields; `airlanes/cli.py`: `main` |
| Discovered during | Map-parser audit (PR #3), 2026-10-03; registered during the Bugs & Cleanup audit, 2026-10-06 |
| Resolution | Fixed in PR #16 |
| Regression tests | `test_non_decimal_digits_raise_parse_error` and `test_non_decimal_population_does_not_crash` in `tests/unit/test_parser.py`; `test_a_directory_is_reported_as_an_unreadable_map` in `tests/integration/test_cli_errors.py`. They fail before the fix. |
| Verification | Full suite passes. Every numeric value accepted before, including other Unicode decimal digits such as `５`, is still accepted. |
| Related PR | PR #16 |

**Violated expected behavior.** A map that cannot be used stops the program
with a clear error message, not a crash (original assignment: "Any other
parsing error must stop the program and return a clear error message").

**Observed behavior.** Two cases ended in an uncaught exception with a
traceback:

- a superscript digit such as `²` in `nb_drones`, `max_drones`,
  `max_link_capacity`, `distance`, or `population`: `ValueError`;
- a directory given instead of a map file: `IsADirectoryError`.

**Reproducer.**

```txt
nb_drones: 1
start_hub: start 0 0
end_hub: goal 1 0
connection: start-goal [max_link_capacity=²]
```

**Root cause (confirmed).**

- The numeric fields were checked with `str.isdigit()`, which accepts
  superscript digits, and then converted with `int()`, which does not.
- `main()` caught only `FileNotFoundError` among the errors of reading the
  file.

**Fix.**

- The numeric fields are checked with `str.isdecimal()`, which accepts
  exactly the digits `int()` converts. A superscript digit gives the field's
  usual parse error with its line number. An invalid population is still
  ignored, as before.
- Any other `OSError` while the map file is read and parsed prints
  `Cannot read map file: <path>: <reason>` and exits with status 1.

Other strictness questions of the map format, such as hyphens in hub names,
self-loops, unknown metadata keys, and the file encoding, are not part of
this fix.

---

## BUG-008

### `--visual` colors a departure on a reverse-declared lane like its origin

| Field | Value |
| --- | --- |
| Status | `VERIFIED` |
| Severity | Low |
| Affected area | `airlanes/output/text.py`: `Visualizer._format_movement` |
| Discovered during | Output & event audit, 2026-10-06; measured during the Bugs & Cleanup audit, 2026-10-06 |
| Resolution | Fixed in PR #17: every token is colored by the destination hub of the outcome it shows |
| Regression test | `test_a_departure_is_colored_by_its_destination` in `tests/unit/test_text_output.py`, for both declaration orders of the lane. The reverse-declared case fails before the fix. |
| Verification | Full suite passes. Text without color is unchanged everywhere, and so is command-line output for every bundled map in every text mode. In the measured corpus, exactly the 9 tokens listed below change color. |
| Related PR | PR #17 |

**Violated expected behavior.** A movement token is colored by the hub
the leg goes to. The order in which the map declares a lane never decides
the color.

**Observed behavior.** A departure token shows the lane name, for example
`D1-goal-start`. Its color came from the last hub in that name, which is
the second hub of the lane's declaration. For an aircraft flying against
the declaration order, that is the hub it leaves. Arrival tokens show a
hub and were colored correctly.

**Reproducer.**

```txt
nb_drones: 1
start_hub: start 0 0 [color=red]
end_hub: goal 1 0 [color=blue]
connection: goal-start [distance=900km]
```

With `--visual`, turn 1 printed `D1-goal-start` in red, the color of
`start`, instead of blue. Declared as `start-goal`, it was blue.

**Scope (measured).** In 372 runs of the bundled maps, without weather
and with 30 weather seeds each, 1,135 of 7,366 departures on legs of more
than one turn used a reverse-declared lane. Only 9 of those tokens
rendered differently: many hub colors give the same terminal color, and
the hub colors of the bonus maps are city names with no terminal color at
all. All 9 are on `challenger/01_the_impossible_dream.txt` with weather
seeds 5 and 21. Without weather, which is how the command line runs the
text modes, no bundled map changes. An earlier estimate of 883 affected
tokens compared color names, not the rendered output.

**Root cause (confirmed).** `_format_movement` received only the token
text. For a lane token it guessed the hub with `split("-")[-1]` on the
lane name.

**Fix.** The renderer receives the outcome itself and colors the token by
its `destination`. The lane name is only the displayed position. Which
outcomes are shown, including a one-turn leg shown once by its arrival,
is decided in one place for both `movement_tokens` and the renderer.

---

## BUG-009

### The flight log calls every multi-turn departure "mid-air refueling"

| Field | Value |
| --- | --- |
| Status | `VERIFIED` |
| Severity | Low |
| Affected area | `airlanes/output/text.py`: `AirlinesVisualizer` |
| Discovered during | Output & event audit, 2026-10-06; measured during the Bugs & Cleanup audit, 2026-10-06 |
| Resolution | Fixed in PR #18: the line says `(in transit)` |
| Regression test | `test_flight_log_shows_a_multi_turn_departure_as_in_transit` in `tests/unit/test_text_output.py`. Fails before the fix. |
| Verification | Full suite passes. Only `--airlines` output changes: on the bundled maps without weather, exactly 199 lines on 5 maps, each only in this suffix. Every other output mode, the simulation results, the events, and the Pygame viewers are unchanged. |
| Related PR | PR #18 |

**Violated expected behavior.** The flight log describes what the
simulation models. `AgentInTransit` means that an aircraft has departed on
a leg that does not finish in the same turn; the model has no refueling,
and the output must not invent a reason why a leg takes more than one
turn.

**Observed behavior.** `--airlines` printed every departure on a leg of
more than one turn as `D1: start -> goal via start-goal (mid-air
refueling)`. The wording was deliberate in the original aircraft-only
version, where a leg of more than one turn was presented as a refueling
stop. It became inaccurate as the model evolved: such a leg now takes
several turns because of its distance, transport mode, weather at
departure, or the two-turn rule for restricted hubs, and road legs exist.
On the bundled maps without weather, 199 lines used it: 69 air legs with
a distance, 120 entries into restricted hubs over lanes without a
distance, and 10 road legs on the Germany map.

**Reproducer.**

```txt
nb_drones: 1
start_hub: start 0 0
end_hub: goal 1 0
connection: start-goal [distance=150km mode=road]
```

With `--airlines`, turn 1 printed
`D1: start -> goal via start-goal (mid-air refueling)` for a road leg.

**Root cause (confirmed).** A fixed suffix in `AirlinesVisualizer`, kept
from the aircraft-only version.

**Fix.** The line says `(in transit)`, for every transport mode. The
flight log still shows no line on the turns between a departure and its
arrival; the README now describes the log as departures on legs of more
than one turn and arrivals, by turn.

**Related finding, not fixed here.** A delivery is shown as `(landed)`
whatever the transport mode, so a road leg into the end hub also
"lands". No bundled map has such a delivery. It concerns the wording of
arrivals and is left for a separate change.

---

## BUG-010

### The standard Pygame viewer calls a later turn without movement the initial state

| Field | Value |
| --- | --- |
| Status | `VERIFIED` |
| Severity | Low |
| Affected area | `airlanes/output/pygame/standard.py`: `DroneSimulationWindow._draw_history_bar` |
| Discovered during | Output & event audit, 2026-10-06; measured during the Bugs & Cleanup audit, 2026-10-06 |
| Resolution | Fixed in PR #19: only frame 0 is captioned as the initial state |
| Regression test | `test_only_the_frame_before_the_first_turn_is_the_initial_state` in `tests/unit/test_pygame_standard.py`, run headless with SDL's dummy video driver. Fails before the fix. |
| Verification | Full suite passes. Text output, simulation results, events, and the Pygame frames recorded for the Architecture refactor are unchanged. Of the 207 frames the standard viewer draws for the bundled maps, only Europe turn 4 changes. |
| Related PR | PR #19 |

**Violated expected behavior.** Only the frame before the first turn is
shown as the initial state. A later turn in which nothing departs or
arrives is a completed turn, not the initial state.

**Observed behavior.** The history bar showed `Initial state (all drones at
base)` for every frame without movement tokens: a turn in which an
aircraft is in the middle of a multi-turn leg, waits at a hub, or only
changes its route. The map drawn below it could show aircraft on a lane.
The standard viewer runs without weather; on the bundled maps that
happens once, on Europe turn 4, with aircraft in transit. With weather,
698 of the frames of 372 bundled runs would have been affected.

**Reproducer.**

```txt
nb_drones: 1
start_hub: start 0 0
end_hub: goal 1 0
connection: start-goal [distance=900km]
```

With `--pygame`, turn 2 showed `Initial state (all drones at base)` while
the aircraft was drawn on the lane `start-goal`.

**Root cause (confirmed).** `frame.movements == ()` was used as a proxy
for the state before the first turn. The frame's `turn_number`, which the
viewer already has, is the actual discriminator: it is 0 only for that
state.

**Fix.** Frame 0 keeps its caption. A later frame without movement tokens
shows `No departures or arrivals this turn`, which says only what the
movement tokens represent; the map shows where each aircraft is. Frame
contents, events, and results are unchanged.

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
- `Simulator._path_cost` and `Simulator.print_stats` are not called.
  `Simulator.print_results` was removed with `SimulationTurn`
  ([ADR-024](decisions.md#adr-024)).
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
