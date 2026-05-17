import random
from dataclasses import dataclass, field
from typing import Dict, List   
import yaml

from .trust import TrustMap, get_role_trust


@dataclass
class Npc:
    id: str
    name: str
    description: str
    faction: str
    role: str
    personality: str
    awareness: int
    faction_leader: bool
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
            role=npc_data.get("role", "resident"),
            personality=npc_data.get("personality", "guarded"),
            awareness=int(npc_data.get("awareness", 50)),
            faction_leader=bool(npc_data.get("faction_leader", False)),
            schedule={int(hour): room_id for hour, room_id in npc_data.get("schedule", {}).items()},
            dialogue=npc_data.get("dialogue", {}),
        )
    return npcs


def get_dialogue(npc: Npc, player_trust: TrustMap) -> str:
    trust_score = get_role_trust(player_trust, npc.faction, npc.role)
    if trust_score > 70:
        key = "friendly" if "friendly" in npc.dialogue else "greeting"
    elif trust_score < 30:
        key = "hostile" if "hostile" in npc.dialogue else "neutral"
    else:
        key = "greeting" if "greeting" in npc.dialogue else "neutral"
    lines = npc.dialogue.get(key, ["..."])
    return random.choice(lines)

