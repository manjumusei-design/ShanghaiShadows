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


def _player_path(save_key: str) -> Path:
    return PLAYERS_SAVE_DIR / f"{_sanitize_username(save_key)}.json"


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


def save_player(player: PlayerData, save_key: str = None) -> None:
    _ensure_dirs()
    if getattr(player, "ephemeral", False):
        return
    if not player.username:
        return

    if save_key is None:
        save_key = getattr(player, "save_key", "") or ""
    elif getattr(player, "save_key", "") and player.save_key != save_key:
        raise ValueError("slot-bound save key mismatch")
    if getattr(player, "account_username", "") or getattr(player, "character_slot_id", ""):
        if not save_key:
            raise ValueError("slot-bound save key required")
    if not save_key:
        save_key = player.username
    player.save_key = save_key
    data = serialize_player(player)
    player_path = _player_path(save_key)
    tmp_path = player_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(player_path)
    _rotate_backups(player_path, PLAYER_BACKUP_COUNT)


def load_player(username: str, storylet_manager=None, *, slot_key: str = None, expected_account_username: str = None, expected_slot_id: str = None, expected_save_key: str = None, account_username: str = None, character_slot_id: str = None) -> Optional[PlayerData]:
    import logging
    import shutil
    logger = logging.getLogger(__name__)

    _ensure_dirs()
    expected_account_username = expected_account_username if expected_account_username is not None else account_username
    expected_slot_id = expected_slot_id if expected_slot_id is not None else character_slot_id
    lookup_key = slot_key or username
    player_path = _player_path(lookup_key)

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
    if expected_account_username is not None:
        expected_account = expected_account_username.strip().lower()
        embedded_account = (player.account_username or player.username).strip().lower()
        if embedded_account != expected_account or player.username.strip().lower() != expected_account:
            return None
    if expected_slot_id is not None and player.character_slot_id != expected_slot_id:
        return None
    if expected_save_key is not None and player.save_key != expected_save_key:
        return None
    if expected_slot_id is not None and getattr(player, "health", 0) <= 0:
        return None
    if expected_slot_id is not None and "player_died" in getattr(player, "flags", []):
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


def load_legacy_player(username: str, storylet_manager=None) -> Optional[PlayerData]:
    import logging
    logger = logging.getLogger(__name__)
    _ensure_dirs()
    player_path = _player_path(username)
    if not player_path.exists():
        return None
    try:
        data = json.loads(player_path.read_text(encoding="utf-8"))
        return deserialize_player(data, storylet_manager)
    except Exception as exc:
        logger.warning(f"Unable to read declared legacy save {username}: {exc}")
        return None


def load_slot_player(slot, account_username: str, storylet_manager=None) -> Optional[PlayerData]:
    if slot is None or slot.status != "living":
        return None
    return load_player(
        slot.save_key,
        storylet_manager,
        expected_account_username=account_username,
        expected_slot_id=slot.slot_id,
        expected_save_key=slot.save_key,
    )


def archive_journal_on_death(player_name: str, shared: SharedWorldState) -> None:
    shared.archived_journals[player_name] = shared.event_log[-100:]


def get_archived_journal(character_name: str, shared: SharedWorldState) -> list:
    return shared.archived_journals.get(character_name, [])
