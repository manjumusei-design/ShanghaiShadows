import json
from pathlib import Path
from typing import Optional

from .game_world import SharedWorldState, deserialize_world_state, serialize_world_state
from .player_data import PlayerData, deserialize_player, serialize_player
from .time_system import EventScheduler, GameTime
from .world import World
from .config import get_setting


WORLD_SAVE_PATH = Path("server/data/saves/world_state.json")
PLAYERS_SAVE_DIR = Path("server/data/saves/players")
SAVES_DIR = Path("server/data/saves")


def _ensure_dirs():
    PLAYERS_SAVE_DIR.mkdir(parents=True, exist_ok=True)
    SAVES_DIR.mkdir(parents=True, exist_ok=True)


def save_world_state(shared: SharedWorldState) -> None:
    _ensure_dirs()
    data = serialize_world_state(shared)
    tmp_path = WORLD_SAVE_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(WORLD_SAVE_PATH)


def load_world_state(world: World = None) -> Optional[SharedWorldState]:
    _ensure_dirs()
    if not WORLD_SAVE_PATH.exists():
        return None

    try:
        data = json.loads(WORLD_SAVE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None

    if world is None:
        world = World()
    return deserialize_world_state(data, world)


def save_player(player: PlayerData) -> None:
    _ensure_dirs()
    if not player.username:
        return

    data = serialize_player(player)
    player_path = PLAYERS_SAVE_DIR / f"{player.username}.json"
    tmp_path = player_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(player_path)


def load_player(username: str, storylet_manager=None) -> Optional[PlayerData]:
    _ensure_dirs()
    player_path = PLAYERS_SAVE_DIR / f"{username}.json"

    if not player_path.exists():
        return None

    try:
        data = json.loads(player_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    return deserialize_player(data, storylet_manager)


def legacy_save_exists(slot_name: str) -> bool:
    _ensure_dirs()
    legacy_path = SAVES_DIR / f"{slot_name}.json"
    return legacy_path.exists()


def migrate_legacy_save(slot_name: str, shared: SharedWorldState, storylet_manager=None) -> Optional[PlayerData]:
    from .serialization import deserialize_item as _deserialize_item
    from .storylets import ActiveStorylet
    from .stealth import TailingState
    from .trust import migrate_resistance_to_ccp_gmd, default_trust

    _ensure_dirs()
    legacy_path = SAVES_DIR / f"{slot_name}.json"
    if not legacy_path.exists():
        return None

    try:
        data = json.loads(legacy_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    player_died = data.get("player_died", False)

    saved_time = data.get("time", {})
    saved_day = int(saved_time.get("day", 1))
    saved_minute = int(saved_time.get("minute", 0))
    saved_total = (saved_day - 1) * 1440 + saved_minute
    current_total = (shared.game_time.day - 1) * 1440 + shared.game_time.minute

    if saved_total > current_total:
        shared.game_time.day = saved_day
        shared.game_time.minute = saved_minute

        room_items = data.get("room_items")
        npc_locations = data.get("npc_locations")
        if isinstance(room_items, dict) or isinstance(npc_locations, dict):
            for room in shared.world.rooms.values():
                room.items = []
                room.npcs = []
            shared.world.npc_locations = {}
            if isinstance(room_items, dict):
                for room_id, rows in room_items.items():
                    room = shared.world.rooms.get(room_id)
                    if room:
                        room.items = [_deserialize_item(row) for row in rows]
            if isinstance(npc_locations, dict):
                for npc_id, room_id in npc_locations.items():
                    if npc_id in shared.world.npcs and room_id in shared.world.rooms:
                        shared.world.place_npc(npc_id, room_id)

        for npc_id, memories in data.get("npc_memory", {}).items():
            npc = shared.world.npcs.get(npc_id)
            if npc:
                npc.memory = list(memories)

        shared.scheduler.load_from_payload(data.get("scheduler", []))
        shared.rumour_mill = dict(data.get("rumour_mill", {}))
        shared.event_log = list(data.get("event_log", []))
        shared.legacy_book = list(data.get("legacy_book", []))
        shared.ccp_influence = int(data.get("ccp_influence", 10))
        shared.gmd_influence = int(data.get("gmd_influence", 15))

    player_data = data.get("player", {})

    player = PlayerData()
    player.username = slot_name
    player.name = player_data.get("name", "Stranger")
    player.current_room = player_data.get("current_room", "bund_dawn")
    player.inventory = [_deserialize_item(row) for row in player_data.get("inventory", [])]
    player.trust = player_data.get("trust", default_trust())
    if "resistance" in player.trust and "ccp" not in player.trust:
        migrate_resistance_to_ccp_gmd(player.trust)
    player.disguise = player_data.get("disguise", "")
    player.stealth_skill = int(player_data.get("stealth_skill", 55))
    player.hidden = bool(player_data.get("hidden", False))
    player.flags = list(player_data.get("flags", []))
    player.world_events = list(player_data.get("world_events", []))
    player.newspapers = list(player_data.get("newspapers", []))
    player.health = int(player_data.get("health", 100))
    player.hunger = int(player_data.get("hunger", 100))
    player.morale = int(player_data.get("morale", 80))
    player.arrested = bool(player_data.get("arrested", False))
    player.relationships = dict(player_data.get("relationships", {}))
    player.storylet_history = list(data.get("storylet_history", []))
    player.planted_evidence = list(data.get("planted_evidence", []))
    player.last_curfew_penalty_day = int(data.get("last_curfew_penalty_day", 0))
    player.last_newspaper_day = int(data.get("last_newspaper_day", 0))
    player.conversation_history = list(data.get("conversation_history", []))

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


def archive_journal_on_death(player_name: str, shared: SharedWorldState) -> None:
    shared.archived_journals[player_name] = shared.event_log[-100:]


def get_archived_journal(character_name: str, shared: SharedWorldState) -> list:
    return shared.archived_journals.get(character_name, [])
