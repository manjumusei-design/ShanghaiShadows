import json
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from .stealth import Disguise
from .time_system import EventScheduler, GameTime
from .trust import TrustMap, get_role_trust
from .world import World


EVENTS_PATH = "server/data/events.yaml"
TRUST_RULES_PATH = "server/data/trust_rules.yaml"
DISGUISES_PATH = "server/data/disguises.yaml"
STORYLETS_PATH = "server/data/storylets.yaml"
SAVES_DIR = Path("server/data/saves")
STATE_BROADCAST_INTERVAL = 5


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
    legacy_book: List[Dict] = field(default_factory=list)
    rumour_mill: Dict[str, List[str]] = field(default_factory=dict)

    def get_trust_value(self, key: str, player_trust: TrustMap) -> int:
        if "." in key:
            faction, role = key.split(".", 1)
            return get_role_trust(player_trust, faction, role)
        return get_role_trust(player_trust, key)


def serialize_world_state(state: SharedWorldState) -> Dict[str, object]:
    from .game import _serialize_item

    room_items = {
        room_id: [_serialize_item(item) for item in room.items]
        for room_id, room in state.world.rooms.items()
    }

    npc_locations = state.world.npc_locations
    npc_memory = {npc_id: npc.memory for npc_id, npc in state.world.npcs.items()}

    payload = {
        "time": {"day": state.game_time.day, "minute": state.game_time.minute},
        "room_items": room_items,
        "npc_locations": npc_locations,
        "npc_memory": npc_memory,
        "scheduler": state.scheduler.to_payload(),
        "rumour_mill": state.rumour_mill,
        "event_log": state.event_log,
        "legacy_book": state.legacy_book,
        "ccp_influence": state.ccp_influence,
        "gmd_influence": state.gmd_influence,
    }
    return payload


def deserialize_world_state(data: Dict[str, object], world: World) -> SharedWorldState:
    from .game import _deserialize_item

    game_time = GameTime(
        day=int(data.get("time", {}).get("day", 1)),
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

    rumour_mill = dict(data.get("rumour_mill", {}))
    event_log = list(data.get("event_log", []))
    legacy_book = list(data.get("legacy_book", []))
    ccp_influence = int(data.get("ccp_influence", 10))
    gmd_influence = int(data.get("gmd_influence", 15))

    return SharedWorldState(
        world=world,
        game_time=game_time,
        scheduler=scheduler,
        ccp_influence=ccp_influence,
        gmd_influence=gmd_influence,
        event_log=event_log,
        legacy_book=legacy_book,
        rumour_mill=rumour_mill,
    )


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
