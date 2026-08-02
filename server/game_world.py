import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .stealth import Disguise
from .time_system import EventScheduler, GameTime
from .trust import TrustMap, get_role_trust
from .world import World
from .constants import (
    EVENTS_PATH,
    TRUST_RULES_PATH,
    DISGUISES_PATH,
    STORYLETS_PATH,
    STATE_BROADCAST_INTERVAL,
    DECISION_LEDGER_MAXLEN,
)

SAVES_DIR = Path("server/data/saves")


def load_disguises(path: str) -> Dict[str, Disguise]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
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
    dead_npcs: set = field(default_factory=set)
    world_decisions: deque = field(default_factory=lambda: deque(maxlen=DECISION_LEDGER_MAXLEN))
    room_state_overrides: Dict[str, dict] = field(default_factory=dict)
    npc_dispositions: Dict[str, dict] = field(default_factory=dict)
    market_rooms: Dict[str, List[str]] = field(default_factory=dict)
    death_journals: Dict[str, List[dict]] = field(default_factory=dict)
    active_rumors: List[str] = field(default_factory=list)
    room_codes: Dict[str, str] = field(default_factory=dict)
    code_to_room: Dict[str, str] = field(default_factory=dict)
    room_layout_coords: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    tutorial_room_clones: Dict[str, Dict[str, str]] = field(default_factory=dict)
    cloned_tutorial_rooms: Dict[str, Any] = field(default_factory=dict)  # Room type from world.py
    tutorial_npc_clones: Dict[str, List[str]] = field(default_factory=dict)
    district_control: Dict[str, str] = field(default_factory=dict)  # district_id → "ccp"|"gmd"|"kempeitai"|"neutral"
    district_influence: Dict[str, Dict[str, int]] = field(default_factory=dict)  # district_id → {ccp: int, gmd: int}
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

    def get_trust_value(self, key: str, player_trust: TrustMap) -> int:
        if "." in key:
            faction, role = key.split(".", 1)
            return get_role_trust(player_trust, faction, role)
        return get_role_trust(player_trust, key)


