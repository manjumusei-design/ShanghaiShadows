import asyncio
import hashlib
import json
import random
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Dict, List, Literal, Optional

import yaml

from .constants import RUMOR_WINDOW, RUMOR_STEP, RUMORS_PATH
from .dataclass_utils import filter_to_dataclass
from .content_validation import load_strict_yaml


class _ImmutableList(list):
    def _deny(self, *args, **kwargs):
        raise TypeError("rumor collections are immutable")

    append = _deny
    extend = _deny
    insert = _deny
    remove = _deny
    pop = _deny
    clear = _deny
    sort = _deny
    reverse = _deny
    __setitem__ = _deny
    __delitem__ = _deny
    __iadd__ = _deny
    __imul__ = _deny


@dataclass(frozen=True)
class RumorRecord:
    id: str
    text: str
    kind: Literal["authored", "dynamic", "tracked", "witnessed", "spun"] = "dynamic"
    category: str = "street_talk"
    source_npc_id: str = ""
    source_location_id: str = ""
    origin_faction: str = ""
    current_faction: str = ""
    districts: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    truth_value: float = 0.8
    created_day: int = 1
    parent_id: str = ""
    witness_npc_ids: List[str] = field(default_factory=list)
    hop_count: int = 0

    def __post_init__(self):
        object.__setattr__(self, "districts", _ImmutableList(self.districts or []))
        object.__setattr__(self, "tags", _ImmutableList(self.tags or []))
        object.__setattr__(self, "witness_npc_ids", _ImmutableList(self.witness_npc_ids or []))
        object.__setattr__(self, "truth_value", _clamp_truth(self.truth_value))


@dataclass
class RumorObservation:
    rumor_id: str
    holder_npc_id: str = ""
    learned_day: int = 1
    source_chain: List[str] = field(default_factory=list)


@dataclass
class TrackedRumor:
    id: str
    text: str
    origin_faction: str = ""
    current_faction: str = ""
    source_npc: str = ""
    hop_count: int = 0
    day_created: int = 1

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "origin_faction": self.origin_faction,
            "current_faction": self.current_faction,
            "source_npc": self.source_npc,
            "hop_count": self.hop_count,
            "day_created": self.day_created,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TrackedRumor":
        return cls(
            id=data.get("id", ""),
            text=data.get("text", ""),
            origin_faction=data.get("origin_faction", ""),
            current_faction=data.get("current_faction", ""),
            source_npc=data.get("source_npc", ""),
            hop_count=int(data.get("hop_count", 0) or 0),
            day_created=int(data.get("day_created", 1) or 1),
        )


@dataclass
class RumourSeed:
    id: str
    event_type: str
    location: str
    district: str = ""
    witnesses: List[str] = field(default_factory=list)
    faction_context: str = ""
    day_created: int = 1
    description: str = ""
    resolved: bool = False
    seed_rumor_ids: List[str] = field(default_factory=list)


_catalog: Dict[str, RumorRecord] = {}


def load_rumors(path: str, refresh: bool = False) -> Dict[str, RumorRecord]:
    if _catalog and not refresh:
        return _catalog
    _catalog.clear()
    data = load_strict_yaml(path) or {}
    for row in data.get("rumors", []):
        record = RumorRecord(**filter_to_dataclass(row, RumorRecord, warn_unknown=True))
        _catalog[record.id] = record
    return _catalog


def compute_active_rumors(catalog: Dict[str, RumorRecord], day: int, window: int = RUMOR_WINDOW, step: int = RUMOR_STEP) -> List[str]:
    ids = sorted(catalog.keys())
    if not ids:
        return []
    n = len(ids)
    start = (day * step) % n
    return [ids[(start + i) % n] for i in range(min(window, n))]


def seed_active_rumors(day: int) -> List[str]:
    try:
        return compute_active_rumors(load_rumors(RUMORS_PATH), day)
    except FileNotFoundError:
        return []


def serialize_record(record: RumorRecord) -> dict:
    return {
        "id": record.id,
        "text": record.text,
        "kind": record.kind,
        "category": record.category,
        "source_npc_id": record.source_npc_id,
        "source_location_id": record.source_location_id,
        "origin_faction": record.origin_faction,
        "current_faction": record.current_faction,
        "districts": list(record.districts),
        "tags": list(record.tags),
        "truth_value": record.truth_value,
        "created_day": record.created_day,
        "parent_id": record.parent_id,
        "witness_npc_ids": list(record.witness_npc_ids),
        "hop_count": record.hop_count,
    }


def deserialize_record(data: dict) -> RumorRecord:
    return RumorRecord(
        id=str(data.get("id", "")),
        text=str(data.get("text", "")),
        kind=str(data.get("kind", "dynamic")),
        category=str(data.get("category", "street_talk")),
        source_npc_id=str(data.get("source_npc_id", "")),
        source_location_id=str(data.get("source_location_id", "")),
        origin_faction=str(data.get("origin_faction", "")),
        current_faction=str(data.get("current_faction", "")),
        districts=_as_string_list(data.get("districts")),
        tags=_as_string_list(data.get("tags")),
        truth_value=_clamp_truth(_as_float(data.get("truth_value"), 0.8)),
        created_day=_as_int(data.get("created_day"), 1),
        parent_id=str(data.get("parent_id", "")),
        witness_npc_ids=_as_string_list(data.get("witness_npc_ids")),
        hop_count=_as_int(data.get("hop_count"), 0),
    )


