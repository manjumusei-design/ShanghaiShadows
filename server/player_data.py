import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .trust import TrustMap, default_trust
from .serialization import deserialize_item, serialize_item
from .world import Item
from .constants import CONVERSATION_HISTORY_MAXLEN, STAT_CAP
from .rumors import RumorObservation, deserialize_observation, normalize_observation_map, serialize_observation


def get_condition_descriptor(durability: int, max_durability: int = 100) -> str:
    if max_durability <= 0:
        return "unknown"
    percentage = (durability / max_durability) * 100
    
    if percentage >= 80:
        return "pristine"
    elif percentage >= 60:
        return "good condition"
    elif percentage >= 40:
        return "worn"
    elif percentage >= 20:
        return "damaged"
    else:
        return "broken"


@dataclass
class PlayerData:
    username: str = ""
    account_username: str = ""
    character_slot_id: str = ""
    save_key: str = ""
    name: str = "Stranger"
    current_room: str = "bund_dawn"
    inventory: List[Item] = field(default_factory=list)
    trust: TrustMap = field(default_factory=default_trust)
    disguise: str = ""
    equipped_disguise_item_id: str = ""
    stealth_skill: int = 55
    hidden: bool = False
    flags: List[str] = field(default_factory=list)
    world_events: List[str] = field(default_factory=list)
    newspapers: List[Dict[str, object]] = field(default_factory=list)
    health: int = 100
    hunger: int = 60
    morale: int = 80
    arrested: bool = False
    relationships: Dict[str, Dict[str, int]] = field(default_factory=dict)
    storylet_history: List[str] = field(default_factory=list)
    active_storylets: List[Any] = field(default_factory=list)
    cancelled_storylet_event_ids: List[str] = field(default_factory=list)
    pending_cancellation_storylets: List[dict] = field(default_factory=list)
    tailing_state: Any = None
    planted_evidence: List[Dict[str, object]] = field(default_factory=list)
    last_newspaper_day: int = 0
    conversation_history: deque = field(default_factory=lambda: deque(maxlen=CONVERSATION_HISTORY_MAXLEN))
    courage: int = 50
    perception: int = 30
    money_fabi: int = 0
    money_silver: int = 0
    money_military_yen: int = 0
    map_revealed: List[str] = field(default_factory=list)
    worn_armour_id: str = ""
    equipped_weapon_id: str = ""
    active_missions: List[dict] = field(default_factory=list)
    completed_missions: List[str] = field(default_factory=list)
    abandoned_missions: List[str] = field(default_factory=list)
    declined_missions: List[str] = field(default_factory=list)
    failed_missions: List[str] = field(default_factory=list)
    deferred_missions: Dict[str, int] = field(default_factory=dict)
    dilemma_commitments: Dict[str, str] = field(default_factory=dict)
    black_market_purchases: Dict[str, int] = field(default_factory=dict)
    black_market_purchase_cycle: int = 0
    wanted_level: int = 0
    wanted_rumor_id: str = ""
    wanted_decay_day: int = 0
    wanted_safe_decay_day: int = 0
    wanted_decay_last_day: int = 0
    last_wanted_bribe_day: int = 0
    last_wanted_favor_day: int = 0
    disguise_worn_continuous_since_day: int = 0
    asked_topics: Dict[str, List[str]] = field(default_factory=dict)
    journal_intel: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    tutorial_stage: int = 0
    tutorial_progress: Dict[str, Any] = field(default_factory=dict)
    in_tutorial: bool = False
    tutorial_choice_pending: bool = False
    revealed_exits: Dict[str, List[str]] = field(default_factory=dict)
    observed_rumors: List[str] = field(default_factory=list)
    tracked_rumors: List[dict] = field(default_factory=list)
    met_npc_ids: set = field(default_factory=set)
    rumor_observations: Dict[str, RumorObservation] = field(default_factory=dict)
    rumor_pending_texts: Dict[str, str] = field(default_factory=dict)
    testimonies: List[Dict[str, Any]] = field(default_factory=list)
    absorbed_death_journal_ids: List[str] = field(default_factory=list)
    curfew_immunity_expires_at: int = -1
    last_curfew_night_key: int | None = None
    last_trust_interaction: Dict[str, int] = field(default_factory=dict)
    tutorial_last_room: str = ""
    tutorial_resume_room_id: str = ""
    tutorial_revealed_rooms: List[str] = field(default_factory=list)
    tutorial_vendor_depletion: Dict[str, List[str]] = field(default_factory=dict)
    tutorial_confirmation: Dict[str, Any] = field(default_factory=dict)
    tutorial_read_note: bool = False
    tutorial_dropped_note: Dict[str, Any] = field(default_factory=dict)
    tutorial_dropped_testimony: Dict[str, Any] = field(default_factory=dict)
    tutorial_journal_lessons: Dict[str, str] = field(default_factory=dict)
    tutorial_social_exchanges: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    escape_charge_available: bool = True
    custody_until: int = -1
    custody_detention_room: str = ""
    discovered_room_hints: Dict[str, List[str]] = field(default_factory=dict)
    rooms_looked: Dict[str, int] = field(default_factory=dict)
    terminal_guidance_first_seen: List[str] = field(default_factory=list)
    terminal_guidance_recovery_seen: List[str] = field(default_factory=list)
    terminal_guidance_cycle: int = 1
    max_inventory: int = 12
    audio_enabled: bool = True
    activity_counters: Dict[str, int] = field(default_factory=lambda: {
        "attacks_performed": 0, "npcs_helped": 0, "medicine_purchased": 0,
        "times_hidden": 0, "items_bought": 0, "npcs_talked_to": 0,
    })


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
    player.equipped_disguise_item_id = ""
    player.wanted_level = 0
    player.wanted_rumor_id = ""
    player.wanted_decay_day = 0
    player.wanted_safe_decay_day = 0
    player.wanted_decay_last_day = 0
    player.disguise_worn_continuous_since_day = 0
    player.stealth_skill = 55
    player.hidden = False
    player.flags = []
    player.world_events = []
    player.newspapers = []
    player.health = 100
    player.hunger = 60
    player.morale = 80
    player.arrested = False
    player.relationships = {}
    player.storylet_history = []
    player.active_storylets = []
    player.tailing_state = None
    player.planted_evidence = []
    player.curfew_immunity_expires_at = -1
    player.last_curfew_night_key = None
    player.last_newspaper_day = 0
    player.conversation_history = deque(maxlen=CONVERSATION_HISTORY_MAXLEN)
    from .economy import set_wallet_fabi_value
    set_wallet_fabi_value(player, 50)
    player.money_military_yen = 0
    player.courage = 50
    player.perception = 30
    player.map_revealed = [spawn_room]
    player.worn_armour_id = ""
    player.equipped_weapon_id = ""
    player.active_missions = []
    player.completed_missions = []
    player.abandoned_missions = []
    player.declined_missions = []
    player.failed_missions = []
    player.deferred_missions = {}
    player.dilemma_commitments = {}
    player.black_market_purchases = {}
    player.black_market_purchase_cycle = 0
    player.last_trust_interaction = {}
    player.tutorial_last_room = ""
    player.tutorial_confirmation = {}
    player.tutorial_journal_lessons = {}
    player.escape_charge_available = True
    player.custody_until = -1
    player.custody_detention_room = ""
    player.discovered_room_hints = {}
    player.terminal_guidance_first_seen = []
    player.terminal_guidance_recovery_seen = []
    player.terminal_guidance_cycle = 1
    player.met_npc_ids = set()
    player.rumor_observations = {}
    player.rumor_pending_texts = {}
    player.testimonies = []
    player.absorbed_death_journal_ids = []


