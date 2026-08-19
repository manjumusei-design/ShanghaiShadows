import json
import random
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .stealth import Disguise
from .time_system import EventScheduler, GameTime
from .trust import TrustMap, get_role_trust
from .world import World
from .content_validation import load_strict_yaml
from .rumors import RumorRecord, deserialize_observation, deserialize_record, normalize_observation_map, normalize_record_map, serialize_observation, serialize_record
from .patrols import is_transient_patrol_id
from .constants import (
    EVENTS_PATH,
    TRUST_RULES_PATH,
    DISGUISES_PATH,
    STORYLETS_PATH,
    STATE_BROADCAST_INTERVAL,
    DECISION_LEDGER_MAXLEN,
)

SAVES_DIR = Path("server/data/saves")


@dataclass(frozen=True)
class NamedNpcDeathRecord:
    event_id: str
    npc_id: str
    npc_name: str
    npc_faction: str
    room_id: str
    day: int
    minute: int
    cause: str
    killer_slot_id: str
    historical: bool
    faction_leader: bool


def named_npc_death_record_to_dict(record: NamedNpcDeathRecord) -> dict:
    return {
        "event_id": record.event_id,
        "npc_id": record.npc_id,
        "npc_name": record.npc_name,
        "npc_faction": record.npc_faction,
        "room_id": record.room_id,
        "day": int(record.day),
        "minute": int(record.minute),
        "cause": record.cause,
        "killer_slot_id": record.killer_slot_id,
        "historical": bool(record.historical),
        "faction_leader": bool(record.faction_leader),
    }


def named_npc_death_record_from_dict(data: dict) -> Optional[NamedNpcDeathRecord]:
    npc_id = str(data.get("npc_id", ""))
    if not npc_id:
        return None
    return NamedNpcDeathRecord(
        event_id=str(data.get("event_id", f"npc_death_{npc_id}_legacy")),
        npc_id=npc_id,
        npc_name=str(data.get("npc_name", npc_id)),
        npc_faction=str(data.get("npc_faction", "")),
        room_id=str(data.get("room_id", "")),
        day=int(data.get("day", 1)),
        minute=int(data.get("minute", 0)),
        cause=str(data.get("cause", "legacy")),
        killer_slot_id=str(data.get("killer_slot_id", "")),
        historical=bool(data.get("historical", False)),
        faction_leader=bool(data.get("faction_leader", False)),
    )


def is_named_npc_dead(shared, npc_id: str) -> bool:
    records = getattr(shared, "named_npc_deaths", None)
    if not records:
        return False
    return str(npc_id) in records


def _retire_npc_placement(shared, npc_id: str) -> None:
    world = getattr(shared, "world", None)
    if world is None:
        return
    world.npc_locations.pop(npc_id, None)
    for room in world.rooms.values():
        if npc_id in room.npcs:
            room.npcs.remove(npc_id)
    world.npcs.pop(npc_id, None)


def record_named_npc_death(
    shared,
    *,
    npc_id: str,
    npc_name: str,
    npc_faction: str,
    room_id: str,
    day: int,
    minute: int,
    cause: str = "combat",
    killer_slot_id: str = "",
    historical: bool = False,
    faction_leader: bool = False,
    event_id: Optional[str] = None,
) -> Optional[NamedNpcDeathRecord]:
    npc_id = str(npc_id)
    if not npc_id or is_transient_patrol_id(npc_id):
        return None
    records = getattr(shared, "named_npc_deaths", None)
    if records is None:
        records = {}
        shared.named_npc_deaths = records
    existing = records.get(npc_id)
    if existing is not None:
        return existing
    record = NamedNpcDeathRecord(
        event_id=event_id or f"npc_death_{npc_id}_{int(day)}_{int(minute)}",
        npc_id=npc_id,
        npc_name=str(npc_name or npc_id),
        npc_faction=str(npc_faction or ""),
        room_id=str(room_id or ""),
        day=int(day),
        minute=int(minute),
        cause=str(cause or "combat"),
        killer_slot_id=str(killer_slot_id or ""),
        historical=bool(historical),
        faction_leader=bool(faction_leader),
    )
    records[npc_id] = record
    _retire_npc_placement(shared, npc_id)
    return record