def serialize_observation(observation: RumorObservation) -> dict:
    return {
        "rumor_id": observation.rumor_id,
        "holder_npc_id": observation.holder_npc_id,
        "learned_day": observation.learned_day,
        "source_chain": list(observation.source_chain),
    }


def deserialize_observation(data: dict) -> RumorObservation:
    return RumorObservation(
        rumor_id=str(data.get("rumor_id", "")),
        holder_npc_id=str(data.get("holder_npc_id", "")),
        learned_day=_as_int(data.get("learned_day"), 1),
        source_chain=_as_string_list(data.get("source_chain")),
    )


def publish_rumor_record(shared, record: RumorRecord) -> str:
    if not record.id:
        raise ValueError("record id must not be empty")
    if record.parent_id and record.parent_id not in shared.rumor_records:
        raise ValueError(f"parent record {record.parent_id} is missing")
    stored = RumorRecord(
        id=record.id,
        text=record.text,
        kind=record.kind,
        category=record.category,
        source_npc_id=record.source_npc_id,
        source_location_id=record.source_location_id,
        origin_faction=record.origin_faction,
        current_faction=record.current_faction,
        districts=list(record.districts or []),
        tags=list(record.tags or []),
        truth_value=record.truth_value,
        created_day=record.created_day,
        parent_id=record.parent_id,
        witness_npc_ids=list(record.witness_npc_ids or []),
        hop_count=record.hop_count,
    )
    existing = shared.rumor_records.get(stored.id)
    if existing is not None:
        if existing == stored:
            return stored.id
        raise ValueError(f"record {stored.id} already exists with different content")
    shared.rumor_records[stored.id] = stored
    return stored.id


def grant_observation(owner, rumor_id: str, holder_npc_id: str, learned_day: int, source_chain: List[str]) -> bool:
    observations = getattr(owner, "rumor_observations", None)
    if observations is None:
        observations = {}
        owner.rumor_observations = observations
    if rumor_id in observations:
        return False
    observations[rumor_id] = RumorObservation(
        rumor_id=rumor_id,
        holder_npc_id=holder_npc_id,
        learned_day=int(learned_day or 1),
        source_chain=list(source_chain or []),
    )
    return True


def grant_npc_observation(shared, npc_id: str, rumor_id: str, learned_day: int, source_chain: List[str]) -> bool:
    npc = shared.world.npcs.get(npc_id)
    if npc is None:
        return False
    return grant_observation(npc, rumor_id, npc_id, learned_day, source_chain)


def normalize_record_map(records: Dict[str, RumorRecord]) -> Dict[str, RumorRecord]:
    normalized = {}
    for map_key in sorted(records):
        record = records[map_key]
        if not record.id:
            record = replace(record, id=map_key)
        existing = normalized.get(record.id)
        if existing is not None and existing != record:
            raise ValueError(f"conflicting records normalize under id {record.id}")
        normalized[record.id] = record
    return normalized


