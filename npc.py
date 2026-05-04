import random
from dataclasses import dataclass, field
from typing import Dict, List
import yaml


@dataclass
class Npc:
    id: str
    name: str
    description: str
    faction: str
    schedule: Dict[int, str] 
    dialogue: Dict[str, List[str]]
    memory: List[str] = field(default_factory=list)


    