def retire_recorded_npcs(shared) -> int:
    retired = 0
    for npc_id in list(getattr(shared, "named_npc_deaths", None) or {}):
        world = getattr(shared, "world", None)
        if world is not None and npc_id in world.npcs:
            _retire_npc_placement(shared, npc_id)
            retired += 1
    return retired


def migrate_legacy_npc_deaths(data: dict, world, canonical: Dict[str, NamedNpcDeathRecord]) -> Dict[str, NamedNpcDeathRecord]:
    result = dict(canonical)
    candidates = {}
    decisions = data.get("world_decisions", [])
    if isinstance(decisions, list):
        for decision in decisions:
            if not isinstance(decision, dict) or decision.get("type") != "npc_killed":
                continue
            npc_id = str(decision.get("npc_id", ""))
            if not npc_id:
                continue
            candidates[npc_id] = {
                "npc_id": npc_id,
                "npc_name": str(decision.get("npc_name", npc_id)),
                "npc_faction": str(decision.get("npc_faction", "")),
                "room_id": str(decision.get("location", "")),
                "day": int(decision.get("day", 1)),
                "historical": bool(decision.get("historical", False)),
                "faction_leader": bool(decision.get("faction_leader", False)),
            }
    raw_dead_npcs = data.get("dead_npcs", [])
    if isinstance(raw_dead_npcs, list):
        for raw_id in raw_dead_npcs:
            npc_id = str(raw_id)
            if not npc_id or is_transient_patrol_id(npc_id):
                continue
            candidates.setdefault(npc_id, {
                "npc_id": npc_id,
                "npc_name": npc_id,
                "npc_faction": "",
                "room_id": "",
                "day": 1,
                "historical": False,
                "faction_leader": False,
            })
    for npc_id, fields in sorted(candidates.items()):
        if npc_id in result:
            continue
        npc = world.npcs.get(npc_id)
        if npc is None:
            continue
        npc_name = fields["npc_name"]
        if npc_name == npc_id and npc.name:
            npc_name = npc.name
        npc_faction = fields["npc_faction"]
        if not npc_faction and npc.faction:
            npc_faction = npc.faction
        result[npc_id] = NamedNpcDeathRecord(
            event_id=f"npc_death_{npc_id}_legacy",
            npc_id=npc_id,
            npc_name=npc_name,
            npc_faction=npc_faction,
            room_id=fields["room_id"],
            day=max(1, fields["day"]),
            minute=0,
            cause="legacy",
            killer_slot_id="",
            historical=fields["historical"],
            faction_leader=fields["faction_leader"],
        )
    return result


def _project_persistent_record(record: RumorRecord) -> dict:
    data = serialize_record(record)
    if is_transient_patrol_id(data["source_npc_id"]):
        data["source_npc_id"] = ""
    data["witness_npc_ids"] = [
        witness_id for witness_id in data["witness_npc_ids"]
        if not is_transient_patrol_id(witness_id)
    ]
    return data


def load_disguises(path: str) -> Dict[str, Disguise]:
    data = load_strict_yaml(Path(path)) or {}
    disguises: Dict[str, Disguise] = {}
    for row in data.get("disguises", []):
        disguise = Disguise(
            id=row["id"],
            name=row["name"],
            apparent_faction=row["apparent_faction"],
            bonus=int(row.get("bonus", 0)),
            description=row.get("description", ""),
            curfew_detection_modifier=int(row.get("curfew_detection_modifier", 0)),
        )
        disguises[disguise.id] = disguise
    return disguises