def grow_stat(player: PlayerData, attr: str, amount: int, cap: int = STAT_CAP) -> None:
    setattr(player, attr, min(cap, getattr(player, attr) + amount))


def serialize_player(player: PlayerData) -> Dict[str, object]:
    from collections import deque
    from .equipment import ensure_inventory_identity
    ensure_inventory_identity(player)
    
    world_events = player.world_events
    if isinstance(world_events, deque):
        world_events = list(world_events)
    
    payload = {
        "username": player.username,
        "account_username": player.account_username,
        "character_slot_id": player.character_slot_id,
        "save_key": getattr(player, "save_key", ""),
        "name": player.name,
        "current_room": player.current_room,
        "inventory": [serialize_item(item) for item in player.inventory],
        "trust": player.trust,
        "disguise": player.disguise,
        "equipped_disguise_item_id": player.equipped_disguise_item_id,
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
        "cancelled_storylet_event_ids": player.cancelled_storylet_event_ids,
        "pending_cancellation_storylets": [
            {"storylet_id": str(entry.get("storylet_id", "")), "anchor": str(entry.get("anchor", ""))}
            for entry in player.pending_cancellation_storylets
            if isinstance(entry, dict)
        ][-16:],
        "tailing_state": {
            "target_npc_id": player.tailing_state.target_npc_id,
            "distance": player.tailing_state.distance,
            "elapsed_minutes": player.tailing_state.elapsed_minutes,
            "last_checked_minute": player.tailing_state.last_checked_minute,
        } if player.tailing_state else None,
        "planted_evidence": player.planted_evidence,
        "curfew_immunity_expires_at": player.curfew_immunity_expires_at,
        "last_curfew_night_key": player.last_curfew_night_key,
        "last_newspaper_day": player.last_newspaper_day,
        "conversation_history": list(player.conversation_history),
        "courage": player.courage,
        "perception": player.perception,
        "money_fabi": player.money_fabi,
        "money_silver": player.money_silver,
        "money_military_yen": player.money_military_yen,
        "map_revealed": player.map_revealed,
        "worn_armour_id": player.worn_armour_id,
        "equipped_weapon_id": player.equipped_weapon_id,
        "active_missions": player.active_missions,
        "completed_missions": player.completed_missions,
        "abandoned_missions": player.abandoned_missions,
        "declined_missions": player.declined_missions,
        "failed_missions": player.failed_missions,
        "deferred_missions": player.deferred_missions,
        "dilemma_commitments": player.dilemma_commitments,
        "black_market_purchases": dict(player.black_market_purchases),
        "black_market_purchase_cycle": player.black_market_purchase_cycle,
        "wanted_level": player.wanted_level,
        "wanted_rumor_id": player.wanted_rumor_id,
        "wanted_decay_day": player.wanted_decay_day,
        "wanted_safe_decay_day": player.wanted_safe_decay_day,
        "wanted_decay_last_day": player.wanted_decay_last_day,
        "last_wanted_bribe_day": player.last_wanted_bribe_day,
        "last_wanted_favor_day": player.last_wanted_favor_day,
        "disguise_worn_continuous_since_day": player.disguise_worn_continuous_since_day,
        "asked_topics": {nid: sorted(ts) for nid, ts in player.asked_topics.items()},
        "journal_intel": player.journal_intel,
        "tutorial_stage": player.tutorial_stage,
        "tutorial_progress": {
            str(stage_key): sorted(value) if isinstance(value, (set, list, tuple)) else []
            for stage_key, value in player.tutorial_progress.items()
        },
        "tutorial_last_room": player.tutorial_last_room,
        "tutorial_resume_room_id": player.tutorial_resume_room_id,
        "tutorial_revealed_rooms": list(player.tutorial_revealed_rooms),
        "tutorial_vendor_depletion": {
            vendor_id: list(item_ids)
            for vendor_id, item_ids in sorted(player.tutorial_vendor_depletion.items())
        },
        "tutorial_confirmation": player.tutorial_confirmation,
        "tutorial_read_note": player.tutorial_read_note,
        "tutorial_dropped_note": dict(player.tutorial_dropped_note),
        "tutorial_dropped_testimony": dict(player.tutorial_dropped_testimony),
        "tutorial_journal_lessons": dict(player.tutorial_journal_lessons),
        "tutorial_social_exchanges": {
            identity: dict(record)
            for identity, record in sorted(player.tutorial_social_exchanges.items())
        },
        "last_trust_interaction": player.last_trust_interaction,
        "escape_charge_available": player.escape_charge_available,
        "custody_until": player.custody_until,
        "custody_detention_room": player.custody_detention_room,
        "discovered_room_hints": player.discovered_room_hints,
        "rooms_looked": player.rooms_looked,
        "terminal_guidance_first_seen": list(player.terminal_guidance_first_seen),
        "terminal_guidance_recovery_seen": list(player.terminal_guidance_recovery_seen),
        "terminal_guidance_cycle": player.terminal_guidance_cycle,
        "revealed_exits": player.revealed_exits,
        "met_npc_ids": sorted(player.met_npc_ids),
        "rumor_observations": {
            rumor_id: serialize_observation(observation)
            for rumor_id, observation in sorted(player.rumor_observations.items())
        },
        "rumor_pending_texts": dict(player.rumor_pending_texts),
        "testimonies": [dict(entry) for entry in player.testimonies],
        "absorbed_death_journal_ids": list(player.absorbed_death_journal_ids),
        "in_tutorial": player.in_tutorial,
        "tutorial_choice_pending": player.tutorial_choice_pending,
        "max_inventory": player.max_inventory,
    }
    return payload


