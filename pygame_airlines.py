import sys

import pygame

from events import EventListener, SimulationEvent, AgentMoved, AgentRefueling, WeatherChanged
from graph import Graph


class PygameAirlinesVisualizer(EventListener):
    def __init__(self, graph: Graph) -> None:
        self.graph = graph
        self.event_queue: list[SimulationEvent] = []
        self.drone_positions: dict[str, str] = {}
        self.connection_weather: dict[str, str] = {}

    def handle(self, event: SimulationEvent) -> None:
        self.event_queue.append(event)


def run_pygame_airlines(visualizer: PygameAirlinesVisualizer) -> None:
    pygame.init()
    width, height = 1000, 800
    screen = pygame.display.set_mode((width, height))
    pygame.display.set_caption("Fly-in: Global Logistics")
    clock = pygame.time.Clock()

    bg_image_name = "germany.png"

    for arg in sys.argv:
        if "europa" in arg.lower():
            bg_image_name = "europa.png"
    try:
        bg_image = pygame.image.load(bg_image_name)
        bg_image = pygame.transform.scale(bg_image, (width, height))
    except FileNotFoundError:
        print(f"Warning: {bg_image_name} not found! Using solid background.")
        bg_image = None

    city_font = pygame.font.SysFont("Arial", 16, bold=True)
    dashboard_font = pygame.font.SysFont("Courier", 14, bold=True)


    last_update_time = pygame.time.get_ticks()
    turn_delay = 500
    current_event_index = 0

    running = True
    while running:
        current_time = pygame.time.get_ticks()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                print(f"Coordinates: {event.pos[0]} {event.pos[1]}")

        if current_time - last_update_time > turn_delay:
            if current_event_index < len(visualizer.event_queue):
                sim_event = visualizer.event_queue[current_event_index]

                if isinstance(sim_event, AgentMoved):
                    visualizer.drone_positions[sim_event.agent_label] = ("zone", sim_event.destination)
                elif isinstance(sim_event, AgentRefueling):
                    visualizer.drone_positions[sim_event.agent_label] = ("connection", sim_event.origin, sim_event.destination)
                elif isinstance(sim_event, WeatherChanged):
                    visualizer.connection_weather[sim_event.connection_name] = sim_event.condition

                current_event_index += 1
                last_update_time = current_time

        if bg_image:
            screen.blit(bg_image, (0, 0))
        else:
            screen.fill((20, 30, 50))

        for conn in visualizer.graph.connections:
            start_pos = (conn.zone_a.x, conn.zone_a.y)
            end_pos = (conn.zone_b.x, conn.zone_b.y)
            condition = visualizer.connection_weather.get(conn.name(), "clear")

            if condition == "storm":
                color, thickness = (255, 50, 50), 5
            elif condition == "snow":
                color, thickness = (200, 200, 255), 5
            elif condition == "rain":
                color, thickness = (50, 100, 255), 4
            elif condition == "tailwind":
                color, thickness = (50, 255, 150), 4
            else:
                color, thickness = (200, 200, 200), 3

            pygame.draw.line(screen, color, start_pos, end_pos, thickness)

        # 2. Рисуем города и названия
        for zone in visualizer.graph.zones.values():
            node_color = (50, 255, 50) if zone.is_start or zone.is_end else (100, 200, 255)
            pygame.draw.circle(screen, node_color, (zone.x, zone.y), 10)

            # --- НОВОЕ: Пишем названия городов ---
            # Создаем черную тень текста, чтобы он читался поверх светлых участков карты
            shadow = city_font.render(zone.name, True, (0, 0, 0))
            screen.blit(shadow, (zone.x + 11, zone.y - 14))

            # Создаем основной белый текст
            text = city_font.render(zone.name, True, (255, 255, 255))
            screen.blit(text, (zone.x + 10, zone.y - 15))

        # 3. Рисуем самолеты
        for drone_label, pos_data in visualizer.drone_positions.items():
            pos_type = pos_data[0]
            if pos_type == "zone":
                zone = visualizer.graph.get_zone(pos_data[1])
                if zone:
                    pygame.draw.circle(screen, (255, 200, 0), (zone.x, zone.y), 6)
            elif pos_type == "connection":
                zone_a = visualizer.graph.get_zone(pos_data[1])
                zone_b = visualizer.graph.get_zone(pos_data[2])
                if zone_a and zone_b:
                    mid_x = (zone_a.x + zone_b.x) // 2
                    mid_y = (zone_a.y + zone_b.y) // 2
                    pygame.draw.circle(screen, (255, 150, 0), (mid_x, mid_y), 6)

        # 4. Дашборд погоды
        dashboard_surface = pygame.Surface((250, 200), pygame.SRCALPHA)
        dashboard_surface.fill((0, 0, 0, 180))
        screen.blit(dashboard_surface, (20, 20))

        title = dashboard_font.render("LIVE WEATHER ALERTS", True, (255, 200, 0))
        screen.blit(title, (30, 30))

        y_offset = 60
        for conn_name, condition in visualizer.connection_weather.items():
            if condition != "clear":
                text_color = (255, 100, 100) if condition in ["storm", "snow"] else (150, 200, 255)
                alert_text = dashboard_font.render(f"{conn_name}: {condition.upper()}", True, text_color)
                screen.blit(alert_text, (30, y_offset))
                y_offset += 20
                if y_offset > 200:
                    break

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
    sys.exit()