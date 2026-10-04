# Open Decisions

Questions about intended behavior that are not decided yet. Until a question
is decided, the current behavior is neither declared correct nor treated as
a bug, and tests do not assert it.

When a question is decided, the decision moves to [decisions.md](decisions.md)
as an ADR, and this entry is marked `DECIDED` with a link to it.

Statuses: `OPEN`, `NEEDS EVIDENCE`, `DECIDED`.

| ID | Question | Status | Blocks |
| --- | --- | --- | --- |
| [DECISION-001](#decision-001) | Does a restricted hub add travel time on distance-based lanes? | `OPEN` | — |
| [DECISION-002](#decision-002) | What should an aircraft do when execution diverges from its plan? | `OPEN` | [BUG-003](bug-triage.md#bug-003) |
| [DECISION-003](#decision-003) | How are turns without movement represented in the output? | `OPEN` | [BUG-004](bug-triage.md#bug-004) |

---

## DECISION-001

### Does a restricted hub add travel time on distance-based lanes?

- **Status:** `OPEN`

**Context.** The project has two travel-time models:

- **On lanes without `distance`:** entering a hub costs its movement cost.
  Restricted hubs cost 2 turns, as required by the original assignment.
- **On lanes with `distance`:** travel time comes from the distance alone.
  Legs under 200 km travel by road at 100 km/h, longer legs by air at
  400 km/h, adjusted by weather.

The README documents both rules, but not what happens when they meet.

**Current behavior.** On a distance-based lane, the destination's zone type is
ignored for travel time: entering a restricted hub takes exactly as long as
entering a normal one. The bundled maps contain this case three times
(Germany: 1 restricted hub, Europe: 2).

**Possible options.**

1. Distance replaces zone cost (current behavior). Document it explicitly.
2. Restricted adds a fixed extra turn on top of the distance time.
3. Restricted multiplies the distance time (for example, ×2).
4. Forbid `zone=restricted` on hubs reached by distance lanes in the parser.

**Impact.**

- Travel times, and therefore turn counts, on the bonus maps.
- The README.
- The invariant checker, which currently enforces restricted transit time
  only on lanes without distance.

**Evidence needed.**

- What restricted hubs are meant to model in the aviation maps (congested
  airspace, slow ground handling, something else).
- Whether the bonus maps rely on the current behavior to finish within a
  reasonable time.

---

## DECISION-002

### What should an aircraft do when execution diverges from its plan?

- **Status:** `OPEN`

**Context.** Every route is planned once, before the first turn, with
reservation tables that assume each aircraft moves exactly on schedule.
During execution an aircraft can fall behind its plan:

- a destination is still full;
- a lane is closed by weather;
- weather changes the travel time.

The plan is not updated, and the reservation tables are not used during
execution.

**Current behavior.**

- The aircraft keeps its planned route and waits until its next move becomes
  possible.
- Each turn is checked locally: hub load includes aircraft already flying
  towards a hub ([ADR-008](decisions.md#adr-008)).
- Routes are never re-planned, including around lanes closed by weather. The
  README documents this limitation.

**Possible options.**

1. Keep local execution checks and make them strictly correct. This part is
   done: [BUG-001](bug-triage.md#bug-001) and
   [BUG-002](bug-triage.md#bug-002) were fixed this way in PR #5
   ([ADR-008](decisions.md#adr-008)). Alone it does not prevent
   [BUG-003](bug-triage.md#bug-003).
2. Add deadlock detection to option 1 and resolve it, for example by letting
   one aircraft step aside or by re-planning the aircraft involved.
3. Re-plan an aircraft whenever it falls behind its plan.
4. Re-plan all remaining aircraft when the weather changes.

**Impact.**

- Whether [BUG-003](bug-triage.md#bug-003) can be fixed.
- Turn counts with weather enabled.
- Runtime on large maps.
- How much the bonus maps' behavior changes.

**Evidence needed.**

- How often execution diverges from the plan on the bundled maps with and
  without weather.
- The runtime cost of re-planning on the largest maps (challenger, Europe).
- Whether deadlocks occur without weather.

---

## DECISION-003

### How are turns without movement represented in the output?

- **Status:** `OPEN`

**Context.** The output format of the original assignment prints one line per
turn and omits aircraft that do not move. On long distance-based legs a turn
can pass in which no aircraft starts or finishes a move.

**Current behavior.** Such turns are not printed, so the number of lines is
lower than the number of simulated turns (see
[BUG-004](bug-triage.md#bug-004)).

**Possible options.**

1. Print an empty line for such a turn.
2. Print in-flight aircraft on every turn of a multi-turn leg, for example by
   repeating `D1-<connection>`.
3. Keep the compact output and report the real turn count separately (for
   example, a summary line or a flag).

**Impact.**

- Compatibility with the original output format, which only defined in-flight
  tokens for restricted hubs.
- Readability of the output, and anything that parses it.

**Evidence needed.**

- Whether any consumer (scripts, the evaluation format) relies on the current
  line count.
- Which option keeps the subject-compatible output unchanged on maps without
  distance.
