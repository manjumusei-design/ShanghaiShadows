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

