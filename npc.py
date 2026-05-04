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


def load_npcs(path: str) -> Dict[str, Npc]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    npcs = {}
    for npc_data in data.get("npcs", []):
        npcs[npc_data["id"]] = Npc(
            id=npc_data["id"],
            name=npc_data["name"],
            description=npc_data["description"],
            faction=npc_data["faction"],
            schedule=npc_data.get("schedule", {}),
            dialogue=npc_data.get("dialogue",{})
        )
    return npcs