def normalize_observation_map(observations: Dict[str, RumorObservation]) -> Dict[str, RumorObservation]:
    normalized = {}
    for map_key in sorted(observations):
        observation = observations[map_key]
        if not observation.rumor_id:
            observation.rumor_id = map_key
        existing = normalized.get(observation.rumor_id)
        if existing is not None and existing != observation:
            raise ValueError(f"conflicting observations normalize under id {observation.rumor_id}")
        normalized[observation.rumor_id] = observation
    return normalized


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_string_list(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _clamp_truth(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _text_record_id(text: str) -> str:
    return f"migrated_{hashlib.md5(_normalize_text(text).encode('utf-8')).hexdigest()[:12]}"


def _owner_text_record_id(owner: str, text: str) -> str:
    raw = f"{owner}:{_normalize_text(text)}"
    return f"migrated_{hashlib.md5(raw.encode('utf-8')).hexdigest()[:12]}"


def _publish_migrated(shared, record: RumorRecord, suffix: str = "") -> str:
    try:
        return publish_rumor_record(shared, record)
    except ValueError:
        if not suffix:
            raise
        return publish_rumor_record(shared, replace(record, id=f"{record.id}:{suffix}"))


def _event_record_id(event_type: str, location: str, district: str, day: int, occurrence: str, text: str) -> str:
    raw = f"{event_type}:{location}:{district}:{day}:{occurrence}:{_normalize_text(text)}"
    return f"evt_{hashlib.md5(raw.encode('utf-8')).hexdigest()[:12]}"


def _hop_id(source_record_id: str, target_npc_id: str, game_day: int) -> str:
    raw = f"{source_record_id}:{target_npc_id}:{game_day}"
    return f"hop_{hashlib.md5(raw.encode('utf-8')).hexdigest()[:12]}"


def gossip_density_chance(npc_count: int) -> float:
    if npc_count < 2:
        return 0.0
    return {2: 0.15, 3: 0.25, 4: 0.35}.get(npc_count, 0.45)


def process_gossip_room(shared, room, *, game_day: Optional[int] = None) -> bool:
    from .trust import exchange_gossip

    npc_ids = list(getattr(room, "npcs", []) or [])
    if len(npc_ids) < 2:
        return False
    day = int(game_day if game_day is not None else shared.game_time.day)
    chance = gossip_density_chance(len(npc_ids))
    if random.random() >= chance:
        return False
    exchanged = False
    observed_action = any(
        "observed player action:" in memory.lower()
        for npc_id in npc_ids
        for memory in getattr(shared.world.npcs.get(npc_id), "memory", [])
    )
    for left_id, right_id in zip(npc_ids, npc_ids[1:]):
        left = shared.world.npcs.get(left_id)
        right = shared.world.npcs.get(right_id)
        if not left or not right:
            continue
        if not exchange_gossip(
            left.memory,
            right.memory,
            chance=1.0,
            game_day=day,
            npc_a=left,
            npc_b=right,
            shared=shared,
        ):
            continue
        exchanged = True
    if exchanged and observed_action:
        for npc_id in npc_ids:
            npc = shared.world.npcs.get(npc_id)
            if npc:
                npc.suspicion = min(100, npc.suspicion + 5)
    return exchanged


def publish_wanted_rumor(shared, player, wanted_level: int, game_day: int) -> str:
    owner = ":".join(
        str(value)
        for value in (
            getattr(player, "username", ""),
            getattr(player, "character_slot_id", ""),
            getattr(player, "save_key", ""),
            getattr(player, "name", ""),
        )
        if value
    ) or "player"
    previous_id = str(getattr(player, "wanted_rumor_id", "") or "")
    if previous_id and previous_id in shared.rumor_records:
        raw = f"{owner}:{previous_id}:{int(wanted_level)}"
        record_id = f"wanted_{hashlib.md5(raw.encode('utf-8')).hexdigest()[:12]}"
        parent_id = previous_id
    else:
        raw = f"{owner}:{int(wanted_level)}"
        record_id = f"wanted_{hashlib.md5(raw.encode('utf-8')).hexdigest()[:12]}"
        parent_id = ""
    record = RumorRecord(
        id=record_id,
        text=f"The Kempeitai are asking after someone whose wanted level has reached {int(wanted_level)}.",
        kind="dynamic",
        category="notoriety",
        origin_faction="kempeitai",
        current_faction="kempeitai",
        tags=["wanted", "notoriety"],
        truth_value=1.0,
        created_day=int(game_day),
        parent_id=parent_id,
    )
    publish_rumor_record(shared, record)
    grant_observation(player, record_id, "", int(game_day), _source_chain(shared, record_id))
    player.wanted_rumor_id = record_id
    return record_id


def _rumor_seed(rumor_id: str, game_day: int, hop_count: int) -> int:
    raw = f"{rumor_id}:{game_day}:{hop_count}"
    return int(hashlib.md5(raw.encode()).hexdigest()[:8], 16)


def _personality_distortion_modifier(personality: str) -> float:
    p = personality.lower()
    honest_keywords = ["honest", "pious", "devout", "loyal", "dependable",
                       "discreet", "meticulous", "disciplined", "measured"]
    corrupt_keywords = ["corrupt", "greedy", "slick", "charming", "calculating",
                        "ruthless", "cunning", "scheming", "amused"]
    honest_count = sum(1 for kw in honest_keywords if kw in p)
    corrupt_count = sum(1 for kw in corrupt_keywords if kw in p)
    if honest_count > corrupt_count:
        return 0.5
    elif corrupt_count > honest_count:
        return 1.5
    return 1.0


def _distort_text(text: str, current_faction: str, game_day: int, record_id: str, hop_count: int, personality: str = "") -> tuple:
    ALL_FACTIONS = ["ccp", "gmd", "kempeitai", "green_gang", "civilian"]
    if hop_count >= 5:
        garbled = [
            "Something happened... but the details are lost in the telling.",
            "There was some kind of incident, or so they say. Maybe.",
            "I heard something, but honestly I can't remember what anymore.",
            "A story's going around, though nobody seems to agree on the details.",
            "People are talking about... something. I've lost track of what.",
        ]
        rng_garble = random.Random(_rumor_seed(record_id, game_day, hop_count))
        return rng_garble.choice(garbled), current_faction

    rng = random.Random(_rumor_seed(record_id, game_day, hop_count))
    modifier = _personality_distortion_modifier(personality) if personality else 1.0

    new_text = text
    new_faction = current_faction

    if rng.random() < 0.30 * modifier:
        other_factions = [f for f in ALL_FACTIONS if f != new_faction]
        if other_factions:
            new_faction = rng.choice(other_factions)

    if rng.random() < 0.20 * modifier:
        exaggerations = [
            "Word is", "Rumor has it", "People are saying",
            "It's been whispered that", "They say",
        ]
        prefix = rng.choice(exaggerations)
        if not any(new_text.startswith(p) for p in exaggerations):
            new_text = f"{prefix} {new_text[0].lower()}{new_text[1:]}"

    if rng.random() < 0.10 * modifier:
        inversions = [
            ("killed", "was seen alive after supposedly being"),
            ("dead", "reportedly still alive, despite claims of being"),
            ("stolen", "returned, contrary to claims it was"),
            ("missing", "found, despite reports of being"),
            ("caught", "apparently never"),
            ("dangerous", "harmless, despite talk of being"),
            ("suspicious", "perfectly ordinary, despite claims of being"),
        ]
        for old, new in inversions:
            if old in new_text.lower():
                new_text = new_text.replace(old, new, 1)
                break
        else:
            new_text = f"Contrary to rumor, {new_text[0].lower()}{new_text[1:]}"

    return new_text, new_faction


def _source_chain(shared, record_id: str) -> List[str]:
    chain: List[str] = []
    seen = set()
    current_id = record_id
    for _ in range(32):
        if not current_id or current_id in seen:
            break
        seen.add(current_id)
        record = shared.rumor_records.get(current_id)
        if record is None:
            break
        chain.append(current_id)
        if not record.parent_id:
            break
        current_id = record.parent_id
    return list(reversed(chain))


def _find_record_by_text(records: Dict[str, RumorRecord], text: str) -> Optional[str]:
    normalized = _normalize_text(text)
    for record_id, record in records.items():
        if _normalize_text(record.text) == normalized:
            return record_id
    return None


def propagate_rumor_hop(shared, source_record_id: str, source_npc_id: str, target_npc_id: str, game_day: int, personality: str = "") -> Optional[str]:
    source = shared.rumor_records.get(source_record_id)
    if source is None:
        return None
    child_id = _hop_id(source_record_id, target_npc_id, game_day)
    existing = shared.rumor_records.get(child_id)
    if existing is not None:
        grant_npc_observation(shared, target_npc_id, child_id, game_day, _source_chain(shared, child_id))
        return child_id
    text, current_faction = _distort_text(
        source.text,
        source.current_faction or source.origin_faction,
        game_day,
        source.id,
        source.hop_count,
        personality,
    )
    target_npc = shared.world.npcs.get(target_npc_id)
    if target_npc is not None and current_faction and target_npc.faction and current_faction != target_npc.faction:
        text = apply_faction_spin(text, target_npc.faction)
        current_faction = target_npc.faction
    child = RumorRecord(
        id=child_id,
        text=text,
        kind="spun",
        category=source.category,
        source_npc_id=source_npc_id or source.source_npc_id,
        source_location_id=source.source_location_id,
        origin_faction=source.origin_faction,
        current_faction=current_faction,
        districts=list(source.districts),
        tags=list(source.tags),
        truth_value=source.truth_value,
        created_day=game_day,
        parent_id=source.id,
        witness_npc_ids=[],
        hop_count=source.hop_count + 1,
    )
    publish_rumor_record(shared, child)
    grant_npc_observation(shared, target_npc_id, child_id, game_day, _source_chain(shared, child_id))
    return child_id


def gossip_hop_for_memory(shared, source_npc, target_npc, memory_text: str, game_day: int, personality: str = "") -> Optional[str]:
    held_ids = sorted(getattr(source_npc, "rumor_observations", {}) or {})
    normalized = _normalize_text(memory_text)
    for record_id in held_ids:
        record = shared.rumor_records.get(record_id)
        if record is None:
            continue
        if _normalize_text(record.text) == normalized:
            return propagate_rumor_hop(
                shared,
                record_id,
                source_npc.id,
                target_npc.id,
                game_day,
                personality=personality,
            )
    return None


def apply_faction_spin(rumor_text: str, faction: str) -> str:
    spins = {
        "ccp": _spin_ccp,
        "gmd": _spin_gmd,
        "kempeitai": _spin_kempeitai,
        "civilian": _spin_civilian,
        "green_gang": _spin_green_gang,
    }
    spinner = spins.get(faction, lambda t: t)
    return spinner(rumor_text)


def _spin_ccp(text: str) -> str:
    replacements = {
        "Kempeitai": "fascist forces",
        "kempeitai": "fascist forces",
        "Japanese": "imperialist aggressors",
        "japanese": "imperialist aggressors",
        "arrested": "detained by occupation authorities",
        "raided": "struck by occupation forces",
        "resistance": "the people's defense",
        "Resistance": "the People's Defense",
    }
    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)
    if result == text:
        result = "Word from the underground says: " + text[0].lower() + text[1:]
    return result


def _spin_gmd(text: str) -> str:
    replacements = {
        "Kempeitai": "military administration forces",
        "kempeitai": "military administration forces",
        "arrested": "taken in for official processing",
        "raided": "subjected to an authorized inspection",
        "resistance": "unsanctioned elements",
        "Resistance": "Unsantioned elements",
    }
    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)
    if result == text:
        result = "Official channels report that " + text[0].lower() + text[1:]
    return result