def _safe_int(val, default: int, field_name: str = "") -> int:
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def _safe_str(val, default: str = "", field_name: str = "") -> str:
    try:
        return str(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def _safe_bool(val, default: bool = False, field_name: str = "") -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    if isinstance(val, (int, float)):
        return bool(val)
    return default


def _safe_list(val, default: list = None, field_name: str = "") -> list:
    if val is None:
        return default if default is not None else []
    if isinstance(val, list):
        return val
    return default if default is not None else []


def _safe_dict(val, default: dict = None, field_name: str = "") -> dict:
    if val is None:
        return default if default is not None else {}
    if isinstance(val, dict):
        return val
    return default if default is not None else {}


def deserialize_player(data: Dict[str, object], storylet_manager=None) -> PlayerData:
    from .stealth import TailingState
    import logging
    logger = logging.getLogger(__name__)
    
    player = PlayerData()
    player.username = _safe_str(data.get("username"), "")
    player.account_username = _safe_str(data.get("account_username"), "")
    player.character_slot_id = _safe_str(data.get("character_slot_id"), "")
    player.save_key = _safe_str(data.get("save_key"), "")
    player.name = _safe_str(data.get("name"), "Stranger")
    from .world_aliases import (
        resolve_current_room,
        resolve_discovery_list,
        translate_strict,
    )

    player.current_room = (
        resolve_current_room(_safe_str(data.get("current_room"), "")) or "bund_dawn"
    )
    
    inv_data = _safe_list(data.get("inventory"), [])
    player.inventory = []
    for row in inv_data:
        try:
            player.inventory.append(deserialize_item(row))
        except Exception as e:
            logger.warning(f"Failed to deserialize inventory item: {e}")
    from .equipment import ensure_inventory_identity
    ensure_inventory_identity(player)
    
    player.trust = _safe_dict(data.get("trust"), default_trust())
    player.disguise = _safe_str(data.get("disguise"), "")
    player.equipped_disguise_item_id = _safe_str(data.get("equipped_disguise_item_id"), "")
    player.stealth_skill = _safe_int(data.get("stealth_skill"), 55)
    player.hidden = _safe_bool(data.get("hidden"), False)
    player.flags = _safe_list(data.get("flags"), [])
    player.world_events = _safe_list(data.get("world_events"), [])
    player.newspapers = _safe_list(data.get("newspapers"), [])
    player.health = _safe_int(data.get("health"), 100)
    player.hunger = _safe_int(data.get("hunger"), 100)
    player.morale = _safe_int(data.get("morale"), 80)
    player.arrested = _safe_bool(data.get("arrested"), False)
    player.relationships = _safe_dict(data.get("relationships"), {})
    player.storylet_history = _safe_list(data.get("storylet_history"), [])
    player.planted_evidence = _safe_list(data.get("planted_evidence"), [])
    player.last_newspaper_day = _safe_int(data.get("last_newspaper_day"), 0)
    
    conv_data = _safe_list(data.get("conversation_history"), [])
    player.conversation_history = deque(conv_data, maxlen=CONVERSATION_HISTORY_MAXLEN)
    
    player.courage = _safe_int(data.get("courage"), 50)
    player.perception = _safe_int(data.get("perception"), 30)
    player.money_fabi = _safe_int(data.get("money_fabi"), 0)
    player.money_silver = _safe_int(data.get("money_silver"), 0)
    player.money_military_yen = _safe_int(data.get("money_military_yen"), 0)
    player.map_revealed = resolve_discovery_list(_safe_list(data.get("map_revealed"), []))
    player.worn_armour_id = _safe_str(data.get("worn_armour_id"), "")
    player.equipped_weapon_id = _safe_str(data.get("equipped_weapon_id"), "")
    player.active_missions = _safe_list(data.get("active_missions"), [])
    player.completed_missions = _safe_list(data.get("completed_missions"), [])
    player.abandoned_missions = _safe_list(data.get("abandoned_missions"), [])
    player.declined_missions = _safe_list(data.get("declined_missions"), [])
    player.failed_missions = _safe_list(data.get("failed_missions"), [])
    player.deferred_missions = _safe_dict(data.get("deferred_missions"), {})
    player.dilemma_commitments = _safe_dict(data.get("dilemma_commitments"), {})
    player.black_market_purchases = _safe_dict(data.get("black_market_purchases"), {})
    player.black_market_purchase_cycle = _safe_int(data.get("black_market_purchase_cycle"), 0)
    player.wanted_level = _safe_int(data.get("wanted_level"), 0)
    player.wanted_rumor_id = str(data.get("wanted_rumor_id", "") or "")
    player.wanted_decay_day = _safe_int(data.get("wanted_decay_day"), 0)
    player.wanted_safe_decay_day = _safe_int(data.get("wanted_safe_decay_day"), 0)
    player.wanted_decay_last_day = _safe_int(data.get("wanted_decay_last_day"), 0)
    player.last_wanted_bribe_day = _safe_int(data.get("last_wanted_bribe_day"), 0)
    player.last_wanted_favor_day = _safe_int(data.get("last_wanted_favor_day"), 0)
    player.disguise_worn_continuous_since_day = _safe_int(data.get("disguise_worn_continuous_since_day"), 0)
    
    asked_data = _safe_dict(data.get("asked_topics"), {})
    player.asked_topics = {nid: list(ts) for nid, ts in asked_data.items()}
    player.journal_intel = _safe_dict(data.get("journal_intel"), {})
    
    player.tutorial_stage = _safe_int(data.get("tutorial_stage"), 0)
    player.tutorial_progress = {
        str(stage_key): set(str(entry) for entry in _safe_list(entries, []))
        for stage_key, entries in _safe_dict(data.get("tutorial_progress"), {}).items()
    }
    player.tutorial_last_room = _safe_str(data.get("tutorial_last_room"), "")
    player.tutorial_resume_room_id = _safe_str(data.get("tutorial_resume_room_id"), "")
    player.tutorial_revealed_rooms = [
        room_id for room_id in _safe_list(data.get("tutorial_revealed_rooms"), [])
        if isinstance(room_id, str)
    ]
    player.tutorial_vendor_depletion = {
        str(vendor_id): [item_id for item_id in _safe_list(item_ids, []) if isinstance(item_id, str)]
        for vendor_id, item_ids in _safe_dict(data.get("tutorial_vendor_depletion"), {}).items()
        if isinstance(vendor_id, str)
    }
    player.tutorial_confirmation = _safe_dict(data.get("tutorial_confirmation"), {})
    player.tutorial_read_note = _safe_bool(data.get("tutorial_read_note"), False)
    player.tutorial_dropped_note = _safe_dict(data.get("tutorial_dropped_note"), {})
    player.tutorial_dropped_testimony = _safe_dict(data.get("tutorial_dropped_testimony"), {})
    player.tutorial_journal_lessons = {
        str(stage_key): str(text)
        for stage_key, text in _safe_dict(data.get("tutorial_journal_lessons"), {}).items()
    }
    player.tutorial_social_exchanges = {
        str(identity): dict(record)
        for identity, record in _safe_dict(data.get("tutorial_social_exchanges"), {}).items()
        if isinstance(record, dict)
    }
    player.curfew_immunity_expires_at = _safe_int(data.get("curfew_immunity_expires_at"), -1)
    player.last_curfew_night_key = _safe_int(data.get("last_curfew_night_key"), None)
    player.last_trust_interaction = _safe_dict(data.get("last_trust_interaction"), {})
    if "escape_charge_available" in data:
        player.escape_charge_available = _safe_bool(data.get("escape_charge_available"), True)
    else:
        from .trust import has_faction_perk
        legacy_used = _safe_int(data.get("escape_charges_used"), 0)
        legacy_max = 3 + (1 if has_faction_perk(player.trust, "ccp") else 0)
        player.escape_charge_available = legacy_used < legacy_max
    player.custody_until = _safe_int(data.get("custody_until"), -1)
    player.custody_detention_room = (
        resolve_current_room(_safe_str(data.get("custody_detention_room"), "")) or ""
    )
    player.discovered_room_hints = {
        resolved: entries
        for key, entries in _safe_dict(data.get("discovered_room_hints"), {}).items()
        if (resolved := translate_strict(key)) is not None
    }
    player.rooms_looked = _safe_dict(data.get("rooms_looked"), {})
    player.terminal_guidance_first_seen = [
        str(family) for family in _safe_list(data.get("terminal_guidance_first_seen"), [])
        if isinstance(family, str)
    ]
    player.terminal_guidance_recovery_seen = [
        str(family) for family in _safe_list(data.get("terminal_guidance_recovery_seen"), [])
        if isinstance(family, str)
    ]
    player.terminal_guidance_cycle = _safe_int(data.get("terminal_guidance_cycle"), 1)
    player.revealed_exits = _safe_dict(data.get("revealed_exits"), {})
    player.observed_rumors = _safe_list(data.get("observed_rumors"), [])
    player.tracked_rumors = _safe_list(data.get("tracked_rumors"), [])
    player.met_npc_ids = set(_safe_list(data.get("met_npc_ids"), []))
    player.rumor_observations = normalize_observation_map({
        str(rumor_id): deserialize_observation(observation)
        for rumor_id, observation in _safe_dict(data.get("rumor_observations"), {}).items()
        if isinstance(observation, dict)
    })
    player.rumor_pending_texts = {
        str(rumor_id): str(text)
        for rumor_id, text in _safe_dict(data.get("rumor_pending_texts"), {}).items()
    }
    from .testimonies import normalize_testimony_archive
    player.testimonies = normalize_testimony_archive(
        data.get("testimonies", data.get("testimony_archive", []))
    )
    player.absorbed_death_journal_ids = [
        str(entry) for entry in _safe_list(data.get("absorbed_death_journal_ids"), [])
    ]
    player.in_tutorial = _safe_bool(data.get("in_tutorial"), False)
    player.tutorial_choice_pending = _safe_bool(data.get("tutorial_choice_pending"), False)
    if player.in_tutorial and "money_fabi" not in data and "money_silver" not in data:
        from .economy import set_wallet_fabi_value
        set_wallet_fabi_value(player, 50)
    if player.in_tutorial and not player.tutorial_resume_room_id:
        legacy_room = player.tutorial_last_room or player.current_room
        if legacy_room.startswith("tut_"):
            legacy_room = legacy_room.split("_", 2)[-1]
        player.tutorial_resume_room_id = legacy_room or "refugee_entry_tea_house"
    if player.in_tutorial and not player.tutorial_revealed_rooms:
        player.tutorial_revealed_rooms = [player.tutorial_resume_room_id]
    player.max_inventory = _safe_int(data.get("max_inventory"), 12)

    from .rumors import migrate_player_rumors
    migrate_player_rumors(player)

    matching_disguises = [item for item in player.inventory if getattr(item, "disguise_id", "") == player.disguise]
    if player.equipped_disguise_item_id:
        equipped = next((item for item in matching_disguises if item.instance_id == player.equipped_disguise_item_id), None)
        if equipped is None:
            legacy = [item for item in matching_disguises if item.id == player.equipped_disguise_item_id]
            equipped = legacy[0] if len(legacy) == 1 else None
        if equipped is None:
            player.equipped_disguise_item_id = ""
            player.disguise = ""
        else:
            player.equipped_disguise_item_id = equipped.instance_id
    elif player.disguise and len(matching_disguises) == 1:
        player.equipped_disguise_item_id = matching_disguises[0].id
    elif player.disguise:
        player.disguise = ""

    for field_name, predicate in (
        ("equipped_weapon_id", lambda item: item.is_weapon),
        ("worn_armour_id", lambda item: item.is_armour),
    ):
        slot_id = getattr(player, field_name)
        if not slot_id:
            continue
        exact = next((item for item in player.inventory if item.instance_id == slot_id and predicate(item)), None)
        if exact is None:
            legacy = [item for item in player.inventory if item.id == slot_id and predicate(item)]
            exact = legacy[0] if len(legacy) == 1 else None
        setattr(player, field_name, exact.instance_id if exact else "")

    player.cancelled_storylet_event_ids = [
        entry for entry in _safe_list(data.get("cancelled_storylet_event_ids"), []) if isinstance(entry, str)
    ][-64:]
    player.pending_cancellation_storylets = [
        {"storylet_id": str(entry.get("storylet_id", "")), "anchor": str(entry.get("anchor", ""))}
        for entry in _safe_list(data.get("pending_cancellation_storylets"), [])
        if isinstance(entry, dict) and isinstance(entry.get("storylet_id"), str) and entry.get("storylet_id")
    ][-16:]

    if storylet_manager:
        legacy_records = []
        seen_timestamps = {}
        for index, record in enumerate(data.get("active_storylets", []) or []):
            if not isinstance(record, dict):
                continue
            storylet_id = record.get("storylet_id")
            if not isinstance(storylet_id, str) or not storylet_id.strip():
                continue
            raw_ts = record.get("triggered_at")
            if not isinstance(raw_ts, (int, float)):
                raw_ts = record.get("timer_started_at")
            if isinstance(raw_ts, (int, float)):
                ts_key = (storylet_id, str(raw_ts))
                seen = seen_timestamps.get(ts_key, 0)
                seen_timestamps[ts_key] = seen + 1
                anchor = str(raw_ts) if seen == 0 else f"{raw_ts}:{index}"
            else:
                anchor = f"pos:{index}"
            legacy_records.append({"storylet_id": storylet_id, "anchor": anchor})
        old_storylet_id = data.get("active_storylet")
        if isinstance(old_storylet_id, str) and old_storylet_id.strip():
            legacy_records.append({"storylet_id": old_storylet_id, "anchor": "singular"})
        if legacy_records:
            player._pending_legacy_cancellations = legacy_records

    tail = data.get("tailing_state")
    if tail and isinstance(tail, dict):
        try:
            player.tailing_state = TailingState(
                target_npc_id=_safe_str(tail.get("target_npc_id"), ""),
                distance=_safe_int(tail.get("distance"), 2),
                elapsed_minutes=_safe_int(tail.get("elapsed_minutes"), 0),
                last_checked_minute=_safe_int(tail.get("last_checked_minute"), 0),
            )
        except (KeyError, TypeError) as e:
            logger.warning(f"Failed to deserialize tailing_state: {e}")
            player.tailing_state = None
    return player