@dataclass
class SharedWorldState:
    world: World
    game_time: GameTime
    scheduler: EventScheduler
    trust_rules: Dict[str, object] = field(default_factory=dict)
    ccp_influence: int = 10
    gmd_influence: int = 15
    event_log: List[Dict] = field(default_factory=list)
    rumour_mill: Dict[str, List[str]] = field(default_factory=dict)
    archived_journals: Dict[str, List[dict]] = field(default_factory=dict)
    mission_manager: Any = None
    milestone_manager: Any = None
    server_cycle: int = 1
    weather: str = "clear"
    active_room_storylets: Dict[str, dict] = field(default_factory=dict)
    named_npc_deaths: Dict[str, "NamedNpcDeathRecord"] = field(default_factory=dict)
    world_decisions: deque = field(default_factory=lambda: deque(maxlen=DECISION_LEDGER_MAXLEN))
    room_state_overrides: Dict[str, dict] = field(default_factory=dict)
    npc_dispositions: Dict[str, dict] = field(default_factory=dict)
    market_rooms: Dict[str, List[str]] = field(default_factory=dict)
    death_journals: Dict[str, List[dict]] = field(default_factory=dict)
    active_rumors: List[str] = field(default_factory=list)
    active_authored_rumor_ids: List[str] = field(default_factory=list)
    rumor_records: Dict[str, RumorRecord] = field(default_factory=dict)
    room_codes: Dict[str, str] = field(default_factory=dict)
    code_to_room: Dict[str, str] = field(default_factory=dict)
    room_layout_coords: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    tutorial_room_clones: Dict[str, Dict[str, str]] = field(default_factory=dict)
    cloned_tutorial_rooms: Dict[str, Any] = field(default_factory=dict)
    tutorial_npc_clones: Dict[str, List[str]] = field(default_factory=dict)
    district_control: Dict[str, str] = field(default_factory=dict)
    district_influence: Dict[str, Dict[str, int]] = field(default_factory=dict)
    tracked_rumors: list = field(default_factory=list)
    rumour_seeds: list = field(default_factory=list)
    layout_seed: int = 0
    patrol_density_modifier: Optional[dict] = None
    temp_stealth_modifier: Optional[dict] = None
    raid_chance_modifier: Optional[dict] = None
    relationship_system: Any = None
    npc_social_schedules: Dict[str, Dict[str, int]] = field(default_factory=dict)
    social_influence_ledger: Dict[str, int] = field(default_factory=dict)
    social_consequences: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    social_consequence_cooldowns: Dict[str, int] = field(default_factory=dict)
    applied_cancellation_event_ids: List[str] = field(default_factory=list)

    def get_trust_value(self, key: str, player_trust: TrustMap) -> int:
        if "." in key:
            faction, role = key.split(".", 1)
            return get_role_trust(player_trust, faction, role)
        return get_role_trust(player_trust, key)


