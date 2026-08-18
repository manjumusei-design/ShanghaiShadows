from typing import Any, Dict, List

from .time_system import GameTime, time_str

JOURNAL_RECENT_HOURS = 24
JOURNAL_CONVERSATION_LIMIT = 10
JOURNAL_EVENT_LIMIT = 50


def _testimony_entries(player: Any) -> List[Dict[str, Any]]:
    from .testimonies import normalize_testimony_archive
    entries = normalize_testimony_archive(getattr(player, "testimonies", []))
    player.testimonies = entries
    return entries


def record_testimony_read(player: Any, item: Any, read_day: int) -> bool:
    from .testimonies import testimony_metadata
    metadata = testimony_metadata(item)
    if metadata is None:
        return False
    entries = _testimony_entries(player)
    if any(entry.get("id") == metadata["id"] for entry in entries):
        return False
    metadata["read_day"] = int(read_day)
    read_orders = []
    for index, entry in enumerate(entries):
        try:
            read_orders.append(int(entry.get("read_order", index + 1)))
        except (TypeError, ValueError):
            read_orders.append(index + 1)
    metadata["read_order"] = max(read_orders, default=0) + 1
    entries.append(metadata)
    return True


def project_testimonies(player: Any) -> List[Dict[str, Any]]:
    entries = _testimony_entries(player)
    return sorted(
        (dict(entry) for entry in entries),
        key=lambda entry: (str(entry.get("date", "")), str(entry.get("title", "")), str(entry.get("id", ""))),
    )


def format_testimony_summary(player: Any) -> str:
    entries = project_testimonies(player)
    if not entries:
        return "Testimonies: none recorded."
    def read_key(index_entry):
        index, entry = index_entry
        try:
            read_order = int(entry.get("read_order", index + 1))
        except (TypeError, ValueError):
            read_order = index + 1
        return (int(entry.get("read_day", 0) or 0), read_order)

    recent = max(enumerate(entries), key=read_key)[1]
    return f"Testimonies: {len(entries)} recorded. Most recent: {recent.get('title', 'untitled')}."


def record_tutorial_journal_lesson(player: Any, stage_key: str, text: str) -> bool:
    lessons = getattr(player, "tutorial_journal_lessons", None)
    if lessons is None:
        lessons = {}
        player.tutorial_journal_lessons = lessons
    if stage_key in lessons:
        return False
    lessons[stage_key] = str(text)
    return True


def normalize_conversation_entry(entry: Any) -> Dict[str, Any]:
    if isinstance(entry, dict):
        normalized = dict(entry)
        if not normalized.get("npc_response") and normalized.get("text"):
            normalized["npc_response"] = str(normalized["text"])
        return normalized
    text = str(entry)
    return {"text": text, "npc_response": text}


def normalize_conversation_history(history, limit: int = JOURNAL_CONVERSATION_LIMIT) -> List[Dict[str, Any]]:
    normalized = [normalize_conversation_entry(entry) for entry in history]
    return normalized[-limit:] if limit else normalized


def _short_name(name: str) -> str:
    return (name or "").split(",")[0].strip()


def build_death_journal_entry(
    player: Any, day_of_death: int, cause: str, last_words: str = "",
    knowledge: Dict[str, Any] | None = None, event_id: str = "",
) -> Dict[str, Any]:
    entry = {
        "character_name": getattr(
            player, "name", getattr(player, "character_name", "Unknown")
        ),
        "day_of_death": day_of_death,
        "cause": cause,
        "last_words": last_words,
        "conversation_history": list(
            getattr(player, "conversation_history", [])
        ),
    }
    if event_id:
        entry["event_id"] = event_id
    if knowledge is not None:
        entry["knowledge"] = dict(knowledge)
    return entry


def apply_death_journal_knowledge(
    player: Any, knowledge: Any, character_name: str = ""
) -> int:
    from collections import deque
    from .constants import CONVERSATION_HISTORY_MAXLEN
    from .rumors import deserialize_observation

    history = getattr(player, "conversation_history", None)
    if history is None:
        history = deque(maxlen=CONVERSATION_HISTORY_MAXLEN)
        player.conversation_history = history
    prefix = f"[from the journal of {character_name}]" if character_name else "[from a death journal]"
    absorbed = 0
    for entry in knowledge.conversations or []:
        tagged = dict(entry)
        text = str(tagged.get("text") or tagged.get("npc_response") or "")
        tagged["text"] = f"{prefix} {text}" if text else prefix
        history.append(tagged)
        absorbed += 1
    intel = getattr(player, "journal_intel", None)
    if intel is None:
        intel = {}
        player.journal_intel = intel
    for npc_id, topics in (knowledge.journal_intel or {}).items():
        existing = intel.setdefault(str(npc_id), {})
        for topic, data in (topics or {}).items():
            if topic not in existing:
                existing[topic] = data
    observations = getattr(player, "rumor_observations", None)
    if observations is None:
        observations = {}
        player.rumor_observations = observations
    for rumor_id, observation_data in (knowledge.rumor_observations or {}).items():
        if rumor_id not in observations:
            observations[str(rumor_id)] = deserialize_observation(observation_data)
    entries = _testimony_entries(player)
    known_ids = {entry.get("id") for entry in entries}
    for entry in getattr(knowledge, "testimonies", []) or []:
        if not isinstance(entry, dict) or not entry.get("id") or entry["id"] in known_ids:
            continue
        entries.append(dict(entry))
        known_ids.add(entry["id"])
    return absorbed


