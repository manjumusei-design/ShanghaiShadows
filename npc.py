import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import yaml

from .trust import TrustMap, get_role_trust
from .dataclass_utils import filter_to_dataclass


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
    authority: int = 50
    courage: int = 50
    perception: int = 50
    is_historical_figure: bool = False


def load_npcs(path: str) -> Dict[str, Npc]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    npcs = {}
    for npc_data in data.get("npcs", []):
        schedule = {int(hour): room_id for hour, room_id in npc_data.get("schedule", {}).items()}
        filtered_data = filter_to_dataclass(npc_data, Npc, exclude={"schedule"}, overrides={"schedule": schedule})
        npcs[npc_data["id"]] = Npc(**filtered_data)
    return npcs


def _pick_line(npc: Npc, bucket: str) -> Optional[str]:
    lines = npc.dialogue.get(bucket, [])
    return random.choice(lines) if lines else None


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


def get_contextual_dialogue(npc: Npc, player_trust: TrustMap, context_type: str = "talk") -> str:
    trust_score = get_role_trust(player_trust, npc.faction, npc.role)

    if context_type == "greeting":
        line = _pick_line(npc, "greeting")
        if line:
            return line

    if context_type == "farewell":
        line = _pick_line(npc, "farewell")
        if line:
            return line

    if context_type == "gossip":
        line = _pick_line(npc, "gossip")
        if line:
            return line

    if trust_score < 30:
        afraid = _pick_line(npc, "afraid")
        if afraid:
            return afraid
        hostile = _pick_line(npc, "hostile")
        if hostile:
            return hostile

    if trust_score > 70:
        friendly = _pick_line(npc, "friendly")
        if friendly:
            return friendly

    if context_type == "ask":
        for bucket in ("gossip", "neutral", "greeting"):
            line = _pick_line(npc, bucket)
            if line:
                return line

    line = _pick_line(npc, "neutral") or _pick_line(npc, "greeting")
    return line or "..."
