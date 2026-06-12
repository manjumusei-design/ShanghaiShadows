import random
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .serialization import _load_yaml
from .time_system import GameTime


DAY_LIBERATION = 2835

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


def adjust_influence(ccp_influence: int, gmd_influence: int, faction: str, amount: int) -> tuple:
    if faction == "ccp":
        ccp_influence = max(0, min(100, ccp_influence + amount))
    elif faction == "gmd":
        gmd_influence = max(0, min(100, gmd_influence + amount))
    return ccp_influence, gmd_influence


def check_victory_conditions(day: int, ccp_influence: int, gmd_influence: int) -> Optional[str]:
    if day >= DAY_LIBERATION:
        if ccp_influence >= 80 and ccp_influence > gmd_influence:
            return "ccp_uprising"
        if gmd_influence >= 80 and gmd_influence > ccp_influence:
            return "gmd_return"
        if ccp_influence >= 60 and gmd_influence >= 60 and abs(ccp_influence - gmd_influence) <= 15:
            return "unity"
        return "gmd_return"
    return None


def check_unity_ending(ccp_influence: int, gmd_influence: int) -> bool:
    return ccp_influence >= 70 and gmd_influence >= 70


def apply_time_skip(state) -> int:
    skip_days = random.randint(30, 180)
    state.game_time.day += skip_days

    for faction in state.player.trust.values():
        for role in faction:
            faction[role] = faction[role] + (50 - faction[role]) // 4

    state.ccp_influence = max(5, min(100, state.ccp_influence + random.randint(-5, 10)))
    state.gmd_influence = max(5, min(100, state.gmd_influence + random.randint(-10, 5)))

    state.event_log.append({
        "day": state.game_time.day - skip_days,
        "minute": 0,
        "text": f"[Time skip: {skip_days} days passed. The city endures under occupation.]",
    })
    return skip_days


def generate_time_skip_summary(skip_days: int, ccp_inf: int, gmd_inf: int) -> str:
    context = {
        "season": _season_from_day(skip_days),
        "ccp_high": ccp_inf > 50,
        "gmd_high": gmd_inf > 50,
        "ccp_low": ccp_inf < 20,
        "gmd_low": gmd_inf < 20,
    }
    templates = _TIME_SKIP_DATA.get("templates", [])
    template = _select_template(templates, context) if templates else None
    if template:
        return template["text"].format(days=skip_days)
    return f"{skip_days} days pass. The Kempeitai tighten their grip. The people endure. The city remembers."


def generate_liberation_ending(ending_type: str, player_alias: str, legacy_book: List[Dict], ccp_influence: int = 0, gmd_influence: int = 0) -> str:
    if check_unity_ending(ccp_influence, gmd_influence):
        ending_type = "unity"

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

    if legacy_book:
        parts.append("---")
        parts.append("Lives lost in the struggle:")
        for entry in legacy_book:
            name = entry.get("character_name", "Unknown")
            summary = entry.get("summary", "Their story remains untold.")
            parts.append(f"  {name}: {summary}")

    return "\n".join(parts)


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
