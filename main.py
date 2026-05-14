import argparse
import sys
from events import EventDispatcher
from parser import Parser, ParseError
from simulation import Simulator
from visualizers import AirlinesVisualizer, Visualizer


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
        if args.airlines or args.pygame_airlines
        else None
    )
    airlines_visualizer = AirlinesVisualizer() if args.airlines else None
    if dispatcher is not None and airlines_visualizer is not None:
        dispatcher.add_listener(airlines_visualizer)

    pygame_visualizer = None
    if args.pygame_airlines:
        from pygame_airlines import PygameAirlinesVisualizer

        pygame_visualizer = PygameAirlinesVisualizer(graph)
        if dispatcher is not None:
            dispatcher.add_listener(pygame_visualizer)

    simulator = Simulator(
        graph,
        nb_drones,
        dispatcher,
        enable_dynamic_weather=args.pygame_airlines
    )
    turns = simulator.run()

    if pygame_visualizer is not None:
        from pygame_airlines import run_pygame_airlines

        run_pygame_airlines(pygame_visualizer)
        return

    if airlines_visualizer is not None:
        for line in airlines_visualizer.render():
            print(line)
        return

    visualizer = Visualizer(graph, use_color=args.visual)
    for turn in turns:
        print(visualizer.render_turn(turn))


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
        "--pygame-airlines",
        action="store_true",
        help="Open the optional Pygame aviation visualizer",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
