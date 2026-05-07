import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .npc import Npc


@dataclass
class TailingState:
    target_npc_id: str
    distance: int = 2
    elapsed_minutes: int = 0
    last_checked_minute: int = 0


@dataclass
class Disguise:
    id: str
    name: str
    apparent_faction: str
    bonus: int
    description: str


