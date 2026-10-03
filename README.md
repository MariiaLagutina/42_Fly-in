# Maria's Airlanes

_Inspired by the 42 school project "Fly-in"._

Maria's Airlanes is a turn-based air-traffic simulation. A fleet of aircraft
departs from one hub and must reach a destination hub through a network of
air lanes, while every hub and every lane has a limited capacity. The planner
schedules each flight through space and time, so aircraft spread across
alternative routes, hold deliberately when a lane is busy, and never exceed a
capacity limit.

The simulator, parser, routing algorithm, event system, and visualizers are
written from scratch in Python. On top of the routing core, the project adds
an aviation layer: real maps of Germany and Europe, distance-based road and
air legs, live weather, and a Pygame dispatch center.

## Highlights

- **Space-time routing.** Flights are planned over `(hub, turn)` states with
  reservation tables, so conflicts are avoided before they happen rather than
  resolved after a collision.
- **Capacity constraints.** Hubs limit how many aircraft they can hold at
  once; air lanes limit how many aircraft can use them at the same time.
- **Hub types.** `normal`, `priority` (preferred by the planner),
  `restricted` (takes two turns to enter), and `blocked` (never used).
- **Road and air legs.** On distance-based maps, legs shorter than 200 km are
  travelled by road, longer legs by air, each with its own speed and default
  lane capacity.
- **Dynamic weather.** In the dispatch center mode, storms, snow, rain, and
  tailwinds appear and clear during the simulation and change which lanes are
  open and how long a leg takes.
- **Real maps.** Germany (16 hubs) and Europe (24 hubs) with real city names,
  populations, and distances.
- **Aviation dispatch center.** A Pygame interface with a geographic map,
  departure board, weather alerts, and a replayable timeline.
- **Event-driven core.** The simulation emits typed events; every output mode,
  from plain text to Pygame, is a listener on the same event stream.

## Quick start

