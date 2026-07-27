import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
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
    schedule: Dict[int, str] = field(default_factory=dict)
    dialogue: Dict[str, Any] = field(default_factory=dict)
    faction_leader: bool = False
    memory: List[str] = field(default_factory=list)
    authority: int = 50
    courage: int = 50
    perception: int = 50
    hp: int = 100
    wounded: bool = False
    wound_type: str = ""
    is_historical_figure: bool = False
    death_influence: Dict[str, int] = field(default_factory=dict)
    bt_archetype: str = ""
    suspicion: int = 0
    shop_inventory: List[Dict[str, Any]] = field(default_factory=list)
    black_market_items: List[Dict[str, Any]] = field(default_factory=list)
    inventory: List[Dict[str, Any]] = field(default_factory=list)
    player_memories: Dict[str, Any] = field(default_factory=dict)
    tracked_rumors: List[dict] = field(default_factory=list)
    personality_traits: Dict[str, int] = field(default_factory=dict)
    needs: Dict[str, int] = field(default_factory=dict)
    burden_gift: str = ""
    burden_unlock_friendship: int = 70
    relationships: Dict[str, Any] = field(default_factory=dict)
    tutorial_dialogue: Dict[str, Any] = field(default_factory=dict)
    tutorial_essential: bool = False
    bolted: bool = False


def load_npcs(path: str) -> Dict[str, Npc]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    npcs = {}
    for npc_data in data.get("npcs", []):
        schedule = {int(hour): room_id for hour, room_id in npc_data.get("schedule", {}).items()}
        filtered_data = filter_to_dataclass(npc_data, Npc, exclude={"schedule"}, overrides={"schedule": schedule}, warn_unknown=True)
        npcs[npc_data["id"]] = Npc(**filtered_data)
    return npcs


def _pick_line(npc: Npc, bucket: str) -> Optional[str]:
    lines = npc.dialogue.get(bucket, [])
    return random.choice(lines) if lines else None


WANTED_PERCEPTION_THRESHOLD = 70
WANTED_FACTIONS_HELP = frozenset({"ccp", "green_gang"])
WANTED_FACTIONS_HOSTILE = frozenset({"kempeitai"})
