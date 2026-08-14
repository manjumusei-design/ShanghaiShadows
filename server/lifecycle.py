import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from .save_manager import save_player

LIVING = "living"
DEAD = "dead"
UNAVAILABLE = "unavailable"
SLOT_STATUSES = (LIVING, DEAD, UNAVAILABLE)


@dataclass(frozen=True)
class DeathJournalKnowledge:
    conversations: List[Dict[str, Any]] = field(default_factory=list)
    journal_intel: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    rumor_observations: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class DeathEvent:
    event_id: str
    slot_id: str
    account_username: str
    save_key: str
    character_name: str
    day: int
    cause: str
    last_words: str
    room_id: str
    inherited: List[Dict[str, Any]]
    knowledge: DeathJournalKnowledge
    predecessor: Dict[str, Any]
    created_at: str


def death_journal_knowledge_from_player(player) -> DeathJournalKnowledge:
    from .journal import normalize_conversation_history
    from .rumors import serialize_observation

    observations = {}
    for rumor_id, observation in sorted((getattr(player, "rumor_observations", {}) or {}).items()):
        observations[rumor_id] = serialize_observation(observation)
    return DeathJournalKnowledge(
        conversations=normalize_conversation_history(
            list(getattr(player, "conversation_history", []) or [])
        ),
        journal_intel={
            str(npc_id): dict(topics)
            for npc_id, topics in (getattr(player, "journal_intel", {}) or {}).items()
        },
        rumor_observations=observations,
    )


def death_journal_knowledge_to_dict(knowledge: DeathJournalKnowledge) -> Dict[str, Any]:
    return {
        "conversations": [dict(entry) for entry in knowledge.conversations],
        "journal_intel": {
            str(npc_id): dict(topics)
            for npc_id, topics in knowledge.journal_intel.items()
        },
        "rumor_observations": {
            str(rumor_id): dict(observation)
            for rumor_id, observation in knowledge.rumor_observations.items()
        },
    }


def death_journal_knowledge_from_dict(data: Dict[str, Any]) -> DeathJournalKnowledge:
    return DeathJournalKnowledge(
        conversations=[dict(entry) for entry in data.get("conversations", []) or []],
        journal_intel={
            str(npc_id): dict(topics)
            for npc_id, topics in (data.get("journal_intel", {}) or {}).items()
        },
        rumor_observations={
            str(rumor_id): dict(observation)
            for rumor_id, observation in (data.get("rumor_observations", {}).items())
        },
    )


def build_death_event(
    session,
    *,
    day: int,
    cause: str,
    last_words: str,
    room_id: str,
    inherited: List[Dict[str, Any]],
    predecessor: Dict[str, Any],
    event_id: Optional[str] = None,
    created_at: Optional[str] = None,
) -> DeathEvent:
    import time

    player = session.player
    return DeathEvent(
        event_id=event_id or f"death_{uuid.uuid4().hex}",
        slot_id=player.character_slot_id,
        account_username=(player.account_username or player.username).strip().lower(),
        save_key=player.save_key,
        character_name=getattr(player, "name", "Unknown"),
        day=day,
        cause=cause,
        last_words=last_words,
        room_id=room_id,
        inherited=[dict(item) for item in inherited],
        knowledge=death_journal_knowledge_from_player(player),
        predecessor=dict(predecessor),
        created_at=created_at or time.strftime("%Y-%m-%dT%H:%M:%S"),
    )


def death_event_to_dict(event: DeathEvent) -> Dict[str, Any]:
    return {
        "event_id": event.event_id,
        "slot_id": event.slot_id,
        "account_username": event.account_username,
        "save_key": event.save_key,
        "character_name": event.character_name,
        "day": event.day,
        "cause": event.cause,
        "last_words": event.last_words,
        "room_id": event.room_id,
        "inherited": [dict(item) for item in event.inherited],
        "knowledge": death_journal_knowledge_to_dict(event.knowledge),
        "predecessor": dict(event.predecessor),
        "created_at": event.created_at,
    }


def death_event_from_dict(data: Dict[str, Any]) -> DeathEvent:
    return DeathEvent(
        event_id=data["event_id"],
        slot_id=data["slot_id"],
        account_username=data["account_username"],
        save_key=data["save_key"],
        character_name=data.get("character_name", "Unknown"),
        day=int(data.get("day", 0)),
        cause=data.get("cause", ""),
        last_words=data.get("last_words", ""),
        room_id=data.get("room_id", ""),
        inherited=[dict(item) for item in data.get("inherited", []) or []],
        knowledge=death_journal_knowledge_from_dict(data.get("knowledge", {}) or {}),
        predecessor=dict(data.get("predecessor", {}) or {}),
        created_at=data.get("created_at", ""),
    )


