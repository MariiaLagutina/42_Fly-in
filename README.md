_This project has been created as part of the 42 curriculum by mlagutin._

# Fly-in

## Description

Fly-in is a turn-based drone-routing simulator built around graph traversal,
capacity management, and conflict-free scheduling. The mandatory objective is
to move every drone from one start hub to one end hub in as few turns as
possible while respecting zone capacity, connection capacity, movement costs,
and simultaneous movement rules.

The core project is implemented from scratch in Python: parser, graph model,
pathfinding, simulator, event system, and visualizers are all custom code. The
main routing strategy uses a cooperative time-expanded search so each drone is
planned not only through space, but also through time. This allows the
simulator to distribute drones across several routes, wait deliberately when a
path is blocked, and avoid collisions or deadlocks before they happen.

Beyond the standard subject, this project also contains my own extended
simulation layer: a multi-modal logistics mode inspired by air-traffic control.
The bonus maps model Germany and Europe with real city hubs, geographic
distances, population metadata, dynamic weather, car routes for short links,
air routes for long links, and an aviation-themed Pygame dispatch center. This
part turns the assignment from a pure routing problem into a richer transport
simulation with changing conditions, different travel speeds, and a more
expressive visual experience.

## Mandatory Features

- Custom parser with explicit error messages for malformed maps
- Support for `normal`, `restricted`, `priority`, and `blocked` zones
- Zone occupancy limits through `max_drones`
- Connection throughput limits through `max_link_capacity`
- Simultaneous drone movement with turn-by-turn conflict checks
- Multi-turn travel through restricted zones
- Standard textual output compatible with the subject format
- Visual feedback through ANSI output and a standard Pygame viewer

## My Extended Features

### Multi-modal transport

The bonus logistics mode chooses transport behavior from the distance stored on
each connection:

- Routes under `200 km` behave like road transport at `100 km/h`
- Longer routes behave like air transport at `400 km/h`
- Short road links can carry more traffic, while long-haul routes use stricter
  capacity and departure spacing

This creates maps that feel less abstract: a nearby city pair behaves like a
regional road corridor, while cross-country links behave like scheduled air
routes.

### Dynamic weather

When the aviation visualizer is enabled, a weather system updates the network
during the simulation:

- `storm` and `snow` can close a route
- `rain` slows ground travel
- `tailwind` reduces long-distance travel time

The simulator applies these conditions during execution, so the bonus mode is
not just a static map replay. Travel time can change, route availability can
change, and the visualizer exposes those changes turn by turn.

### Real map metadata

The Germany and Europe bonus maps use city names, populations, distances, and
hub-specific capacities. Population metadata is also reused by the aviation
visualizer to size and color cities, which gives the maps a stronger sense of
place than a generic graph layout.

### Event-driven architecture

The simulation engine does not depend on any specific visualizer. Instead, it
emits typed events such as `TurnStarted`, `AgentMoved`, `AgentRefueling`,
`CapacitySnapshot`, and `WeatherChanged`. Console output, capacity reporting,
the standard viewer, and the aviation viewer subscribe to the same event flow.

This keeps the simulator testable in headless mode while making it possible to
add richer interfaces without rewriting the core logic.

### Aviation dispatch center

The custom Pygame airline mode adds:

- Geographic background maps for Germany and Europe
- Live route coloring based on weather
- A departure board with flight-like identifiers and statuses
- Distinct airplane and car rendering for different route types
- Play, pause, reset, previous-turn, and next-turn controls
- A replayable event timeline that behaves like a small time machine

Sprite silhouettes are outlined programmatically with `pygame.mask`, which
keeps vehicles readable against detailed map backgrounds.

## Algorithm and Implementation Strategy

The project uses a cooperative pathfinding approach over `(zone, time)` states.
Each drone is assigned a route in sequence. While planning a route, the
pathfinder keeps reservation tables for:

- occupied zones at a specific turn
- occupied connections during multi-turn travel
- departure conflicts on distance-based routes