def bootstrap_cycle_state(
    initial_day: int = 1,
    initial_minute: int = 480,
    server_cycle: int = 1,
    layout_seed: int = None,
) -> SharedWorldState:
    from .constants import MILESTONES_PATH
    from .milestones import MilestoneManager, load_milestones
    from .missions import load_missions, MissionManager
    from .room_codes import generate_room_codes, layout_rooms, layout_tutorial_rooms
    from .trust import load_trust_rules
    from .economy import load_economy_state
    load_economy_state({})

    world = World()
    from .content_references import assert_valid_authored_references
    assert_valid_authored_references(world)
    scheduler = EventScheduler()
    scheduler.load_from_yaml(EVENTS_PATH)
    trust_rules = load_trust_rules(TRUST_RULES_PATH)
    milestone_manager = MilestoneManager(load_milestones(MILESTONES_PATH))
    mission_manager = MissionManager(load_missions())
    if layout_seed is None:
        layout_seed = random.randint(1, 1000000)
    room_codes = generate_room_codes(world.rooms)
    layout_coords = layout_rooms(world.rooms, layout_seed=layout_seed)
    layout_coords.update(layout_tutorial_rooms(world.rooms))
    code_to_room = {code: room_id for room_id, code in room_codes.items()}

    faction_archetypes = {
        "civilian": "civilian_vendor",
        "ccp": "ccp_operative",
        "gmd": "gmd_operative",
        "kempeitai": "kempeitai_patrol",
        "green_gang": "gang_enforcer",
    }
    for npc in world.npcs.values():
        if not npc.bt_archetype:
            npc.bt_archetype = faction_archetypes.get(npc.faction, "civilian_vendor")

    state = SharedWorldState(
        world=world,
        game_time=GameTime(day=initial_day, minute=initial_minute),
        scheduler=scheduler,
        trust_rules=trust_rules,
        ccp_influence=10,
        gmd_influence=15,
        mission_manager=mission_manager,
        milestone_manager=milestone_manager,
        server_cycle=server_cycle,
        market_rooms=build_market_tracker(world),
        room_codes=room_codes,
        code_to_room=code_to_room,
        room_layout_coords=layout_coords,
        layout_seed=layout_seed,
    )

    from .rumors import activate_authored_rumors
    activate_authored_rumors(state, initial_day)
    world._death_records = state.named_npc_deaths
    return state


