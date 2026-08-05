import random
import re
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
    mood: str = "neutral"
    social_visibility: str = "visible"
    goals: List[Dict[str, Any]] = field(default_factory=list)
    tutorial_dialogue: Dict[str, Any] = field(default_factory=dict)
    bolted: bool = False
    ask: Dict[str, Any] = field(default_factory=dict)


def load_npcs(path: str) -> Dict[str, Npc]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    npcs = {}
    for npc_data in data.get("npcs", []):
        _complete_dialogue_content(npc_data)
        schedule = {int(hour): room_id for hour, room_id in npc_data.get("schedule", {}).items()}
        filtered_data = filter_to_dataclass(npc_data, Npc, exclude={"schedule"}, overrides={"schedule": schedule}, warn_unknown=True)
        npcs[npc_data["id"]] = Npc(**filtered_data)
    return npcs


def _pick_line(npc: Npc, bucket: str) -> Optional[str]:
    lines = npc.dialogue.get(bucket, [])
    return random.choice(lines) if lines else None



WANTED_PERCEPTION_THRESHOLD = 70
WANTED_FACTIONS_HELP = frozenset({"ccp", "green_gang"})
WANTED_FACTIONS_HOSTILE = frozenset({"kempeitai"})

_STANDARD_DIALOGUE = {
    "greeting": ["Good day. Keep your voice steady; the street has enough ears already.", "You are welcome to stand a moment, provided you do not bring trouble with you.", "Shanghai gives nobody an easy morning, yet we still have work to do.", "I have seen you about. That is not the same as knowing you, but it is a beginning.", "Come in from the weather. A person should not have to face the city alone."],
    "neutral": ["The day is moving along, whether any of us are ready for it or not.", "There is no certainty here except the next task and the price it demands.", "People manage by noticing what changes and keeping the rest to themselves.", "The streets are busy today. That can mean trade, or it can mean trouble.", "I keep my attention on what is in front of me. It is the safest habit."],
    "friendly": ["You have treated me fairly. That is remembered in a city where favours are costly.", "Sit a while if you can. Conversation is easier when nobody is rushing away.", "I trust your judgement more than most, though neither of us should grow careless.", "When the day turns hard, it helps to know one familiar face is nearby.", "You have earned a little candour from me. Do not spend it lightly."],
    "hostile": ["Do not mistake my patience for an invitation. I have work to finish.", "You ask too freely for someone who has not earned an answer.", "This is not your concern. Leave it alone before it becomes your problem.", "I have learned to be cautious around strangers, and you are still one.", "We have nothing to discuss. Please take the hint and move on."],
    "afraid": ["Please, not here. A careless word can follow a person home.", "Keep your voice down. I cannot afford to be noticed with you.", "I do not know what you want, and I do not want to know in public.", "There are uniforms nearby. Whatever this is, it can wait.", "Forgive me, but I have people depending on me to return safely."],
    "farewell": ["Take care on the road. Shanghai changes its face quickly after dark.", "Go carefully, and keep your papers close if you have them.", "May your next stop be kinder than your last. That is no small wish today.", "Until next time. I hope we meet under quieter circumstances.", "Mind yourself. The city remembers both kindness and carelessness."],
    "gossip": ["Rice is even more expensive again, and every stallholder has a different explanation for it.", "People say the patrol route changed near dawn, though nobody agrees who ordered it.", "A shipment arrived late at the docks. That is enough to set half the district talking.", "The market has been quiet in a way that makes experienced people uneasy.", "News travels faster than carts in this city, and it becomes less reliable at every corner."],
}
_ASK_TOPICS_BY_ROLE = {"vendor": ("prices", "city", "danger"), "merchant": ("prices", "foreigners", "city"), "worker": ("work", "prices", "danger"), "doctor": ("people", "danger", "war"), "officer": ("city", "danger", "war"), "default": ("city", "work", "danger")}


def _content_role(npc_data: Dict[str, Any]) -> str:
    role = str(npc_data.get("role", "")).lower()
    return next((key for key in _ASK_TOPICS_BY_ROLE if key != "default" and key in role), "default")


def _ask_lines(topic: str) -> list[str]:
    subject = topic.replace("_", " ")
    return [f"About {subject}: I can only tell you what I have seen with my own eyes.", f"People discuss {subject} quietly, because a loose story can harm the wrong family.", f"There is no simple answer about {subject}; Shanghai asks everyone to make do.", f"If you want to understand {subject}, watch who is hurrying and who is standing still.", f"That is all I will say about {subject} for now. Use it with care."]


