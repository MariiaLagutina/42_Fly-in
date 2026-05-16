from dataclasses import dataclass
from typing import Literal, Optional

import pygame

from events import (
    AgentMoved,
    AgentRefueling,
    EventListener,
    SimulationEvent,
    TurnFinished,
)
from graph import Graph
from zone import Zone, ZoneType