def serialize_world_state(state: SharedWorldState) -> Dict[str, object]:
    from .serialization import serialize_item as _serialize_item
    from .economy import serialize_economy_state

    room_items = {
        room_id: [_serialize_item(item) for item in room.items]
        for room_id, room in state.world.rooms.items()
    }

    room_discovery_state = {
        room_id: {
            "search_signal": room.search_signal,
            "dead_drops": [
                {
                    "signal": drop.get("signal", ""),
                    "recipient": drop.get("recipient", ""),
                    "item": _serialize_item(drop["item"]),
                }
                for drop in room.dead_drops
            ],
        }
        for room_id, room in state.world.rooms.items()
    }

    persistent_npcs = {
        npc_id: npc
        for npc_id, npc in state.world.npcs.items()
        if not is_transient_patrol_id(npc_id)
    }
    npc_locations = {
        npc_id: room_id
        for npc_id, room_id in state.world.npc_locations.items()
        if not is_transient_patrol_id(npc_id)
    }
    npc_memory = {npc_id: npc.memory for npc_id, npc in persistent_npcs.items()}
    npc_rumor_observations = {
        npc_id: {
            rumor_id: serialize_observation(observation)
            for rumor_id, observation in sorted(getattr(npc, "rumor_observations", {}).items())
        }
        for npc_id, npc in persistent_npcs.items()
        if getattr(npc, "rumor_observations", None)
    }
    npc_social_state = {
        npc_id: {
            "mood": getattr(npc, "mood", "neutral"),
            "social_visibility": getattr(npc, "social_visibility", "visible"),
            "needs": getattr(npc, "needs", {}),
            "inventory": getattr(npc, "inventory", []),
            "goals": getattr(npc, "goals", []),
        }
        for npc_id, npc in persistent_npcs.items()
    }
    relationships = []
    seen_relationships = set()
    for npc_id, npc in persistent_npcs.items():
        for other_id, relationship in getattr(npc, "relationships", {}).items():
            if is_transient_patrol_id(other_id):
                continue
            pair = tuple(sorted((npc_id, other_id)))
            if pair in seen_relationships:
                continue
            seen_relationships.add(pair)
            relationships.append({
                "npc_1": relationship.npc_id_1,
                "npc_2": relationship.npc_id_2,
                "type": relationship.relationship_type,
                "strength": relationship.strength,
                "shared_secrets": list(relationship.shared_secrets),
            })

    npc_player_memories = {}
    for npc_id, npc in persistent_npcs.items():
        if hasattr(npc, 'player_memories') and npc.player_memories:
            npc_player_memories[npc_id] = {
                player_name: {
                    'trust_mod': mem.trust_mod,
                    'relationship_type': mem.relationship_type,
                    'last_interaction_day': mem.last_interaction_day,
                    'interactions': mem.interactions[-10:],
                    'remembered_events': mem.remembered_events,
                }
                for player_name, mem in npc.player_memories.items()
            }

    from datetime import datetime
    payload = {
        "_version": 1,
        "_saved_at": datetime.utcnow().isoformat(),
        "time": {"day": state.game_time.day, "minute": state.game_time.minute},
        "room_items": room_items,
        "room_discovery_state": room_discovery_state,
        "npc_locations": npc_locations,
        "npc_memory": npc_memory,
        "npc_rumor_observations": npc_rumor_observations,
        "npc_social_state": npc_social_state,
        "npc_relationships": relationships,
        "npc_social_schedules": {
            npc_id: schedule
            for npc_id, schedule in state.npc_social_schedules.items()
            if not is_transient_patrol_id(npc_id)
        },
        "social_influence_ledger": state.social_influence_ledger,
        "social_consequences": {
            consequence_id: state.social_consequences[consequence_id]
            for consequence_id in sorted(state.social_consequences)
        },
        "social_consequence_cooldowns": {
            cooldown_id: state.social_consequence_cooldowns[cooldown_id]
            for cooldown_id in sorted(state.social_consequence_cooldowns)
        },
        "applied_cancellation_event_ids": list(state.applied_cancellation_event_ids),
        "npc_player_memories": npc_player_memories,
        "scheduler": state.scheduler.to_payload(),
        "event_log": list(state.event_log),
        "ccp_influence": state.ccp_influence,
        "gmd_influence": state.gmd_influence,
        "archived_journals": state.archived_journals,
        "server_cycle": state.server_cycle,
        "weather": state.weather,
        "named_npc_deaths": {
            npc_id: named_npc_death_record_to_dict(record)
            for npc_id, record in sorted(state.named_npc_deaths.items())
        },
        "world_decisions": list(state.world_decisions),
        "room_state_overrides": {
            room_id: state.room_state_overrides[room_id]
            for room_id in sorted(state.room_state_overrides)
        },
        "npc_dispositions": {
            npc_id: state.npc_dispositions[npc_id]
            for npc_id in sorted(state.npc_dispositions)
            if not is_transient_patrol_id(npc_id)
        },
        "death_journals": state.death_journals,
        "economy": serialize_economy_state(),
        "district_control": state.district_control,
        "district_influence": state.district_influence,
        "rumor_records": {
            record_id: _project_persistent_record(record)
            for record_id, record in sorted(state.rumor_records.items())
        },
        "active_authored_rumor_ids": list(state.active_authored_rumor_ids),
        "layout_seed": state.layout_seed,
    }
    return payload