def serialize_world_state(state: SharedWorldState) -> Dict[str, object]:
    from .serialization import serialize_item as _serialize_item
    from .economy import serialize_economy_state

    room_items = {
        room_id: [_serialize_item(item) for item in room.items]
        for room_id, room in state.world.rooms.items()
    }

    npc_locations = state.world.npc_locations
    npc_memory = {npc_id: npc.memory for npc_id, npc in state.world.npcs.items()}
    npc_tracked_rumors = {
        npc_id: npc.tracked_rumors
        for npc_id, npc in state.world.npcs.items()
        if getattr(npc, 'tracked_rumors', None)
    }
    npc_social_state = {
        npc_id: {
            "mood": getattr(npc, "mood", "neutral"),
            "social_visibility": getattr(npc, "social_visibility", "visible"),
            "needs": getattr(npc, "needs", {}),
            "inventory": getattr(npc, "inventory", []),
            "goals": getattr(npc, "goals", []),
        }
        for npc_id, npc in state.world.npcs.items()
    }
    relationships = []
    seen_relationships = set()
    for npc_id, npc in state.world.npcs.items():
        for other_id, relationship in getattr(npc, "relationships", {}).items():
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
    for npc_id, npc in state.world.npcs.items():
        if hasattr(npc, 'player_memories') and npc.player_memories:
            npc_player_memories[npc_id] = {
                player_name: {
                    'trust_mod': mem.trust_mod,
                    'relationship_type': mem.relationship_type,
                    'last_interaction_day': mem.last_interaction_day,
                    'interactions': mem.interactions[-10:],
                    'remembered_events': mem.remembered_events,  # BUG FIX: was missing
                }
                for player_name, mem in npc.player_memories.items()
            } 

    from datetime import datetime
    payload = {
        "_version": 1,
        "_saved_at": datetime.utcnow().isoformat(),
        "time": {"day": state.game_time.day, "minute": state.game_time.minute},
        "room_items": room_items,
        "npc_locations": npc_locations,
        "npc_memory": npc_memory,
        "npc_tracked_rumors": npc_tracked_rumors,
                "npc_social_state": npc_social_state,
        "npc_relationships": relationships,
        "npc_social_schedules": state.npc_social_schedules,
        "social_influence_ledger": state.social_influence_ledger,
        "social_consequences": {
            consequence_id: state.social_consequences[consequence_id]
            for consequence_id in sorted(state.social_consequences)
        },
        "social_consequence_cooldowns": {
            cooldown_id: state.social_consequence_cooldowns[cooldown_id]
            for cooldown_id in sorted(state.social_consequence_cooldowns)
        },
        "npc_player_memories": npc_player_memories,
        "scheduler": state.scheduler.to_payload(),
        "rumour_mill": state.rumour_mill,
        "event_log": state.event_log,
        "legacy_book": state.legacy_book,
        "ccp_influence": state.ccp_influence,
        "gmd_influence": state.gmd_influence,
        "archived_journals": state.archived_journals,
        "server_cycle": state.server_cycle,
        "dead_npcs": sorted(str(npc_id) for npc_id in state.dead_npcs),
        "world_decisions": list(state.world_decisions),
        "room_state_overrides": {
            room_id: state.room_state_overrides[room_id]
            for room_id in sorted(state.room_state_overrides)
        },
        "npc_dispositions": {
            npc_id: state.npc_dispositions[npc_id]
            for npc_id in sorted(state.npc_dispositions)
        },
        "death_journals": state.death_journals,
        "active_rumors": state.active_rumors,
        "economy": serialize_economy_state(),
        "district_control": state.district_control,
        "district_influence": state.district_influence,
        "tracked_rumors": [r.to_dict() if hasattr(r, 'to_dict') else r for r in state.tracked_rumors],
        "rumour_seeds": [
            {
                "id": s.id, "event_type": s.event_type, "location": s.location,
                "district": s.district, "witnesses": s.witnesses,
                "faction_context": s.faction_context, "day_created": s.day_created,
                "description": s.description, "resolved": s.resolved,
                "seed_rumor_ids": s.seed_rumor_ids,
            }
            for s in state.rumour_seeds
        ],
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

    npc_locations = data.get("npc_locations")
    if isinstance(npc_locations, dict):
        for room in world.rooms.values():
            room.npcs = []
        world.npc_locations = {}
        for npc_id, room_id in npc_locations.items():
            if npc_id in world.npcs and room_id in world.rooms:
                world.place_npc(npc_id, room_id)

    for npc_id, memories in data.get("npc_memory", {}).items():
        npc = world.npcs.get(npc_id)
        if npc:
            npc.memory = list(memories)

    for npc_id, tracked in data.get("npc_tracked_rumors", {}).items():
        npc = world.npcs.get(npc_id)
        if npc and hasattr(npc, 'tracked_rumors'):
            npc.tracked_rumors = list(tracked)

    for npc_id, social_state in data.get("npc_social_state", {}).items():
        npc = world.npcs.get(npc_id)
        if npc:
            npc.mood = str(social_state.get("mood", "neutral"))
            npc.social_visibility = str(social_state.get("social_visibility", "visible"))
            npc.needs = dict(social_state.get("needs", {}))
            npc.inventory = list(social_state.get("inventory", []))
            npc.goals = list(social_state.get("goals", []))

    relationship_rows = data.get("npc_relationships", [])
    if relationship_rows:
        from .npc_memory import NpcRelationshipSystem
        NpcRelationshipSystem().load_relationships(relationship_rows, world.npcs)

    npc_player_memories = data.get("npc_player_memories", {})
    if isinstance(npc_player_memories, dict):
        for npc_id, player_mems in npc_player_memories.items():
            npc = world.npcs.get(npc_id)
            if npc and hasattr(npc, 'player_memories'):
                from .npc_memory import PlayerMemory
                for player_name, mem_data in player_mems.items():
                    npc.player=memories[player_name] = PlayerMemory(
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
    raw_dead_npcs = data.get("dead_npcs", [])
    dead_npcs = {str(npc_id) for npc_id in raw_dead_npcs} if isinstance(raw_dead_npcs, list) else set()
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
        if isinstance(disposition, dict)
    } if isinstance(raw_dispositions, dict) else {}
    death_journals = dict(data.get("death_journals", {}))
    active_rumors = list(data.get("active_rumors", []))
    if not active_rumors:
        from .rumors import seed_active_rumors
        active_rumors = seed_active_rumors(game_time.day)
    
    district_control = dict(data.get("district_control", {}))
    district_influence = {k: dict(v) for k, v in data.get("district_influence", {}).items()}
    npc_social_schedules = {npc_id: dict(schedule) for npc_id, schedule in data.get("npc_social_schedules", {}).items()}
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
            from .trust import TrackedRumor
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

    from .room_codes import generate_room_codes, layout_room, layout_tutorial_rooms
    layout_seed = int(data.get("layout_seed", 0))
    room_codes = generate_room_codes(world.rooms)
    layout_coords = layout_rooms(world.rooms, layout_seed=layout_seed)
    tutorial_coords = layout_tutorial_rooms(world.rooms)
    layout_coords.update(tutorial_coords)

    return SharedWorldState(
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
        dead_npcs=dead_npcs,
        world_decisions=world_decisions,
        room_state_overrides=room_state_overrides,
        npc_dispositions=npc_dispositions,
        death_journals=death_journals,
        active_rumors=active_rumors,
        tutorial_room_clones={},
        cloned_tutorial_rooms={},
        district_control=district_control,
        district_influence=district_influence,
        npc_social_schedules=npc_social_schedules,
        social_influence_ledger=social_influence_ledger,
        social_consequences=social_consequences,
        social_consequence_cooldowns=social_consequence_cooldowns,
        tracked_rumors=tracked_rumors,
        rumour_seeds=rumour_seeds,
        room_codes=room_codes,
        code_to_room={code: rid for rid, code in room_codes.items()},
        room_layout_coords=layout_coords,
        layout_seed=layout_seed,
    )


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
