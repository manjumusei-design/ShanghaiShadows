import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import uuid
import yaml

from .constants import RUMOR_WINDOW, RUMOR_STEP, RUMORS_PATH
from .dataclass_utils import filter_to_dataclass


@dataclass
class Rumor:
    id: str
    text: str
    factions: List[str] = field(default_factory=list)
    districts: List[str] = field(default_factory=list)
    source_npc: Optional[str] = None
    source_location: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    category: str = "street_talk"
    truth_value: float = 0.8
    dialogue: Optional[dict] = None


@dataclass
class RumourSeed:
    id: str
    event_type: str
    location: str
    district: str = ""
    witnesses: List[str] = field(default_factory=list)
    faction_context: str = ""
    day_created: int = 1
    description: str = ""
    resolved: bool = False
    seed_rumor_ids: List[str] = field(default_factory=list)


_catalog: Dict[str, Rumor] = {}
_seed: List[RumourSeed] = []


def load_rumors(path: str, refresh: bool = False) -> Dict[str, Rumor]:
    if _catalog and not refresh:
        return _catalog
    _catalog.clear()
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    for row in data.get("rumors", []):
        _catalog[row["id"]] = Rumor(**filter_to_dataclass(row, Rumor))
    return _catalog


def compute_active_rumors(catalog: Dict[str, Rumor], day: int, window: int = RUMOR_WINDOW, step: int = RUMOR_STEP) -> List[str]:
    ids = sorted(catalog.keys())
    if not ids:
        return []
    n = len(ids)
    start = (day * step) % n
    return [ids[(start + i) % n] for i in range(min(window, n))]


def seed_active_rumors(day: int) -> List[str]:
    try:
        return compute_active_rumors(load_rumors(RUMORS_PATH), day)
    except FileNotFoundError:
        return []


def get_rumours_for_player(state, player) -> List[Rumor]:
    return []


import time
import json

PRIORITY_MAP = {
    "defection": 1, "extortion": 2, "intimidation": 2,
    "argument": 3, "shuttering": 3, "gossip": 4, "ambient": 5
}

def push_panel_entry(session, entry_type: str, data: dict) -> None:
    entry = {
        "id": f"panel_{uuid.uuid4().hex[:8]}",
        "type": entry_type,
        "speaker": data.get("speaker", ""),
        "listener": data.get("listener", ""),
        "turns": data.get("turns", []),
        "priority": data.get("priority", PRIORITY_MAP.get(entry_type, 5)),
        "timestamp": time.time()
    }
    if not hasattr(session, '_panel_queue'):
        session._panel_queue = []
    session._panel_queue.append(entry)
    session._panel_queue.sort(key=lambda e: (e["priority"], e["timestamp"]))
    session._panel_queue = session._panel_queue[-8:]
    try:
        payload = json.dumps({"type": "rumors", "payload": session._panel_queue})
        asyncio.create_task(session.websocket.send(payload))
    except Exception:
        pass


def push_gossip_to_rumor_panel(session, speaker_name: str, listener_name: str, lines: List[str]) -> None:
    turns = [
        {"speaker": speaker_name if index == 0 else listener_name, "text": line, "delay_ms": 900}
        for index, line in enumerate(lines[:2])
    ]
    push_panel_entry(session, "gossip", {"speaker": speaker_name, "listener": listener_name, "turns": turns})


def create_rumour_seed(
    event_type: str,
    location: str,
    district: str = "",
    witnesses: Optional[List[str]] = None,
    faction_context: str = "",
    description: str = "",
    shared=None,
) -> Optional[RumourSeed]:
    if shared is None:
        return None

    seed = RumourSeed(
        id=f"seed_{event_type}_{uuid.uuid4().hex[:8]}",
        event_type=event_type,
        location=location,
        district=district,
        witnesses=witnesses or [],
        faction_context=faction_context,
        day_created=shared.game_time.day if hasattr(shared, 'game_time') else 1,
        description=description,
    )

    if not hasattr(shared, 'rumour_seeds'):
        shared.rumour_seeds = []
    shared.rumour_seeds.append(seed)
    _seeds.append(seed)
    if faction_context and hasattr(shared, 'rumour_mill'):
        short_desc = description or f"Something happened in {district or location}"
        shared.rumour_mill.setdefault(faction_context, [])
        if short_desc not in shared.rumour_mill[faction_context]:
            shared.rumour_mill[faction_context].append(short_desc)
            if len(shared.rumour_mill[faction_context]) > 12:
                shared.rumour_mill[faction_context] = shared.rumour_mill[faction_context][-12:]

    return seed


