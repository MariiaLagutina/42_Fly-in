# Engineering Decisions

A lightweight decision log (ADR style) for Maria's Airlanes. It records
decisions the project has already made and still follows, so a new contributor
can see why the code and tests look the way they do.

Questions that are still open live in [open-decisions.md](open-decisions.md).
Known defects live in [bug-triage.md](bug-triage.md).

Statuses: `Accepted`, `Accepted; partly superseded by ADR-XXX`,
`Superseded by ADR-XXX`, `Deprecated`. A superseded ADR keeps its original
text; the superseding ADR states what it replaces.

| ID | Title | Status |
| --- | --- | --- |
| [ADR-001](#adr-001) | Dependencies are locked; developer commands never modify the lockfile | Accepted |
| [ADR-002](#adr-002) | Tests protect contracts and invariants, not implementation details | Accepted |
| [ADR-003](#adr-003) | Tests isolate and restore global random state | Superseded by [ADR-012](#adr-012) |
| [ADR-004](#adr-004) | Simulation invariants are checked against state rebuilt from events | Accepted |
| [ADR-005](#adr-005) | Bundled maps are reference scenarios with documented turn budgets | Accepted |
| [ADR-006](#adr-006) | Known bugs are not encoded as expected behavior in tests | Accepted |
| [ADR-007](#adr-007) | Production bugfixes are separate from test-only pull requests | Accepted |
| [ADR-008](#adr-008) | Hub capacity counts aircraft flying towards the hub | Accepted |
| [ADR-009](#adr-009) | Python 3.14 is the single supported version; CI runs the local quality gates | Accepted |
| [ADR-010](#adr-010) | An aircraft in transit is committed to its leg | Accepted |
| [ADR-011](#adr-011) | Routing decisions are made at hubs; replanning is triggered by events | Accepted; partly superseded by [ADR-015](#adr-015) and [ADR-020](#adr-020) |
| [ADR-012](#adr-012) | Weather comes from a provider as a snapshot of the current state | Accepted |
| [ADR-013](#adr-013) | Routing uses explicit state; planner and executor share one capacity model | Accepted; partly superseded by [ADR-015](#adr-015) and [ADR-019](#adr-019) |
| [ADR-014](#adr-014) | Waiting happens in place; deadlocks are detected, not waited out | Accepted |
| [ADR-015](#adr-015) | Every hub is a safe waiting location; hub capacity has one layer | Accepted |
| [ADR-016](#adr-016) | Transport mode is map data; weather acts through one set of transport rules | Accepted |
| [ADR-017](#adr-017) | Road is a fallback with a consecutive-road budget | Accepted |
| [ADR-018](#adr-018) | Aircraft reroute only when weather makes their route unusable | Accepted |
| [ADR-019](#adr-019) | One capacity model; committed claims are the only live reservations | Accepted |
| [ADR-020](#adr-020) | Structural deadlocks are detected each turn and resolved or reported | Accepted |

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

- **Status:** Superseded by [ADR-012](#adr-012). Since PR #8, weather comes
  from providers that own their random generator, and no production code
  uses the global `random` module.
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

- **Status:** Accepted; partly superseded by [ADR-015](#adr-015) (hub
  safety, waiting, and weather diversion) and [ADR-020](#adr-020) (the
  no-progress threshold)
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

- **Status:** Accepted; partly superseded by [ADR-015](#adr-015) (two
  layers of hub capacity) and [ADR-019](#adr-019) (reservations v2)
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

---

## ADR-015

### Every hub is a safe waiting location; hub capacity has one layer

- **Status:** Accepted
- **Date:** 2026-10-04

**Context.** [ADR-011](#adr-011) allowed waiting only in a safe hub and
introduced weather diversion to a nearby safe hub. [ADR-013](#adr-013) added
weather emergency overflow so that a diverting aircraft could enter a full
hub. Both assumed that a hub can become unsafe. In the project's world model
weather acts on connections and transport modes, never on hubs.

**Decision.**

- **Hubs are always safe.** Every hub is always a safe waiting location.
  Weather affects connections and transport modes, not hub safety, so an
  aircraft never has to leave a hub because the hub became unsafe.
- **Waiting is always possible.** Waiting at the current hub is always
  physically safe. Routing policy may still prefer to continue or reroute.
- **Unavailable route.** A route is unavailable when it contains a connection
  that is unavailable under the current weather
  ([ADR-016](#adr-016)), or when it breaks a routing-policy limit such as
  the consecutive-road budget ([ADR-017](#adr-017)).
- **Reroute, not diversion.** If a route to the destination exists, taking it
  is a reroute, even when it passes through other hubs or returns to a hub
  visited before. There is no emergency diversion away from an unsafe hub,
  because there are no unsafe hubs.
- **No route means waiting.** If no route to the destination is currently
  available, the aircraft waits in its current hub. Moving to an intermediate
  hub without an available route to the destination (a positioning move) is
  deferred ([DECISION-010](open-decisions.md#decision-010)).
- **One capacity layer.** Hub capacity is the normal capacity (`max_drones`)
  only. There is no emergency overflow.

**Supersedes.**

- In [ADR-011](#adr-011):
  - the condition that waiting is valid only in a safe hub;
  - the "divert to a nearby safe hub because of weather" option, as an
    escape from an unsafe hub;
  - the consequences that waiting is valid only in a safe hub and that
    diversion needs a safe-hub definition and emergency capacity.

  Decision points, replanning triggers, continue, wait, reroute, and
  backtracking remain as accepted.
- In [ADR-013](#adr-013):
  - the "Two layers of hub capacity" decision;
  - the consequence that the invariant checker must tell overflow arrivals
    from capacity violations.

  Explicit routing inputs, one capacity model, reservations v2, and the
  executor as a safety layer remain as accepted.

**Rationale.** Overflow existed only for an aircraft that had to enter a full
hub. With every hub safe, no such aircraft exists:

- an aircraft in a hub can wait;
- an aircraft in transit already holds its destination slot
  ([ADR-008](#adr-008));
- start and end hubs have unlimited capacity.

A second capacity layer would add exceptions to the hub-capacity invariant
and special events without a use case.

**Consequences.**

- The hub-capacity invariant stays simple: no hub ever holds more aircraft
  than its normal capacity.
- [DECISION-004](open-decisions.md#decision-004) and
  [DECISION-005](open-decisions.md#decision-005) are decided.
- If a future weather source can close hubs themselves (for example, real
  airport closures), that is a new decision with new evidence.

---

## ADR-016

### Transport mode is map data; weather acts through one set of transport rules

- **Status:** Accepted
- **Date:** 2026-10-04

**Context.**

- Until PR #8 a lane's transport mode was inferred from its distance: under
  200 km meant road, longer meant air. The rule was repeated in the
  pathfinder, the parser's capacity defaults, and the dispatch center. A road
  leg could not be longer than 199 km, and an air leg could not be shorter
  than 200 km.
- Weather lived on `Connection` objects: storm and snow closed every lane,
  roads included.

The routing engine must not infer geography from coordinates, names, or
distances. The map has to say which transport exists.

**Decision.**

- **Mode is map data.** Each connection has a transport mode, `air` or
  `road`, set by `mode=air|road` in the map. The default is `air`. A lane
  without `distance` (the assignment's abstract maps) is an air lane, and
  its travel time still comes from the hub it enters.
- **Road needs a distance.** An explicit `mode=road` requires a positive
  numeric `distance`. An unknown mode or a non-numeric distance is a parse
  error.
- **Weather cannot create transport.** Weather never creates a connection or
  a transport mode, and never changes a connection's distance. A weather
  state that names a connection the map does not define is rejected.
- **One transport-rules boundary.** `transport.py` turns the current weather,
  a connection's mode, and its static data into availability and travel
  time. Simulator and pathfinder do not branch on weather conditions
  themselves.
- **Availability.** Air legs are unavailable in storm and snow. Road legs are
  available in any weather. Bad weather only makes them slower.
- **Travel time.** Road legs travel at 100 km/h and air legs at 400 km/h.
  Tailwind affects only air legs. Rain, snow, and storm slow road legs.
- **Provisional penalties.** The current numbers (rain +1 turn on roads,
  storm or snow +2, tailwind halves air distance) are transitional. Their
  final semantics belong to [DECISION-001](open-decisions.md#decision-001).
- **One lane per pair.** Two connections between the same pair of hubs, such
  as an air lane and a road lane, are not supported
  ([DECISION-009](open-decisions.md#decision-009)).

**Rationale.** A map that lists its transport options is explicit and
testable. Islands, seas, and borders need no special code: a map without a
road between two hubs has no road there. Keeping all weather-and-mode rules in
one module lets the cost model change later without touching routing or
execution.

**Consequences.**

- Bundled maps keep their behavior. The ten Germany lanes under 200 km are
  marked `mode=road`, and every other bundled lane was already an air or
  abstract lane.
- A map written for the old rule that relies on short lanes being roads must
  add `mode=road`. Otherwise those lanes become air lanes (400 km/h, default
  capacity 1, closed in storm and snow).
- Weather runs on maps with road lanes change: aircraft drive through storm
  and snow instead of waiting for them to clear.

---

## ADR-017

### Road is a fallback with a consecutive-road budget

- **Status:** Accepted
- **Date:** 2026-10-04

**Context.** Maria's Airlanes is primarily an air-routing system. With roads
open in any weather ([ADR-016](#adr-016)), routing could turn a flight into
an arbitrarily long drive. Germany already has a chain of six road lanes,
745 km long.

**Decision.**

- **Budget.** Routing limits the total consecutive road distance of a route
  with the routing-policy value `max_consecutive_road_km`. The default is
  700 km. It is one explicit, configurable value, not a constant repeated in
  routing code.
- **What counts.** The limit applies to the sum of consecutive road legs, not
  to each leg. An air leg resets it. Examples:
  - 250 km road + 300 km road = 550 km: allowed;
  - 400 km road + 400 km road = 800 km: not allowed;
  - 500 km road → air → 600 km road: allowed.
- **Policy, not physics.** A road beyond the limit may physically exist.
  Routing only declines to use it as part of an Airlanes journey.
- **No special cases.** Road fallback arises from routing over the currently
  usable topology. There is no rule of the form "in a storm, take the car".
  In good weather air normally wins because it is faster. When weather closes
  an air lane, an existing road route within the budget may become the best
  usable alternative. Otherwise the aircraft waits or uses another air route.
- **When it applies.** The budget is enforced by dynamic routing in PR #9,
  together with the routing-policy configuration and the road distance each
  aircraft has driven since its last air leg. PR #8 adds no unused setting.

**Rationale.** The limit keeps road travel a fallback while still letting it
bridge gaps that weather opens in the air network. Counting the consecutive
segment, rather than single legs, prevents chains of short roads from adding
up to a long drive.

**Consequences.**

- Route search must track the road distance driven since the last air leg as
  part of its state, and an aircraft carries it across replanning.
- Until PR #9, routes are not checked against the budget. On the bundled
  maps, planned routes use at most 245 km of consecutive road.

---

## ADR-018

### Aircraft reroute only when weather makes their route unusable

- **Status:** Accepted
- **Date:** 2026-10-04

**Context.** [ADR-011](#adr-011) separates decision points from replanning
triggers and leaves the comparison of options to a routing policy
([DECISION-006](open-decisions.md#decision-006)). Weather providers give no
forecasts ([ADR-012](#adr-012)), and every hub is a safe place to wait
([ADR-015](#adr-015)). A prototype on all bundled maps (30 seeds each, see
[dynamic-routing.md](dynamic-routing.md#since-pr-9)) compared:

- searching when only the next leg is unavailable;
- searching when any leg of the remaining route is unavailable;
- recomputing the fastest route on every turn.

**Decision.**

- **Decision point.** Every turn, each aircraft waiting at a hub checks its
  remaining route. Planned waits are not legs. Aircraft in transit are not
  considered ([ADR-010](#adr-010)).
- **Trigger.** A route search runs only when a leg of the remaining route is
  unavailable under the current weather. Routes are always planned within
  the consecutive-road budget from the aircraft's current road distance, so
  only weather can make them unusable.
- **Reroute.** If a route to the destination is available, the aircraft
  takes it. The route is the fastest under the current weather, ignores
  other aircraft, never visits a hub twice, and respects the road budget.
  An `AgentRerouted` event records the hub and the new route.
- **Wait.** If no route is available, the aircraft waits and keeps its old
  route, which it continues as soon as the weather allows.
- **No comparison while usable.** A usable route is kept even if another
  route has become faster. There is no periodic re-optimization and no
  hysteresis setting.
- **Road budget everywhere.** The initial cooperative plan, the route search,
  and the executor all follow `RoutingPolicy.max_consecutive_road_km`
  ([ADR-017](#adr-017)). A map whose only route breaks the budget fails
  before the first turn.
- **Search state.** A search state includes the consecutive road distance.
  A partial route is dropped only when another one reached the same state
  (hub, or hub and turn) with no higher cost and no more road.
- **Deferred to PR #10.** A trigger for aircraft that make no progress
  because of capacity. In the prototype it resolved every BUG-003 deadlock,
  so it belongs with deadlock handling.

**Rationale.**

- Searching on any unusable leg reroutes before an aircraft flies into a
  dead end. Searching only on the next leg brought aircraft up to the closed
  lane and jammed them there: the challenger map averaged 362 turns instead
  of 91.
- Recomputing every turn made aircraft switch back and forth (1,421 A-B-A
  switches against 243 weather-driven ones) and changed outputs even without
  weather.
- Ignoring other aircraft keeps routing separate from capacity, which stays
  the executor's job until reservations v2 (PR #10).

**Consequences.**

- Without weather nothing changes: no route becomes unusable, and the road
  budget does not change any bundled plan.
- Weather runs change wherever a route becomes unusable.
- A rerouted aircraft drops its remaining planned waits and is no longer
  coordinated with the others. Capacity stays safe, but turn counts on
  crowded maps can grow until PR #10.
- The weather reproducers of [BUG-003](bug-triage.md#bug-003) no longer hang:
  after more than a hundred blocked turns, weather closes a lane on the
  blocked route and one aircraft reroutes. The root cause remains.

---

## ADR-019

### One capacity model; committed claims are the only live reservations

- **Status:** Accepted
- **Date:** 2026-10-05

**Context.** [ADR-013](#adr-013) requires that planner and executor apply
one capacity model and planned live reservations owned by aircraft. They
disagreed in three ways:

- the planner booked a hub only on the turn an aircraft arrived, while the
  executor holds it from the departure of a leg towards it
  ([ADR-008](#adr-008));
- the planner checked a lane without a distance only on the departure turn
  of a two-turn leg, while the executor counts the aircraft on the lane
  until it arrives;
- the executor handed out a lane's capacity and its one departure slot
  before it knew whether the move fit its destination hub, so a rejected
  move kept the lane from an aircraft that could leave
  ([BUG-003](bug-triage.md#bug-003) variant B).

Both sides allowed one departure per distance lane per turn in either
direction, which forbade two aircraft from swapping full hubs over a lane
with room for both (variant A, [DECISION-008](open-decisions.md#decision-008)).

The PR #10 audit (see [dynamic-routing.md](dynamic-routing.md#since-pr-10))
measured 10,000 random maps without weather: 1,681 had an aircraft
delivered later than planned and 13 hung. It also tried rerouting against
reservations derived from every other aircraft's remaining route: turn
counts moved both ways, structural deadlocks became more frequent (18
instead of 4 in the weather runs), and runs took 2.8 times longer.

**Decision.**

- **Shared rules.** Planner and executor apply the same capacity rules:
  - a hub's load is the aircraft in it plus the aircraft flying towards it,
    and never exceeds its capacity at the end of a turn; start and end hubs
    are unlimited;
  - a leg holds its destination hub from its departure turn to its arrival
    turn;
  - a lane is held on every turn of a leg, from departure to arrival,
    whatever its distance, and both directions count towards its capacity;
  - a distance lane allows one departure per direction per turn
    (DECISION-008);
  - a hub is freed in the same turn only by aircraft that actually leave.
- **Lanes go only to admitted moves.** The executor collects the aircraft
  that want to leave, hands out lanes in aircraft order, and keeps the
  moves that fit their hubs. A move that holds a lane but cannot enter its
  hub is excluded for that turn and the lanes are handed out again. Each
  round excludes one move, so the selection is bounded and deterministic.
- **No reservation store.** What an aircraft holds now is derived from its
  state, not stored:
  - its place in its hub;
  - while in transit, its claim on the destination hub and its place on
    the lane, created at departure and turned into occupancy on arrival.

  Future hubs, lanes, and waits are tentative. They exist only while the
  cooperative planner builds the initial routes, and in each aircraft's
  route. A reroute replaces the route; there is nothing to release.
- **Executor as a safety layer.** The executor still validates every move.

**Rationale.**

- With the same rules, a plan that the planner accepts is a plan the
  executor runs: on the 10,000 random maps, no aircraft is late and none
  hangs. Bundled map output does not change.
- A rejected move gives nothing up. Handing lanes only to admitted moves
  removes the wasted-lane deadlock without any retry loop.
- Opposite directions do not compete for a departure slot, which models
  takeoff separation within one direction. Removing the rule completely
  would change the bonus maps (Germany from 14 to 9 printed turns).
- Derived claims cannot leak: every claim belongs to an aircraft's current
  state. Live future reservations did not make rerouting better.

**Consequences.**

- The "Reservations v2" part of ADR-013 is replaced: reservations are not
  stored live; committed claims are derived and future reservations stay
  tentative. The rest of ADR-013 stands.
- A rerouted aircraft is still not coordinated with the others. Deadlocks
  that follow are detected and handled ([ADR-020](#adr-020)).
- The planner is more conservative. Measured for the capacity-model
  change alone (lanes only for admitted moves, plus this ADR's shared
  rules), on the random maps 813 runs finish sooner and 9 later than
  before, by up to 9 turns. This is not the result of the whole PR #10; see
  [dynamic-routing.md](dynamic-routing.md#since-pr-10) for the final
  comparison.
- The invariant checker verifies the hub load including aircraft in
  transit and the departure rule.

---

## ADR-020

### Structural deadlocks are detected each turn and resolved or reported

- **Status:** Accepted
- **Date:** 2026-10-05

**Context.** [ADR-014](#adr-014) requires deadlocks to be detected and
handled, and [ADR-011](#adr-011) proposed a no-progress threshold as a
replanning trigger. After [ADR-019](#adr-019), plans without weather
execute exactly. Deadlocks remain possible after weather reroutes, which
ignore other aircraft ([ADR-018](#adr-018)): for example, two aircraft in
full hubs that each need the other's hub over a lane for one aircraft. No
legal next state exists, and the run used to continue until the
10,000-turn limit. A turn without movement is not a deadlock: aircraft can
be in transit, wait for weather, or follow a planned wait. The planner also
used routes that left a hub and came back only to pass time, which created
opposite traffic ([DECISION-007](open-decisions.md#decision-007)).

**Decision.**

- **Definition.** After each turn's moves, a structural deadlock is the
  largest set of aircraft at hubs such that:
  - each tried to leave on a lane open under the current weather and was
    not admitted;
  - everything that blocks it is a member: the aircraft in or flying to its
    full destination hub, and the aircraft on its full lane.

  Nothing outside the set can release it. An aircraft that waits for
  weather, a planned wait, or an aircraft in transit is never a member.
- **Response.** On the turn a deadlock is found:
  1. the first member, in aircraft order, with a route under the current
     weather that avoids the hub it waits for takes that route
     (`AgentRerouted` with reason `deadlock`);
  2. if no member has one now, but one would exist with every lane open,
     the aircraft wait and the check repeats on the next turn;
  3. otherwise the run stops with `DeadlockError`, which names the turn,
     the aircraft, and their hubs.
- **The clear-weather check is not a forecast.** It never predicts future
  weather. It is a classification probe: is a way out structurally possible
  under the topology and the routing policy once the current, temporary
  weather restriction is removed? If yes, the situation may change, so the
  aircraft wait. If no, no weather can help.
- **No no-progress threshold.** The threshold proposed in ADR-011 is not
  added.
- **Waiting happens in place.** A planned route never returns to a hub it
  has left. Revisiting a hub happens only across decisions: a reroute, a
  deadlock way-around, or backtracking plans a simple route from the
  current hub. No route search can loop to reset the road budget.
- **`AgentRerouted.reason`.** Every reroute says why it happened: `weather`
  or `deadlock`.

**Rationale.**

- The definition needs no history and no guessed number of turns. The
  members hold every resource they wait for, so the state repeats until a
  route changes.
- A threshold cannot tell a deadlock from a long wait for weather or a
  planned wait. It would only add a second, weaker detector.
- A route that avoids the blocked hub is the smallest change that breaks
  the cycle. Only one aircraft reroutes per turn, so the response stays
  deterministic.
- Stopping with a named error turns a silent hang into a diagnosable
  failure.
- Simple routes remove the waiting cycles that created opposite traffic.

**Consequences.**

- Waiting forever for a lane that never reopens is not a deadlock. Such a
  run still ends at the 10,000-turn limit.
- Three bundled maps change routes and keep their turn counts: an aircraft
  that used to fly out and back from the start now waits there.
- Supersedes the no-progress threshold of ADR-011 and refines the deadlock
  handling of ADR-014.
- Resolves [DECISION-007](open-decisions.md#decision-007).
