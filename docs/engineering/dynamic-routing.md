# Dynamic Routing Design

Design for moving Maria's Airlanes from routes planned once before the first
turn to routing decisions made during the simulation, as the world changes.

This document describes the current model, the evidence collected for this
design, the target model, and the decisions that are still open. It does not
change any code. Implementation follows in later pull requests (see
[Delivery plan](#delivery-plan)).

Accepted decisions are recorded as ADRs in [decisions.md](decisions.md):

| ADR | Decision |
| --- | --- |
| [ADR-010](decisions.md#adr-010) | An aircraft in transit is committed to its leg |
| [ADR-011](decisions.md#adr-011) | Routing decisions are made at hubs; replanning is triggered by events |
| [ADR-012](decisions.md#adr-012) | Weather comes from a provider as a snapshot of the current state |
| [ADR-013](decisions.md#adr-013) | Routing uses explicit state; planner and executor share one capacity model |
| [ADR-014](decisions.md#adr-014) | Waiting happens in place; deadlocks are detected, not waited out |

Questions that still need a decision are listed in
[Open questions](#open-questions) and tracked in
[open-decisions.md](open-decisions.md).

---

## Current model

```text
Parser → Graph
   ↓
Simulator._assign_paths ── Pathfinder.find_cooperative_path
   ↓                       once, before turn 1; reservation tables live only here
every turn: WeatherSystem.update_weather (global random)
            → finish arrivals → plan departures → select feasible moves → apply
```

- **Planning.** Every route is planned once, before the first turn, by a
  time-expanded search (`find_cooperative_path`). Each aircraft books the hubs
  and lanes it will use in reservation tables, in order, so later aircraft
  plan around earlier ones. A route is a list of hubs. Waiting is a repeated
  hub in that list.
- **Execution.** Every turn, each aircraft at a hub tries the next step of its
  list. The executor checks lane state and capacity, then hub capacity
  ([ADR-008](decisions.md#adr-008)), and applies only moves that fit. An
  aircraft that cannot move simply tries the same step again next turn. The
  reservation tables are not used during execution.
- **Weather.** `WeatherSystem` changes lanes at random using the global
  `random` module, and mutates `Connection` objects in place. Storm and snow
  close a lane; rain and tailwind change its travel time. Weather is applied
  only during execution. Routes never change in response.
- **Travel time.** `Pathfinder._calculate_move_cost` computes it for both the
  planner and the executor: from the destination's zone type on lanes without
  distance, and from distance and weather on distance lanes.

---

## Evidence

Measured on `main` at `52015cf` with throwaway scripts that import the
production modules without changing them. The scripts are not part of the
repository. The method below is enough to rebuild them.

### Method

- **Planned schedule.** Run `Simulator._assign_paths()` and add up
  `Pathfinder._calculate_move_cost` along each route. This gives the turn at
  which each aircraft is planned to be delivered.
- **Executed schedule.** Run the simulation and take each aircraft's
  delivery turn from its `AgentMoved` event with `delivered=True`.
- **Divergence.** An aircraft diverges if its executed delivery turn differs
  from its planned one. No aircraft was ever delivered early, so every
  divergence is a delay.
- **Wait reasons.** A copy of `Simulator._plan_departures` with the same rules
  records why each waiting aircraft did not move. The difference between
  planned and selected moves counts as "next hub full".
- **Weather runs.** `random.seed(s)` for `s` in 0–99, then
  `Simulator(..., enable_dynamic_weather=True)`.
- **Random graphs.** 3,000 maps from `random.Random(7)`, generated as follows.
  Maps without a route are skipped.
  - **Hubs:** `S` and `E` plus 2–7 more. Each hub has a type of normal (3/6),
    restricted, priority, or blocked (1/6 each), and in half the cases
    `max_drones` 1–3.
  - **Lanes:** n to 2n+2 random distinct pairs. In half the cases they have
    `max_link_capacity` 1–3. In half the maps, every lane has a distance from
    {80, 150, 450, 700, 1200} km.
  - **Aircraft:** 1–12.

  1,524 of the 3,000 maps have distance lanes. Weather is off.

### Bundled maps

Without weather, execution matches the plan exactly on all 12 maps: every
aircraft is delivered on its planned turn.

With weather (100 seeds per map), plans fall apart:

| Map | Planned turns | Late aircraft | Mean extra turns | Max extra turns |
| --- | ---: | ---: | ---: | ---: |
| easy/01_linear_path | 4 | 12.5% | 0.6 | 13 |
| easy/02_simple_fork | 5 | 16.7% | 1.8 | 33 |
| easy/03_basic_capacity | 6 | 18.2% | 1.5 | 19 |
| medium/01_dead_end_trap | 8 | 31.4% | 3.1 | 23 |
| medium/02_circular_loop | 16 | 51.5% | 6.6 | 33 |
| medium/03_priority_puzzle | 7 | 31.2% | 4.0 | 48 |
| hard/01_maze_nightmare | 14 | 61.5% | 11.2 | 51 |
| hard/02_capacity_hell | 18 | 67.6% | 10.7 | 38 |
| hard/03_ultimate_challenge | 26 | 89.7% | 19.8 | 67 |
| challenger/01_the_impossible_dream | 43 | 97.0% | 48.7 | 113 |
| bonus/germany_map | 14 | 44.5% | 4.2 | 26 |
| bonus/europa_map | 34 | 70.0% | 11.6 | 45 |

"Extra turns" is the executed makespan minus the planned one. No weather run
hit the 10,000-turn limit.

Why aircraft waited, summed over all weather runs (aircraft-turns): planned
wait 69,600; lane at capacity 48,923; lane closed by weather 36,299; next hub
full 26,830; distance-lane departure slot already taken 890.

### Random graphs without weather

| Result | Maps |
| --- | ---: |
| Execution matches the plan | 2,507 |
| At least one aircraft delivered late | 487 (423 with distance lanes, 64 without) |
| Deadlock (10,000-turn limit) | 6 (all with distance lanes) |

Why aircraft waited (aircraft-turns): distance-lane departure slot taken
173,047; next hub full 83,614; planned wait 64,017; lane at capacity 11,669.

All 6 deadlocks are [BUG-003](bug-triage.md#bug-003), both variants, without
any weather.

### Route computation cost

Wall-clock time of one route search on Python 3.14. For
`find_cooperative_path`, the range covers every aircraft of one planning run,
as the reservation tables fill up. `find_path_dijkstra` is the mean of 20
calls on the empty network.

| Map | Aircraft | `find_cooperative_path` | `find_path_dijkstra` |
| --- | ---: | ---: | ---: |
| challenger/01_the_impossible_dream | 25 | 16–22 ms | 0.28 ms |
| bonus/europa_map | 15 | 4–5 ms | 0.06 ms |
| hard/03_ultimate_challenge | 15 | 3–4 ms | 0.10 ms |

`Graph.get_neighbors` and `Graph.get_connection` scan every lane on each call,
and the time-expanded search copies the path at every step. Running the
cooperative search for every aircraft on every turn would cost seconds per
run on the largest map. Replanning on a trigger costs only a fraction of that.

### Findings

1. **Deadlocks happen without weather.** Earlier evidence (PR #5) saw BUG-003
   only with weather. The random audit reproduces both variants with weather
   off, and they reproduce from the plain CLI.
2. **Planner and executor disagree about capacity.** The planner books a hub
   only on the turn an aircraft arrives. The executor holds the hub's slot from
   departure until arrival ([ADR-008](decisions.md#adr-008)), and gives a
   distance lane one departure per turn in list order. A plan that is valid for
   the planner can therefore be rejected during execution, with no weather at
   all. Example from the audit: five aircraft planned to pass a one-slot
   restricted hub one turn apart are delivered 1, 2, 3, 4, and 5 turns late.
3. **The planner uses cycles through other hubs as waiting.** Routes such as
   `S → h0 → S → E` and `S → h3 → h4 → h2 → h0 → h0 → h2 → h4 → h3 → S → E`
   park an aircraft in another hub and bring it back, instead of waiting where
   it is. This creates opposite-direction traffic on the same lane, which is
   how the deadlocked pairs end up facing each other.
   - **Prevalence.** 1,516 of 19,500 planned routes in the random audit revisit
     a hub. On the bundled maps, 4 of 109 routes do: one on
     `hard/01_maze_nightmare`, two on `hard/03_ultimate_challenge`, and one on
     `medium/03_priority_puzzle`. Each leaves the start and comes back to it.
     Those routes execute without problems today.
   - **Priority discount.** Moving and waiting both cost one unit per turn, so
     a loop is never more expensive than waiting. The priority-hub discount
     (`PRIORITY_ZONE_DISCOUNT`) makes a loop through a priority hub strictly
     cheaper than waiting. In 715 of the 1,516 revisiting routes the loop
     passes through a priority hub, and every one of the 6 deadlocks parks in
     a priority hub, although only one hub in six is a priority hub.
4. **A delayed plan still runs its planned waits.** A route is a list of
   steps, not a timetable. An aircraft that falls behind still waits wherever
   its list says to wait, so delays add up instead of being absorbed.
5. **A time-expanded search needs a limit once closed lanes count.** Waiting
   in place is always a valid move, so a search over (hub, turn) states never
   ends if every route is closed. Today the planner ignores weather, so this
   cannot happen yet.

---

## Target model

### Committed legs

See [ADR-010](decisions.md#adr-010).

An aircraft that departs on a leg is committed to it until it arrives:

- it is not replanned in flight;
- its travel time is fixed at departure;
- later weather changes do not affect the leg it is flying;
- its destination hub's slot stays held, as in [ADR-008](decisions.md#adr-008).

Every routing decision is therefore made at a hub.

### Decision points and replanning triggers

See [ADR-011](decisions.md#adr-011).

Two different things happen at a hub:

- **Decision point.** Each turn an aircraft spends at a hub, it decides what
  to do this turn. Most of the time this means following its current route,
  which is cheap.
- **Replanning trigger.** An event that justifies a new route search. The
  minimum set is:
  - the remaining route is invalidated: under the current weather it contains
    a lane that is closed or otherwise unusable;
  - the aircraft has waited without progress for a number of consecutive
    turns that reaches a configurable threshold.

A full route search does not run on every turn. The threshold is an explicit,
configurable routing-policy parameter. Its default is chosen in PR #8 from
evidence.

### Routing options

At a decision point, routing policy chooses one of four options:

| Option | Meaning |
| --- | --- |
| Continue | Take the next leg of the current route toward the destination. |
| Wait | Stay in the current hub this turn. Valid only if the current hub is safe. |
| Reroute | Take a different route toward the destination. |
| Divert | Because of weather, head for a nearby safe hub instead of the destination. |

Policy compares these options using the current state. How it estimates
delays (for example, how long a closed lane may stay closed) is not fixed yet
([DECISION-006](open-decisions.md#decision-006)).

Weather can therefore change more than the cost or availability of the next
lane. It can change the aircraft's immediate goal, from "reach the
destination" to "reach safety".

### Weather diversion

A diversion is triggered by weather. When moving on along the planned route
has become unsafe or impossible, an aircraft may head for a nearby suitable
safe hub instead of only waiting or rerouting.

- **Only from a hub.** An aircraft in transit always finishes its committed
  leg first ([ADR-010](decisions.md#adr-010)), then decides using the weather
  it finds on arrival.
- **Backtracking is valid.** An aircraft that flew `S → A → B` may divert
  `B → A` if `A` is now the right safe hub. Returning to a hub because the
  state changed is a legitimate decision. What is excluded is using a cycle
  through other hubs as a way of waiting ([ADR-014](decisions.md#adr-014)).
- **Waiting is not automatically safe.** "If the destination is unreachable,
  wait" is not enough. Waiting is valid only if the current hub is safe and
  policy chooses it.

What makes a hub or route "unsafe", and how the target hub is chosen, is not
defined yet ([DECISION-004](open-decisions.md#decision-004)). Today weather
exists only on lanes.

### Emergency hub capacity

A diverting aircraft may need a hub that is already full. Capacity is
modelled in two layers ([ADR-013](decisions.md#adr-013)):

```text
normal capacity  +  weather emergency overflow
```

- **Normal capacity** (`max_drones`) is what ordinary routing and planning
  may use. Emergency arrivals never change it: a capacity-2 hub holding
  3 aircraft in an emergency is still a capacity-2 hub.
- **Emergency overflow** is extra room that only qualifying weather-diversion
  arrivals may use. Ordinary routing and planning never consume it.
- **The amount is policy, not a constant.** `+1` may become the first default
  if evidence supports it.

Who qualifies, how long overflow lasts, and how it is released are open
([DECISION-005](open-decisions.md#decision-005)). The hub-capacity invariant
will need to tell overflow from a violation (see
[Invariants and tests](#invariants-and-tests)).

### Routing state

See [ADR-013](decisions.md#adr-013).

Route search depends only on explicit inputs and is deterministic with
respect to them:

- the static network: hubs, zone types, lanes, distances, normal capacities;
- the current `WeatherState`;
- the current turn;
- current occupancy and commitments: aircraft in hubs, aircraft in transit
  and the slots they hold, and (from PR #9) live reservations;
- the routing request: the aircraft's position and its goal (destination or
  diversion target).

Route search does not read `Drone` objects as hidden state, does not mutate
the graph, does not use the global `random` module, and never talks to a
weather provider or external API directly. Priority hubs remain a cost
preference, not a capacity rule.

### Capacity semantics and reservations

See [ADR-013](decisions.md#adr-013).

- **One capacity model.** The planner and the executor must apply the same
  capacity rules: hub load including aircraft in transit towards it,
  lane capacity, and distance-lane departures. Evaluated against the same
  state and the same rules, they must not disagree about resource
  feasibility. A move or reservation that the planner accepts as
  capacity-feasible must not be rejected by the executor merely because the
  executor applies a different capacity model. This removes finding 2. It
  does not promise that a whole schedule always executes: scheduling,
  departure, and deadlock semantics are refined in PR #9 and
  [DECISION-008](open-decisions.md#decision-008).
- **Reservations v2 (PR #9).**
  - Reservations are live state, not a table built once before the first turn.
  - Each reservation belongs to an aircraft.
  - When an aircraft reroutes, its future reservations are released. Its
    current hub occupancy and its committed transit stay.
- **Executor as a safety layer.** The executor keeps validating every move at
  runtime ([ADR-008](decisions.md#adr-008)), even when plans are correct.

PR #8 delivers dynamic replanning without reservations v2. A rerouted or
diverted aircraft plans against the current state only, and the executor
keeps the run safe. Cooperative scheduling moves to the new model in PR #9.
The initial cooperative planning is kept: it is what keeps the bundled maps
within their turn budgets ([ADR-005](decisions.md#adr-005)).

### Waiting and deadlocks

See [ADR-014](decisions.md#adr-014).

- **Waiting is staying in the current hub.** The planner must not build
  routes that leave a hub and come back only to pass time, as in finding 3.
  Legitimate revisits after a change of state (backtracking, diversion) remain
  allowed. When a revisit is legitimate and when it should be limited is open
  until PR #9 ([DECISION-007](open-decisions.md#decision-007)).
- **Wasted departure slots.** A distance lane's departure slot goes only to a
  move that has passed the hub-capacity check. This fixes BUG-003 variant B.
- **Deadlock detection.** The simulator builds a wait-for graph: aircraft A
  waits for aircraft B if A's next hub is full because B is in it. A cycle in
  which every aircraft waits only on another aircraft in the cycle, and no
  weather change or arrival can release it, is a deadlock.
- **Deadlock handling.** Detection comes first. A detected deadlock is
  resolved where possible, for example by replanning one aircraft of the
  cycle. If it cannot be resolved, the run stops with a clear error instead of
  running into the 10,000-turn limit. The exact strategy is designed in PR #9.
- **Departure-slot rule.** In both variant A reproducers the swap is blocked
  by the one-departure-per-turn rule, not by lane capacity: the shared lane
  has capacity 3 in both. Whether that rule applies per lane or per direction is
  open ([DECISION-008](open-decisions.md#decision-008)).

### Weather boundary

See [ADR-012](decisions.md#adr-012).

```text
WeatherProvider ──→ WeatherState ──→ Simulator / routing state
(no weather,         snapshot of the       (decisions, travel time,
 seeded random,      current normalized     events)
 scripted,           domain weather
 later real weather)
```

- **Provider.** The simulator asks the provider for the weather of a turn.
  Planned providers:
  - `NoWeather`;
  - `RandomWeather`, seeded, with its own `random.Random`;
  - `ScriptedWeather`, a fixed schedule for deterministic tests;
  - later, a real-weather provider ([Part 4](#delivery-plan)).
- **`WeatherState`** is a snapshot of the current, observed weather in the
  project's own terms: condition and open or closed, per lane.
  - It is not a forecast. Providers are not required to supply forecasts or
    expected durations, because a real-weather provider may not know how many
    turns a condition will last.
  - Whether hubs also get weather is part of
    [DECISION-004](open-decisions.md#decision-004).
- **Simulator.** It compares each turn's state with the previous one and emits
  `WeatherChanged` events. Routing reads `WeatherState`, never the provider.
- **No global `random`.** Tests never depend on the global `random` module or
  on network access. Random mode stays available for ordinary runs. This also
  removes the debt of `update_weather()` drawing from the global state even
  when no storm can start.
- **Shared travel time.** Planner and executor will compute travel time in
  one place. How weather and restricted hubs affect it on distance lanes stays
  open until PR #10 ([DECISION-001](open-decisions.md#decision-001)).

---

## Invariants and tests

The independent invariant checker ([ADR-004](decisions.md#adr-004)) keeps
working from events. The new model affects it as follows:

- **Committed transit** is already checked: an aircraft in transit arrives
  where it was heading.
- **Emergency overflow** must be visible in events. The checker has to tell a
  qualifying weather-diversion arrival from an ordinary one, so that it can
  allow normal capacity plus overflow for the first and normal capacity for
  everything else.
- **Reroutes and diversions** need events of their own, so that tests can
  observe decisions without asserting specific routes
  ([ADR-002](decisions.md#adr-002)). How they appear in the text output is
  PR #11 ([DECISION-003](open-decisions.md#decision-003)).
- **`ScriptedWeather`** lets behavior tests close a lane on a known turn and
  check that an aircraft finds another way, without fixing which way when
  several are equally good.
- **Deadlock-free runs.** Once BUG-003 is fixed, the random audit above
  becomes a candidate for a maintained regression or property-based test.

---

## Delivery plan

| PR | Scope |
| --- | --- |
| PR #8 | Weather provider boundary (`NoWeather`, seeded `RandomWeather`, `ScriptedWeather`). Decision points and replanning triggers. Continue, wait, and reroute. Diversion and emergency overflow only if [DECISION-004](open-decisions.md#decision-004) and [DECISION-005](open-decisions.md#decision-005) are decided first. No reservations v2. |
| PR #9 | Reservations v2 and one capacity model for planner and executor. No artificial waiting cycles. Departure-slot fix. Deadlock detection and handling. BUG-003. [DECISION-007](open-decisions.md#decision-007), [DECISION-008](open-decisions.md#decision-008). |
| PR #10 | Weather-aware route cost: rain, tailwind, storm and snow semantics, road and air travel. [DECISION-001](open-decisions.md#decision-001). The delay model of [DECISION-006](open-decisions.md#decision-006) if not settled in PR #8. |
| PR #11 | Output and timeline: turns without movement, waiting, transit, reroutes, and diversions. [DECISION-003](open-decisions.md#decision-003), [BUG-004](bug-triage.md#bug-004). |
| PR #12 | Cleanup: unused pathfinder methods and model state ([TD-001, TD-002](bug-triage.md#technical-debt)), module boundaries. |

Real weather comes after PR #10, as another provider behind the same
boundary.

---

## Open questions

### Before PR #8

These need a decision before the parts of PR #8 that depend on them:

- **What makes a hub or route unsafe, and how is a diversion target chosen?**
  ([DECISION-004](open-decisions.md#decision-004)). Weather exists only on
  lanes today. Without this answer, PR #8 can ship continue, wait, and reroute,
  and diversion follows separately.
- **Emergency overflow semantics** ([DECISION-005](open-decisions.md#decision-005)):
  who qualifies, how much, for how long, and how it is released and shown.
  Needed only if diversion is in PR #8.
- **Minimal wait, reroute, and divert policy**
  ([DECISION-006](open-decisions.md#decision-006)): how options are compared
  without requiring forecasts from providers.
- **Defaults chosen from evidence in PR #8**, not decided in advance: the
  no-progress threshold, and the search limit for time-expanded route search
  (finding 5).

### Later

- When a legitimate revisit is allowed or limited
  ([DECISION-007](open-decisions.md#decision-007)), PR #9.
- Whether the one-departure-per-turn rule on distance lanes applies per lane or
  per direction ([DECISION-008](open-decisions.md#decision-008)), PR #9.
- Restricted hubs on distance lanes
  ([DECISION-001](open-decisions.md#decision-001)), PR #10.
- Turns without movement in the output
  ([DECISION-003](open-decisions.md#decision-003)), PR #11.