def exchange_gossip(npc_a, npc_b, shared) -> bool:
    from .trust import exchange_gossip as _trust_exchange, TrackedRumor

    seeds = getattr(shared, 'rumour_seeds', [])
    for seed in seeds:
        if seed.resolved:
            continue
        if seed.faction_context and seed.faction_context in (npc_a.faction, npc_b.faction):
            target_npc = npc_a if seed.faction_context == npc_a.faction else npc_b
            if not hasattr(target_npc, 'tracked_rumors'):
                target_npc.tracked_rumors = []
            seed_rumor = TrackedRumor(
                id=seed.id,
                text=seed.description or f"Event in {seed.district or seed.location}",
                origin_faction=seed.faction_context,
                current_faction=seed.faction_context,
                source_npc=seed.witnesses[0] if seed.witnesses else "unknown",
                hop_count=0,
                day_created=seed.day_created,
            )
            tr_text = seed_rumor.text
            already_present = any(
                tr_text in m or m in tr_text
                for m in target_npc.memory
            )
            if not already_present:
                target_npc.memory.append(tr_text)
                target_npc.tracked_rumors.append(seed_rumor.to_dict())
            seed.resolved = True

    return _trust_exchange(
        npc_a.memory if hasattr(npc_a, 'memory') else [],
        npc_b.memory if hasattr(npc_b, 'memory') else [],
        chance=0.25,
        tracked_a=getattr(npc_a, 'tracked_rumors', None),
        tracked_b=getattr(npc_b, 'tracked_rumors', None),
        game_day=shared.game_time.day if hasattr(shared, 'game_time') else 1,
        npc_a=npc_a,
        npc_b=npc_b,
    )


def trace_rumour_source(rumour_id: str, npc_id: str, shared) -> Optional[dict]:
    from .trust import TrackedRumor

    global_rumors = getattr(shared, 'tracked_rumors', [])
    for item in global_rumors:
        if hasattr(item, 'id'):
            tr = item
        elif isinstance(item, dict):
            tr = TrackedRumor.from_dict(item)
        else:
            continue
        if tr.id == rumour_id or rumour_id in tr.text or tr.text in rumour_id:
            return {
                "origin_faction": tr.origin_faction,
                "source_npc": tr.source_npc,
                "hop_count": tr.hop_count,
                "day_created": tr.day_created,
                "text": tr.text,
                "from_seed": tr.id.startswith("seed_"),
                "seed_event_type": _extract_seed_type(tr.id, shared),
            }

    for _npc in shared.world.npcs.values():
        npc_tr_list = getattr(_npc, 'tracked_rumors', None)
        if not npc_tr_list:
            continue
        for item in npc_tr_list:
            if isinstance(item, dict):
                tr = TrackedRumor.from_dict(item)
            else:
                continue
            if tr.id == rumour_id or rumour_id in tr.text or tr.text in rumour_id:
                return {
                    "origin_faction": tr.origin_faction,
                    "source_npc": tr.source_npc,
                    "hop_count": tr.hop_count,
                    "day_created": tr.day_created,
                    "text": tr.text,
                    "from_seed": tr.id.startswith("seed_"),
                    "seed_event_type": _extract_seed_type(tr.id, shared),
                }

    seeds = getattr(shared, 'rumour_seeds', [])
    for seed in seeds:
        if seed.id == rumour_id or rumour_id in seed.description:
            return {
                "origin_faction": seed.faction_context,
                "source_npc": seed.witnesses[0] if seed.witnesses else "unknown",
                "hop_count": 0,
                "day_created": seed.day_created,
                "text": seed.description,
                "from_seed": True,
                "seed_event_type": seed.event_type,
            }

    return None