def _spin_kempeitai(text: str) -> str:
    replacements = {
        "resistance": "terrorist elements",
        "Resistance": "Terrorist elements",
        "rescued": "assaulted a facility and liberated",
        "fought": "engaged in subversive activities",
        "attacked": "conducted an act of terror against",
        "Ambush": "Terrorist attack",
        "ambush": "terrorist attack",
        "Kempeitai": "security forces",
        "kempeitai": "security forces",
    }
    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)
    if result == text:
        result = "Standard procedure continues: " + text[0].lower() + text[1:]
    return result


def _spin_civilian(text: str) -> str:
    political_terms = [
        "fascist forces", "imperialist aggressors", "occupation authorities",
        "liberation", "resistance", "the cause", "patriotic",
        "terrorist elements", "subversive", "criminal insurgents",
        "military administration", "authorized operation",
    ]
    result = text
    for term in political_terms:
        result = result.replace(term, "they")
        result = result.replace(term.capitalize(), "They")

    if result != text:
        result = "I try to stay out of it, but from what I heard: " + result[0].lower() + result[1:]
    else:
        result = "Keep your head down, but: " + result[0].lower() + result[1:]
    return result


def _spin_green_gang(text: str) -> str:
    replacements = {
        "arrested": "got themselves collected. That's gonna cost someone",
        "raided": "got hit. Someone didn't pay their dues",
        "killed": "was made an example of. Bad for business",
        "rescued": "was rescued. Someone definetly paid well for that",
    }
    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)
    if result == text:
        result = "There's angles to this: " + text[0].lower() + text[1:]
    return result