For every candidate move, the search checks whether the destination zone has
capacity at the arrival turn and whether the connection remains available for
the entire transit duration. Waiting in place is also considered as a valid
move, which is important when a drone must avoid a temporary conflict instead
of taking a worse route.

The cost model combines:

- travel time
- zone movement cost
- a small preference for priority zones
- historical traffic penalties that encourage route distribution
- weather-adjusted travel time in the extended simulation mode

This is not a globally optimal solver for every possible map, because routes
are committed one drone at a time, but it is explainable, efficient, and well
matched to the subject constraints. It handles overlapping paths, bottlenecks,
restricted zones, and capacity-limited links while still producing compact
turn counts on the provided maps.

## Instructions

### Requirements

- Python `3.10+`
- `uv` for the provided `Makefile` workflow
- `pygame-ce` for the Pygame visualizers

Install the development environment:

```sh
make install
```

### Run the simulator

Run the mandatory text mode:

```sh
make run MAP=maps/easy/01_linear_path.txt
```

Equivalent direct command:

```sh
python3 main.py maps/easy/01_linear_path.txt
```

Useful options:

- `--visual` adds ANSI colors to the standard textual output
- `--airlines` prints an aviation-themed event log
- `--capacity-info` prints live zone and connection usage
- `--pygame` opens the standard graph visualizer
- `--pygame-airlines` opens the extended aviation visualizer

Examples:

```sh
make run-pygame MAP=maps/easy/01_linear_path.txt
make run-pygame MAP=maps/challenger/01_the_impossible_dream.txt
make run-pygame-airlines MAP=maps/bonus/germany_map.txt
make run-pygame-airlines MAP=maps/bonus/europa_map.txt
```

### Pygame controls

Standard and Aviation viewer:

- `Space`: play or pause
- `Left Arrow`: previous turn
- `Right Arrow`: next turn
- `R`: reset to turn `0`

## Map Format

Example:

```txt
nb_drones: 4
start_hub: start 0 0 [color=green max_drones=4]
hub: tunnel 1 0 [zone=restricted color=red max_drones=2]
end_hub: goal 2 0 [color=green]
connection: start-tunnel [max_link_capacity=1]
connection: tunnel-goal
```

Supported zone metadata:

- `zone=normal|restricted|priority|blocked`
- `color=<name>`
- `max_drones=<positive integer>`
- `population=<positive integer>` for extended visual maps

Supported connection metadata:

- `max_link_capacity=<positive integer>`
- `distance=<positive integer>km` for extended transport behavior

The parser rejects malformed lines, duplicate zones, duplicate connections,
invalid capacities, missing start or end hubs, and invalid zone types with a
line-numbered `ParseError`.

## Visual Representation

The project provides several levels of feedback:

- strict text output for subject evaluation
- optional colored terminal output for quick reading
- a standard Pygame graph viewer for turn-by-turn inspection
- a custom aviation Pygame interface for the bonus maps

The visual layers are useful for more than presentation. They make occupancy,
delays, route choices, and bottlenecks easier to understand while debugging the
algorithm, especially on maps where several drones interact at once.

## Development

Run linting and type checks:

```sh
make lint
make lint-strict
```

Clean generated files:

```sh
make clean
```

## Resources

- Hart, P. E., Nilsson, N. J., and Raphael, B. (1968).
  "A Formal Basis for the Heuristic Determination of Minimum Cost Paths."
- Silver, D. (2005). "Cooperative Pathfinding."
  https://ojs.aaai.org/index.php/AIIDE/article/view/18726/18503
- https://theory.stanford.edu/~amitp/GameProgramming/AStarComparison.html
- Gamma, E., Helm, R., Johnson, R., and Vlissides, J. (1994).
  *Design Patterns: Elements of Reusable Object-Oriented Software.*
- Python documentation
- Pygame documentation

### AI usage

AI tools were used as learning support during development: to discuss design
alternatives, improve wording, review type-checking issues. The graph model,
parser rules, scheduling logic, cooperative pathfinding approach, simulation
architecture, and project-specific bonus features were designed and implemented
by me.
