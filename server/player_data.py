import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .trust import TrustMap, default_trust
from .serialization import deserialize_item, serialize_item
from .world import Item
from .constants import CONVERSATION_HISTORY_MAXLEN, STAT_CAP


@dataclass
class PlayerData:
    username: str = ""
    name: str = "Stranger"
    current_room: str = "bund_dawn"
    inventory: List[Item] = field(default_factory=list)
    trust: TrustMap = field(default_factory=default_trust)
    disguise: str = ""
    stealth_skill: int = 55
    hidden: bool = False
    flags: List[str] = field(default_factory=list)
    world_events: List[str] = field(default_factory=list)
    newspapers: List[Dict[str, object]] = field(default_factory=list)
    health: int = 100
    hunger: int = 100
    morale: int = 80
    arrested: bool = False
    relationships: Dict[str, Dict[str, int]] = field(default_factory=dict)
    storylet_history: List[str] = field(default_factory=list)
    active_storylet: Any = None
    tailing_state: Any = None
    planted_evidence: List[Dict[str, object]] = field(default_factory=list)
    last_curfew_pentaly_day: int = 0
    last_newspaper_day: int = 0
    conversation_history: deque = field(default_factory=lambda: deque(maxlen=CONVERSATION_HISTORY_MAXLEN))
    courage: int = 50
    perception: int = 30
    money_fabi: int = 0
    money_silver: int = 0
    map_revealed: List[str] = field(default_factory=list)
    maps_purchased: List[str] = field(default_factory=list)
    worn_armour_id: str = ""
    active_missions: List[dict] = field(default_factory=list)
    completed_missions: List[str] = field(default_factory=list)
    abandoned_missions: List[str] = field(default_factory=list)
    visited_rooms: List[str] = field(default_factory=list)
    wanted_level: int = 0

def _reset_player_defaults(player: PlayerData, name: str, spawn_room: str = "bund_dawn") -> None:
    from collections import deque
    from .constants import CONVERSATION_HISTORY_MAXLEN
    player.name = name or "Newcomer"
    player.current_room = spawn_room
    player.inventory = []
    player.disguise = ""
    player.stealth_skill = 55
    player.hidden = False
    player.flags = []
    player.world_events = []
    player.newspapers = []
    player.health = 100
    player.hunger = 100
    player.morale = 80
    player.arrested = False
    player.relationships = {}
    player.storylet_history = []
    player.active_storylet = None
    player.tailing_state = None
    player.planted_evidence = []
    player.last_curfew_penalty_day = 0
    player.last_newspaper_day = 0
    player.conversation_history = deque(maxlen=CONVERSATION_HISTORY_MAXLEN)
    player.money_fabi = 50
    player.money_silver = 0
    player.courage = 50
    player.perception = 30
    player.map_revealed = [spawn_room]
    player.maps_purchased = []
    player.worn_armour_id = ""
    player.active_missions = []
    player.completed_missions = []
    player.abandoned_missions = []



def grow_stat(player: PlayerData, attr: str, amount: int, cap: int = STAT_CAP) -> None:
    setattr(player, attr, min(cap, getattr(player, attr) + amount))


