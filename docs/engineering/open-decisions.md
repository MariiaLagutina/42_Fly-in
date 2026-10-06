# Open Decisions

Questions about intended behavior that are not decided yet. Until a question
is decided, the current behavior is neither declared correct nor treated as
a bug, and tests do not assert it.

When a question is decided, the decision moves to [decisions.md](decisions.md)
as an ADR, and this entry is marked `DECIDED` with a link to it.

Statuses: `OPEN`, `NEEDS EVIDENCE`, `DECIDED`.

Target steps follow the delivery plan in
[dynamic-routing.md](dynamic-routing.md#delivery-plan). Future steps are
named by their scope, not by a predicted pull request number.

| ID | Question | Status | Blocks |
| --- | --- | --- | --- |
| [DECISION-001](#decision-001) | What are the final weather travel times, and do restricted hubs affect distance-based lanes? | `DECIDED` (weather part, [ADR-021](decisions.md#adr-021); restricted hubs moved to DECISION-011) | — |
| [DECISION-002](#decision-002) | What should an aircraft do when execution diverges from its plan? | `DECIDED` | — |
| [DECISION-003](#decision-003) | How are turns without movement represented in the output? | `OPEN` | — |
| [DECISION-004](#decision-004) | What makes a hub or route unsafe, and where does a weather diversion go? | `DECIDED` | — |
| [DECISION-005](#decision-005) | How does weather emergency overflow work? | `DECIDED` (not needed) | — |
| [DECISION-006](#decision-006) | How does routing policy compare waiting, rerouting, and diverting? | `DECIDED` (minimal policy) | — |
| [DECISION-007](#decision-007) | When is revisiting a hub legitimate? | `DECIDED` | — |
| [DECISION-008](#decision-008) | Does the one-departure-per-turn rule apply per lane or per direction? | `DECIDED` (per direction) | — |
| [DECISION-009](#decision-009) | Can two connections, such as air and road, join the same pair of hubs? | `OPEN` | — |
| [DECISION-010](#decision-010) | Should an aircraft move to an intermediate hub when no route to its destination is available? | `OPEN` | — |
| [DECISION-011](#decision-011) | Should a restricted hub add travel time on lanes with a distance? | `OPEN` | — |

---

## DECISION-001

### What are the final weather travel times, and do restricted hubs affect distance-based lanes?

- **Status:** `DECIDED` (weather part); restricted hubs moved to
  [DECISION-011](#decision-011)
- **Decided in:** [ADR-021](decisions.md#adr-021), in the Weather-aware cost
  step.

In short:

- **Weather travel times are final.** Rain adds one turn to a road leg,
  storm and snow add two, and a tailwind halves the distance of an air leg.
  `transport.travel_time` is the only source of route cost; routing adds no
  weather penalties.
- **Restricted hubs keep the current behavior.** On a lane with a distance,
  the destination's zone type does not change travel time. This is now
  documented and tested. Whether it should change is
  [DECISION-011](#decision-011), still open.

The text below is the question as it was recorded before the decision,
under the title "Does a restricted hub add travel time on distance-based
lanes?". It also covered the weather travel times.

- **Since PR #8:** the transport mode is map data, and travel time comes from
  one set of transport rules ([ADR-016](decisions.md#adr-016)). The weather
  penalties there are provisional and are settled together with this
  decision.

**Context.** The project has two travel-time models:

- **On lanes without `distance`:** entering a hub costs its movement cost.
  Restricted hubs cost 2 turns, as required by the original assignment.
- **On lanes with `distance`:** travel time comes from the distance and the
  lane's transport mode: road at 100 km/h, air at 400 km/h, adjusted by
  weather. (Before PR #8 the mode was inferred: under 200 km meant road.)

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

- **Status:** `DECIDED`
- **Decided in:**
  - [ADR-011](decisions.md#adr-011): decision points, replanning triggers, and
    routing options;
  - [ADR-013](decisions.md#adr-013): one capacity model and live reservations;
  - [ADR-014](decisions.md#adr-014): waiting in place and deadlock detection.

  The design and its evidence are in
  [dynamic-routing.md](dynamic-routing.md).

In short:

- An aircraft at a hub is replanned when its remaining route becomes unusable
  or it stops making progress (option 3, on triggers).
- Deadlocks are detected and handled (option 2).
- Planner and executor share one capacity model, so they do not disagree about
  resource feasibility when they evaluate the same state.
- Re-planning every aircraft on every weather change (option 4) was not
  chosen.

The text below is the question as it was recorded before the decision.

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

**Evidence collected (PR #7).**

- **Bundled maps without weather:** no divergence on any of the 12 maps.
- **Bundled maps with weather:** 12–97% of aircraft are delivered late.
- **3,000 random graphs without weather:** 487 diverge and 6 deadlock, so
  deadlocks occur without weather.
- **Cost of one cooperative route search:** up to about 20 ms on the challenger
  map and 5 ms on Europe.

Details are in [dynamic-routing.md](dynamic-routing.md#evidence).

---

## DECISION-003

### How are turns without movement represented in the output?

- **Status:** `OPEN`
- **To be decided in:** the Output & event audit step, together
  with how waiting, reroutes, and diversions are shown.

**Context.** The output format of the original assignment prints one line per
turn and omits aircraft that do not move. On long distance-based legs a turn
can pass in which no aircraft starts or finishes a move.

**Current behavior.** The simulation result keeps every completed turn,
including turns without movement ([ADR-023](decisions.md#adr-023)). The
assignment-style text output prints only turns with a movement, so the
number of lines is lower than the number of simulated turns. With
`--capacity-info`, such a turn prints only its capacity block. The movement
filter now belongs to the output, so any option below changes only the
output.

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

---

## DECISION-004

### What makes a hub or route unsafe, and where does a weather diversion go?

- **Status:** `DECIDED`
- **Decided in:** [ADR-015](decisions.md#adr-015).

In short:

- Every hub is always a safe waiting location. Weather affects connections
  and transport modes, never hub safety, so an aircraft never has to leave a
  hub because the hub became unsafe.
- Waiting at the current hub is always physically safe. Routing policy may
  still prefer rerouting.
- A route is *unavailable* when, under the current weather, it contains a
  connection whose transport mode is unavailable, or when it breaks a
  routing-policy limit such as the consecutive-road budget
  ([ADR-017](decisions.md#adr-017)).
- When a route to the destination exists, taking it is a **reroute**, even if
  it passes through different intermediate hubs or returns to a hub visited
  before. There is no emergency diversion from an unsafe hub.
- When no route to the destination is available, the aircraft waits. Moving
  to an intermediate hub in that case (a positioning move) is a separate open
  question ([DECISION-010](#decision-010)).

The text below is the question as it was recorded before the decision.

**Context.** [ADR-011](decisions.md#adr-011) lets an aircraft divert to a
nearby safe hub because of weather, and allows waiting only in a safe hub.
Today weather exists only on lanes: a lane is open or closed, and its
condition changes its travel time. No hub is ever unsafe.

**Questions.**

- **Unsafe hub.** Does a hub become unsafe through weather of its own, through
  the state of its lanes (for example, all of its onward lanes closed), or
  never in the first version?
- **Unsafe route.** Is a route unsafe only when a lane on it is closed, or also
  under conditions that leave it open (storm nearby, severe rain)?
- **Safe target.** What makes a hub a suitable safe target: not unsafe itself,
  reachable now over open lanes, with normal or emergency room, and not the
  start or end hub?
- **"Nearby".** Is it the shortest travel time over currently open lanes, a
  maximum number of legs, or something else?
- **After the diversion.** What does the aircraft do once it has diverted:
  stay until a trigger fires, or plan toward the destination at its next
  decision point?

**Possible options.**

1. In the first version, hubs are never unsafe. A route is unsafe when it is
   unavailable. Diversion means heading for the nearest hub from which the
   destination is still reachable over open lanes.
2. Add hub weather to `WeatherState` ([ADR-012](decisions.md#adr-012)), so a
   hub itself can be unsafe, and divert away from it.
3. Define unsafe from the state of a hub's lanes, without hub weather.

**Evidence needed.**

- What hub weather would add over lane weather on the bundled maps.
- What a real-weather source can provide per hub and per lane (Part 4 of the
  roadmap).

---

## DECISION-005

### How does weather emergency overflow work?

- **Status:** `DECIDED`: not needed
- **Decided in:** [ADR-015](decisions.md#adr-015).

Every hub is always safe, so no aircraft ever has to enter a full hub: an
aircraft in a hub can wait, an aircraft in transit already holds its
destination slot ([ADR-008](decisions.md#adr-008)), and start and end hubs
have unlimited capacity. Hub capacity keeps a single layer. The text below is
the question as it was recorded before the decision.

**Context.** [ADR-013](decisions.md#adr-013) splits hub capacity into normal
capacity and weather emergency overflow:

- only qualifying weather-diversion arrivals may use the overflow;
- ordinary routing and planning never consume it;
- it never changes the hub's normal capacity;
- the amount is policy, not a constant.

**Questions.**

- **Who qualifies.** Only diverting aircraft, or also an aircraft arriving
  from a leg that was closed behind it?
- **Amount.** A fixed number per hub, a fraction of normal capacity, or
  configured per map or run?
- **Start and end hubs.** Their capacity is unlimited today. Does overflow
  apply to them at all?
- **Leaving overflow.** How long may a hub stay above normal capacity? Must
  overflowing aircraft leave first once their route is available?
- **Other arrivals.** While a hub is above normal capacity, are ordinary
  arrivals refused until it is back below it?
- **Visibility.** How do events and the invariant checker show that an
  arrival used overflow, so that it is not reported as a capacity violation?

**Possible options.**

1. Overflow of `k` aircraft per hub, with `k` a policy parameter and `1` as
   the first default if evidence supports it. Only diverting aircraft qualify.
   Ordinary arrivals are refused while the hub is above normal capacity.
2. Overflow proportional to normal capacity.
3. No overflow in the first version: a diversion may only target a hub with
   normal room.

**Evidence needed.**

- How often a diversion would find no hub with normal room, on the bundled
  maps with weather.

---

## DECISION-006

### How does routing policy compare waiting, rerouting, and diverting?

- **Status:** `DECIDED` (minimal policy)
- **Decided in:** [ADR-018](decisions.md#adr-018), PR #9.

In short:

- An aircraft at a hub keeps its route while every remaining leg is
  available. It searches for a new route only when the weather makes a leg
  unavailable; it takes the route found, or waits and keeps its old route if
  there is none.
- No delay estimate is needed: a usable route is never compared with
  alternatives, and an unusable one is replaced by whatever route is
  available now.
- **No-progress trigger:** not added. Aircraft blocked by capacity are
  handled by deadlock detection instead
  ([ADR-020](decisions.md#adr-020), PR #10).
- **Since the Weather-aware cost step:** the trigger is wider. An aircraft
  also reconsiders its route when the weather makes it slower than in clear
  weather, and replaces an open route only by a strictly faster one under
  the same weather ([ADR-021](decisions.md#adr-021)). Still no delay
  estimate and no forecast: routes are costed with the current weather.

The text below is the question as it was recorded before the decision.

**Context.** [ADR-011](decisions.md#adr-011) requires routing policy to choose
between continuing, waiting, rerouting, and diverting using the current state.
[ADR-012](decisions.md#adr-012) does not require weather providers to supply
forecasts or how long a condition will last, because a real-weather source
may not know that.

**Questions.**

- How does policy estimate the cost of waiting for a closed lane without a
  forecast?
- When is a longer route better than waiting?
- How do the no-progress threshold and the waiting estimate interact?
- What is the fallback when no estimate is possible?

**Possible options.**

1. **Fixed estimate.** Treat a closed lane as closed for an assumed number of
   turns (a policy parameter), and compare ETAs.
2. **Prefer moving.** Reroute whenever an open alternative exists. Otherwise
   wait until the no-progress threshold.
3. **Learned estimate.** Estimate expected closure from what the simulation
   has observed so far in the run, with no provider support.
4. **Optional hints.** Use expected durations when a provider offers them as
   optional information, and fall back to option 1 or 2 otherwise.

**Evidence needed.**

- Turn counts on the bundled maps with weather under each option, using
  seeded `RandomWeather`.
- The cost of extra route searches each option causes.

---

## DECISION-007

### When is revisiting a hub legitimate?

- **Status:** `DECIDED`
- **Decided in:** [ADR-020](decisions.md#adr-020), PR #10.

In short:

- **Within one route, never.** A planned route does not return to a hub it
  has left; an aircraft waits in place instead. Every route search uses
  simple paths, so no loop can reset the consecutive-road budget.
- **Across decisions, yes.** A weather reroute, a way around a deadlock, or
  backtracking plans a simple route from the current hub, which may lead
  back to a hub visited earlier.
- **No oscillation limit.** The PR #10 audit found no run that failed to
  finish because of repeated reroutes, so none is added.
- **Evidence.** Three bundled maps change routes with the same turn
  counts. On 10,000 random maps without weather, the branch with this rule
  finishes 186 runs sooner and 8 runs one turn later than the same branch
  without it. Measured on the PR #10 code before and after the rule; the
  later deadlock handling never acts on these runs.

The text below is the question as it was recorded before the decision.

**Context.** [ADR-014](decisions.md#adr-014) forbids cycles used as a way of
waiting, and [ADR-011](decisions.md#adr-011) allows returning to a hub when the
state changes (backtracking, weather diversion). Between the two:

- A route found by a single search may still contain a revisit that is not
  waiting, for example a detour around a lane that is closed now and will be
  closed later.
- A sequence of reroutes could make an aircraft oscillate between hubs.

**Questions.**

- **Within one route.** May a single planned route revisit a hub at all, or
  only routes produced by separate decisions?
- **Oscillation.** Is a limit or penalty needed for an aircraft moving back and
  forth between the same hubs across decisions?
- **Telling them apart.** How does the planner distinguish "waiting through a
  cycle" from a legitimate detour?

**Possible options.**

1. **Simple routes.** A single route never repeats a hub. Revisits happen only
   across separate decisions, with an oscillation limit.
2. **Cost-based.** Revisits are allowed but never cheaper than waiting in
   place, so they appear only when they reach the goal sooner.
3. **No rule.** Detect oscillation only through the no-progress trigger.

**Evidence needed.**

- How many legitimate revisits remain on the bundled maps and in the random
  audit once artificial waiting cycles are gone.

---

## DECISION-008

### Does the one-departure-per-turn rule apply per lane or per direction?

- **Status:** `DECIDED` (per direction)
- **Decided in:** [ADR-019](decisions.md#adr-019), PR #10.

In short:

- **Per direction.** A distance lane allows one departure per direction per
  turn, in the planner and in the executor. Both directions still count
  towards the lane's capacity, so two aircraft can swap full hubs only
  when the lane has room for both.
- **Only admitted moves take a lane.** A departure gets lane capacity and
  its departure slot only if it also fits its destination hub. A rejected
  move takes nothing (BUG-003 variant B).
- **What the rule models.** Takeoff separation within one direction.
  Opposite directions do not share it.
- **Evidence.** Bundled map output is unchanged. Without any rule, the
  bonus maps would change (Germany from 14 to 9 printed turns), which is a
  larger change than this decision needs.

The text below is the question as it was recorded before the decision.

**Context.** The executor and the planner allow one departure per turn on each
distance lane, regardless of direction, in addition to `max_link_capacity`.
In both variant A reproducers of BUG-003, two aircraft need to swap hubs over
a lane with capacity 3. The capacity allows it, but the departure rule never
lets both leave in the same turn.

**Possible options.**

1. **Per lane** (current behavior). Swaps on distance lanes need deadlock
   handling.
2. **Per direction.** Two aircraft may leave in opposite directions in the
   same turn if lane capacity allows it.
3. **No departure rule.** Only `max_link_capacity` limits a lane.

**Impact.**

- Whether BUG-003 variant A can be resolved without deadlock handling.
- Turn counts on the bonus maps, which are the only bundled maps with distance
  lanes.
- The invariant checker, if the rule becomes an invariant.

**Evidence needed.**

- What the rule is meant to model (runway or takeoff separation, a single
  air corridor).
- How each option changes turn counts on the bonus maps.

---

## DECISION-009

### Can two connections, such as air and road, join the same pair of hubs?

- **Status:** `OPEN`
- **To be decided in:** not scheduled.

**Context.** Since PR #8 each connection has one transport mode
([ADR-016](decisions.md#adr-016)). Between two cities both a road and a
flight can exist, and a road could then serve as a fallback for that exact
pair when weather grounds the flight. Today the parser rejects a second
connection between the same hubs, in either direction.

**What it would change.**

- **Connection identity.** The name `A-B` is the key in reservations, events,
  weather states, the invariant checker, and the visualizers.
- **Route representation.** A route is a list of hubs, so it does not record
  which of two lanes it uses.
- **Lookup.** `Graph.get_connection` returns the first lane between two hubs.
- **Map format.** It needs a way to declare both lanes.

**Possible options.**

1. Keep one connection per pair (current behavior). Represent a road
   alternative through other hubs.
2. Allow parallel connections with distinct identities, and represent routes
   as legs (connection plus direction).
3. Allow one connection to offer several modes, each with its own
   availability and travel time, and record the chosen mode per leg.

**Evidence needed.**

- Which bundled or planned maps need a road and a flight between the same
  hubs (for example, road fallback on the Europe map, which has no road lanes
  today).

---

## DECISION-010

### Should an aircraft move to an intermediate hub when no route to its destination is available?

- **Status:** `OPEN`
- **To be decided in:** not scheduled. Needs evidence or forecasts first.

**Context.** [ADR-015](decisions.md#adr-015) makes every hub a safe waiting
location: with a route to the destination the aircraft continues or
reroutes, and without one it waits. A positioning move would take an aircraft
to another hub even though no route to its destination is available yet, for
example to be closer when a lane reopens.

**Why it is deferred.** Weather is a snapshot of the current state
([ADR-012](decisions.md#adr-012)). The current state alone never shows that
a positioning move beats waiting in a safe hub. It needs expectations about
future conditions, such as forecast hints from a real-weather provider or
statistics observed during the run
([DECISION-006](#decision-006)).

**Evidence needed.**

- Whether positioning moves would shorten runs with weather on the bundled
  maps, once dynamic replanning exists.

---

## DECISION-011

### Should a restricted hub add travel time on lanes with a distance?

- **Status:** `OPEN`
- **To be decided in:** not scheduled.
- **Split from:** [DECISION-001](#decision-001), whose weather part was
  decided in [ADR-021](decisions.md#adr-021).

**Context.** On lanes without a distance, entering a restricted hub takes
two turns instead of one, as required by the original assignment. On lanes
with a distance, travel time comes from the distance, the transport mode,
and the weather ([ADR-016](decisions.md#adr-016)).

**Current behavior.** On a lane with a distance, the destination's zone
type is ignored: entering a restricted hub takes as long as entering a
normal one. This is documented in the README and asserted by a transport
test, so that a change is a deliberate decision.

**Evidence from the Weather-aware cost audit.**

- The bonus maps contain three restricted hubs: Saarbrucken (Germany),
  Zurich and Milan (Europe). Milan has no lanes, so two restricted hubs are
  reached by distance lanes.
- The Europe map describes its restricted hubs as "Crossing the Alps is
  slow (restricted)". The current behavior does not make them slower.
- No initial plan on the bundled maps passes through a restricted hub: 0 of
  10 aircraft on Germany and 0 of 15 on Europe. Reroutes in weather runs can
  pass through them.

**Alternative considered.** Entering a restricted hub adds one turn on every
lane, so the rule is the same with and without a distance. Measured with
seeded `RandomWeather`, 30 seeds per map: Germany is unchanged (16.07
turns on average), Europe averages 47.43 turns instead of 46.93. Without
weather, neither map changes. It is not selected.

**Other options.** A multiplier on the distance travel time, or a parser
error for `zone=restricted` on hubs reached by distance lanes.

**Impact of a change.**

- Travel times on the bonus maps, mostly in weather runs.
- The invariant checker, which enforces restricted transit time only on
  lanes without a distance.
- The README and the transport test that asserts the current behavior.