def _complete_dialogue_content(npc_data: Dict[str, Any]) -> None:
    dialogue = npc_data.setdefault("dialogue", {})
    for bucket, defaults in _STANDARD_DIALOGUE.items():
        current = list(dialogue.get(bucket) or [])
        dialogue[bucket] = (current + [line for line in defaults if line not in current])[:8]
    existing_ask = dialogue.get("ask") if isinstanec(dialogue.get("ask"), dict) else {}
    topics = list(existing_ask)[:3]
    for topic in _ASK_TOPICS_BY_ROLE[_content_role(npc_data)]:
        if len(topics) >= 3:
            break
        if topic not in topics:
            topics.append(topic)
    dialogue["ask"] = {topic: (list(existing_ask.get(topic) or []) + _ask_lines(topic))[:8] for topic in topics}
    wanted = {"wanted_nervous": "Your face has been noticed. Do not make this place answer for you.", "wanted_fear": "Please leave before someone decides I knew you were here.", "wanted_refuse": "I cannot help a person carrying this much attention. Not today."}
    if npc_data.get("faction") in WANTED_FACTIONS_HELP:
        wanted["wanted_help"] = "I can spare a moment, but we must be careful about who sees it."
    if npc_data.get("faction") in WANTED_FACTIONS_HOSTILE:
        wanted["wanted_hostile"] = "You are wanted. Stay where you are and make this easier on yourself."
    for bucket, line in wanted.items():
        dialogue.setdefault(bucket, [line])
WANTED_DIALOGUE_FALLBACKS = {
    1: "People have started asking questions about you. Keep moving.",
    2: "Your face is drawing the wrong kind of attention. Do not linger here.",
    3: "Everyone has heard the warnings. I cannot be seen helping you.",
    4: "You are hunted. Leave before your trouble becomes mine.",
    5: "There is a price on your head. Go now.",
}


def _get_wanted_aware_dialogue(npc: Npc, wanted_level: int, player_trust: TrustMap, player_relationships: Optional[Dict[str, Dict[str, int]]] = None) -> Optional[str]:
    trust_score = get_role_trust(player_trust, npc.faction, npc.role)

    if npc.faction in WANTED_FACTIONS_HOSTILE and wanted_level >= 1:
        line = _pick_line(npc, "wanted_hostile")
        if line:
            return line
        line = _pick_line(npc, "hostile")
        if line:
            return line

    if npc.faction in WANTED_FACTIONS_HELP and wanted_level >= 2 and trust_score >= 30:
        line = _pick_line(npc, "wanted_help")
        if line:
            return line

    if npc.perception >= WANTED_PERCEPTION_THRESHOLD and wanted_level >= 1:
        line = _pick_line(npc, "wanted_nervous")
        if line:
            return line

    if wanted_level >= 3:
        line = _pick_line(npc, "wanted_fear")
        if line:
            return line
        line = _pick_line(npc, "afraid")
        if line:
            return line

    if wanted_level >= 2:
        line = _pick_line(npc, "wanted_refuse")
        if line:
            return line
        line = _pick_line(npc, "hostile")
        if line:
            return line

    if wanted_level >= 1:
        line = _pick_line(npc, "wanted_nervous")
        if line:
            return line

    return None



MORALE_DESPERATE_THRESHOLD = 15
MORALE_LOW_THRESHOLD = 30


def _get_low_morale_dialogue(npc: Npc, player_morale: int, player_trust: TrustMap) -> Optional[str]:
    trust_score = get_role_trust(player_trust, npc.faction, npc.role)

    if trust_score >= 50:
        line = _pick_line(npc, "desperate_pity")
        if line:
            return line

    if trust_score < 30:
        line = _pick_line(npc, "desperate_exploit")
        if line:
            return line

    line = _pick_line(npc, "desperate")
    if line:
        return line

    if player_morale < MORALE_DESPERATE_THRESHOLD:
        line = _pick_line(npc, "afraid")
        if line:
            return line

    return None


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
    "rumor": ("rumor", "rumour", "hear", "gossip", "whisper", "word", "heard"),
}


def _normalize_topic(raw: str) -> str:
    return " ".join((raw or "").lower().replace("_", " ").replace("-", " ").split())