def serialize_player(player: PlayerData) -> Dict[str, object]:
    payload = {
        "username": player.username,
        "name": player.name,
        "current_room": player.current_room,
        "inventory": [serialize_item(item) for item in player.inventory],
        "trust": player.trust,
        "disguise": player.disguise,
        "stealth_skill": player.stealth_skill,
        "hidden": player.hidden,
        "flags": player.flags,
        "world_events": player.world_events,
        "newspapers": player.newspapers,
        "health": player.health,
        "hunger": player.hunger,
        "morale": player.morale,
        "arrested": player.arrested,
        "relationships": player.relationships,
        "storylet_history": player.storylet_history,
        "active_storylet": player.active_storylet.storylet_id if player.active_storylet else "",
        "tailing_state": {
            "target_npc_id": player.tailing_state.target_npc_id,
            "distance": player.tailing_state.distance,
            "elapsed_minutes": player.tailing_state.elapsed_minutes,
            "last_checked_minute": player.tailing_state.last_checked_minute,
        } if player.tailing_state else None,
        "planted_evidence": player.planted_evidence,
        "last_curfew_penalty_day": player.last_curfew_penalty_day,
        "last_newspaper_day": player.last_newspaper_day,
        "conversation_history": list(player.conversation_history),
        "courage": player.courage,
        "perception": player.perception,
        "money_fabi": player.money_fabi,
        "money_silver": player.money_silver,
        "map_revealed": player.map_revealed,
        "maps_purchased": player.maps_purchased,
        "worn_armour_id": player.worn_armour_id,
        "active_missions": player.active_missions,
        "completed_missions": player.completed_missions,
        "abandoned_missions": player.abandoned_missions,
        "visited_rooms": player.visited_rooms,
        "wanted_level": player.wanted_level,
    }
    return payload


def deserialize_player(data: Dict[str, object], storylet_manager=None) -> PlayerData:
    from .storylets import ActiveStorylet, TailingState
    player = PlayerData()
    player.username = str(data.get("username", ""))
    player.name = str(data.get("name", "Stranger"))
    player.current_room = str(data.get("current_room", "bund_dawn"))
    player.inventory = [deserialize_item(row) for row in data.get("inventory", [])]
    player.trust = data.get("trust", default_trust())
    player.disguise = str(data.get("disguise", ""))
    player.stealth_skill = int(data.get("stealth_skill", 55))
    player.hidden = bool(data.get("hidden", False))
    player.flags = list(data.get("flags", []))
    player.world_events = list(data.get("world_events", []))
    player.newspapers = list(data.get("newspapers", []))
    player.health = int(data.get("health", 100))
    player.hunger = int(data.get("hunger", 100))
    player.morale = int(data.get("morale", 80))
    player.arrested = bool(data.get("arrested", False))
    player.relationships = dict(data.get("relationships", {}))
    player.storylet_history = list(data.get("storylet_history", []))
    player.planted_evidence = list(data.get("planted_evidence", []))
    player.last_curfew_penalty_day = int(data.get("last_curfew_penalty_day", 0))
    player.last_newspaper_day = int(data.get("last_newspaper_day", 0))
    player.conversation_history = deque(data.get("conversation_history", []), maxlen=CONVERSATION_HISTORY_MAXLEN)
    player.courage = int(data.get("courage", 50))
    player.perception = int(data.get("perception", 30))
    player.money_fabi = int(data.get("money_fabi", 0))
    player.money_silver = int(data.get("money_silver", 0))
    player.map_revealed = list(data.get("map_revealed", []))
    player.maps_purchased = list(data.get("maps_purchased", []))
    player.worn_armour_id = str(data.get("worn_armour_id", ""))
    player.active_missions = list(data.get("active_missions", []))
    player.completed_missions = list(data.get("completed_missions", []))
    player.abandoned_missions = list(data.get("abandoned_missions", []))
    player.visited_rooms = list(data.get("visited_rooms", []))

    if storylet_manager:
        storylet_id = data.get("active_storylet", "")
        if storylet_id and storylet_id in storylet_manager.storylets:
            storylet = storylet_manager.storylets[storylet_id]
            player.active_storylet = ActiveStorylet(
                storylet_id=storylet.id,
                narrative=storylet.narrative,
                options=storylet.options,
            )

    tail = data.get("tailing_state")
    if tail:
        player.tailing_state = TailingState(
            target_npc_id=tail["target_npc_id"],
            distance=int(tail.get("distance", 2)),
            elapsed_minutes=int(tail.get("elapsed_minutes", 0)),
            last_checked_minute=int(tail.get("last_checked_minute", 0)),
        )
    return player

