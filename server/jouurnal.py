from typing import Dict, List

from .time_system import GameTIme, time_str


def collect_recent_events(event_log: List[Dict], game_time: GameTime, hours: int = 24) -> List[Dict]:
    current_total = (game_time.day - 1) * 1440 + game_time.minute
    cutoff = current_total - (hours * 60)
    return [e for e in event_log if (e["day"] - 1) * 1440 + e.get("minute", 0) >= cutoff]


def format_journal(event_log: List[Dict], game_time: GameTime) -> str:
    recent = collect_recent_events(event_log, game_time)
    if not recent:
        return "Day {}. You remember nothing. The hours passed unnoticed." .format(game_time.day)
    lines = [f"Day {game_time.day}. You remember:"]
    for event in recent[-20]:
        lines.append(f"- {event['text']}")
    return "\n".join(lines)


def format_life_retrospective(event_log: List[Dict], player_name: str) -> str:
    entries = event_log[-100:]
    if not entries:
        return f"{player_name} lived and died in occupied Shanghai. The city endures, and so does their memory."
    lines = [f"The life of {player_name}, in brief:"]
    for e in entries[-30:]:
        lines.append(f"- {e['text']}")
    return "\n".join(lines)