def _topic_keyword_score(text: str, keywords: tuple[str, ...]) -> int:
    return sum(len(k) for k in keywords if re.search(rf"\b{re.escape(k)}\b", text))


def match_topic(raw: str, npc: Optional[Npc] = None) -> Optional[str]:
    t = _normalize_topic(raw)
    if npc:
        ask = npc.dialogue.get("ask")
        if isinstance(ask, dict):
            normalized_topics = [(topic, _normalize_topic(topic)) for topic in ask]
            for topic in ask:
                normalized_topic = _normalize_topic(topic)
                if t == normalized_topic:
                    return topic
            partial_matches = [
                (topic, normalized_topic)
                for topic, normalized_topic in normalized_topics
                if normalized_topic in t or t in normalized_topic
            ]
            if partial_matches:
                return max(partial_matches, key=lambda item: len(item[1]))[0]
    matches = [(topic, _topic_keyword_score(t, keywords)) for topic, keywords in CANON_TOPICS.items()]
    matches = [(topic, size) for topic, size in matches if size > 0]
    if matches:
        return max(matches, key=lambda item: item[1])[0]
    return None


def get_topic_dialogue(npc: Npc, topic_key: str) -> Optional[str]:
    ask = npc.dialogue.get("ask")
    lines = ask.get(topic_key) if isinstance(ask, dict) else None
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


def get_contextual_dialogue(npc: Npc, player_trust: TrustMap, context_type: str = "talk", player_relationships: Optional[Dict[str, Dict[str, int]]] = None, wanted_level: int = 0, player_morale: int = 50) -> str:
    if wanted_level > 0:
        wanted_line = _get_wanted_aware_dialogue(npc, wanted_level, player_trust, player_relationships)
        if wanted_line:
            return wanted_line

    if player_morale < 30:
        morale_line = _get_low_morale_dialogue(npc, player_morale, player_trust)
        if morale_line:
            return morale_line

    trust_score = get_role_trust(player_trust, npc.faction, npc.role)

    friendship = 0
    fear = 0 
    if player_relationships and npc.id in player_relationships:
        rel = player_relationships[npc.id]
        friendship = rel.get("friendship", 0)
        fear = rel.get("fear", 0)

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

    high_trust = trust_score >= 70
    low_trust = trust_score < 30
    high_friendship = friendship >= 30
    high_fear = fear >= 30

    if wanted_level >= 1 and npc.perception > 20:
        wanted_fear = wanted_level * 15
        high_fear = (fear + wanted_fear) >= 30
        if wanted_level >= 2:
            high_trust = False
            high_friendship = False
    flee_flag = wanted_level >= 3

    if high_trust and high_friendship and not high_fear:
        friendly = _pick_line(npc, "friendly")
        if friendly:
            return friendly

    if high_trust and high_friendship and high_fear:
        friendly = _pick_line(npc, "friendly")
        if friendly:
            return friendly

    if high_trust and not high_friendship and not high_fear:
        neutral = _pick_line(npc, "neutral")
        if neutral:
            return neutral

    if low_trust and not high_friendship and high_fear:
        afraid = _pick_line(npc, "afraid")
        if afraid:
            return afraid
        hostile = _pick_line(npc, "hostile")
        if hostile:
            return hostile

    if low_trust and not high_friendship and not high_fear:
        hostile = _pick_line(npc, "hostile")
        if hostile:
            return hostile

    if low_trust:
        afraid = _pick_line(npc, "afraid")
        if afraid:
            return afraid
        hostile = _pick_line(npc, "hostile")
        if hostile:
            return hostile

    if high_trust:
        friendly = _pick_line(npc, "friendly")
        if friendly:
            return friendly

    line = _pick_line(npc, "neutral") or _pick_line(npc, "greeting")
    return line or "..."


def load_district_profiles(path: str = None) -> dict:
    if path is None:
        from .constants import NPC_INTERACTIONS_PATH
        path = NPC_INTERACTIONS_PATH
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("district_profiles", {})


def load_personality_traits(path: str = None) -> dict:
    if path is None:
        from .constants import NPC_INTERACTIONS_PATH
        path - NPC_INTERACTIONS_PATH
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("personality_traits", {})


def get_district_for_room(room_id: str, world) -> str:
    room = world.get_room(room_id)
    if room and hasattr(room, 'district') and room.district:
        return room.district.lower()
    return "default"