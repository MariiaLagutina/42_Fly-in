import argparse
import sys
from events import EventDispatcher
from parser import Parser, ParseError
from simulation import Simulator
from visualizers import AirlinesVisualizer, CapacityInfoVisualizer, Visualizer


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
        from pygame_standard import PygameStandardVisualizer

        standard_visualizer = PygameStandardVisualizer(graph, nb_drones)
        if dispatcher is not None:
            dispatcher.add_listener(standard_visualizer)

    airlines_pygame_visualizer = None
    if args.pygame_airlines:
        from pygame_airlines import PygameAirlinesVisualizer

        airlines_pygame_visualizer = PygameAirlinesVisualizer(graph)
        if dispatcher is not None:
            dispatcher.add_listener(airlines_pygame_visualizer)

    simulator = Simulator(
        graph,
        nb_drones,
        dispatcher,
        enable_dynamic_weather=args.pygame_airlines,
    )
    try:
        turns = simulator.run()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return

    if standard_visualizer is not None:
        from pygame_standard import run_pygame_standard

        run_pygame_standard(standard_visualizer)
        return

    if airlines_pygame_visualizer is not None:
        from pygame_airlines import run_pygame_airlines

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
    capacity_blocks = (
        capacity_visualizer.render_blocks()
        if capacity_visualizer is not None
        else []
    )
    for index, turn in enumerate(turns):
        print(visualizer.render_turn(turn))
        if index < len(capacity_blocks):
            for line in capacity_blocks[index]:
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
