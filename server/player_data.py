import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .trust import TrustMap, default_trust
from .serialization import deserialize_item, serialize_item
from .world import Item
from .constants import CONVERSATION_HISTORY_MAXLEN, STAT_CAP


def get_condition_descriptor(durability: int, max_durability: int = 100) -> str:
    if max_durability <= 0:
        return "unknown"
    percentage = (durability / max_durability) * 100

    if percentage >= 80:
        return "pristine"
    elif percentage >=60:
        return "good condition"
    elif percentage >=40:
        return "worn"
    elif percentage >=20:
        return "damaged"
    else:
        return "broken"
    
    
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
    hunger: int = 60 # This is for the tutoorial so that when player eats the baozi they visibly see their hunger meter go up
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
    worn_armour_id: str = ""
    active_missions: List[dict] = field(default_factory=list)
    completed_missions: List[str] = field(default_factory=list)
    abandoned_missions: List[str] = field(default_factory=list)

    wanted_level: int = 0
    wanted_decay_day: int = 0 
    asked_topics: Dict[str, List[str]] = field(default_factory=dict)
    tutorial_stage: int = 0 
    in_tutorial: bool = False
    revealed_exits: Dict[str, List[str]] = field(default_factory=dict)
    observed_rumors: List[str] = field(default_factory=list)
    curfew_hidden_until_minute: int = -1
    curfew_hidden_day: int = -1


def _reset_player_defaults(player: PlayerData, name: str, spawn_room: str = "bund_dawn") -> None:
    from collections import deque
    from .constants import CONVERSATION_HISTORY_MAXLEN
    player.name = name or "Newcomer"
    player.current_room = spawn_room
    player.inventory = []
    from .serialization import deserialize_item
    player.inventory.append(deserialize_item({
        "id": "rice_bowl", "name": "a bowl of rice", "description": "Plain short grained rice from the Northeastern part of China, now overrun by the Imperial Japanese troops, highly prized for its fresh taste and nutrition which everyone needs more of nowadays.",
        "takeable": True, "food_value": 20, "morale_restore": 3,
    }))
    player.disguise = ""
    player.stealth_skill = 55
    player.hidden = False
    player.flags = []
    player.world_events = []
    player.newspapers = []
    player.health = 60
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
    player.worn_armour_id = ""
    player.equipped_weapon_id = ""
    player.active_missions = []
    player.completed_missions = []
    player.abandoned_missions = []



def grow_stat(player: PlayerData, attr: str, amount: int, cap: int = STAT_CAP) -> None:
    setattr(player, attr, min(cap, getattr(player, attr) + amount))


def serialize_player(player: PlayerData) -> Dict[str, object]:
    from collections import deque
    world_events = player.world_events
    if isinstance(world_events, deque):
        world_events = list(world_events)

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
        "world_events": world_events,
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
        "worn_armour_id": player.worn_armour_id,
        "equipped_weapon_id": player.equipped_weapon_id,
        "active_missions": player.active_missions,
        "completed_missions": player.completed_missions,
        "abandoned_missions": player.abandoned_missions,
        "wanted_level": player.wanted_level,
        "asked_topics": {nid: sorted(ts) for nid, ts in player.asked_topics.items()},
        "tutorial_stage": player.tutorial_stage,
        "curfew_hidden_until_minute": player.curfew_hidden_until_minute,
        "curfew_hidden_day": player.curfew_hidden_day,
    }
    return payload


def deserialize_player(data: Dict[str, object], storylet_manager=None) -> PlayerData:
    from .storylets import ActiveStorylet
    from .stealth import TailingState
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
    player.worn_armour_id = str(data.get("worn_armour_id", ""))
    player.equipped_weapon_id = str(data.get("equipped_weapon_id", ""))
    player.active_missions = list(data.get("active_missions", []))
    player.completed_missions = list(data.get("completed_missions", []))
    player.abandoned_missions = list(data.get("abandoned_missions", []))
    player.wanted_level = int(data.get("wanted_level", 0))
    player.asked_topics = {nid: list(ts) for nid, ts in data.get("asked_topics", {}).items()}
    player.tutorial_stage = int(data.get("tutorial_stage", 0))
    player.curfew_hidden_until_minute = int(data.get("curfew_hidden_until_minute", -1))
    player.curfew_hidden_day = int(data.get("curfew_hidden_day", -1))
    
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