def deserialize_world_state(data: Dict[str, object], world: World) -> SharedWorldState:
    from .serialization import deserialize_item as _deserialize_item

    game_time = GameTime(
        day=min(int(data.get("time", {}).get("day", 1)), 180),
        minute=int(data.get("time", {}).get("minute", 0))
    )

    scheduler = EventScheduler()
    scheduler.load_from_payload(data.get("scheduler", []))

    room_items = data.get("room_items")
    if isinstance(room_items, dict):
        for room in world.rooms.values():
            room.items = []
        for room_id, rows in room_items.items():
            room = world.rooms.get(room_id)
            if room:
                room.items = [_deserialize_item(row) for row in rows]

    raw_discovery = data.get("room_discovery_state")
    if isinstance(raw_discovery, dict):
        for room_id, fields in raw_discovery.items():
            room = world.rooms.get(room_id)
            if not room or not isinstance(fields, dict):
                continue
            if "search_signal" in fields:
                room.search_signal = fields["search_signal"]
            if "dead_drops" in fields and isinstance(fields["dead_drops"], list):
                room.dead_drops = []
                for drop in fields["dead_drops"]:
                    if not isinstance(drop, dict) or "item" not in drop:
                        continue
                    item = _deserialize_item(drop["item"])
                    room.dead_drops.append({
                        "signal": drop.get("signal", ""),
                        "recipient": drop.get("recipient", ""),
                        "item": item,
                    })

    raw_named_npc_deaths = data.get("named_npc_deaths", {})
    named_npc_deaths = {}
    if isinstance(raw_named_npc_deaths, dict):
        for npc_id, record_data in raw_named_npc_deaths.items():
            if not isinstance(record_data, dict):
                continue
            record = named_npc_death_record_from_dict(record_data)
            if record is not None:
                named_npc_deaths[record.npc_id] = record
    named_npc_deaths = migrate_legacy_npc_deaths(data, world, named_npc_deaths)
    world._death_records = named_npc_deaths

    npc_locations = data.get("npc_locations")
    if isinstance(npc_locations, dict):
        for room in world.rooms.values():
            room.npcs = []
        world.npc_locations = {}
        for npc_id, room_id in npc_locations.items():
            if (
                not is_transient_patrol_id(npc_id)
                and npc_id in world.npcs
                and room_id in world.rooms
            ):
                world.place_npc(npc_id, room_id)

    for npc_id in list(world.npcs):
        if is_transient_patrol_id(npc_id):
            world.npcs.pop(npc_id, None)
    for room in world.rooms.values():
        room.npcs = [npc_id for npc_id in room.npcs if not is_transient_patrol_id(npc_id)]
    for npc_id in list(world.npc_locations):
        if is_transient_patrol_id(npc_id):
            world.npc_locations.pop(npc_id, None)

    for npc_id, memories in data.get("npc_memory", {}).items():
        if is_transient_patrol_id(npc_id):
            continue
        npc = world.npcs.get(npc_id)
        if npc:
            npc.memory = list(memories)

    for npc_id, tracked in data.get("npc_tracked_rumors", {}).items():
        if is_transient_patrol_id(npc_id):
            continue
        npc = world.npcs.get(npc_id)
        if npc and hasattr(npc, 'tracked_rumors'):
            npc.tracked_rumors = list(tracked)

    npc_rumor_observations_raw = data.get("npc_rumor_observations", {})
    if isinstance(npc_rumor_observations_raw, dict):
        for npc_id, observations in npc_rumor_observations_raw.items():
            if is_transient_patrol_id(npc_id):
                continue
            npc = world.npcs.get(npc_id)
            if npc is None or not isinstance(observations, dict):
                continue
            npc.rumor_observations = normalize_observation_map({
                str(rumor_id): deserialize_observation(observation)
                for rumor_id, observation in observations.items()
                if isinstance(observation, dict)
            })

    for npc_id, social_state in data.get("npc_social_state", {}).items():
        if is_transient_patrol_id(npc_id):
            continue
        npc = world.npcs.get(npc_id)
        if npc:
            npc.mood = str(social_state.get("mood", "neutral"))
            npc.social_visibility = str(social_state.get("social_visibility", "visible"))
            npc.needs = dict(social_state.get("needs", {}))
            npc.inventory = list(social_state.get("inventory", []))
            npc.goals = list(social_state.get("goals", []))

    relationship_rows = [
        row for row in data.get("npc_relationships", [])
        if isinstance(row, dict)
        if not is_transient_patrol_id(row.get("npc_1"))
        and not is_transient_patrol_id(row.get("npc_2"))
    ]
    if relationship_rows:
        from .npc_memory import NpcRelationshipSystem
        NpcRelationshipSystem().load_relationships(relationship_rows, world.npcs)

    npc_player_memories = data.get("npc_player_memories", {})
    if isinstance(npc_player_memories, dict):
        for npc_id, player_mems in npc_player_memories.items():
            if is_transient_patrol_id(npc_id):
                continue
            npc = world.npcs.get(npc_id)
            if npc and hasattr(npc, 'player_memories'):
                from .npc_memory import PlayerMemory
                for player_name, mem_data in player_mems.items():
                    npc.player_memories[player_name] = PlayerMemory(
                        player_name=player_name,
                        interactions=mem_data.get('interactions', []),
                        trust_mod=mem_data.get('trust_mod', 0),
                        relationship_type=mem_data.get('relationship_type', 'neutral'),
                        last_interaction_day=mem_data.get('last_interaction_day', 0),
                        remembered_events=mem_data.get('remembered_events', [])
                    )

    rumour_mill = dict(data.get("rumour_mill", {}))
    event_log = list(data.get("event_log", []))
    ccp_influence = int(data.get("ccp_influence", 10))
    gmd_influence = int(data.get("gmd_influence", 15))
    archived_journals = dict(data.get("archived_journals", {}))
    server_cycle = int(data.get("server_cycle", 1))
    weather = str(data.get("weather", "clear"))
    raw_world_decisions = data.get("world_decisions", [])
    world_decisions = deque(
        (decision for decision in raw_world_decisions if isinstance(decision, dict)),
        maxlen=DECISION_LEDGER_MAXLEN,
    ) if isinstance(raw_world_decisions, list) else deque(maxlen=DECISION_LEDGER_MAXLEN)
    raw_room_overrides = data.get("room_state_overrides", {})
    room_state_overrides = {
        str(room_id): dict(override)
        for room_id, override in raw_room_overrides.items()
        if isinstance(override, dict)
    } if isinstance(raw_room_overrides, dict) else {}
    raw_dispositions = data.get("npc_dispositions", {})
    npc_dispositions = {
        str(npc_id): dict(disposition)
        for npc_id, disposition in raw_dispositions.items()
        if isinstance(disposition, dict) and not is_transient_patrol_id(npc_id)
    } if isinstance(raw_dispositions, dict) else {}
    death_journals = dict(data.get("death_journals", {}))
    active_rumors = list(data.get("active_rumors", []))
    active_authored_rumor_ids = list(data.get("active_authored_rumor_ids", []) or [])
    rumor_records_raw = data.get("rumor_records", {})
    rumor_records = normalize_record_map({
        str(record_id): deserialize_record(record)
        for record_id, record in rumor_records_raw.items()
        if isinstance(record, dict)
    }) if isinstance(rumor_records_raw, dict) else {}

    district_control = dict(data.get("district_control", {}))
    district_influence = {k: dict(v) for k, v in data.get("district_influence", {}).items()}
    npc_social_schedules = {
        npc_id: dict(schedule)
        for npc_id, schedule in data.get("npc_social_schedules", {}).items()
        if not is_transient_patrol_id(npc_id)
    }
    social_influence_ledger = {key: int(value) for key, value in data.get("social_influence_ledger", {}).items()}
    raw_social_consequences = data.get("social_consequences", {})
    if not isinstance(raw_social_consequences, dict):
        raw_social_consequences = {}
    social_consequences = {
        str(consequence_id): dict(record)
        for consequence_id, record in sorted(raw_social_consequences.items())
        if isinstance(record, dict)
    }
    raw_social_consequence_cooldowns = data.get("social_consequence_cooldowns", {})
    if not isinstance(raw_social_consequence_cooldowns, dict):
        raw_social_consequence_cooldowns = {}
    social_consequence_cooldowns = {
        str(cooldown_id): int(created_at)
        for cooldown_id, created_at in sorted(raw_social_consequence_cooldowns.items())
    }
    raw_applied_cancellations = data.get("applied_cancellation_event_ids", [])
    applied_cancellation_event_ids = [
        entry for entry in raw_applied_cancellations if isinstance(entry, str)
    ] if isinstance(raw_applied_cancellations, list) else []

    from .rumors import RumourSeed
    rumour_seeds_raw = data.get("rumour_seeds", [])
    rumour_seeds = []
    for s in rumour_seeds_raw:
        rumour_seeds.append(RumourSeed(
            id=s.get("id", ""),
            event_type=s.get("event_type", ""),
            location=s.get("location", ""),
            district=s.get("district", ""),
            witnesses=list(s.get("witnesses", [])),
            faction_context=s.get("faction_context", ""),
            day_created=int(s.get("day_created", 1)),
            description=s.get("description", ""),
            resolved=bool(s.get("resolved", False)),
            seed_rumor_ids=list(s.get("seed_rumor_ids", [])),
        ))

    tracked_rumors_raw = data.get("tracked_rumors", [])
    tracked_rumors = []
    if tracked_rumors_raw:
        try:
            from .rumors import TrackedRumor
            for r in tracked_rumors_raw:
                if isinstance(r, dict):
                    tracked_rumors.append(TrackedRumor.from_dict(r))
                else:
                    tracked_rumors.append(r)
        except Exception:
            tracked_rumors = tracked_rumors_raw
        
    economy_data = data.get("economy", {})
    if economy_data:
        from .economy import load_economy_state
        load_economy_state(economy_data)

    from .room_codes import generate_room_codes, layout_rooms, layout_tutorial_rooms
    layout_seed = int(data.get("layout_seed", 0))
    room_codes = generate_room_codes(world.rooms)
    layout_coords = layout_rooms(world.rooms, layout_seed=layout_seed)
    tutorial_coords = layout_tutorial_rooms(world.rooms)
    layout_coords.update(tutorial_coords)

    state = SharedWorldState(
        world=world,
        game_time=game_time,
        scheduler=scheduler,
        ccp_influence=ccp_influence,
        gmd_influence=gmd_influence,
        event_log=event_log,
        rumour_mill=rumour_mill,
        archived_journals=archived_journals,
        server_cycle=server_cycle,
        weather=weather,
        named_npc_deaths=named_npc_deaths,
        world_decisions=world_decisions,
        room_state_overrides=room_state_overrides,
        npc_dispositions=npc_dispositions,
        death_journals=death_journals,
        active_rumors=active_rumors,
        active_authored_rumor_ids=active_authored_rumor_ids,
        rumor_records=rumor_records,
        tutorial_room_clones={},
        cloned_tutorial_rooms={},
        district_control=district_control,
        district_influence=district_influence,
        npc_social_schedules=npc_social_schedules,
        social_influence_ledger=social_influence_ledger,
        social_consequences=social_consequences,
        social_consequence_cooldowns=social_consequence_cooldowns,
        applied_cancellation_event_ids=applied_cancellation_event_ids,
        tracked_rumors=tracked_rumors,
        rumour_seeds=rumour_seeds,
        room_codes=room_codes,
        code_to_room={code: rid for rid, code in room_codes.items()},
        room_layout_coords=layout_coords,
        layout_seed=layout_seed,
    )

    from .rumors import migrate_world_rumors
    migrate_world_rumors(state)
    world._death_records = state.named_npc_deaths
    retire_recorded_npcs(state)
    return state


def build_market_tracker(world: World) -> Dict[str, List[str]]:
    tracker: Dict[str, List[str]] = {}
    for room_id, room in world.rooms.items():
        food_ids = [item.id for item in room.items if item.food_value > 0]
        if food_ids:
            tracker[room_id] = food_ids
    return tracker


def load_world_state(world: World = None) -> SharedWorldState:
    from .save_manager import WORLD_SAVE_PATH
    path = WORLD_SAVE_PATH
    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            import json
            data = json.load(f)
    except Exception:
        return None

    if world is None:
        world = World()

    return deserialize_world_state(data, world)


def save_world_state(state: SharedWorldState) -> None:
    from .save_manager import WORLD_SAVE_PATH
    import json

    data = serialize_world_state(state)
    tmp_path = WORLD_SAVE_PATH.with_suffix(".json.tmp")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp_path.replace(WORLD_SAVE_PATH)
