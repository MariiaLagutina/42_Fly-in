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
| [ADR-009](#adr-009) | Python 3.14 is the single supported version; CI runs the local quality gates | Accepted |
| [ADR-010](#adr-010) | An aircraft in transit is committed to its leg | Accepted |
| [ADR-011](#adr-011) | Routing decisions are made at hubs; replanning is triggered by events | Accepted |
| [ADR-012](#adr-012) | Weather comes from a provider as a snapshot of the current state | Accepted |
| [ADR-013](#adr-013) | Routing uses explicit state; planner and executor share one capacity model | Accepted |
| [ADR-014](#adr-014) | Waiting happens in place; deadlocks are detected, not waited out | Accepted |

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

---

## ADR-009

### Python 3.14 is the single supported version; CI runs the local quality gates

- **Status:** Accepted
- **Date:** 2026-10-04

**Context.** The project started as a school assignment that required
Python 3.10 compatibility. That requirement no longer applies: Maria's
Airlanes is developed and run on Python 3.14, but `pyproject.toml` still
declared `>=3.10`, and nothing checked the code automatically on any
version.

**Decision.**

- The project moves from its historical Python 3.10 support to Python 3.14.
- Python 3.14 is the only officially supported and tested version for now.
- No compatibility matrix is used, on purpose.
- CI runs the same quality gates that are available locally through the
  Makefile (`make lint-strict` and `make test`), against the locked
  dependencies.
- The supported version is stated in three places that must agree:
  `requires-python` in `pyproject.toml` declares the project's requirement,
  `.python-version` sets the default interpreter for local tooling and uv,
  and CI explicitly tests on Python 3.14.

**Rationale.** One version keeps the setup simple and lets the code use
current language features. Supporting older versions would cost testing and
maintenance without serving any current user. Running the Makefile targets
in CI means a green local `make check` and a green CI run check the same
things.

**Consequences.**

- Python 3.10–3.13 are no longer supported. Backport packages that only older
  versions needed are dropped from the lockfile.
- Adding another supported version later is an explicit decision that
  changes `requires-python` and adds a matrix to CI.
- Changing the supported version means updating `pyproject.toml`,
  `.python-version`, `uv.lock`, the CI workflow, and the README together.

---

## ADR-010

### An aircraft in transit is committed to its leg

- **Status:** Accepted
- **Date:** 2026-10-04

**Context.** Routing is becoming dynamic: aircraft will change their routes
as the weather and traffic change ([dynamic-routing.md](dynamic-routing.md)).
The movement rules already say an aircraft on a multi-turn leg cannot wait
on the connection. The open question was whether a route may also change
while an aircraft is flying a leg.

**Decision.** Once an aircraft departs on a leg, it is committed to that leg
until it arrives:

- it is not replanned in flight;
- its travel time is fixed at departure;
- later weather changes do not affect the leg already started;
- its destination hub's slot stays held, as in [ADR-008](#adr-008).

All routing decisions are made at hubs.

**Rationale.** It matches the existing movement rules and keeps execution
simple to reason about: an aircraft in the air has exactly one possible
outcome. It also keeps the hub-capacity guarantee of ADR-008, which depends
on knowing where every aircraft in transit will arrive.

**Consequences.**

- An aircraft that departs just before a lane closes still completes that
  leg. Weather affects it only at its next decision point.
- Weather diversion ([ADR-011](#adr-011)) starts from a hub, never mid-leg.

---

## ADR-011

### Routing decisions are made at hubs; replanning is triggered by events

- **Status:** Accepted
- **Date:** 2026-10-04

**Context.** Every route is planned once, before the first turn, and never
changes. With weather, most aircraft on the larger maps fall behind their
plans (up to 97% on the challenger map), and an aircraft facing a closed lane
can only wait. A single cooperative route search costs up to about 20 ms on
the largest map, so searching again for every aircraft on every turn is too
expensive. Evidence is in [dynamic-routing.md](dynamic-routing.md#evidence).

**Decision.**

- **Decision point.** Each turn an aircraft spends at a hub, routing policy
  decides what it does that turn.
- **Replanning trigger.** A new route search runs only when a trigger fires.
  The minimum triggers are:
  - the remaining route is invalidated: under the current weather it is
    unavailable or contains an unusable lane;
  - the aircraft has waited without progress for a number of consecutive
    turns that reaches a threshold.
- **Threshold.** The threshold is an explicit, configurable routing-policy
  parameter. Its default is chosen from evidence when it is implemented.
- **Routing options.** At a decision point, policy chooses one of:
  - continue toward the destination on the current route;
  - wait in the current hub, only if that hub is safe;
  - reroute toward the destination;
  - divert to a nearby safe hub because of weather.
- **Weather can change the goal.** Weather may change the aircraft's
  immediate routing goal, not only the cost or availability of a lane.
- **Backtracking.** Returning to a previously visited hub is a valid result of
  a decision made on the current state.
- **Comparing options.** Policy compares the options using the current state.
  The delay model it uses (estimated time until a lane reopens, ETA, fallbacks)
  is not part of this decision ([DECISION-006](open-decisions.md#decision-006)).

**Rationale.**

- Separating decision points from triggers keeps the common case cheap:
  following a valid route costs nothing extra, and a search runs only when
  something changed.
- Diversion and backtracking are needed because weather can make both the
  route ahead and the current position a poor place to be. A global ban on
  revisiting hubs would forbid exactly these decisions.

**Consequences.**

- Waiting is no longer the automatic answer when the destination is
  unreachable. It is valid only when the current hub is safe.
- Diversion needs a definition of a safe hub and of the diversion target
  ([DECISION-004](open-decisions.md#decision-004)), and emergency hub capacity
  ([ADR-013](#adr-013), [DECISION-005](open-decisions.md#decision-005)).
- Turn counts with weather enabled will change. Without weather, execution on
  the bundled maps currently follows the plan exactly, so no trigger fires
  and this decision alone does not change routes there.
- Replanning makes [DECISION-002](open-decisions.md#decision-002) decided.

---

## ADR-012

### Weather comes from a provider as a snapshot of the current state

- **Status:** Accepted
- **Date:** 2026-10-04

**Context.** `WeatherSystem` draws from the global `random` module and mutates
`Connection` objects in place. Tests cannot script a weather sequence, they
must save and restore global random state ([ADR-003](#adr-003)), and the code
draws random numbers even when no storm can start. Real weather is planned
later as another source, and it must never be needed to run the tests.

**Decision.**

- The weather boundary is
  `WeatherProvider → WeatherState → Simulator / routing state`.
- A `WeatherProvider` produces the weather for a turn. Planned providers:
  - `NoWeather`;
  - `RandomWeather`, seeded, with its own `random.Random` instance;
  - `ScriptedWeather`, a fixed schedule for deterministic tests;
  - later, a real-weather provider.
- `WeatherState` is a snapshot of the current, normalized weather in the
  project's own domain terms. It describes what is observed now. Providers
  are not required to supply forecasts or expected durations.
- The simulator turns changes between snapshots into `WeatherChanged`
  events. Routing reads `WeatherState` and never calls a provider, an HTTP
  client, or an external API.
- Random weather stays available as a normal mode. The test suite never
  depends on the global `random` module or on network access.
- Planner and executor will compute travel time in one place.
  [DECISION-001](open-decisions.md#decision-001) remains open until PR #10.

**Rationale.** A snapshot of observed weather is something every source can
supply, including a real-weather API that cannot predict how many simulation
turns a condition will last. Owning the random generator makes runs
reproducible from a seed and lets tests script weather without touching
global state.

**Consequences.**

- `WeatherSystem` is replaced by providers. Connection objects stop being
  the place where weather lives.
- ADR-003's save-and-restore fixture becomes unnecessary once no code path
  uses the global `random` module.
- Any routing policy that needs an expected delay must estimate it itself or
  use optional provider information
  ([DECISION-006](open-decisions.md#decision-006)).
- Whether hubs also have weather is part of
  [DECISION-004](open-decisions.md#decision-004).

---

## ADR-013

### Routing uses explicit state; planner and executor share one capacity model

- **Status:** Accepted
- **Date:** 2026-10-04

**Context.** The planner and the executor apply different capacity rules:

- the planner books a hub only on the turn an aircraft arrives;
- the executor holds the slot from departure ([ADR-008](#adr-008)) and gives
  each distance lane one departure per turn.

Without any weather, 487 of 3,000 random graphs are delivered later than
planned, and 6 deadlock. Reservations exist only while routes are planned
before the first turn. Route search also reads model objects and zone fields
directly, which will not survive dynamic routing.

**Decision.**

- **Explicit inputs.** Route search depends only on explicit inputs and is
  deterministic with respect to them:
  - the static network;
  - the current `WeatherState`;
  - the current turn;
  - current occupancy and commitments, including aircraft in transit;
  - live reservations, once they exist;
  - the routing request.

  It does not read `Drone` objects as hidden state, mutate the graph, use the
  global `random` module, or call a weather provider.
- **One capacity model.** The planner and the executor apply the same capacity
  rules. Evaluated against the same state and the same rules, they must not
  disagree about resource feasibility. A move or reservation that the planner
  accepts as capacity-feasible must not be rejected by the executor merely
  because the executor applies a different capacity model. This does not
  promise that a whole schedule always executes: scheduling, departure, and
  deadlock semantics are refined in PR #9 and
  [DECISION-008](open-decisions.md#decision-008).
- **Reservations v2.**
  - Reservations are live state, not a one-time table built before the
    simulation.
  - Each reservation is owned by an aircraft.
  - On a reroute, the aircraft's future reservations are released. Its current
    hub occupancy and its committed transit stay.
- **Executor as a safety layer.** The executor keeps validating every move at
  runtime.
- **Two layers of hub capacity.** Normal capacity is available to all routing
  and planning. Weather emergency overflow is available only to qualifying
  weather-diversion arrivals, and ordinary routing never consumes it.
  Overflow never changes a hub's normal capacity. Its amount is policy or
  configuration, not an architectural constant. The details are in
  [DECISION-005](open-decisions.md#decision-005).
- **Scope.** PR #8 adds dynamic replanning without reservations v2. Planner,
  executor, and reservations are aligned in PR #9.

**Rationale.**

- A plan is only useful if execution judges its moves by the same rules.
  With two capacity models, plans diverge even in a world that never changes.
- Explicit inputs make route search testable on its own and keep weather
  sources replaceable.
- Keeping the executor's checks means a planning mistake can delay an aircraft
  but never break a capacity rule.

**Consequences.**

- Cooperative planning is kept. It keeps the bundled maps within their turn
  budgets ([ADR-005](#adr-005)).
- Aligning the capacity model may change routes and turn counts on the
  bundled maps. Turn budgets stay the acceptance criterion.
- The invariant checker must be able to tell overflow arrivals from capacity
  violations, so diversions must be visible in events.

---

## ADR-014

### Waiting happens in place; deadlocks are detected, not waited out

- **Status:** Accepted
- **Date:** 2026-10-04

**Context.** [BUG-003](bug-triage.md#bug-003) deadlocks also occur without
weather. In all 6 deadlocks found without weather, the opposite-direction
traffic comes from routes that leave a hub and come back only to pass time,
and every one of those loops runs through a priority hub, whose cost discount
makes a loop cheaper than waiting. The same holds for 715 of the 1,516
revisiting routes in the random audit.
When aircraft block each other, nothing detects it, and the run continues
until the 10,000-turn limit.

**Decision.**

- **Waiting is staying in the current hub.** Routes must not create
  artificial cycles through other hubs as a way of waiting.
- **Revisits are not banned.** A route may return to a hub when the current
  state makes that the right decision, for example backtracking or a weather
  diversion ([ADR-011](#adr-011)). When a revisit is legitimate and when it
  should be limited stays open until PR #9
  ([DECISION-007](open-decisions.md#decision-007)).
- **Departure slots.** A distance lane's departure slot is given only to a
  move that has passed the hub-capacity check (fixes BUG-003 variant B).
- **Deadlock detection.** Deadlocks are detected from a wait-for graph between
  aircraft at hubs. A cycle that no weather change or arrival can release is a
  deadlock.
- **Deadlock handling.** A detected deadlock is resolved where possible. If it
  cannot be resolved, the run stops with a clear error instead of reaching the
  turn limit. The resolution strategy is designed in PR #9.

**Rationale.** Waiting in place costs the same time without using lanes or
other hubs, so artificial cycles only add traffic. Detection turns a silent
hang into either a resolved situation or an explicit, diagnosable failure.

**Consequences.**

- Route cost or search must make an artificial cycle no cheaper than waiting,
  including through priority hubs.
- Four routes on the bundled maps currently leave the start and return to it.
  They may change.
- Whether the one-departure-per-turn rule applies per lane or per direction
  is open ([DECISION-008](open-decisions.md#decision-008)). In both variant A
  reproducers it blocks the swap even when lane capacity would allow it.
