from collections import deque
from typing import Dict, List
import re

from .time_system import GameTIme, time_str

_ASK_RE = re.compile(r"^You asked (.+?) about (.+)\.$")


def collect_recent_events(event_log: List[Dict], game_time: GameTime, hours: int = 24) -> List[Dict]:
    current_total = (game_time.day - 1) * 1440 + game_time.minute
    cutoff = current_total - (hours * 60)
    return [e for e in event_log if (e["day"] - 1) * 1440 + e.get("minute", 0) >= cutoff]


def _collapse_events(events: List[Dict]) -> List[str]:
    compressed: List = []
    for e in events:
        t = e.get("text", "")
        if compressed and compressed[-1][0] == t:
            compressed[-1][1] += 1
        else:
            compressed.append([t, 1])
    out: List[str] = []
    i = 0
    while i < len(compressed):
        text, count = compressed[i]
        m = _ASK_RE.match(text)
        if m and count == 1:
            npc_name = m.group(1)
            topics = [m.group(2)]
            j = i + 1
            while j < len(compressed):
                m2 = _ASK_RE.match(compressed[j][0])
                if m2 and m2.group(1) == npc_name and compressed[j][1] == 1 and m2.group(2) not in topics:
                    topics.append(m2.group(2))
                    j += 1
                else:
                    break
            out.append(text if len(topics) == 1 else f"You asked {npc_name} about several topics ({', '.join(topics)}).")
            i = j
        else:
            out.append(text if count == 1 else f"{text} (x{count})")
            i += 1
    return out


def format_journal(event_log: List[Dict], game_time: GameTime) -> str:
    recent = collect_recent_events(event_log, game_time)
    if not recent:
        return "Day {}. You remember nothing. The hours passed unnoticed." .format(game_time.day)
    lines = [f"Day {game_time.day}. You remember:"]
    for event in recent[-20]:
        lines.append(f"- {event['text']}")
    return "\n".join(lines)


def format_life_retrospective(event_log: List[Dict], player_name: str) -> str:
    entries = list(event_log)[-100:]
    if not entries:
        return f"{player_name} lived and died in occupied Shanghai. The city endures, and so does their memory."
    lines = [f"The life of {player_name}, in brief:"]
    for e in entries[-30:]:
        lines.append(f"- {e['text']}")
    return "\n".join(lines)


def build_death_journal_entry(player, day: int, cause: str, last_words: str) -> dict:
    return {
        "character_name": player.name,
        "day_of_death": day,
        "cause": cause,
        "last_words": last_words or "",
        "conversation_history": [dict(c) for c in player.conversation_history],
    }


def absorb_death_journal(reader_history: deque, entry: dict) -> int:
    prefix = f"[from the journal of {entry['character_name']}] "
    history = entry.get("conversation_history", [])
    for conv in history:
        copied = dict(conv)
        copied["npc_response"] = prefix + str(copied.get("npc_response", ""))
        reader_history.append(copied)
    return len(history)