def _extract_seed_type(rumour_id: str, shared) -> Optional[str]:
    seeds = getattr(shared, 'rumour_seeds', [])
    for seed in seeds:
        if seed.id == rumour_id:
            return seed.event_type
    return None


def apply_faction_spin(rumor_text: str, faction: str) -> str:
    spins = {
        "ccp": _spin_ccp,
        "gmd": _spin_gmd,
        "kempeitai": _spin_kempeitai,
        "civilian": _spin_civilian,
        "green_gang": _spin_green_gang,
    }
    spinner = spins.get(faction, lambda t: t)
    return spinner(rumor_text)


def _spin_ccp(text: str) -> str:
    replacements = {
        "Kempeitai": "fascist forces",
        "kempeitai": "fascist forces",
        "Japanese": "imperialist aggressors",
        "japanese": "imperialist aggressors",
        "arrested": "detained by occupation authorities",
        "raided": "struck by occupation forces",
        "resistance": "the people's defense",
        "Resistance": "the People's Defense",
    }
    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)
    if result == text:
        result = "Word from the underground says: " + text[0].lower() + text[1:]
    return result


def _spin_gmd(text: str) -> str:
    replacements = {
        "Kempeitai": "military administration forces",
        "kempeitai": "military administration forces",
        "arrested": "taken in for official processing",
        "raided": "subjected to an authorized inspection",
        "resistance": "unsanctioned elements",
        "Resistance": "Unsantioned elements",
    }
    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)
    if result == text:
        result = "Official channels report that " + text[0].lower() + text[1:]
    return result


def _spin_kempeitai(text: str) -> str:
    replacements = {
        "resistance": "terrorist elements",
        "Resistance": "Terrorist elements",
        "rescued": "assaulted a facility and liberated",
        "fought": "engaged in subversive activities",
        "attacked": "conducted an act of terror against",
        "Ambush": "Terrorist attack",
        "ambush": "terrorist attack",
        "Kempeitai": "security forces",
        "kempeitai": "security forces",
    }
    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)
    if result == text:
        result = "Standard procedure continues: " + text[0].lower() + text[1:]
    return result


def _spin_civilian(text: str) -> str:
    political_terms = [
        "fascist forces", "imperialist aggressors", "occupation authorities",
        "liberation", "resistance", "the cause", "patriotic",
        "terrorist elements", "subversive", "criminal insurgents",
        "military administration", "authorized operation",
    ]
    result = text
    for term in political_terms:
        result = result.replace(term, "they")
        result = result.replace(term.capitalize(), "They")

    if result != text:
        result = "I try to stay out of it, but from what I heard: " + result[0].lower() + result[1:]
    else:
        result = "Keep your head down, but: " + result[0].lower() + result[1:]
    return result


def _spin_green_gang(text: str) -> str:
    replacements = {
        "arrested": "got themselves collected. That's gonna cost someone",
        "raided": "got hit. Someone didn't pay their dues",
        "killed": "was made an example of. Bad for business",
        "rescued": "was rescued. Someone definetly paid well for that",
    }
    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)
    if result == text:
        result = "There's angles to this: " + text[0].lower() + text[1:]
    return result


def reseed_active_rumors(shared, day: int) -> List[str]:
    active_ids = seed_active_rumors(day)
    shared.active_rumors = active_ids

    seed = getattr(shared, 'rumour_seeds', [])
    catalog = load_rumors(RUMORS_PATH)
    for seed in seeds:
        if seed.resolved:
            continue
        for rid in list(active_ids):
            rumor = catalog.get(rid)
            if rumor and seed.faction_context in rumor.factions:
                if rid not in shared.active_rumors:
                    shared.active_rumors.append(rid)
                break
    return shared.active_rumors