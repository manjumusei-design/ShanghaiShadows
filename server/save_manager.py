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


WORLD_BACKUP_COUNT = 5
PLAYER_BACKUP_COUNT = 3


def _rotate_backups(base_path: Path, keep: int) -> None:
    for i in range(keep - 1, 0, -1):
        src = base_path.with_suffix(f".json.{i}")
        dst = base_path.with_suffix(f".json.{i + 1}")
        if src.exists():
            try:
                src.rename(dst)
            except Exception:
                pass
    if base_path.exists():
        try:
            import shutil
            shutil.copy2(str(base_path), str(base_path.with_suffix(".json.1")))
        except Exception:
            pass
    i = keep + 1
    while True:
        p = base_path.with_suffix(f".json.{i}")
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
            i += 1
        else:
            break


def save_world_state(shared: SharedWorldState) -> None:
    _ensure_dirs()
    data = serialize_world_state(shared)
    tmp_path = WORLD_SAVE_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(WORLD_SAVE_PATH)
    _rotate_backups(WORLD_SAVE_PATH, WORLD_BACKUP_COUNT)    


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
    _rotate_backups(player_path, PLAYER_BACKUP_COUNT)


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
        player = deserialize_player(data, storylet_manager)
    except Exception as e:
        logger.error(f"Failed to deserialize player data for {username}: {e}")
        corrupted_path = player_path.with_suffix(".json.corrupted")
        try:
            shutil.move(str(player_path), str(corrupted_path))
            logger.info(f"Backed up corrupted save to {corrupted_path}")
        except Exception as backup_err:
            logger.warning(f"Failed to backup corrupted save: {backup_err}")
        return None
    
    if player is None:
        return None
    _DEFAULTS = {'health': 100, 'hunger': 60, 'morale': 80, 'money_fabi': 50}
    for field, default_val in _DEFAULTS.items():
        val = getattr(player, field, None)
        if val is None:
            logger.warning(f"Player {username} missing {field}, setting default")
            setattr(player, field, default_val)
    if not hasattr(player, 'inventory') or player.inventory is None:
        logger.warning(f"Player {username} missing inventory, setting empty")
        player.inventory = []
    return player


def archive_journal_on_death(player_name: str, shared: SharedWorldState) -> None:
    shared.archived_journals[player_name] = shared.event_log[-100:]


def get_archived_journal(character_name: str, shared: SharedWorldState) -> list:
    return shared.archived_journals.get(character_name, [])