def materialize_player_rumor_records(shared, player) -> None:
    pending = dict(getattr(player, "rumor_pending_texts", None) or {})
    if not pending:
        return
    observations = player.rumor_observations
    for rid, text in pending.items():
        existing = _find_record_by_text(shared.rumor_records, text)
        if existing is not None:
            if rid in observations:
                observation = observations.pop(rid)
                observation.rumor_id = existing
                observations.setdefault(existing, observation)
        elif rid in shared.rumor_records:
            observation = observations.get(rid)
            if observation is not None:
                observation.rumor_id = rid
        else:
            learned_day = 1
            if rid in observations:
                learned_day = observations[rid].learned_day
            publish_rumor_record(
                shared,
                RumorRecord(
                    id=rid,
                    text=text,
                    kind="dynamic",
                    created_day=learned_day,
                ),
            )
    player.rumor_pending_texts = {}


def is_record_eligible(shared, player, record_id: str) -> bool:
    if record_id not in shared.rumor_records:
        return False
    if record_id in getattr(player, "rumor_observations", {}):
        return True
    for npc_id in getattr(player, "met_npc_ids", set()):
        npc = shared.world.npcs.get(npc_id)
        if npc is not None and record_id in getattr(npc, "rumor_observations", {}):
            return True
    return False


def _eligible_record_ids(shared, player) -> set:
    record_ids = set(getattr(player, "rumor_observations", {}))
    for npc_id in getattr(player, "met_npc_ids", set()):
        npc = shared.world.npcs.get(npc_id)
        if npc is not None:
            record_ids.update(getattr(npc, "rumor_observations", {}))
    return {
        record_id
        for record_id in record_ids
        if is_record_eligible(shared, player, record_id)
    }


def eligible_records_for_player(shared, player) -> List[RumorRecord]:
    return [
        shared.rumor_records[record_id]
        for record_id in sorted(_eligible_record_ids(shared, player))
    ]


def ask_trace(shared, player, holder_npc_id: str, record_id: str) -> Optional[dict]:
    if record_id not in shared.rumor_records:
        return None
    npc = shared.world.npcs.get(holder_npc_id)
    if npc is None or record_id not in getattr(npc, "rumor_observations", {}):
        return None
    if not is_record_eligible(shared, player, record_id):
        return None
    chain = _source_chain(shared, record_id)
    return {
        "record": serialize_record(shared.rumor_records[record_id]),
        "trace": [serialize_record(shared.rumor_records[rid]) for rid in chain],
        "chain": chain,
    }


def _npc_matches_record(npc, record: RumorRecord, shared) -> bool:
    if record.current_faction and npc.faction == record.current_faction:
        return True
    if record.origin_faction and npc.faction == record.origin_faction:
        return True
    if record.districts:
        room_id = shared.world.npc_locations.get(npc.id)
        room = shared.world.rooms.get(room_id) if room_id else None
        district = getattr(room, "district", "") if room else ""
        if district and district.lower() in [d.lower() for d in record.districts]:
            return True
    return False


