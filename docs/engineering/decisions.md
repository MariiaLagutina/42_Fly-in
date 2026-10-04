# Engineering Decisions

A lightweight decision log (ADR style) for Maria's Airlanes. It records
decisions the project has already made and still follows, so a new contributor
can see why the code and tests look the way they do.

Questions that are still open live in [open-decisions.md](open-decisions.md).
Known defects live in [bug-triage.md](bug-triage.md).

Statuses: `Accepted`, `Superseded by ADR-XXX`, `Deprecated`.

| ID | Title | Status |
| --- | --- | --- |
| [ADR-001](#adr-001) | Dependencies are locked; developer commands never modify the lockfile | Accepted |
| [ADR-002](#adr-002) | Tests protect contracts and invariants, not implementation details | Accepted |
| [ADR-003](#adr-003) | Tests isolate and restore global random state | Accepted |
| [ADR-004](#adr-004) | Simulation invariants are checked against state rebuilt from events | Accepted |
| [ADR-005](#adr-005) | Bundled maps are reference scenarios with documented turn budgets | Accepted |
| [ADR-006](#adr-006) | Known bugs are not encoded as expected behavior in tests | Accepted |
| [ADR-007](#adr-007) | Production bugfixes are separate from test-only pull requests | Accepted |
| [ADR-008](#adr-008) | Hub capacity counts aircraft flying towards the hub | Accepted |

---

## ADR-001

### Dependencies are locked; developer commands never modify the lockfile

- **Status:** Accepted
- **Date:** 2026-10-03

**Context.** Dependencies used to be installed with an unpinned
`uv pip install`, so two machines could run different versions of mypy or
pygame-ce, and tooling results were not reproducible.

**Decision.**

- Dependencies are declared in `pyproject.toml`: runtime dependencies in
  `[project]`, development tools in the `dev` dependency group. Exact versions
  are pinned in `uv.lock`.
- `make install` runs `uv sync --locked`, and every `uv run` in the Makefile
  uses `--locked`.
- Changing dependencies is an explicit step: edit `pyproject.toml`, run
  `uv lock`, review the diff, and commit both files together.

**Rationale.** Reproducible environments for development and CI. A lockfile
change is always a visible, reviewed diff and never a side effect of running
tests.

**Consequences.** `make` targets fail if `pyproject.toml` and `uv.lock`
disagree. Contributors must run `uv lock` deliberately after changing
dependencies.

---

## ADR-002

### Tests protect contracts and invariants, not implementation details

- **Status:** Accepted
- **Date:** 2026-10-03

**Context.** The test suite was added to an existing project that still needs
refactoring. Tests tied to internal structure would make that refactoring
harder instead of safer.

**Decision.** Tests assert observable, documented behavior:

- the map format and its documented defaults;
- public model behavior;
- system invariants of the simulation;
- documented travel-time rules.

They do not assert:

- private methods or internal data formats (for example, reservation tables);
- error message text;
- the order of equivalent results;
- `__repr__` output;
- code that the program never calls.

Exact values are asserted only where the rules leave a single correct answer.

**Rationale.** A test should fail only when user-visible behavior changes, so
the suite can guide refactoring rather than block it.

**Consequences.** Some lines stay uncovered on purpose. Coverage is reported
but not optimized as a target, and no coverage threshold is enforced yet.

---

## ADR-003

### Tests isolate and restore global random state

- **Status:** Accepted
- **Date:** 2026-10-03

**Context.** The weather system draws from the global `random` module, even
when no weather change can happen. A test that seeds or consumes it would
change the behavior of every test that runs after it.

**Decision.**

- Every test that triggers weather saves the global `random` state before it
  runs and restores it afterwards (a fixture).
- Tests that need reproducible randomness seed it explicitly.
- Tests assert invariants that hold for any random outcome, never a specific
  sequence of random events.

**Rationale.** Test results must not depend on run order, test selection, or
the internal order of random calls inside the weather system.

**Consequences.** Changing how weather draws random numbers does not break
tests, as long as the weather rules still hold.

---

## ADR-004

### Simulation invariants are checked against state rebuilt from events

- **Status:** Accepted
- **Date:** 2026-10-03

**Context.** The simulator publishes `CapacitySnapshot` events computed from
its own internal counters. Using them to verify capacity would let a counting
bug confirm itself.

**Decision.** `tests/support/simulation.py` rebuilds the position of every
aircraft on every turn using only `AgentMoved`, `AgentInTransit`, and
`WeatherChanged` events, and checks the rules against that independent state.
It covers:

- conservation of aircraft;
- moves only along existing lanes;
- no blocked hubs;
- hub and lane capacity at the end of each turn;
- restricted transit time on lanes without distance;
- no departures on closed lanes;
- final delivery.

`CapacitySnapshot` is not used as an oracle. The checker has its own
self-tests with hand-written event streams.

**Rationale.** An independent check is what found [BUG-001](bug-triage.md#bug-001)
and [BUG-002](bug-triage.md#bug-002), which the simulator's own counters did
not reveal.

**Consequences.** The checker must follow the documented movement and
occupancy rules. Where a rule is still undecided (for example
[DECISION-001](open-decisions.md#decision-001)), the checker does not enforce it.

---

## ADR-005

### Bundled maps are reference scenarios with documented turn budgets

- **Status:** Accepted
- **Date:** 2026-10-03

**Context.** The bundled maps exercise the whole system, but their exact
routes and turn counts depend on the current routing algorithm, which is
expected to improve.

**Decision.**

- Every bundled map must be fully delivered without any invariant violation.
- Runs without weather must be deterministic.
- Turn counts are checked as `<= budget`, where the budget is the documented
  performance target of the original assignment, not the current result.
- Maps without a documented target (challenger, bonus) are only required to
  finish.
- Routes and exact turn counts are never asserted on bundled maps.
- The number of turns is the number of simulated turns, not the number of
  printed lines (see [BUG-004](bug-triage.md#bug-004)).

**Rationale.** Algorithm improvements must not break tests; only regressions
past a documented target or broken rules should.

**Consequences.** A slower but still valid algorithm passes as long as it
stays within the documented targets.

---

## ADR-006

### Known bugs are not encoded as expected behavior in tests

- **Status:** Accepted
- **Date:** 2026-10-03

**Context.** Audits found defects that are not fixed yet. Tests could either
assert the current wrong behavior, mark failing reproducers as
`xfail`, or leave them out.

**Decision.**

- Tests never assert behavior that is recorded as a bug in
  [bug-triage.md](bug-triage.md), and known bugs are not added as `xfail`
  tests.
- Synthetic scenarios are chosen so that they test correct rules without
  hitting a known bug.
- A bug's reproducer becomes a regression test in the pull request that fixes
  it.

**Rationale.** A test that passes on wrong behavior makes the bug look
intended. An `xfail` test is easy to forget and passes silently when
behavior changes for an unrelated reason. The bug registry tracks open
defects explicitly instead.

**Consequences.** The test suite is green while known bugs exist. The bug
registry, not the test suite, is the source of truth for open defects.

---

## ADR-007

### Production bugfixes are separate from test-only pull requests

- **Status:** Accepted
- **Date:** 2026-10-03

**Context.** Test pull requests can reveal production bugs. Fixing them in the
same pull request mixes two kinds of review: "are these tests right?" and
"is this behavior change right?".

**Decision.** A test-only pull request does not change production code.
Production bugs it reveals are recorded in [bug-triage.md](bug-triage.md) and
fixed in separate pull requests that contain the fix together with its
regression test. For example, [BUG-001](bug-triage.md#bug-001) and
[BUG-002](bug-triage.md#bug-002), found by the pathfinding and simulation
test suite (PR #4), were fixed in a separate pull request (PR #5).

**Rationale.** Each pull request has one purpose and can be reviewed and
reverted on its own. The fix lands with the existing invariant suite already
in place as a safety net.

**Consequences.** There is a short period in which a known bug is documented
but not yet fixed.

---

## ADR-008

### Hub capacity counts aircraft flying towards the hub

- **Status:** Accepted
- **Date:** 2026-10-03

**Context.** The movement rules say an aircraft on a multi-turn leg must
arrive after the leg's travel time and cannot wait on the connection. The
simulator used to check a destination's capacity only at departure, against
its current occupancy, and placed arriving aircraft without any check. It
also counted a hub as freed by every planned departure, including departures
it later rejected. Both let hubs exceed their capacity
([BUG-001](bug-triage.md#bug-001), [BUG-002](bug-triage.md#bug-002)).

**Decision.**

- For capacity checks during execution, a hub's load is the aircraft in it
  plus the aircraft already in transit towards it. An arrival slot is held
  from departure until arrival.
- Each turn, all planned moves are validated as a set before any is applied.
  A hub counts as freed only by departures that are kept. Rejecting a move can
  invalidate others, so validation repeats until no move is rejected.
- `CapacitySnapshot` keeps reporting physical occupancy (aircraft in the hub),
  not this load.

**Rationale.** Holding the slot from departure is the simplest rule that
guarantees an in-flight aircraft always has room on arrival, without
predicting future departures. Validating moves as a set keeps the existing
rule that aircraft leaving a hub free their place in the same turn, while
never counting a departure that does not happen.

**Consequences.**

- Hub capacity can no longer be exceeded during execution. The randomized
  audit of 6,000 small graphs dropped from 474 violations to 0.
- A hub's slot is held for the whole multi-turn leg, which is more
  conservative than the planner's reservation at arrival time. On the bundled
  maps this changes nothing: output is byte-for-byte identical.
- The rule does not prevent deadlocks between aircraft waiting for each
  other ([BUG-003](bug-triage.md#bug-003)).
