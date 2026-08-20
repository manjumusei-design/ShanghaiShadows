import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from . import save_manager
from .game_world import SharedWorldState, bootstrap_cycle_state, load_world_state

RUN_STATE_CLEAN = "clean"
RUN_STATE_UNCLEAN = "unclean"
RUN_MARKER_FILENAME = "run_state.json"
ARCHIVE_DIRNAME = "archives"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run_marker_path() -> Path:
    return save_manager.SAVES_DIR / RUN_MARKER_FILENAME


def _archives_dir() -> Path:
    return save_manager.SAVES_DIR / ARCHIVES_DIRNAME


def _world_save_path() -> Path:
    return save_manager.WORLD_SAVE_PATH


def _read_run_state() -> Optional[str]:
    payload = _read_run_marker()
    state = payload.get("state") if payload else None
    return state if state in (RUN_STATE_CLEAN, RUN_STATE_UNCLEAN) else None


def _read_run_marker() -> Optional[dict]:
    marker_path = _run_marker_path()
    if not marker_path.exists():
        return None
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _read_run_cycle() -> Optional[int]:
    cycles = []
    marker = _read_run_marker()
    if marker:
        try:
            cycle = int(marker.get("server_cycle", 0))
        except (TypeError, ValueError):
            cycle = 0
        if cycle > 0:
            cycles.append(cycle)

    world_path = _world_save_path()
    if world_path.is_file():
        try:
            payload = json.loads(world_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                cycle = int(payload.get("server_cycle", 0))
                if cycle > 0:
                    cycles.append(cycle)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
    return max(cycles) if cycles else None


def _read_persisted_guidance_cycle() -> Optional[int]:
    cycles = []
    players_dir = save_manager.PLAYERS_SAVE_DIR
    if not players_dir.is_dir():
        return None
    for player_path in players_dir.glob("*.json"):
        try:
            payload = json.loads(player_path.read_text(encoding="utf-8"))
            cycle = int(payload.get("terminal_guidance_cycle", 0))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if cycle > 0:
            cycles.append(cycle)
    return max(cycles) if cycles else None


def _write_run_state(state: str, server_cycle: Optional[int] = None) -> None:
    marker_path = _run_marker_path()
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": state,
        "writter_at": _now().isoformat(timespec="seconds"),
    }
    if server_cycle is not None:
        payload["server_cycle"] = int(server_cycle)
    tmp_path = marker_path.with_name(marker_path.name + ".tmp")
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    tmp_path.replace(marker_path)


def _unique_archive_dir() -> Path:
    base_name = _now().strftime("run_%Y%m%d-%H%M%S")
    archives_dir = _archives_dir()
    candidate = archives_dir / base_name
    suffix = 2
    while candidate.exists():
        candidate = archives_dir / f"{base_name}_{suffix}"
        suffix += 1
    return candidate


def archive_prior_world() -> Optional [Path]:
    world_path = _world_save_path()
    if not world_path.is_file():
        return None
    archive_dir = _unique_archive_dir()
    archive_dir.mkdir(parents=True, exist_ok=True)
    world_path.rename(archive_dir / "world_state.json")
    return archive_dir


def begin_run(fresh_world: bool = False) -> SharedWorldState:
    save_manager.SAVES_DIR.mkdir(parents=True, exist_ok=True)
    prior_state = _read_run_state()
    if fresh_world or prior_state != RUN_STATE_UNCLEAN:
        prior_cycle = _read_run_cycle()
        archive_prior_world()
        state = bootstrap_cycle_state(server_cycle=(prior_cycle or 0) + 1)
    else:
        try:
            state = load_world_state()
        except Exception:
            state = None
        if state is None or not isinstance(state, SharedWorldState):
            prior_cycle = _read_run_cycle()
            if prior_cycle is None:
                prior_cycle = _read_persisted_guidance_cycle()
            archive_prior_world()
            state = bootstrap_cycle_state(server_cycle=(prior_cycle or 0) + 1)
        else:
            marker = _read_run_marker() or {}
            try:
                marker_cycle = int(marker.get("server_cycle", 0))
            except (TypeError, ValueError):
                marker_cycle = 0
            if marker_cycle > state.server_cycle:
                state.server_cycle = marker_cycle
    _write_run_state(RUN_STATE_UNCLEAN, state.server_cycle)
    return state


def finish_run_cleanly(sessions: Iterable, shared: SharedWorldState) -> bool:
    from . import lifecycle
    all_saved = True
    for session in sessions:
        if getattr(session, "ephemeral", False) or getattr(session, "clean_close_completed", False):
            continue
        if not lifecycle.attempt_authorized_session_save(session):
            all_saved = False
    try:
        save_manager.save_world_state(shared)
    except Exception:
        all_saved = False
    if not all_saved:
        return False
    _write_run_state(RUN_STATE_CLEAN, shared.server_cycle)
    return True
