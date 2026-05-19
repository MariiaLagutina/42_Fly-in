import math


class SimulationConfig:
    """Central configuration for simulation thresholds, speeds,
    and multipliers."""
    # Travel mechanics
    UNREACHABLE_COST: float = math.inf
    AIR_TRAVEL_MIN_DIST: int = 200
    CAR_SPEED_KMH: float = 100.0
    AIRPLANE_SPEED_KMH: float = 400.0

    # Weather penalties
    WEATHER_PENALTY_SEVERE: int = 2
    WEATHER_PENALTY_MILD: int = 1
    TAILWIND_DIST_DIVISOR: float = 2.0

    # Weights and scoring factors
    PRIORITY_ZONE_DISCOUNT: float = 0.1
    PRIORITY_ZONE_BASE_COST: float = 0.5
    HIST_TRAFFIC_WEIGHT: float = 0.01
    CURR_TRAFFIC_WEIGHT: float = 0.02
    RESERVATION_PENALTY_WEIGHT: float = 0.1