def activate_authored_rumors(shared, day: int) -> List[str]:
    catalog = load_rumors(RUMORS_PATH)
    for record in catalog.values():
        publish_rumor_record(shared, record)
    active_ids = compute_active_rumors(catalog, day) if catalog else []
    shared.active_authored_rumor_ids = active_ids
    for record_id in active_ids:
        record = shared.rumor_records.get(record_id)
        if record is None:
            continue
        for npc_id, npc in shared.world.npcs.items():
            if _is_transient_npc_id(npc_id):
                continue
            if _is_tutorial_clone_npc_id(shared, npc_id):
                continue
            if _npc_matches_record(npc, record, shared):
                grant_npc_observation(shared, npc_id, record_id, day, [record_id])
    return active_ids


def _is_transient_npc_id(npc_id: str) -> bool:
    from .patrols import is_transient_patrol_id
    return is_transient_patrol_id(npc_id)


def _is_tutorial_clone_npc_id(shared, npc_id: str) -> bool:
    clone_rosters = getattr(shared, "tutorial_npc_clones", None) or {}
    return any(npc_id in roster for roster in clone_rosters.values())


def reseed_active_rumors(shared, day: int) -> List[str]:
    return activate_authored_rumors(shared, day)


def _legacy_record(rid: str, text: str, *, kind: str, origin_faction: str = "", current_faction: str = "", source: str = "", location: str = "", districts: Optional[List[str]] = None, witnesses: Optional[List[str]] = None, created_day: int = 1, hop_count: int = 0) -> RumorRecord:
    return RumorRecord(
        id=rid,
        text=text,
        kind=kind,
        origin_faction=origin_faction,
        current_faction=current_faction,
        source_npc_id=source,
        source_location_id=location,
        districts=list(districts or []),
        witness_npc_ids=list(witnesses or []),
        created_day=created_day,
        hop_count=hop_count,
    )


