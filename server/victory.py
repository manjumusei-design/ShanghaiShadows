import asyncio
import json
from pathlib import Path
from typing import Dict, List, Optional

from .serialization import _load_yaml
from .time_system import GameTime


DAY_LIBERATION = 180

_DATA_DIR = "server/data"


_ENDINGS_DATA = _load_yaml(f"{_DATA_DIR}/endings.yaml")
_TIME_SKIP_DATA = _load_yaml(f"{_DATA_DIR}/time_skip_templates.yaml")


def _season_from_day(day: int) -> str:
    month = ((day - 1) // 90) % 4
    return ["winter", "spring", "summer", "autumn"][month]


def _match_score(condition: object, context: Dict) -> int:
    if condition == "default" or condition == {} or condition is None:
        return 0
    if not isinstance(condition, dict):
        return -1
    score = 0
    for key, value in condition.items():
        actual = context.get(key)
        if actual is None:
            if value is True:
                continue
            return -1
        if actual == value:
            score += 1
        elif isinstance(actual, str) and isinstance(value, str) and actual.lower() == value.lower():
            score += 1
        else:
            return -1
    return score


def _select_template(templates: List[Dict], context: Dict) -> Optional[Dict]:
    best, best_score = None, -1
    for t in templates:
        score = _match_score(t.get("condition", "default"), context)
        if score > best_score:
            best, best_score = t, score
    return best


def compute_progress(day: int) -> int:
    return min(100, int(day * 100 / DAY_LIBERATION))


def fabi_inflation_multiplier(day: int) -> float:
    return 1.0 + min(2.0, (day // 30) * 0.15)


def adjust_influence(ccp_influence: int, gmd_influence: int, faction: str, amount: int, district: str = "", shared=None) -> tuple:
    if faction == "ccp":
        ccp_influence = max(0, min(100, ccp_influence + amount))
    elif faction == "gmd":
        gmd_influence = max(0, min(100, gmd_influence + amount))
    
    if district and shared and hasattr(shared, "district_influence"):
        if district not in shared.district_influence:
            shared.district_influence[district] = {"ccp": 0, "gmd": 0}
        if faction in ("ccp", "gmd"):
            shared.district_influence[district][faction] = max(0, min(100, shared.district_influence[district].get(faction, 0) + amount))
        _update_district_control(district, shared)
    
    return ccp_influence, gmd_influence


def _update_district_control(district: str, shared) -> None:
    if not hasattr(shared, 'district_control'):
        return
    inf = shared.district_influence.get(district, {"ccp": 0, "gmd": 0})
    ccp = inf.get("ccp", 0)
    gmd = inf.get("gmd", 0)
    if ccp >= 30 and ccp > gmd:
        shared.district_control[district] = "ccp"
    elif gmd >= 30 and gmd > ccp:
        shared.district_control[district] = "gmd"
    elif ccp < 20 and gmd < 20:
        shared.district_control[district] = "neutral"


def select_liberation_ending(ccp_influence: int, gmd_influence: int) -> str:
    if ccp_influence >= 80 and ccp_influence - gmd_influence >= 10:
        return "ccp_uprising"
    if gmd_influence >= 80 and gmd_influence - ccp_influence >= 10:
        return "gmd_return"
    if ccp_influence >= 60 and gmd_influence >= 60 and abs(ccp_influence - gmd_influence) <= 15:
        return "unity"
    return "default_liberation"


def predict_ending(ccp_influence: int, gmd_influence: int) -> str:
    return select_liberation_ending(ccp_influence, gmd_influence)


def check_victory_conditions(day: int, ccp_influence: int, gmd_influence: int) -> Optional[str]:
    if day >= DAY_LIBERATION:
        return select_liberation_ending(ccp_influence, gmd_influence)
    return None


def check_unity_ending(ccp_influence: int, gmd_influence: int) -> bool:
    return select_liberation_ending(ccp_influence, gmd_influence) == "unity"


def generate_liberation_ending(ending_type: str, player_alias: str, legacy_book: List[Dict], ccp_influence: int = 0, gmd_influence: int = 0) -> str:

    endings = _ENDINGS_DATA.get("endings", [])
    ending = None
    for e in endings:
        if e["id"] == ending_type:
            ending = e
            break
    if not ending:
        ending = endings[0] if endings else None
    if not ending:
        return "Shanghai is free. The cost was beyond counting."

    headline = ending.get("headline", "LIBERATION")
    paragraphs = ending.get("paragraphs", [])

    parts = [headline, ""]
    for p in paragraphs:
        parts.append(p.replace("{alias}", player_alias))
        parts.append("")

    return "\n".join(parts)

def _active_sessions(session_manager) -> list:
    return [
        session
        for session in list(getattr(session_manager, "sessions", {}).values())
        if getattr(session, "running", True)
    ]


def _reset_shared_world(shared, session_manager) -> None:
    cycle = getattr(shared, "server_cycle", 1)
    death_journals = {
        room_id: entries[-50:]
        for room_id, entries in getattr(shared, "death_journals", {}).items()
    }
    relationship_system = getattr(shared, "relationship_system", None)
    from .game_world import bootstrap_cycle_state

    fresh_state = bootstrap_cycle_state(
        initial_day=1,
        initial_minute=0,
        server_cycle=cycle,
    )
    fresh_state.death_journals = death_journals
    fresh_state.relationship_system = relationship_system
    shared.__dict__.clear()
    shared.__dict__.update(fresh_state.__dict__)
    sessions = getattr(session_manager, "sessions", None)
    if sessions is not None:
        sessions.clear()

def archive_legacy_cycle(legacy_book: List[Dict], cycle: int) -> None:
    if not legacy_book:
        return
    archive_dir = Path(_DATA_DIR) / "archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"legacy_cycle_{cycle}.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(legacy_book, f, allow_unicode=True, default_flow_style=False)


def compile_legacy_narrative(legacy_book: List[Dict]) -> str:
    if not legacy_book:
        return "No one lived to tell the tale. But the city remembers."
    lines = []
    for e in legacy_book:
        name = e.get("character_name", "Unknown")
        day = e.get("day_of_death", "?")
        summary = e.get("summary", "Their story is their own.")
        lines.append(f"{name} (died day {day}): {summary}")
    return "\n".join(lines)
