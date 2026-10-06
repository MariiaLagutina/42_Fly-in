import argparse
import sys

from airlanes.events import EventDispatcher
from airlanes.mapfile import Parser, ParseError
from airlanes.output.text import (
    AirlinesVisualizer,
    CapacityInfoVisualizer,
    Visualizer,
)
from airlanes.simulation.engine import Simulator
from airlanes.world.weather import RandomWeather


def main() -> None:
    args = _parse_args()
    parser = Parser()

    try:
        graph, nb_drones = parser.parse(args.map_file)
    except ParseError as exc:
        print(f"Error parsing input file: {exc}", file=sys.stderr)
        return
    except FileNotFoundError:
        print(f"File not found: {args.map_file}", file=sys.stderr)
        return

    dispatcher = (
        EventDispatcher()
        if (
            args.airlines
            or args.pygame
            or args.pygame_airlines
            or args.capacity_info
        )
        else None
    )
    airlines_visualizer = AirlinesVisualizer() if args.airlines else None
    if dispatcher is not None and airlines_visualizer is not None:
        dispatcher.add_listener(airlines_visualizer)

    capacity_visualizer = (
        CapacityInfoVisualizer() if args.capacity_info else None
    )
    if dispatcher is not None and capacity_visualizer is not None:
        dispatcher.add_listener(capacity_visualizer)

    standard_visualizer = None
    if args.pygame:
        from airlanes.output.pygame.standard import PygameStandardVisualizer

        standard_visualizer = PygameStandardVisualizer(graph, nb_drones)
        if dispatcher is not None:
            dispatcher.add_listener(standard_visualizer)

    airlines_pygame_visualizer = None
    if args.pygame_airlines:
        from airlanes.output.pygame.airlines import PygameAirlinesVisualizer

        airlines_pygame_visualizer = PygameAirlinesVisualizer(graph)
        if dispatcher is not None:
            dispatcher.add_listener(airlines_pygame_visualizer)

    simulator = Simulator(
        graph,
        nb_drones,
        dispatcher,
        weather=RandomWeather(graph) if args.pygame_airlines else None,
    )
    try:
        turns = simulator.run()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return

    if standard_visualizer is not None:
        from airlanes.output.pygame.standard import run_pygame_standard

        run_pygame_standard(standard_visualizer)
        return

    if airlines_pygame_visualizer is not None:
        from airlanes.output.pygame.airlines import run_pygame_airlines

        run_pygame_airlines(airlines_pygame_visualizer)
        return

    if airlines_visualizer is not None:
        for line in airlines_visualizer.render():
            print(line)
        if capacity_visualizer is not None:
            for line in capacity_visualizer.render():
                print(line)
        return

    visualizer = Visualizer(graph, use_color=args.visual)
    for turn in turns:
        # Assignment-style output prints only turns with a movement; the
        # capacity block of every turn follows it, matched by turn number.
        if turn.movements:
            print(visualizer.render_turn(turn))
        if capacity_visualizer is not None:
            block = capacity_visualizer.block_for(turn.turn_number)
            if block is not None:
                for line in block:
                    print(line)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Drone routing simulator")
    parser.add_argument("map_file", help="Path to the map file")
    parser.add_argument(
        "--visual",
        action="store_true",
        help="Use ANSI colors in strict evaluation output",
    )
    parser.add_argument(
        "--airlines",
        action="store_true",
        help="Use aviation-themed presentation output",
    )
    parser.add_argument(
        "--pygame",
        action="store_true",
        help="Open the standard Pygame turn viewer",
    )
    parser.add_argument(
        "--pygame-airlines",
        action="store_true",
        help="Open the optional Pygame aviation visualizer",
    )
    parser.add_argument(
        "--capacity-info",
        action="store_true",
        help="Display real-time zone and connection capacity usage",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
