class SimulationConfig:
    """Central configuration for simulation thresholds, speeds,
    and multipliers."""
    # Travel mechanics
    CAR_SPEED_KMH: float = 100.0
    AIRPLANE_SPEED_KMH: float = 400.0

    # Extra turns on a road leg in bad weather, and the tailwind divisor for
    # air distance (DECISION-001); applied by transport.travel_time.
    WEATHER_PENALTY_SEVERE: int = 2
    WEATHER_PENALTY_MILD: int = 1
    TAILWIND_DIST_DIVISOR: float = 2.0

    # Weights and scoring factors
    PRIORITY_ZONE_DISCOUNT: float = 0.1
    HIST_TRAFFIC_WEIGHT: float = 0.01
    CURR_TRAFFIC_WEIGHT: float = 0.02
