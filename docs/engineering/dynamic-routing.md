# Dynamic Routing Design

Design for moving Maria's Airlanes from routes planned once before the first
turn to routing decisions made during the simulation, as the world changes.

This document describes the current model, the evidence collected for this
design, the target model, and the decisions that are still open.
Implementation happens in a series of pull requests (see
[Delivery plan](#delivery-plan)). PR #8 laid the transport and weather
foundation; dynamic replanning starts in PR #9.

Accepted decisions are recorded as ADRs in [decisions.md](decisions.md):

| ADR | Decision |
| --- | --- |
| [ADR-010](decisions.md#adr-010) | An aircraft in transit is committed to its leg |
| [ADR-011](decisions.md#adr-011) | Routing decisions are made at hubs; replanning is triggered by events |
| [ADR-012](decisions.md#adr-012) | Weather comes from a provider as a snapshot of the current state |
| [ADR-013](decisions.md#adr-013) | Routing uses explicit state; planner and executor share one capacity model |
| [ADR-014](decisions.md#adr-014) | Waiting happens in place; deadlocks are detected, not waited out |
| [ADR-015](decisions.md#adr-015) | Every hub is a safe waiting location; hub capacity has one layer |
| [ADR-016](decisions.md#adr-016) | Transport mode is map data; weather acts through one set of transport rules |
| [ADR-017](decisions.md#adr-017) | Road is a fallback with a consecutive-road budget |
| [ADR-018](decisions.md#adr-018) | Aircraft reroute only when weather makes their route unusable |
| [ADR-019](decisions.md#adr-019) | One capacity model; committed claims are the only live reservations |
| [ADR-020](decisions.md#adr-020) | Structural deadlocks are detected each turn and resolved or reported |

ADR-015 replaces the parts of ADR-011 and ADR-013 about unsafe hubs, weather
diversion, and emergency hub capacity. ADR-019 replaces the live reservations
of ADR-013, and ADR-020 the no-progress threshold of ADR-011. The sections
below already reflect them.

Questions that still need a decision are listed in
[Open questions](#open-questions) and tracked in
[open-decisions.md](open-decisions.md).

---

## Current model

This section describes the model as it was when this design started
(`52015cf`, before PR #8). [Since PR #8](#since-pr-8) lists what the
foundation changed.

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

### Since PR #8

- **Transport modes.** Each connection has a transport mode, `air` or `road`,
  taken from the map ([ADR-016](decisions.md#adr-016)). It is no longer
  inferred from distance.
- **Transport rules.** `transport.py` turns the current weather and a
  connection's mode and data into availability and travel time. Air legs
  close in storm and snow; road legs stay open and get slower.
- **Weather providers.** The simulator takes a `WeatherProvider`
  (`NoWeather`, seeded `RandomWeather`, `ScriptedWeather`) and keeps the
  current `WeatherState` ([ADR-012](decisions.md#adr-012)). Connections no
  longer store weather, and no production code uses the global `random`
  module.
- **Unchanged.** Routes are still planned once, before the first turn, in
  clear weather. Without weather, every bundled map produces exactly the same
  output as before.

### Since PR #9

- **Rerouting.** Each turn, an aircraft waiting at a hub checks its remaining
  route. If the weather makes a leg unavailable, it takes the fastest route
  available now, or waits and keeps its route if there is none
  ([ADR-018](decisions.md#adr-018)). A usable route is never replaced.
- **Road budget.** `RoutingPolicy.max_consecutive_road_km` (700 km) applies
  to the initial plan, to every reroute, and to the aircraft's road distance
  carried across reroutes. Search states include the consecutive road
  distance, with dominance pruning.
- **Unchanged.** Without weather, no route becomes unusable and the budget
  changes no bundled plan: every bundled map produces exactly the same
  output as before.

Evidence for the trigger, measured with a throwaway prototype of the
decision layer (30 seeds per map, seeded `RandomWeather`), as mean turns:

| Map | Without rerouting | Next leg closed | Any remaining leg closed | Fastest route every turn |
| --- | ---: | ---: | ---: | ---: |
| challenger | 91.1 | 362.1 | 95.8 | 93.7 |
| hard/maze_nightmare | 26.0 | 31.3 | 18.2 | 17.9 |
| hard/capacity_hell | 27.4 | 30.5 | 24.5 | 24.1 |
| hard/ultimate_challenge | 46.4 | 57.8 | 46.8 | 44.1 |
| medium/priority_puzzle | 10.5 | 17.6 | 10.0 | 9.8 |
| bonus/germany | 17.6 | 15.2 | 16.1 | 15.6 |
| bonus/europa | 45.9 | 43.9 | 46.9 | 49.9 |

- Searching only when the next leg closes brings aircraft up to the closed
  lane and jams them there.
- Recomputing the fastest route every turn produced 1,421 A-B-A route
  switches (against 243 weather-driven ones) and changed seven maps even
  without weather.
- A no-progress trigger (three turns) changed turn counts by less than two
  turns either way, but resolved every BUG-003 deadlock, so it moved to
  PR #10 with deadlock handling.
- No variant broke an invariant or hit the turn limit.

The implementation reproduces the chosen variant exactly: over the same
360 seeded runs it made 6,157 reroutes, with no invariant violations and no
failed runs; 200 of the 360 runs end on the same turn as before.
The larger maps lose some coordination, because a rerouted aircraft drops
its planned waits and ignores other aircraft: challenger +4.7 turns,
Europe +1.0. PR #10 measured live reservations for this and did not adopt
them (see [Since PR #10](#since-pr-10)).

### Since PR #10

- **One capacity model.** Planner and executor apply the same rules
  ([ADR-019](decisions.md#adr-019)): a leg holds its destination hub from
  departure to arrival, a lane is held on every turn of a leg, and a distance
  lane allows one departure per direction per turn
  ([DECISION-008](open-decisions.md#decision-008)).
  `Pathfinder.reserve_path` records a route with the rules that
  `_is_move_valid` checks.
- **Lanes go only to admitted moves.** The executor hands out lanes in
  aircraft order and keeps the moves that fit their hubs. A move that holds a
  lane but cannot enter its hub is excluded for the turn, and lanes are
  handed out again.
- **No reservation store.** What an aircraft holds now is derived from its
  state: its hub, or, in transit, its lane and its destination hub. Future
  reservations exist only while the initial routes are planned.
- **Waiting in place.** A planned route never returns to a hub it has left
  ([DECISION-007](open-decisions.md#decision-007)).
- **Structural deadlocks.** After each turn, the simulator looks for
  aircraft that block only each other. One of them takes a route around the
  hub it waits for; if such a route would exist only with every lane open,
  they wait; otherwise the run stops with `DeadlockError`
  ([ADR-020](decisions.md#adr-020)). `AgentRerouted` carries a reason,
  `weather` or `deadlock`.
- **No no-progress threshold.** Deadlock detection replaces it.
- **Output.** Without weather, nine bundled maps produce exactly the same
  output as before. Three maps (`hard/01_maze_nightmare`,
  `hard/03_ultimate_challenge`, `medium/03_priority_puzzle`) change routes
  and keep their turn counts: an aircraft that flew out of the start and back
  now waits there.

Evidence, measured with throwaway scripts on the method of
[Random graphs without weather](#random-graphs-without-weather), on 10,000
random maps that have a route. Lanes under 200 km are `mode=road`. A run
that needs more than 1,500 turns counts as a hang.

| Without weather | Before PR #10 | After |
| --- | ---: | ---: |
| Maps with an aircraft delivered later than planned | 1,681 | 0 |
| Late aircraft (of 65,010) | 7,829 | 0 |
| Hangs | 13 | 0 |
| Detected deadlocks | — | 0 |

Each change was also measured alone. Aligning the planner removes every
late aircraft and every hang without weather. With seeded weather on 3,000
random maps, it leaves one hang; adding the per-direction departure rule
removes it.

| With weather | Before PR #10 | After |
| --- | ---: | ---: |
| Bundled maps, 30 seeds each (360 runs): hangs, violations | 0, 0 | 0, 0 |
| Bundled maps: deadlocks resolved by a way around | — | 4 (challenger) |
| 3,000 random maps, seeded `RandomWeather`: hangs | 2 | 0 |
| Scripted weather, 2–4 storms on random lanes: hangs | 64 of 30,000 | 0 of 90,000 |
| Scripted weather on maps with long roads: `DeadlockError` | — | 1 of 50,000 |

With weather, mean turns stay the same on ten bundled maps; challenger goes
from 95.8 to 94.6 and `medium/03_priority_puzzle` from 10.0 to 10.1.

- **Arbitration.** A brute-force check over every subset of candidates found
  no turn on which the executor admitted nothing while a legal set of
  departures existed (turns with more than 16 candidates were not checked).
- **Live future reservations.** Rerouting against reservations derived from
  every other aircraft's remaining route changed mean turns both ways
  (challenger −1.7, `hard/03_ultimate_challenge` +1.3), detected more
  deadlocks (18 instead of 4 in the bundled weather runs), and was 2.8 times
  slower. It was not adopted.
- **Deadlocks.** Every deadlock examined in detail (three challenger runs
  and the two scripted regression maps) involved a lane for one aircraft
  and aircraft that had rerouted for weather. The only one without a way out is a
  road-budget trap, now a regression test. A permanent storm on the only
  route made 2,609 of 20,000 scripted runs wait forever; none was taken for
  a deadlock.

---

## Evidence

Measured on `main` at `52015cf`, before PR #8, with throwaway scripts that
import the production modules without changing them. The scripts are not part
of the repository. The method below is enough to rebuild them.

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

These measurements use the semantics of the time: a lane under 200 km was a
road, and storm and snow closed every lane. To repeat them after PR #8, mark
generated lanes under 200 km with `mode=road`. Road lanes now stay open in
storm and snow, so weather runs on maps with road lanes will differ.

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
- **Replanning trigger.** An event that justifies a new route search:
  - the remaining route is invalidated: under the current weather it contains
    a lane that is closed or otherwise unusable
    ([ADR-018](decisions.md#adr-018), PR #9);
  - the aircraft is part of a structural deadlock
    ([ADR-020](decisions.md#adr-020), PR #10).

A full route search does not run on every turn. ADR-011 also proposed a
trigger after a number of turns without progress. PR #10 replaced it with
deadlock detection: a threshold cannot tell a deadlock from a long wait for
weather, and the detector finds every deadlock on the turn it forms.

### Routing options

See [ADR-011](decisions.md#adr-011) and [ADR-015](decisions.md#adr-015).

At a decision point, routing policy chooses one of three options:

| Option | Meaning |
| --- | --- |
| Continue | Take the next leg of the current route toward the destination. |
| Wait | Stay in the current hub this turn. Every hub is a safe place to wait. |
| Reroute | Take a different available route toward the destination. |

Policy compares these options using the current state. How it estimates
delays (for example, how long a closed lane may stay closed) is not fixed yet
([DECISION-006](open-decisions.md#decision-006)).

### Hubs are always safe

See [ADR-015](decisions.md#adr-015).

Weather acts on connections and transport modes, never on hubs. An aircraft
never has to leave a hub because the hub became unsafe.

- **Only from a hub.** An aircraft in transit always finishes its committed
  leg first ([ADR-010](decisions.md#adr-010)), then decides using the weather
  it finds on arrival.
- **Unavailable route.** A route is unavailable when it contains a connection
  that is unavailable under the current weather, or when it breaks a
  routing-policy limit such as the consecutive-road budget.
- **Route available.** If a route to the destination exists, the aircraft
  continues or reroutes. A reroute may pass through other hubs or return to a
  hub visited before: an aircraft that flew `S → A → B` may go back
  `B → A` when that is now the way to the destination. What is excluded is
  using a cycle through other hubs as a way of waiting
  ([ADR-014](decisions.md#adr-014)).
- **No route available.** The aircraft waits in its current hub. Moving to an
  intermediate hub without an available route to the destination (a
  positioning move) is deferred
  ([DECISION-010](open-decisions.md#decision-010)).
- **One capacity layer.** No aircraft ever needs to enter a full hub, so hub
  capacity has no emergency overflow. The design in PR #7 proposed one; ADR-015
  removed it ([DECISION-005](open-decisions.md#decision-005)).

### Transport modes and road fallback

See [ADR-016](decisions.md#adr-016) and [ADR-017](decisions.md#adr-017).

- **Topology comes from the map.** A connection is an air or road lane because
  the map says so. Routing never infers geography from coordinates, names, or
  distances. An island has no road because its map has no road lane.
- **Weather never creates transport.** It can make an existing connection
  unavailable or slower, but it cannot create a connection or a mode.
- **Road is a fallback.** Roads stay open in any weather, so they can bridge
  an air lane closed by a storm. Routing limits the consecutive road distance
  of a route with `max_consecutive_road_km` (700 km by default). An air leg
  resets it. Fallback arises from routing over the usable topology, not from
  a special rule.
- **One lane per pair.** An air lane and a road lane between the same pair of
  hubs are not supported yet
  ([DECISION-009](open-decisions.md#decision-009)).

### Routing state

See [ADR-013](decisions.md#adr-013).

Route search depends only on explicit inputs and is deterministic with
respect to them:

- the static network: hubs, zone types, lanes, distances, normal capacities;
- the current `WeatherState`;
- the current turn;
- current occupancy and commitments: aircraft in hubs, aircraft in transit
  and the slots they hold ([ADR-019](decisions.md#adr-019));
- the routing request: the aircraft's position, its destination, and (from
  PR #9) the road distance it has driven since its last air leg.

Route search does not read `Drone` objects as hidden state, does not mutate
the graph, does not use the global `random` module, and never talks to a
weather provider or external API directly. Priority hubs remain a cost
preference, not a capacity rule.

### Capacity semantics and reservations

See [ADR-013](decisions.md#adr-013) and [ADR-019](decisions.md#adr-019).
Implemented in PR #10.

- **One capacity model.** The planner and the executor apply the same
  capacity rules:
  - a hub's load is the aircraft in it plus the aircraft flying towards it;
  - a leg holds its destination hub from departure to arrival
    ([ADR-008](decisions.md#adr-008));
  - a lane is held on every turn of a leg, and both directions count
    towards its capacity;
  - a distance lane allows one departure per direction per turn
    ([DECISION-008](open-decisions.md#decision-008));
  - a hub is freed in the same turn only by aircraft that actually leave.

  Without weather, plans now execute exactly, which removes finding 2.
- **Lanes only for admitted moves.** A departure gets a lane only if it also
  fits its destination hub. This fixes BUG-003 variant B.
- **Committed claims, not a reservation store.** What an aircraft holds is
  derived from its state:

  | Category | Kind |
  | --- | --- |
  | Its place in its current hub | Physical state |
  | In transit: its destination hub and its place on the lane | Committed, from departure to arrival |
  | Future hubs, lanes, and waits | Tentative, only while the initial routes are planned |
  | A route after a reroute | Intent, not reserved |

  A reroute replaces the route. There is nothing to release, and no claim
  can outlive the action it belongs to. Live future reservations were
  measured in PR #10 and not adopted (see [Since PR #10](#since-pr-10)).
- **Executor as a safety layer.** The executor keeps validating every move at
  runtime, even when plans are correct.

The initial cooperative planning is kept: it is what keeps the bundled maps
within their turn budgets ([ADR-005](decisions.md#adr-005)).

### Waiting and deadlocks

See [ADR-014](decisions.md#adr-014) and [ADR-020](decisions.md#adr-020).
Implemented in PR #10.

- **Waiting is staying in the current hub.** A planned route never returns to
  a hub it has left. Revisits happen only across decisions: a reroute or a way
  around a deadlock plans a simple route from the current hub
  ([DECISION-007](open-decisions.md#decision-007)).
- **Structural deadlock.** After each turn, the largest set of aircraft that
  tried to leave on an open lane, were not admitted, and are blocked only by
  each other: the aircraft in or flying to a full destination hub, and the
  aircraft on a full lane. A plain cycle in a wait-for graph is not enough:
  two aircraft can still swap over a lane with room for both, and a cycle
  through an aircraft in transit changes when it arrives.
- **Not a deadlock.** A turn without movement; aircraft waiting for weather,
  for a planned wait, or for an aircraft in transit; and anything waiting
  behind them.
- **Handling.** The first aircraft of the deadlock with a route around the
  hub it waits for takes it (`AgentRerouted`, reason `deadlock`). If such a
  route would exist only with every lane open, the aircraft wait. That check
  is a classification probe, not a forecast: it asks whether a way out is
  structurally possible once the temporary weather restriction is removed.
  Otherwise the run stops with `DeadlockError`.

### Weather boundary

See [ADR-012](decisions.md#adr-012).

```text
WeatherProvider ──→ WeatherState ──→ Simulator / routing state
(no weather,         snapshot of the       (decisions, travel time,
 seeded random,      current normalized     events)
 scripted,           domain weather
 later real weather)
```

Implemented in PR #8.

- **Provider.** The simulator asks the provider for the weather of a turn.
  Providers:
  - `NoWeather`;
  - `RandomWeather`, seeded, with its own `random.Random`;
  - `ScriptedWeather`, a fixed schedule for deterministic tests;
  - later, a real-weather provider (after PR #11, see
    [Delivery plan](#delivery-plan)).
- **`WeatherState`** is a snapshot of the current, observed condition of each
  connection, in the project's own terms.
  - It is not a forecast. Providers are not required to supply forecasts or
    expected durations, because a real-weather provider may not know how many
    turns a condition will last.
  - Whether a connection is open is not part of the weather. It depends on
    the connection's transport mode and is decided by the transport rules
    ([ADR-016](decisions.md#adr-016)).
  - Hubs have no weather: they are always safe
    ([ADR-015](decisions.md#adr-015)).
- **Simulator.** It compares each turn's state with the previous one and emits
  a `WeatherChanged` event for each connection whose condition changed. It
  rejects a state that names a connection the map does not define. Routing
  reads `WeatherState`, never the provider.
- **No global `random`.** Tests never depend on the global `random` module or
  on network access. Random mode stays available for ordinary runs. This also
  removes the debt of `update_weather()` drawing from the global state even
  when no storm can start.
- **Shared travel time.** Planner and executor compute travel time with the
  same transport rules. The weather penalties are provisional; how weather and
  restricted hubs affect distance lanes stays open until PR #11
  ([DECISION-001](open-decisions.md#decision-001)).

---

## Invariants and tests

The independent invariant checker ([ADR-004](decisions.md#adr-004)) keeps
working from events. The new model affects it as follows:

- **Committed transit** is already checked: an aircraft in transit arrives
  where it was heading.
- **Hub capacity** keeps one layer ([ADR-015](decisions.md#adr-015)), so the
  hub-capacity invariant needs no exceptions. Since PR #10 the checker also
  verifies the hub load of [ADR-008](decisions.md#adr-008): the aircraft in a
  hub plus those flying towards it never exceed its capacity.
- **Departure rule.** A distance lane has at most one departure per
  direction per turn (PR #10).
- **Closed lanes** are judged per transport mode. `WeatherChanged` carries
  whether the connection is open, computed by the transport rules, so the
  checker's "no departure on a closed lane" rule already follows the mode.
- **Consecutive road distance** is checked from movement events: no aircraft
  drives more consecutive road than the routing policy allows (PR #9).
- **Reroutes happen only at hubs.** An `AgentRerouted` event must name the
  hub the aircraft is in, never an aircraft in transit, and its route must
  end at the destination (PR #9). Each reroute carries its reason,
  `weather` or `deadlock` (PR #10).
- **Reroutes** need events of their own, so that tests can observe decisions
  without asserting specific routes ([ADR-002](decisions.md#adr-002)). How
  they appear in the text output is PR #12
  ([DECISION-003](open-decisions.md#decision-003)).
- **`ScriptedWeather`** lets behavior tests close a lane on a known turn and
  check that an aircraft finds another way, without fixing which way when
  several are equally good.
- **Plans execute exactly.** Without weather, every aircraft is delivered on
  its planned turn: checked on every bundled map and on three regression maps
  (PR #10).
- **Deadlock-free runs.** The random audit of [Since PR #10](#since-pr-10)
  remains a candidate for a maintained property-based test.

---

## Delivery plan

The original PR #8 was split in two: a transport and weather foundation, and
dynamic replanning. Later pull requests moved up by one.

| PR | Scope |
| --- | --- |
| PR #8 | Transport and weather foundation. Transport mode as map data, one set of transport rules, `WeatherState` with `NoWeather`, seeded `RandomWeather`, and `ScriptedWeather`. Roads stay open in storm and snow. ADR-015, ADR-016, ADR-017. No routing changes. |
| PR #9 | Dynamic replanning. Decision points, continue, wait, and reroute when the weather makes a route unusable, a reroute search on the current weather, `RoutingPolicy.max_consecutive_road_km` in every route search, the road distance each aircraft carries, `AgentRerouted`. ADR-018. No reservations v2. |
| PR #10 | One capacity model for planner and executor, with committed claims instead of a reservation store. Lanes only for admitted departures. No artificial waiting cycles. Deadlock detection and handling instead of a no-progress trigger. `DeadlockError`. BUG-003. ADR-019, ADR-020, [DECISION-007](open-decisions.md#decision-007), [DECISION-008](open-decisions.md#decision-008). |
| PR #11 | Weather-aware route cost and final weather penalties. [DECISION-001](open-decisions.md#decision-001). |
| PR #12 | Output and timeline: turns without movement, waiting, transit, and reroutes. [DECISION-003](open-decisions.md#decision-003), [BUG-004](bug-triage.md#bug-004). |
| PR #13 | Cleanup: unused pathfinder methods and model state ([TD-001, TD-002](bug-triage.md#technical-debt)), module boundaries. |

Not scheduled: parallel air and road lanes between the same hubs
([DECISION-009](open-decisions.md#decision-009)) and positioning moves
([DECISION-010](open-decisions.md#decision-010)). Real weather comes after
PR #11, as another provider behind the same boundary.

Accepted ADRs keep the numbers that were current when they were written. Read
them with this mapping:

| In ADR-010 to ADR-014 | Now |
| --- | --- |
| PR #8 (dynamic replanning, weather boundary) | PR #8 (weather boundary) and PR #9 (dynamic replanning) |
| PR #9 (reservations v2, BUG-003) | PR #10 |
| PR #10 (weather-aware routing) | PR #11 |
| PR #11 (output) | PR #12 |
| PR #12 (cleanup) | PR #13 |

---

## Open questions

PR #10 decided the no-progress trigger (not added,
[ADR-020](decisions.md#adr-020)),
[DECISION-007](open-decisions.md#decision-007), and
[DECISION-008](open-decisions.md#decision-008).

- A run that waits forever for a lane that never reopens still ends at the
  10,000-turn limit with a generic error. Telling it apart would need
  knowledge about future weather that providers do not give
  ([ADR-012](decisions.md#adr-012)).
- Restricted hubs on distance lanes and final weather penalties
  ([DECISION-001](open-decisions.md#decision-001)), PR #11.
- Turns without movement in the output
  ([DECISION-003](open-decisions.md#decision-003)), PR #12.
- Parallel air and road lanes ([DECISION-009](open-decisions.md#decision-009))
  and positioning moves ([DECISION-010](open-decisions.md#decision-010)),
  not scheduled.