def archive_player_death(session, event: DeathEvent) -> str:
    from .auth import _get_db
    db = _get_db()
    existing = db.get_lifecycle_event(event.event_id)
    if existing is not None:
        return event.event_id
    save_key = authorized_session_save_key(session)
    if not save_key or save_key != event.save_key:
        raise ValueError("unauthorized death archive")
    player = session.player
    account_username = (player.account_username or session.username).strip().lower()
    if event.slot_id != session.slot_id or event.account_username != account_username:
        raise ValueError("unauthorized death archive")
    payload = death_event_to_dict(event)
    archived = db.archive_death_transaction({
        "event_id": event.event_id,
        "event_type": "gameplay_death",
        "payload": payload,
        "slot_id": event.slot_id,
        "account_username": event.account_username,
        "save_key": event.save_key,
        "predecessor": event.predecessor,
        "inherited": event.inherited,
        "created_at": event.created_at,
    })
    if not archived:
        raise ValueError("death archive rejected: slot is not living or account is missing")
    return event.event_id


def replay_death_projection(shared, event: DeathEvent) -> None:
    from .auth import _get_db
    room_journals = getattr(shared, "death_journals", None)
    if room_journals is None:
        room_journals = {}
        shared.death_journals = room_journals
    existing = room_journals.get(event.room_id, [])
    if any(entry.get("event_id") == event.event_id for entry in existing):
        _get_db().mark_lifecycle_event_projected(event.event_id)
        return
    from .journal import build_death_journal_entry
    entry = build_death_journal_entry(
        event,
        event.day,
        event.cause,
        event.last_words,
        knowledge=death_journal_knowledge_to_dict(event.knowledge),
        event_id=event.event_id,
    )
    room_journals.setdefault(event.room_id, []).append(entry)
    _get_db().mark_lifecycle_event_projected(event.event_id)


def replay_lifecycle_outbox(shared) -> int:
    from .auth import _get_db
    projected = 0
    for row in _get_db().list_unprojected_lifecycle_events():
        if row["event_type"] != "gameplay_death":
            _get_db().mark_lifecycle_event_projected(row["event_id"])
            continue
        event = death_event_from_dict(json.loads(row["payload_json"]))
        replay_death_projection(shared, event)
        projected += 1
    return projected


def claim_death_journal(session, shared, event_id: str) -> Optional[Dict[str, Any]]:
    save_key = authorized_session_save_key(session)
    if not save_key:
        return None
    from .auth import _get_db
    db = _get_db()
    event_row = db.get_lifecycle_event(event_id)
    if event_row is None or event_row["event_type"] != "gameplay_death":
        return None
    event = death_event_from_dict(json.loads(event_row["payload_json"]))
    room_journals = getattr(shared, "death_journals", {}) or {}
    if not any(
        entry.get("event_id") == event_id
        for entries in room_journals.values()
        for entry in entries
    ):
        return None
    claimant_slot_id = session.slot_id
    if not claimant_slot_id:
        return None
    knowledge_json = json.dumps(death_journal_knowledge_to_dict(event.knowledge))
    claim = db.get_death_journal_claim(event_id)
    if claim is None:
        if not db.insert_death_journal_claim(event_id, claimant_slot_id, knowledge_json, event.created_at):
            return None
        claim = db.get_death_journal_claim(event_id)
        if claim is  None or claim["claimant_slot_id"] != claimant_slot_id:
            return None
    elif claim["claimant_slot_id"] != claimant_slot_id:
        return None
    absorbed_ids = getattr(session.player, "absorbed_death_journal_event_ids", None)
    if absorbed_ids is None:
        absorbed_ids = []
        session.player.absorbed_death_journal_ids = absorbed_ids
    if event_id in absorbed_ids:
        if save_authorized_session(session):
            db.set_death_journal_claim_status(event_id, "applied")
        return death_journal_knowledge_from_dict(json.loads(claim["knowledge_json"])).__dict__
    knowledge = death_journal_knowledge_from_dict(json.loads(claim["knowledge_json"]))
    from .journal import apply_death_journal_knowledge
    apply_death_journal_knowledge(session.player, knowledge, character_name=event.character_name)
    absorbed_ids.append(event_id)
    if not save_authorized_session(session):
        return None
    db.set_death_journal_claim_status(event_id, "applied")
    return death_journal_knowledge_to_dict(knowledge)