def absorb_death_journal(
    living_history: List[Dict], journal: Dict[str, Any]
) -> int:
    name = journal.get("character_name", "Unknown")
    dead_history = journal.get("conversation_history", [])
    if not dead_history:
        return 0

    prefix = f"[from the journal of {name}]"
    absorbed = []
    for entry in dead_history:
        if isinstance(entry, dict):
            tagged = dict(entry)
            text = tagged.get("text", "")
            tagged["text"] = f"{prefix} {text}" if text else prefix
            absorbed.append(tagged)
        elif isinstance(entry, str):
            absorbed.append({"text": f"{prefix} {entry}"})
        else:
            absorbed.append(entry)

    living_history.extend(absorbed)
    return len(absorbed)


def collect_recent_events(event_log, game_time: GameTime, hours: int = 24) -> List[Dict]:
    current_total = (game_time.day - 1) * 1440 + game_time.minute
    cutoff = current_total - (hours * 60)
    recent = [e for e in event_log if (e["day"] - 1) * 1440 + e.get("minute", 0) >= cutoff]
    return recent[-JOURNAL_EVENT_LIMIT:]


def format_journal(event_log, game_time: GameTime) -> str:
    recent = collect_recent_events(event_log, game_time)
    if not recent:
        return "Day {}. You remember nothing. The hours passed without mark.".format(game_time.day)
    lines = [f"Day {game_time.day}. You remember:"]
    for event in recent:
        lines.append(f"- {event['text']}")
    return "\n".join(lines)


def project_journal_intel(
    journal_intel: Dict[str, Dict[str, Any]],
    npc_lookup: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    from .npc import display_topic_label
    rows = []
    for npc_id, topics in (journal_intel or {}).items():
        if not isinstance(topics, dict):
            continue
        for topic in sorted(topics):
            topic_data = topics[topic]
            npc_name = topic_data.get("npc_name", npc_id) if isinstance(topic_data, dict) else npc_id
            rows.append({
                "npc_id": npc_id,
                "npc_name": npc_name,
                "label": display_topic_label((npc_lookup or {}).get(npc_id), topic),
            })
    return rows


def format_journal_summary(
    event_log,
    game_time: GameTime,
    conversations: List[Dict[str, Any]],
    journal_intel: Dict[str, Dict[str, Any]],
    active_missions: List[Dict[str, Any]],
    mission_manager: Any = None,
    npc_lookup: Dict[str, Any] | None = None,
) -> str:
    lines = [f"--- Journal Entry, {time_str(game_time)} ---", format_journal(event_log, game_time)]

    if active_missions:
        lines.append("\n\n=== Active Missions ===")
        for active in active_missions:
            mission_id = active.get("mission_id", "")
            mission = getattr(mission_manager, "missions", {}).get(mission_id) if mission_manager else None
            if not mission:
                continue
            progress_lines = []
            for progress in active.get("objectives_progress", []):
                current = progress.get("current", 0)
                count = progress.get("count", 0)
                status = "DONE" if current >= count else f"{current}/{count}"
                progress_lines.append(
                    f"  {progress.get('type', '')} {progress.get('target', '')}: {status}"
                )
            lines.append(f"[{mission_id}] {mission.title}")
            lines.extend(progress_lines)

    if conversations:
        lines.append("\n\n=== Recent Conversations ===")
        for conversation in conversations:
            npc_id = conversation.get("npc_id", "")
            if npc_id == "_rumor":
                character_name = "street talk"
            else:
                npc = (npc_lookup or {}).get(npc_id)
                character_name = _short_name(getattr(npc, "name", "")) if npc else npc_id or "?"
            response = conversation.get("npc_response", "")
            lines.append(
                f'Day {conversation.get("day", "?")}, {character_name}: "{response[:140]}"'
            )

    if journal_intel:
        intel_lines = ["\n--- Discovered Intel ---"]
        grouped = {}
        for row in project_journal_intel(journal_intel, npc_lookup=npc_lookup):
            grouped.setdefault(row["npc_name"], []).append(row["label"])
        for npc_name, labels in grouped.items():
            intel_lines.append(f"  From {npc_name}: {', '.join(labels)}")
        lines.append("\n".join(intel_lines))

    return "\n".join(lines)


def format_life_retrospective(event_log, player_name: str) -> str:
    log_list = list(event_log)
    entries = log_list[-100:]
    if not entries:
        return f"{player_name} lived and died in occupied Shanghai. The city endures, and so does their memory."
    lines = [f"The life of {player_name}, in brief:"]
    for e in entries[-30:]:
        lines.append(f"- {e['text']}")
    return "\n".join(lines)
