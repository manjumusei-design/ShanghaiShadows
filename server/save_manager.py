import json
import re
from pathlib import Path
from typing import Optional

from .game_world import SharedWorldState, deserialize_world_state, serialize_world_state
from .player_data import PlayerData, deserialize_player, serialize_player
from .time_system import EventScheduler, GameTime
from .world import World
from .config import get_setting


def _sanitize_username(username: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_-]', '', username)


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

    sanitized_username = _sanitize_username(player.username)
    data = serialize_player(player)
    player_path = PLAYERS_SAVE_DIR / f"{sanitized_username}.json"
    tmp_path = player_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(player_path)


def load_player(username: str, storylet_manager=None) -> Optional[PlayerData]:
    import logging
    import shutil
    logger = logging.getLogger(__name__)

    _ensure_dirs()
    sanitized_username = _sanitize_username(username)
    player_path = PLAYERS_SAVE_DIR / f"{sanitized_username}.json"

    if not player_path.exists():
        return None

    try:
        data = json.loads(player_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        logger.error(f"Corrupted save file for {username}: {e}")
        corrupted_path = player_path.with_suffix(".json.corrupted")
        try:
            shutil.move(str(player_path), str(corrupted_path))
            logger.info(f"Backed up corrupted save to {corrupted_path}")
        except Exception as backup_err:
            logger.warning(f"Failed to backup corrupted save: {backup_err}")
        return None
    except Exception as e:
        logger.error(f"Failed to read save file for {username}: {e}")
        return None

    try:
        return deserialize_player(data, storylet_manager)
    except Exception as e:
        logger.error(f"Failed to deserialize player data for {username}: {e}")
        corrupted_path = player_path.with_suffix(".json.corrupted")
        try:
            shutil.move(str(player_path), str(corrupted_path))
            logger.info(f"Backed up corrupted save to {corrupted_path}")
        except Exception as backup_err:
            logger.warning(f"Failed to backup corrupted save: {backup_err}")
        return None
    

# might need to change to a more robust system later on but this will do for now 
def archive_journal_on_death(player_name: str, shared: SharedWorldState) -> None:
    shared.archived_journals[player_name] = shared.event_log[-100:]


def get_archived_journal(character_name: str, shared: SharedWorldState) -> list:
    return shared.archived_journals.get(character_name, [])