def migrate_world_rumors(shared) -> None:
    for faction, texts in dict(getattr(shared, "rumour_mill", {}) or {}).items():
        for index, text in enumerate(texts):
            if not text:
                continue
            rid = _owner_text_record_id(f"mill:{faction}:{index}", text)
            publish_rumor_record(shared, _legacy_record(rid, text, kind="dynamic", origin_faction=faction, current_faction=faction))
    for index, item in enumerate(list(getattr(shared, "tracked_rumors", []) or [])):
        tracked = TrackedRumor.from_dict(item) if isinstance(item, dict) else item
        rid = tracked.id or _owner_text_record_id(f"shared:{index}", tracked.text)
        publish_rumor_record(
            shared,
            _legacy_record(
                rid,
                tracked.text,
                kind="tracked",
                origin_faction=tracked.origin_faction,
                current_faction=tracked.current_faction,
                source=tracked.source_npc,
                created_day=tracked.day_created,
                hop_count=tracked.hop_count,
            ),
        )
    for index, seed in enumerate(list(getattr(shared, "rumour_seeds", []) or [])):
        seed_text = seed.description or f"Event in {seed.district or seed.location}"
        rid = seed.id or _owner_text_record_id(f"seed:{seed.event_type}:{seed.location}:{seed.district}:{index}", seed_text)
        publish_rumor_record(
            shared,
            _legacy_record(
                rid,
                seed_text,
                kind="dynamic",
                origin_faction=seed.faction_context,
                current_faction=seed.faction_context,
                source=seed.witnesses[0] if seed.witnesses else "",
                location=seed.location,
                districts=[seed.district] if seed.district else [],
                witnesses=list(seed.witnesses),
                created_day=seed.day_created,
            ),
        )
    for npc_id, npc in shared.world.npcs.items():
        for index, item in enumerate(list(getattr(npc, "tracked_rumors", []) or [])):
            tracked = TrackedRumor.from_dict(item) if isinstance(item, dict) else item
            rid = tracked.id or _owner_text_record_id(f"{npc_id}:{index}", tracked.text)
            published_id = _publish_migrated(
                shared,
                _legacy_record(
                    rid,
                    tracked.text,
                    kind="tracked",
                    origin_faction=tracked.origin_faction,
                    current_faction=tracked.current_faction,
                    source=tracked.source_npc,
                    created_day=tracked.day_created,
                    hop_count=tracked.hop_count,
                ),
                suffix=npc_id,
            )
            grant_npc_observation(
                shared,
                npc_id,
                published_id,
                tracked.day_created,
                [tracked.source_npc] if tracked.source_npc else [],
            )
        npc.tracked_rumors = []
    if not shared.active_authored_rumor_ids:
        legacy_active = list(getattr(shared, "active_rumors", []) or [])
        if legacy_active:
            catalog = load_rumors(RUMORS_PATH)
            shared.active_authored_rumor_ids = [
                rid for rid in legacy_active if rid in catalog or rid in shared.rumor_records
            ]
        if not shared.active_authored_rumor_ids:
            activate_authored_rumors(shared, shared.game_time.day)
    current_day = getattr(getattr(shared, "game_time", None), "day", 1)
    for consequence_id in sorted(getattr(shared, "social_consequences", {}) or {}):
        record = shared.social_consequences[consequence_id]
        retained = record.get("rumor_record_id")
        if retained and retained in shared.rumor_records:
            continue
        if record.get("state") != "active":
            continue
        if record.get("visibility", "local") == "hidden":
            continue
        rumour = record.get("rumour")
        if not rumour:
            continue
        created_at = record.get("created_at")
        created_day = (int(created_at) // 1440) + 1 if created_at is not None else current_day
        backfilled_id = publish_event_rumor(
            shared,
            event_type=f"consequence_{consequence_id}",
            text=rumour,
            location=str(record.get("room_id", "") or ""),
            district=str(record.get("district_id", "") or ""),
            witnesses=[],
            faction_context="",
            created_day=created_day,
            category=str(record.get("category", "street_talk") or "street_talk"),
        )
        record["rumor_record_id"] = backfilled_id
        for npc_id in record.get("npc_ids", []) or []:
            grant_npc_observation(shared, npc_id, backfilled_id, created_day, [backfilled_id])
    shared.rumour_mill = {}
    shared.tracked_rumors = []
    shared.rumour_seeds = []


_DEDUP_KEY_PATTERN = None


def _is_dedup_key(text: str) -> bool:
    import re
    global _DEDUP_KEY_PATTERN
    if _DEDUP_KEY_PATTERN is None:
        _DEDUP_KEY_PATTERN = re.compile(r"^[a-z_]+:.+:\d+$")
    return bool(_DEDUP_KEY_PATTERN.match(text))


def migrate_player_rumors(player) -> None:
    met = set(getattr(player, "met_npc_ids", None) or set())
    for entry in list(getattr(player, "conversation_history", []) or []):
        if isinstance(entry, dict):
            npc_id = str(entry.get("npc_id", "") or "")
            if npc_id and npc_id != "_rumor":
                met.add(npc_id)
    for npc_id in (getattr(player, "asked_topics", None) or {}):
        if npc_id and npc_id != "_rumor":
            met.add(npc_id)
    player.met_npc_ids = met

    observations = player.rumor_observations
    pending = dict(getattr(player, "rumor_pending_texts", None) or {})
    for text in list(getattr(player, "observed_rumors", []) or []):
        if not isinstance(text, str) or not text or _is_dedup_key(text):
            continue
        rid = _text_record_id(text)
        pending.setdefault(rid, text)
        if rid not in observations:
            observations[rid] = RumorObservation(rumor_id=rid, learned_day=1)
    for index, item in enumerate(list(getattr(player, "tracked_rumors", []) or [])):
        tracked = TrackedRumor.from_dict(item) if isinstance(item, dict) else item
        rid = tracked.id or _owner_text_record_id(f"player:{index}", tracked.text)
        if not tracked.id:
            pending.setdefault(rid, tracked.text)
        if rid not in observations:
            observations[rid] = RumorObservation(
                rumor_id=rid,
                learned_day=tracked.day_created,
                source_chain=[tracked.source_npc] if tracked.source_npc else [],
            )
    for entry in list(getattr(player, "conversation_history", []) or []):
        if not isinstance(entry, dict) or str(entry.get("npc_id", "")) != "_rumor":
            continue
        response = str(entry.get("npc_response", "") or "")
        for text in response.split("|"):
            text = text.strip()
            if not text:
                continue
            rid = _text_record_id(text)
            pending.setdefault(rid, text)
            if rid not in observations:
                observations[rid] = RumorObservation(
                    rumor_id=rid,
                    learned_day=int(entry.get("day", 1) or 1),
                )
    player.rumor_pending_texts = pending


def publish_event_rumor(
    shared,
    *,
    event_type: str,
    text: str,
    location: str = "",
    district: str = "",
    witnesses: Optional[List[str]] = None,
    faction_context: str = "",
    created_day: Optional[int] = None,
    kind: str = "dynamic",
    category: str = "street_talk",
    tags: Optional[List[str]] = None,
    source_npc_id: str = "",
    occurrence: str = "",
) -> str:
    if created_day is None:
        created_day = getattr(getattr(shared, "game_time", None), "day", 1)
    witness_ids = [
        witness_id
        for witness_id in (witnesses or [])
        if not _is_transient_npc_id(witness_id)
    ]
    record_id = _event_record_id(event_type, location, district, int(created_day or 1), occurrence, text)
    record = RumorRecord(
        id=record_id,
        text=text,
        kind=kind,
        category=category,
        source_npc_id=source_npc_id,
        source_location_id=location,
        origin_faction=faction_context,
        current_faction=faction_context,
        districts=[district] if district else [],
        tags=list(tags or []),
        created_day=int(created_day or 1),
        witness_npc_ids=witness_ids,
    )
    publish_rumor_record(shared, record)
    for witness_id in witness_ids:
        grant_npc_observation(shared, witness_id, record_id, int(created_day or 1), [record_id])
    return record_id


def create_rumour_seed(
    event_type: str,
    location: str,
    district: str = "",
    witnesses: Optional[List[str]] = None,
    faction_context: str = "",
    description: str = "",
    shared=None,
    occurrence: str = "",
) -> Optional[str]:
    if shared is None:
        return None

    day = getattr(getattr(shared, "game_time", None), "day", 1)
    return publish_event_rumor(
        shared,
        event_type=event_type,
        text=description or f"Something happened in {district or location}",
        location=location,
        district=district,
        witnesses=witnesses or [],
        faction_context=faction_context,
        created_day=day,
        source_npc_id=witnesses[0] if witnesses else "",
        occurrence=occurrence,
    )


def known_eligible_holders(shared, player, record_id: str) -> List[dict]:
    holders = []
    for npc_id in sorted(getattr(player, "met_npc_ids", set()) or set()):
        npc = shared.world.npcs.get(npc_id)
        if npc is not None and record_id in getattr(npc, "rumor_observations", {}):
            holders.append({"id": npc.id, "name": npc.name})
    return holders


def rumors_panel_payload(shared, player, *, generation: int = 0) -> dict:
    eligible = eligible_records_for_player(shared, player)
    wanted_records = [record for record in eligible if "wanted" in record.tags]
    if wanted_records:
        current_wanted_id = str(getattr(player, "wanted_rumor_id", "") or "")
        if current_wanted_id not in {record.id for record in wanted_records}:
            child_ids = {record.parent_id for record in wanted_records if record.parent_id}
            current_wanted_id = max(
                (record for record in wanted_records if record.id not in child_ids) or wanted_records,
                key=lambda record: (record.created_day, record.id),
            ).id
        eligible = [record for record in eligible if "wanted" not in record.tags or record.id == current_wanted_id]
    entries = {}
    for record in eligible:
        entries[record.id] = serialize_record(record)
        entries[record.id]["holders"] = known_eligible_holders(shared, player, record.id)
        entries[record.id]["source_chain"] = _source_chain(shared, record.id)
    return {"generation": int(generation), "records": entries}


def newspaper_projections(shared, player) -> tuple:
    materialize_player_rumor_records(shared, player)
    records = sorted(shared.rumor_records.values(), key=lambda record: record.id)
    all_rumors = [serialize_record(record) for record in records]
    active_ids = list(getattr(shared, "active_authored_rumor_ids", []) or [])
    whispers: Dict[str, List[str]] = {}
    for record in records:
        faction = record.current_faction or record.origin_faction
        if faction:
            whispers.setdefault(faction, []).append(record.text)
    return all_rumors, active_ids, whispers


PRIORITY_MAP = {
    "defection": 1, "extortion": 2, "intimidation": 2,
    "argument": 3, "shuttering": 3, "gossip": 4, "ambient": 5
}

async def send_panel_queue(session, *, force_empty: bool = False) -> None:
    queue = list(getattr(session, "_panel_queue", []))
    if not queue and not force_empty:
        return
    try:
        payload = json.dumps({"type": "rumors", "payload": queue})
        await session.websocket.send(payload)
    except Exception:
        pass


def _panel_room_id(session) -> str:
    return str(getattr(getattr(session, "player", None), "current_room", "") or "")


def _client_panel_room_id(session, room_id: str, data: dict) -> str:
    explicit = data.get("client_room_id")
    if explicit:
        return str(explicit)
    shared = getattr(session, "shared", None)
    player = getattr(session, "player", None)
    instance_id = getattr(player, "tutorial_instance_id", "")
    if shared is not None and getattr(player, "in_tutorial", False) and instance_id:
        from .tutorial import get_original_tutorial_room_id
        return get_original_tutorial_room_id(instance_id, room_id, shared)
    return room_id


def clear_panel_queue(session, room_id: str = "") -> None:
    session._panel_queue = []
    session._panel_room_id = room_id or _panel_room_id(session)


def push_panel_entry(session, entry_type: str, data: dict) -> bool:
    current_room = _panel_room_id(session)
    source_room = str(data.get("room_id") or current_room)
    if current_room and source_room and source_room != current_room:
        return False
    queued_room = getattr(session, "_panel_room_id", "")
    if queued_room != current_room:
        clear_panel_queue(session, current_room)
    client_room = _client_panel_room_id(session, source_room, data)
    entry = {
        "id": f"panel_{uuid.uuid4().hex[:8]}",
        "type": entry_type,
        "room_id": client_room,
        "speaker": data.get("speaker", ""),
        "listener": data.get("listener", ""),
        "turns": data.get("turns", []),
        "priority": data.get("priority", PRIORITY_MAP.get(entry_type, 5)),
        "timestamp": time.time()
    }
    if not hasattr(session, '_panel_queue'):
        session._panel_queue = []
    session._panel_queue.append(entry)
    session._panel_queue.sort(key=lambda e: (e["priority"], e["timestamp"]))
    session._panel_queue = session._panel_queue[-8:]
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return True
    asyncio.create_task(send_panel_queue(session))
    return True


def push_gossip_to_rumour_panel(session, speaker_name: str, listener_name: str, lines: List[str]) -> None:
    turns = [
        {"speaker": speaker_name if index == 0 else listener_name, "text": line, "delay_ms": 900}
        for index, line in enumerate(lines[:2])
    ]
    push_panel_entry(session, "gossip", {"speaker": speaker_name, "listener": listener_name, "turns": turns})


def replay_durable_exchanges(session, player) -> int:
    return 0