Requirements: Python 3.10+, [`uv`](https://docs.astral.sh/uv/), and
`pygame-ce` for the graphical modes (installed by `make install`).

```sh
make install
make run MAP=maps/easy/01_linear_path.txt
```

Open the aviation dispatch center on a real map:

```sh
make run-pygame-airlines MAP=maps/bonus/germany_map.txt
make run-pygame-airlines MAP=maps/bonus/europa_map.txt
```

Open the standard turn viewer on any map:

```sh
make run-pygame MAP=maps/hard/03_ultimate_challenge.txt
```

## Output modes

`main.py <map>` accepts one map file and these options:

| Option | Output |
| --- | --- |
| _(none)_ | Compact text: one line per turn, one `D<n>-<destination>` token per moving aircraft |
| `--visual` | The same text, colored with ANSI codes from the map's hub colors |
| `--airlines` | Readable flight log: departures, legs in progress, arrivals |
| `--capacity-info` | Adds per-turn hub and lane usage, for example `Hamburg=2/18` |
| `--pygame` | Standard Pygame turn viewer for any map |
| `--pygame-airlines` | Aviation dispatch center with dynamic weather |

Example of the compact output:

```txt
D1-waypoint1
D1-waypoint2 D2-waypoint1
D1-goal D2-waypoint2
D2-goal
```

## How routing works

Aircraft are planned one after another with a cooperative, Dijkstra-style
best-first search over `(hub, turn)` states. While a route is being built, the planner reads and
updates shared reservation tables:

- hub occupancy at each turn
- lane usage for every turn a leg is in progress
- departure slots on distance-based lanes, so two aircraft do not take off
  on the same lane in the same turn

A candidate move is accepted only if the destination hub has room at the
arrival turn and the lane stays available for the whole leg. Holding in place
is a valid move, which lets an aircraft wait out a conflict instead of taking
a much longer route.

The cost of a move combines its travel time (restricted hubs take two turns,
distance-based legs follow the table below), a discount for priority hubs, and
small penalties for hubs that earlier flights already use or have booked for
the same turn. The penalties spread traffic across parallel routes.

Routes are committed one aircraft at a time, so the result is not a proven
global optimum. In exchange the planner is fast, explainable, and produces
compact schedules on all included maps.

During execution, the simulator runs each turn in phases: aircraft finishing
a leg arrive first, then departures are planned from a stable snapshot, and
only moves that pass the capacity checks are applied.

## Road and air legs

When a lane has a `distance`, travel time is derived from it:

| Distance | Mode | Speed | Default lane capacity |
| --- | --- | --- | --- |
| under 200 km | road | 100 km/h | 3 |
| 200–500 km | air | 400 km/h | 1 |
| over 500 km | air | 400 km/h | 2 |

The default capacity applies only when the lane does not set
`max_link_capacity` itself. Similarly, a hub with a `population` but no
explicit capacity gets one slot per 100,000 inhabitants.

## Weather

Weather is active in `--pygame-airlines` mode. Each turn, every clear lane has
a 5% chance to change, and every affected lane has a 20% chance to clear again.

| Condition | Effect |
| --- | --- |
| `storm`, `snow` | Lane closes; aircraft waiting for it hold until it reopens |
| `rain` | Road legs take one extra turn |
| `tailwind` | Air legs count as half their distance |

Routes are planned before the first turn and are not re-planned when the
weather changes. Weather affects whether a leg can start and how long it
takes once started. Weather is random and not seeded, so two runs of the same
map can differ.

## Aviation dispatch center

`--pygame-airlines` opens an air-traffic-control style view:

- geographic background for the Germany and Europe maps
- cities sized and colored by population
- airplanes on air legs and cars on road legs, outlined with `pygame.mask` so
  they stay readable on the map
- lanes colored by current weather, with weather icons
- a departure board with a flight number and status for every aircraft
  (`EN ROUTE`, `DRIVING`, `DELAYED`, `ROAD DELAY`, `LANDED`)
- weather alerts in the sidebar
- clicking a city prints a hub report (population, hub type, current load)
  to the terminal

The viewer replays the recorded event stream, so it can step backwards and
forwards through time.

| Key | Action |
| --- | --- |
| `Space` | Play or pause |
| `Right Arrow` | Next turn |
| `Left Arrow` | Previous turn |
| `R` | Reset to turn 0 |

The standard viewer (`--pygame`) uses the same controls.

## Map format

```txt
nb_drones: 4
start_hub: start 0 0 [color=green max_drones=4]
hub: tunnel 1 0 [zone=restricted color=red max_drones=2]
end_hub: goal 2 0 [color=green]
connection: start-tunnel [max_link_capacity=1]
connection: tunnel-goal
```

The keywords `nb_drones` and `max_drones` come from the original project and
are kept for compatibility: `nb_drones` is the number of aircraft, and
`max_drones` is a hub's capacity.

Hub metadata:

- `zone=normal|restricted|priority|blocked`
- `color=<name>`
- `max_drones=<positive integer>`
- `population=<positive integer>`

Lane metadata:

- `max_link_capacity=<positive integer>`
- `distance=<positive integer>km`

The parser reports malformed lines, duplicate hubs and lanes, invalid
capacities, unknown hub types, and missing start or end hubs as a `ParseError`
with the line number. If no route connects the start and end hubs, the
simulator stops with an explicit error.

### Included maps

| Folder | Content |
| --- | --- |
| `maps/easy`, `maps/medium`, `maps/hard` | Abstract graphs from a single lane to dense mazes with tight capacities |
| `maps/challenger` | A 25-aircraft stress test |
| `maps/bonus` | Germany and Europe with real cities, populations, and distances |

## Architecture

```txt
map file → Parser → Graph (hubs, lanes)
                      ↓
                  Pathfinder ← reservation tables
                      ↓
                  Simulator ← WeatherSystem
                      ↓
                EventDispatcher
          ↙        ↓         ↓          ↘
      text    flight log  Pygame     dispatch center
```

| Module | Responsibility |
| --- | --- |
| `parser.py` | Reads map files into a `Graph`, reports `ParseError` |
| `graph.py`, `zone.py`, `connection.py` | Hubs, lanes, and their capacities |
| `drone.py` | State of a single aircraft (waiting, in transit, delivered) |
| `pathfinder.py` | Cooperative space-time search and move costs |
| `simulation.py` | Turn execution and capacity checks |
| `weather.py` | Random weather changes on lanes |
| `events.py` | Typed events and the dispatcher |
| `visualizers.py` | Text, flight log, and capacity output |
| `pygame_standard.py`, `pygame_airlines.py`, `pygame_common.py` | Pygame viewers and their shared helpers |
| `config.py` | Speeds, thresholds, and cost weights |

The simulator does not know which visualizer is attached, so it can run
headless while the graphical viewers replay the same events.

## Development

After cloning, set up the environment and enable the repository hooks once:

```sh
make install       # create .venv and install dependencies
make hooks         # git config core.hooksPath .githooks
```

`make hooks` is the only command that changes your local Git configuration.
It activates `.githooks/pre-commit`, which rejects commits made directly on
`main`.

```sh
make lint          # flake8 + mypy
make lint-strict   # flake8 + mypy --strict
make clean         # remove caches and the virtual environment
```

Changes reach `main` only through pull requests, and every pull request is
squash-merged into a single commit.

## Background

The project started as "Fly-in", a 42 school assignment about moving a fleet
through a capacity-limited graph in as few turns as possible. The compact text
output still follows that assignment's format. Maria's Airlanes continues from
there as an independent project focused on aviation-style simulation.

## Resources

- Hart, P. E., Nilsson, N. J., and Raphael, B. (1968).
  "A Formal Basis for the Heuristic Determination of Minimum Cost Paths."
- Silver, D. (2005). "Cooperative Pathfinding."
  <https://ojs.aaai.org/index.php/AIIDE/article/view/18726/18503>
- <https://theory.stanford.edu/~amitp/GameProgramming/AStarComparison.html>
- Gamma, E., Helm, R., Johnson, R., and Vlissides, J. (1994).
  _Design Patterns: Elements of Reusable Object-Oriented Software._
- Python documentation
- Pygame documentation

### AI usage

AI tools were used as learning support during development: to discuss design
alternatives, improve wording, review type-checking issues. The graph model,
parser rules, scheduling logic, cooperative pathfinding approach, simulation
architecture, and project-specific bonus features were designed and implemented
by me.

## License

MIT, © 2026 Mariia Lagutina. See [LICENSE](LICENSE).
