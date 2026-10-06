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
| [ADR-018](#adr-018) | Aircraft reroute only when weather makes their route unusable | Accepted; partly superseded by [ADR-021](#adr-021) |
| [ADR-019](#adr-019) | One capacity model; committed claims are the only live reservations | Accepted |
| [ADR-020](#adr-020) | Structural deadlocks are detected each turn and resolved or reported | Accepted |
| [ADR-021](#adr-021) | Weather that slows a route triggers its reconsideration; route cost is the transport travel time | Accepted |
| [ADR-022](#adr-022) | Package structure and layer boundaries | Accepted; partly superseded by [ADR-024](#adr-024) |
| [ADR-023](#adr-023) | The simulation result keeps every completed turn; the output decides what to print | Accepted; partly superseded by [ADR-024](#adr-024) |
| [ADR-024](#adr-024) | Turn results are typed outcomes of completed turns | Accepted |

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

- **Status:** Accepted; partly superseded by [ADR-021](#adr-021) (the
  trigger, and keeping a usable route without comparison)
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

---

## ADR-021

### Weather that slows a route triggers its reconsideration; route cost is the transport travel time

- **Status:** Accepted
- **Date:** 2026-10-05

**Context.** [ADR-018](#adr-018) searches for a new route only when the
weather closes a leg of the remaining route, and keeps a usable route even
if another one has become faster. Roads stay open in rain, snow, and storm,
but get slower ([ADR-016](#adr-016)), so a road route could become much
slower without the aircraft ever looking for another one. The route search
already costs routes with the transport rules under the current weather;
the trigger never reached it for a slowdown. The initial plan is made
before any weather is observed. Weather is a snapshot of the current state,
not a forecast ([ADR-012](#adr-012)), and the weather travel times were
provisional until this decision
([DECISION-001](open-decisions.md#decision-001)).

**Decision.**

- **Initial plan.** The cooperative plan made before the first turn is a
  deterministic clear-weather baseline, on purpose. The first observed
  weather is that of turn 1. The simulator reads it at the start of turn 1,
  and every aircraft passes its decision point before any departure, so no
  aircraft leaves without it.
- **One source of route cost.** The cost of a route is the sum of
  `transport.travel_time` over its legs under the current weather. Routing
  adds no weather penalties of its own. Planned waits are not legs.
- **Availability stays separate.** Whether a leg can start is decided by
  `transport.is_available`. A closed leg makes the cost of a route
  infinite.
- **Trigger: degradation.** At a decision point, an aircraft reconsiders
  its route when the current weather makes the remaining route slower than
  the same route in clear weather. A closed leg counts as infinitely slow,
  so the trigger of ADR-018 is a special case of this one.
- **Reconsidering is not rerouting.** The search is that of ADR-018: the
  fastest route under the current weather, ignoring other aircraft, never
  visiting a hub twice, and within the road budget from the aircraft's
  current road distance.
  - A route that is still open is replaced only by a route that is strictly
    faster under the same weather snapshot. A tie keeps the current route.
  - A closed route is replaced by any route found. With none, the aircraft
    waits in the hub and keeps its route, as before.
- **The whole remaining route is costed under the current snapshot.** This
  is the semantics ADR-018 already uses for the availability of later legs.
  It is not a forecast: no duration is inferred. The cost of the next leg
  is exact, because a leg's travel time is fixed when it starts.
- **Asymmetry.** Weather that only makes routes faster, such as a
  tailwind, never triggers reconsideration: a route that is not slowed is
  kept. Once a slowdown elsewhere has triggered it, the search uses the
  whole current snapshot, so an alternative that a tailwind makes faster can
  win.
- **Weather travel times are final.** Rain adds one turn to a road leg,
  storm and snow add two, and a tailwind halves the distance of an air leg.
  They are no longer provisional.
- **Restricted hubs** do not change travel time on lanes with a distance.
  Whether they should is a separate question
  ([DECISION-011](open-decisions.md#decision-011)).

**Rationale.** A prototype compared five designs with the current behavior
on the 12 bundled maps with seeded `RandomWeather`, 30 seeds each (360 runs
per design):

| Design | Mean turns | Faster / slower runs | Changed outputs |
| --- | ---: | ---: | ---: |
| Current: search only when a leg is closed | 25.52 | — | — |
| Search when slowed, whole route costed (chosen) | 25.48 | 3 / 0 | 5 |
| Search when the next leg is slowed, next leg costed | 25.55 | 2 / 4 | 21 |
| Search whenever any weather exists | 25.28 | 52 / 29 | 111 |
| Initial plan under turn-1 weather | 25.45 | 8 / 4 | 30 |
| Initial plan under turn-1 weather, search when slowed | 25.41 | 11 / 4 | 34 |

- **Whole route, not the next leg.** Costing only the next leg ignores a
  slowdown that is already observed further along the route, and it
  disagrees with how ADR-018 treats a closed later leg.
- **No opportunistic search.** Searching whenever any weather exists breaks
  the spreading of the cooperative plan: on Europe it costs 2.67 turns on
  average, and over all maps 29 runs get slower.
- **No weather in the initial plan.** Planning with turn-1 weather needs
  that weather before planning. `RandomWeather` keeps state, so it would
  have to be cached. The cooperative search would also need a reachability
  check under the same weather, or it does not terminate while a lane stays
  closed. And it would build the snapshot into a plan that spans many
  turns. It gave no clear gain.
- **Fixed extra turns stay.** Speed factors would add constants and change
  every weather run on Germany, without evidence that they describe roads
  better.

**Consequences.**

- **Without weather nothing changes.** All 12 bundled maps produce the same
  output, and so do all 36 command-line runs in the default,
  `--capacity-info`, and `--airlines` modes.
- **With seeded weather** (360 runs), 5 runs change, all on Germany: 3 are
  faster (22 to 19, 23 to 15, and 19 to 17 turns), none is slower. Germany
  averages 15.63 turns instead of 16.07. On the other maps weather only
  closes lanes or makes them faster, so nothing changes. 0 invariant
  violations, 0 errors.
- **Known limitation: herd behavior.** Reconsidering ignores other
  aircraft, so several aircraft at one hub can switch to the same route at
  once, and switch back when the weather moves. In two Germany runs, 14
  extra reroutes gained no turn.
- **Known limitation: road-budget deadlocks.** Uncoordinated rerouting can
  change which structural deadlock the consecutive-road budget makes
  impossible to leave ([ADR-020](#adr-020)). On 40,000 random road-heavy
  maps with scripted rain, snow, and storm, `DeadlockError` occurred 3 times
  before and 3 times after this change. One map fails in both versions; two
  fail only before and two only after. With an unlimited road budget, both
  maps that fail only after are delivered. The rate did not increase.
- **Runtime.** With weather, runs on the bundled maps take 10 to 20% longer:
  each waiting aircraft's route is evaluated twice per turn. Without weather
  runtime is unchanged.
- **Replaces** the trigger of ADR-018 and its rule that a usable route is
  never compared with alternatives. Decides the weather part of
  [DECISION-001](open-decisions.md#decision-001) and the open note of
  [DECISION-006](open-decisions.md#decision-006).

---

## ADR-022

### Package structure and layer boundaries

- **Status:** Accepted; partly superseded by [ADR-024](#adr-024) (the
  dependencies of `output` and `simulation` on the new `results` module,
  and what `resolve_deadlock` returns)
- **Date:** 2026-10-06

**Context.** All application code lived in seventeen flat modules at the
repository root. Nothing showed which module may depend on which, and
`simulation.py` combined turn execution with two self-contained decision
procedures: departure arbitration ([ADR-019](#adr-019),
[DECISION-008](open-decisions.md#decision-008)) and deadlock handling
([ADR-020](#adr-020)). Both could be tested only through whole simulation
runs. The next step, the Output & event audit, works on the boundary
between the simulation and its outputs, so that boundary had to be visible
first. The refactor was not allowed to change behavior.

**Decision.**

- **One application package.** All application code, including the images
  the Pygame viewers load at runtime, lives in the `airlanes/` package.
  Outside it are only the tests (`tests/`), map data that is passed in by
  path (`maps/`), documentation, and the `main.py` entry point.
- **A root package, not a `src/` layout.** The project runs from a checkout:
  `uv` does not build it (`package = false`), and the tests import it from
  the repository root. A `src/` layout guards against importing an
  uninstalled tree instead of the installed package; with nothing
  installed, that protection has no use, and the root layout keeps both
  entry points working from a checkout.
- **Not installable yet.** There is no build backend and no console script.
  Making the package installable changes the dependency setup and how the
  project is distributed, and nothing needs it now. It is a separate
  decision.
- **Responsibilities:**

  | Package or module | Responsibility |
  | --- | --- |
  | `config` | Speeds, weather penalties, and cost weights |
  | `model` | Hubs, lanes, the network, aircraft state, and transport modes |
  | `world` | Weather providers and state, and the transport rules that apply the weather to a lane |
  | `routing` | The cooperative initial plan, route search, route cost, and the routing policy |
  | `simulation` | Turn execution (`engine`), departure arbitration (`departures`), and deadlock resolution (`deadlock`) |
  | `events` | Typed simulation events and the dispatcher |
  | `mapfile` | Reads map files into a network, reports `ParseError` |
  | `output` | Text output (`output.text`) and the Pygame viewers with their images (`output.pygame`) |
  | `cli` | The command line: arguments, wiring, and the choice of output |

- **Dependency directions.** Besides its own modules, a package depends
  only on the packages listed for it:

  | Package | May depend on |
  | --- | --- |
  | `config`, `events`, `model` | nothing else in the application |
  | `world` | `model`, `config` |
  | `routing` | `model`, `world`, `config` |
  | `simulation` | `model`, `world`, `routing`, `events`, `config` |
  | `mapfile` | `model`, `world` |
  | `output` | `model`, `events`, `simulation` |
  | `cli` | everything except `__main__` |

  Imports are absolute (`airlanes.…`). Package `__init__.py` files contain
  only a docstring and re-export nothing, so every import names the module
  that defines the name.
- **Two entry points, one command line.** `python3 main.py <map>` and
  `python3 -m airlanes <map>` both call `airlanes.cli.main`. Root `main.py`
  stays because it is the documented command, the `make` targets and the
  smoke test use it, and it is the entry point of the original 42 project.
  It only calls the command line. The two entry points differ only where
  Python itself shows the entry point: the program name in `--help` and
  usage errors, and the frames of a traceback.
- **Departure arbitration and deadlock resolution are separate modules.**
  Each is a complete decision with its own ADR, so it gets its own module
  with explicit parameters instead of access to the whole `Simulator`, and
  its own unit tests. The order of state changes and events is unchanged:
  - `departures.plan_departures` lists the aircraft that want to leave on
    an open lane and, as before, uses up planned waits.
    `departures.select_feasible_moves` hands out lanes, departure slots,
    and hub places, and adds the departures it keeps to the lane usage of
    the turn.
  - `deadlock.resolve_deadlock` replaces the route of the one aircraft that
    takes a way around and returns the `AgentRerouted` event. The
    simulator emits it immediately, at the same point in the turn as
    before. `DeadlockError` moved with it.
- **Route reconsideration stays in the engine.** Reconsidering routes when
  the weather slows them ([ADR-021](#adr-021)) is a step of the turn
  between arrivals and departures. Extracting it would mean either passing
  the event dispatcher into it, or returning the events and emitting them
  after the loop over all aircraft instead of right after each change. No
  current listener could see that difference, but it is not worth
  introducing for symmetry between modules.
- **Deliberately unchanged:**
  - **`output` depends on `simulation`** only because `SimulationTurn`, the
    per-turn movement list, is defined in the engine and used in one type
    annotation of the text output. What the output should consume is the
    question of the Output & event audit.
  - **Planner and executor keep their own capacity representations.** They
    follow one capacity model ([ADR-019](#adr-019)), but unifying the data
    structures is not a move.
  - **The planner's reservation tables keep their format.** One table mixes
    lane usage with departure slots, whose keys are built from the lane and
    hub names with `_dept_`. A typed reservation table would separate them,
    but it changes the representation and can change behavior for hub names
    that contain `_dept_`, so it needs its own change.
  - **The Pygame viewers moved without redesign**, including their window
    titles and the background chosen from the command-line arguments.
  - **Outside this refactor:** renaming `Drone` to `Aircraft`, removing
    dead code ([TD-001, TD-002](bug-triage.md#technical-debt)), a shared
    arrival step in the engine, performance work, parser hardening, and the
    other Cleanup & benchmark items.

**Rationale.** A move can break behavior silently: an import that resolves
to a stale module, an image path that no longer resolves (the image
loaders return nothing instead of failing), or an event emitted at a
different point in the turn. Before the first move, the behavior was
recorded, and every commit was compared against that record:

- **Tests.** The full suite, which grew from 313 to 324 tests with the new
  direct tests for departures, deadlocks, and `python -m airlanes`.
- **Simulation fingerprints.** A hash of the complete event stream, the
  final status, and the printed output of every run: the 12 bundled maps
  without weather and with 30 weather seeds each, all bundled maps in each
  text mode of the command line, and 60,000 generated maps with scripted
  weather, three of which end in a road-budget deadlock, the known
  limitation of ADR-021. They were identical for `PYTHONHASHSEED` 0 to 5,
  so no result depends on the hash order of sets.
- **Parser snapshot.** The networks built from all bundled maps, and the
  exception type, message, and line for crafted and randomly corrupted
  maps, in process and through the command line.
- **Text-output snapshot.** Plain and colored turn lines, the flight log,
  and the capacity blocks for runs with weather, reroutes, deadlocks, and
  turns without movement, compared byte for byte.
- **Headless Pygame.** With SDL's dummy video driver: every image found and
  loaded with the same pixels, every frame of both viewers drawn with the
  same pixels, the background chosen for Germany and Europe, and both
  viewers' event loops driven by posted key, mouse, and quit events.
- **Dependency audit.** Imports, cycles, and the directions above, checked
  after every commit.

The scripts are not part of the repository; this list is enough to rebuild
them.

**Consequences.**

- **No change in behavior.** Every simulation fingerprint, the text-output
  snapshot, and the Pygame check are identical before and after. The only
  differences are file names and line numbers in the traceback of an
  uncaught exception, and the program name that `argparse` shows under
  `python -m airlanes`.
- **New modules have a place.** A module joins the package whose
  responsibility it has, and its imports follow the directions above.
- **The directions are documented, not enforced.** No test checks them yet.
  A check can be added when the structure has settled.
- **`python -m airlanes` works from the repository root**, or with the
  repository root on `PYTHONPATH`, until the project becomes installable.

---

## ADR-023

### The simulation result keeps every completed turn; the output decides what to print

- **Status:** Accepted; partly superseded by [ADR-024](#adr-024) (each
  completed turn is a `TurnResult` instead of a `SimulationTurn`; the
  invariant and the failure boundary are unchanged)
- **Date:** 2026-10-06

**Context.** `Simulator.run()` kept a turn only if an aircraft started or
finished a move in it. A turn in which every aircraft was in the air,
waited for weather or for a hub place, or followed a planned wait was
simulated, sent its events, and was then left out of the result
([BUG-004](bug-triage.md#bug-004)). The engine was deciding what the
output prints. The text output of the original assignment does print only
turns with a movement, but the other outputs show every turn, and the
`--capacity-info` mode paired the shortened turn list with the capacity
block of every turn by position, so blocks landed on the wrong turns
([BUG-005](bug-triage.md#bug-005)). The Output & event audit found 699 of
9,368 simulated turns (7.5%) missing from the result in 372 runs of the
bundled maps, without weather and with 30 weather seeds each.

**Decision.**

- **Two different notions.** A *completed turn* is a turn whose execution
  returned without an exception. A *movement turn* is a completed turn in
  which at least one aircraft started or finished a move. Every movement
  turn is a completed turn; the reverse does not hold.
- **The result keeps every completed turn.** For every turn `n` that
  completes, the result of `Simulator.run()` contains exactly one
  `SimulationTurn` with `turn_number == n`, in order and without gaps: turn
  numbers run `1, 2, …, N`. A turn without movement is kept with an empty
  movement list.
- **The failure boundary.** A turn interrupted by an exception, such as
  `DeadlockError`, is not completed and is not kept. The exception leaves
  `run()`, so `run()` returns no result; `Simulator.turns` still holds the
  turns that completed before it. At the 10,000-turn limit, the last turn
  completes and is kept before `RuntimeError` is raised.
- **The output decides what to print.** The assignment-style text output,
  with or without `--visual`, prints only movement turns, exactly as
  before. It prints no empty line, turn header, or placeholder for other
  turns. With `--capacity-info`, every completed turn has its capacity
  block, found by turn number, and a turn without movement prints only its
  block.
- **Deliberately unchanged.** `SimulationTurn`, the events, the flight
  log, and the Pygame viewers are not changed. How turns without movement,
  waiting, and transit should appear in the text output is still open
  ([DECISION-003](open-decisions.md#decision-003)).

**Rationale.**

- Which turns happened is a fact of the simulation; which turns are worth
  printing is a choice of one output. Filtering in the engine forced that
  choice on every consumer of the result.
- Matching a capacity block to its turn by number does not depend on two
  lists having the same length, which was the cause of BUG-005.
- Keeping the filter in the text output preserves the assignment format
  byte for byte, so the decision does not prejudge DECISION-003.

**Consequences.**

- `len(Simulator.run())` is the number of completed turns.
- The movement filter appears in two places: the command line and the test
  helper `run_simulation`, whose `output` models the assignment-style text.
  Both go away when the result model replaces `SimulationTurn`, which is a
  separate decision.
- Verified against the behavior record of [ADR-022](#adr-022), with the
  printed output compared for movement turns only: event streams and
  simulation fingerprints for the bundled maps with and without weather
  and for 60,000 generated maps, the text-output snapshot, the Pygame
  frames, and the command line in the default, `--visual`, and
  `--airlines` modes are identical. Only `--capacity-info` output changes,
  on maps with a turn without movement: among the bundled maps without
  weather, only Europe. In every run, including the three that end in
  `DeadlockError`, the kept turns are exactly the turns that finished.
- Fixes [BUG-004](bug-triage.md#bug-004) and
  [BUG-005](bug-triage.md#bug-005).

---

## ADR-024

### Turn results are typed outcomes of completed turns

- **Status:** Accepted
- **Date:** 2026-10-06

**Context.** Since [ADR-023](#adr-023), `Simulator.run()` keeps one
`SimulationTurn` for every completed turn. That class was a list of
`(aircraft, position)` string pairs in the format of the original
assignment: the second string was a hub when an aircraft arrived and a lane
when it started a multi-turn leg, so its meaning depended on the
assignment's format. It also formatted its own output line, and the output
package depended on the simulation package only to read it
([ADR-022](#adr-022)). The result described what to print, not what
happened.

**Decision.**

- **Four representations, four jobs.**
  - *Simulation state* is the full internal truth: aircraft, routes,
    weather, occupancy. It changes every turn and is not exposed.
  - *Events* (`airlanes.events`) are live observations sent while a turn
    runs, including weather changes and capacity snapshots. The event
    stream is not a complete trace of execution.
  - *Turn results* (`airlanes.results`) are the immutable outcomes of a
    completed turn: the significant things that actually happened.
  - *Presentation* (`airlanes.output`) decides what to show and how, from
    results or events.
- **One `TurnResult` per completed turn.** `TurnResult(turn_number,
  outcomes)` replaces `SimulationTurn`. The invariant and failure boundary
  of ADR-023 are unchanged. A completed turn in which nothing significant
  happened has `outcomes == ()`; that is a valid result, not a missing one.
- **A closed vocabulary of significant facts.** An outcome is one of:
  - `Departure(aircraft, origin, destination, lane)`: an aircraft started a
    leg;
  - `Arrival(aircraft, origin, destination, lane)`: an aircraft finished a
    leg;
  - `Reroute(aircraft, hub, old_route, new_route)`: an aircraft waiting at
    `hub` replaced its remaining route.

  A new kind of outcome needs its own decision.
- **Not a world snapshot and not a trace.** A result contains no weather,
  no capacity, no aircraft or network state, no reasons, no failed or
  blocked departures, no waits, and no transit progress. It does not
  explain why something did not happen.
- **Departure and Arrival are symmetric.** Both name the leg completely, so
  an arrival can be understood without finding its departure. A leg that
  takes one turn starts and finishes in the same turn: it is a `Departure`
  followed by an `Arrival`, so every leg that starts is a departure and
  every leg that finishes is an arrival. Neither carries the travel time
  or a delivery flag: a delivery is an arrival at the end hub.
- **A reroute records the transition.** `old_route` and `new_route` are the
  remaining steps of the plan after `hub`, as the aircraft holds them. A
  wait planned by the initial cooperative plan is a step that stays in the
  same hub, so `old_route` may repeat a hub; reroutes never plan waits. The
  reason for the reroute stays in `AgentRerouted`.
- **Names, not objects.** Aircraft are identified by their label (`D1`),
  hubs and lanes by their names from the map. A lane name keeps the order
  of the map file, so the direction of a leg comes from `origin` and
  `destination`.
- **One ordered collection.** `outcomes` holds every outcome in the order
  it happened: arrivals of legs started earlier, reroutes for weather,
  departures and one-turn legs, then a reroute that resolves a deadlock.
- **A taxonomy, not behavior.** `TurnOutcome` is a plain base class with no
  fields and no methods. The outcomes and `TurnResult` are frozen
  dataclasses. Outcomes do not render, apply, or emit themselves;
  consumers check their type and ignore kinds they do not use.
- **Outcomes and events come from the same fact.** Neither is derived from
  the other. Where the simulation changes state, it records the outcome
  and emits the event at the same point, so event timing and order are
  unchanged. `resolve_deadlock` returns the `Reroute` together with its
  `AgentRerouted` event, both built before the old route is replaced.
- **The output renders results.** `output.text.movement_tokens` turns a
  result into the assignment's movements: a departure shows its lane, an
  arrival its hub, a one-turn leg only its arrival, and a reroute nothing.
  The command line and the test helper print a turn's line only when the
  renderer returns one.
- **Module and dependencies.** `airlanes/results.py` depends on nothing
  else in the application. `simulation` may also depend on `results`;
  `output` depends on `model`, `events`, and `results`, and no longer on
  `simulation`. Other directions of ADR-022 are unchanged.
- **Duplication accepted for now.** The engine still builds
  `TurnFinished.movements` in the assignment's format at the same points,
  and `AgentMoved`, `AgentInTransit`, and `AgentRerouted` still describe
  the same facts as the outcomes. A test checks, for every bundled map
  with and without weather, that each turn's outcomes match its events in
  order and that the assignment tokens of each result equal
  `TurnFinished.movements`. Whether to remove the duplication is
  [DECISION-012](open-decisions.md#decision-012).

**Rationale.**

- The output needs to know what happened, not one format's view of it. A
  hub-or-lane string forced every consumer to guess which one it got.
- A snapshot would duplicate the simulation state and grow with it, and a
  trace is the job of events. A result that records only what happened
  stays small, and an empty result is meaningful.
- Weather and capacity describe the world, not something an aircraft did,
  so they are observed, not recorded. A wait or a refused departure is the
  absence of an outcome; explaining it needs diagnostics that do not
  exist yet.
- One ordered collection keeps the order of the turn, which separate
  collections per kind would lose. The assignment's format depends on that
  order.
- A base class names the vocabulary, and frozen dataclasses give value
  equality and immutability. Keeping behavior out of the outcomes leaves
  every decision about display or use with the consumer, so a new output
  never changes the result model. The cost: mypy cannot check that a
  consumer handles every kind.
- Symmetric departure and arrival make each outcome self-contained. A
  one-turn leg is both, so counting departures or arrivals needs no
  special case.
- A route change is the transition from one plan to another, so a reroute
  needs both routes; the new route alone does not show what changed.
- Names keep a result immutable and comparable by value. `Drone`, `Zone`,
  and `Connection` are mutable, compare by identity, and belong to one
  network instance, so references would show their current state, not
  what happened.
- Removing the duplication changes the event contract that the Pygame
  viewers, the flight log, and the invariant checker read. That is a
  separate decision, and the test keeps the two representations from
  drifting apart until it is made.

**Consequences.**

- `SimulationTurn`, `SimulationTurn.to_output_line`, and the unused
  `Simulator.print_results` ([TD-001](bug-triage.md#technical-debt)) are
  removed; `Simulator.run()` and `Simulator.turns` hold `TurnResult`s.
- The movement filter of ADR-023 is gone. The command line and the test
  helper keep a line only when the renderer returns one, so which turns
  are printed is decided by the renderer alone.
- A turn with only a reroute is a non-empty result with no line in the
  assignment-style output: 12 of the 9,368 turns of the bundled runs.
- Verified against `main` with the behavior record of ADR-022 and the
  movement-only comparison of ADR-023. Event streams, statuses, and
  printed output of the 372 bundled runs and the 60,000 generated maps,
  the command line in every text mode, the text-output snapshot, and the
  Pygame frames are identical, also for `PYTHONHASHSEED` 1 and 2. In every
  completed generated run, the outcomes agree with the events.
