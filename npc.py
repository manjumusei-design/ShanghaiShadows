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
    is_historical_figure: bool = False
    death_influence: Dict[str, int] = field(default_factory=dict)
    bt_archetype: str = ""
    suspicion: int = 0


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


CANON_TOPICS = {
    "work": ("work", "job", "money", "earn", "employ", "labor", "hire", "pay"),
    "kempeitai": ("kempeitai", "japanese", "soldier", "patrol", "military", "gendarmerie", "garrison", "devil"),
    "city": ("city", "shanghai", "bund", "street", "here", "place", "town", "district", "where"),
    "people": ("people", "contact", "who", "friend", "resistance", "underground", "faction", "ccp", "gmd", "chen", "xu"),
    "family": ("family", "daughter", "son", "wife", "husband", "mother", "father", "home", "child", "kid"),
    "prices": ("price", "rice", "food", "cost", "fabi", "silver", "hungry", "eat", "ration", "market", "coal"),
    "danger": ("danger", "safe", "curfew", "arrest", "hide", "fear", "trouble", "caught", "informer"),
    "war": ("war", "fight", "resistance", "bomb", "front", "army", "liberation", "chungking", "nationalist"),
    "gangs": ("gang", "green", "mafia", "smuggle", "opium", "triad", "madam", "broker"),
    "foreigners": ("british", "french", "foreign", "concession", "german", "west", "american", "english"),
}


def match_topic(raw: str) -> Optional[str]:
    t = (raw or "").lower()
    for topic, keywords in CANON_TOPICS.items():
        if any(k in t for k in keywords):
            return topic
        return None
    

def get_topic_dialogue(npc: Npc, topic_key: str) -> Optional [str]:
    ask = npc.dialogue.get("ask")
    lines = ask.get(topic_key) if instance(ask, dict) else None
    return random.choice(lines) if lines else None


def npc_ask_topics(npc: Npc) -> List[str]:
    ask = npc.dialogue.get("ask")
    return list(ask.keys()) if isinstance(ask, dict) else []


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

    line = _pick_line(npc, "neutral") or _pick_line(npc, "greeting")
    return line or "..."