def _stash_payload_granted(payload: dict, inventory_payloads: list) -> bool:
    if payload in inventory_payloads:
        return True
    if payload.get("instance_id"):
        return False
    for entry in inventory_payloads:
        if entry.get("id") == payload.get("id") and (not entry.get("instance_id") or entry.get("instance_id") == payload.get("id")):
            return True
    return False


def _recover_pending_stash_transfers(session, db, account_username: str, stash: list) -> None:
    from .serialization import deserialize_item, serialize_item
    rows = db.list_stash_transfers(account_username, slot_id=session.slot_id)
    if not rows:
        return
    inventory_payloads = [serialize_item(item) for item in session.player.inventory]
    appended = []
    for row in rows:
        for payload in [dict(entry) for entry in json.loads(row["items_json"])]:
            if _stash_payload_granted(payload, inventory_payloads):
                continue
            item = deserialize_item(payload)
            session.player.inventory.append(item)
            appended.append(item)
            inventory_payloads.append(payload)
    if appended and not save_authorized_session(session):
        for item in appended:
            session.player.inventory.remove(item)
        raise ValueError("stash recovery failed")
    touched = False
    for row in rows:
        for payload in [dict(entry) for entry in json.loads(row["items_json"])]:
            index = next((i for i, entry in enumerate(stash) if entry == payload), None)
            if index is not None:
                stash.pop(index)
                touched = True
    if touched:
        try:
            db.set_stash(account_username, stash)
        except Exception:
            raise ValueError("stash recovery failed")
    for row in rows:
        db.delete_stash_transfer(row["transfer_id"])


def retrieve_successor_stash(session, room_id: str, *, limit: Optional[int] = None) -> tuple:
    save_key = authorized_session_save_key(session)
    if not save_key:
        raise ValueError("unauthorized stash retrieval")
    from .auth import _get_db, get_account, resolve_spawn_room
    from .serialization import deserialize_item
    account_username = (session.player.account_username or session.username).strip().lower()
    if get_account(account_username) is None:
        raise ValueError("unauthorized stash retrieval")
    if resolve_spawn_room(account_username) != room_id:
        raise ValueError("stash retrieval requires the account safehouse")
    import hashlib
    import time
    db = _get_db()
    stash = db.get_stash(account_username)
    _recover_pending_stash_transfers(session, db, account_username, stash)
    capacity = limit if limit is not None else max(0, getattr(session.player, "max_inventory", 12) - len(session.player.inventory))
    taken = stash[:capacity]
    remaining = stash[capacity:]
    if not taken:
        return [], remaining
    items_json = json.dumps(taken)
    transfer_id = f"stash_{hashlib.md5((account_username + ":" + session.slot_id + ":" + items_json).encode("utf-8")).hexdigest()[:16]}"
    db.insert_stash_transfer(transfer_id, account_username, session.slot_id, items_json, time.strftime("%Y-%m-%dT%H:%M:%S"))
    appended = []
    try:
        for data in taken:
            item = deserialize_item(data)
            session.player.inventory.append(item)
            appended.append(item)
    except Exception:
        for item in appended:
            session.player.inventory.remove(item)
        db.delete_stash_transfer(transfer_id)
        raise ValueError("stash retrieval failed")
    if not save_authorized_session(session):
        for item in appended:
            session.player.inventory.remove(item)
        db.delete_stash_transfer(transfer_id)
        raise ValueError("stash retrieval failed")
    try:
        db.set_stash(account_username, remaining)
    except Exception:
        raise ValueError("stash retrieval failed")
    db.delete_stash_transfer(transfer_id)
    return appended, remaining


@dataclass(frozen=True)
class CharacterSlot:
    slot_id: str
    account_username: str
    slot_number: int
    display_name: str
    status: Literal["living", "dead", "unavailable"]
    save_key: str
    unavailable_reason: str = ""


class CharacterSlotRepository:
    def __init__(self, account_db):
        self.account_db = account_db

    def list(self, account_username: str):
        return self.account_db.list_character_slots(account_username)

    def lookup(self, account_username: str, slot_number: int):
        return self.account_db.get_character_slot(account_username, slot_number)

    def living(self, account_username: str):
        return self.account_db.get_living_character_slot(account_username)

    def create(self, account_username: str, display_name: str, status: str = LIVING, unavailable_reason: str = ""):
        return self.account_db.create_character_slot(account_username, display_name, status, unavailable_reason)

    def rename(self, account_username: str, slot_number: int, display_name: str):
        return self.account_db.rename_character_slot(account_username, slot_number, display_name)

    def transition(self, account_username: str, slot_number: int, status: str, unavailable_reason: str = ""):
        return self.account_db.set_character_slot_status(account_username, slot_number, status, unavailable_reason)

