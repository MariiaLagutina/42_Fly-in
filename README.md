# Fly-in

Fly-in is an autonomous drone routing simulator. It parses a map of hubs,
zones, and bidirectional connections, assigns routes to multiple drones, and
runs a discrete turn-based simulation until every drone reaches the end hub.

## Requirements

- Python 3.10 or later
- No external graph libraries are used; the graph, parser, pathfinder, and
  simulator are custom object-oriented Python classes.
- Optional visual mode uses ANSI terminal colors.
- Optional Pygame visualizer requires `pygame`.

Install development tools:

```sh
make install
```

## Usage

Run a map:

```sh
make run MAP=maps/easy/01_linear_path.txt
```

Or directly:

```sh
python3 main.py maps/easy/01_linear_path.txt
```

Useful flags:

- `--visual`: colorizes strict simulation output using zone metadata.
- `--airlines`: prints a more descriptive aviation-style event log.
- `--capacity-info`: prints live zone and connection usage after each turn.
- `--pygame-airlines`: opens the optional Pygame visualizer.

Example:

```sh
python3 main.py maps/easy/03_basic_capacity.txt --capacity-info
```

## Map Format

Maps define the drone count, one start hub, one end hub, optional intermediate
hubs, and connections:

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
- `color=<ansi color name>` or `color=rainbow`
- `max_drones=<positive integer>`

Supported connection metadata:

- `max_link_capacity=<positive integer>`

The parser rejects malformed lines, missing start/end hubs, duplicate zone
names, duplicate connections, repeated start/end definitions, and invalid
capacity values with explicit `ParseError` messages.

## Simulation Rules

- The simulation is turn-based and all drones are considered simultaneously.
- Normal and priority zones cost 1 turn to enter.
- Restricted zones cost 2 turns to enter, and the drone occupies the
  connection while in transit.
- Blocked zones are inaccessible and excluded from neighbor expansion.
- Start and end hubs have unlimited effective capacity.
- Intermediate zones enforce `max_drones`.
- Connections enforce `max_link_capacity`.

## Algorithm

Routing uses a cooperative time-expanded search. Drones are assigned one at a
time. For each drone, the pathfinder explores `(zone, time)` states with a
priority queue, considering both movement and waiting in place. Existing zone
and connection reservations are checked before a move is accepted, so later
drones avoid conflicts created by earlier route plans.

Priority zones receive a small cost discount, restricted zones add their
movement cost, and historical usage adds a small traffic penalty to spread
drones across available alternatives.

For `V` zones, `E` connections, and a practical time horizon `T`, the
cooperative search is approximately `O((V * T + E * T) log(V * T))` per drone
because each time-expanded state is pushed through a heap. The trade-off is
that routes are planned greedily per drone rather than globally optimized,
which keeps the implementation explainable and fast while still avoiding most
capacity conflicts and deadlocks.

## Development

Run linting and typing:

```sh
make lint
make lint-strict
```

Clean generated files:

```sh
make clean
```
