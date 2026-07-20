from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import hashlib
import random

import yaml


FACTION_ROLES: Dict[str, List[str]] = {
    "ccp": ["guerrilla", "organizer", "courier", "operative", "healer"],
    "gmd": ["officer", "spy", "smuggler"],
    "kempeitai": ["informant", "officer", "patrol", "guard"],
    "green_gang": ["broker", "enforcer", "smuggler"],
    "french_concession": ["clerks", "police", "merchant"],
    "british": ["dockmaster", "consul", "merchant"],
    "civilian": ["resident", "worker", "vendor", "guide"],
}

ALL_FACTIONS = list(FACTION_ROLES.keys())


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
            hop_count=data.get("hop_count", 0),
            day_created=data.get("day_created", 1),
        )


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


def distort_rumor(rumor: TrackedRumor, game_day: int, personality: str = "") -> TrackedRumor:
    if rumor.hop_count >= 5:
        garbled = [
            "Something happened... but the details are lost in the telling.",
            "There was some kind of incident, or so they say. Maybe.",
            "I heard something, but honestly I can't remember what anymore.",
            "A story's going around, though nobody seems to agree on the details.",
            "People are talking about... something. I've lost track of what.",
        ]
        rng_garble = random.Random(_rumor_seed(rumor.id, game_day, rumor.hop_count))
        new_text = rng_garble.choice(garbled)
        return TrackedRumor(id=rumor.id, text=new_text, origin_faction=rumor.origin_faction, current_faction=rumor.current_faction, source_npc=rumor.source_npc, hop_count=rumor.hop_count + 1, day_created=rumor.day_created,
        )
    
    rng = random.Random(_rumor_seed(rumor.id, game_day, rumor.hop_count))

    modifier = _personality_distortion_modifier(personality) if personality else 1.0

    new_text = rumor.text
    new_faction = rumor.current_faction or rumor.origin_faction
    
    if rng.random() < 0.30 * modifier:
        other_factions = [f for f in ALL_FACTIONS if f ! = new_faction]
        if other_factions:
            new_faction = rng.choice(other_factions)

    if rng.random() < 0.20 * modifier:
        exaggerations = [
            "Word is", "Rumor has it", "People are saying",
            "It's been whispered that", "They say",
        ]
        prefix = rng.choice(exaggerations)
        # Don't double-prefix
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

    return TrackedRumor(
        id=rumor.id,
        text=new_text,
        origin_faction=rumor.origin_faction,
        current_faction=new_faction,
        source_npc=rumor.source_npc,
        hop_count=rumor.hop_count + 1,
        day_created=rumor.day_created,
    )


TrustMap = Dict[str, Dict[str, int]]


@dataclass
class TrustRule:
    action: str
    deltas: Dict[str, int]
    visible: bool = False


def default_trust() -> TrustMap:
    return {
        faction: {role: 50 for role in roles}
        for faction, roles in FACTION_ROLES.items()
    }


def load_trust_rules(path: str) -> Dict[str, TrustRule]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    rules: Dict[str, TrustRule] = {}
    for row in data.get("rules", []):
        action = row.get("action")
        if not action:
            continue
        rules[action] = TrustRule(
            action=action,
            deltas=row.get("deltas", {}),
            visible=bool(row.get("visible", False)),
        )
    return rules


def get_role_trust(trust: TrustMap, faction: str, role: Optional[str] = None) -> int:
    roles = trust.get(faction, {})
    if not roles:
        return 50
    if role and role in roles:
        return roles[role]
    return int(sum(roles.values()) / max(1, len(roles)))


def change_trust(
    trust: TrustMap,
    key: str,
    delta: int,
    last_trust_interaction: Optional[Dict[str, int]] = None,
    current_day: Optional[int] = None,
    player_flags: Optional[List[str]] = None,
) -> Tuple[int, List[str]]:
    notifications: List[str] = []

    if last_trust_interaction is not None and current_day is not None:
        record_trust_interaction(trust, last_trust_interaction, key, current_day)

    faction = key.split(".", 1)[0] if "." in key else key
    was_below_connected = False
    was_at_connected = False
    if faction in FACTION_PERKS:
        prev_score = get_role_trust(trust, faction)
        was_below_connected = prev_score < TRUST_TIER_CONNECTED
        was_at_connected = prev_score >= TRUST_TIER_CONNECTED

    if "." in key:
        faction, role = key.split(".", 1)
        if faction not in trust:
            trust[faction] = {}
        prev = trust[faction].get(role, 50)
        trust[faction][role] = max(0, min(100, prev + int(delta)))
        actual = trust[faction][role] - prev
    else:
        if key not in trust:
            trust[key] = {}
        actual = 0
        for role, prev in trust[key].items():
            trust[key][role] = max(0, min(100, prev + int(delta)))
            actual += trust[key][role] - prev

    if faction in FACTION_PERKS and was_below_connected:
        new_score = get_role_trust(trust, faction)
        if new_score >= TRUST_TIER_CONNECTED:
            perk = FACTION_PERKS[faction]
            notifications.append(f"perk_unlocked:{faction}:{perk['name']}")
            if faction == "kempeitai" and player_flags is not None:
                if "kempeitai_perk_applied" not in player_flags:
                    apply_kempeitai_perk_penalty(trust)
                    player_flags.append("kempeitai_perk_applied")

    if faction in FACTION_PERKS and was_at_connected:
        new_score = get_role_trust(trust, faction)
        if new_score < TRUST_TIER_CONNECTED:
            perk = FACTION_PERKS[faction]
            notifications.append(f"perk_lost:{faction}:{perk['name']}")

    return (actual, notifications)


def apply_trust_delta(
    player_trust: TrustMap,
    rule: TrustRule,
    dynamic_vars: Optional[Dict[str, str]] = None,
    last_trust_interaction: Optional[Dict[str, int]] = None,
    current_day: Optional[int] = None,
    player_flags: Optional[List[str]] = None,
) -> Tuple[Dict[str, int], List[str]]:
    changed: Dict[str, int] = {}
    all_notifications: List[str] = []
    dynamic_vars = dynamic_vars or {}
    for key, delta in rule.deltas.items():
        if "{" in key:
            resolved_key = key.format(**dynamic_vars)
        else:
            resolved_key = key
        actual, notifications = change_trust(
            player_trust,
            resolved_key,
            int(delta),
            last_trust_interaction=last_trust_interaction,
            current_day=current_day,
            player_flags=player_flags,
        )
        changed[resolved_key] = actual
        all_notifications.extend(notifications)
    return (changed, all_notifications)


def summarize_faction_trust(trust: TrustMap) -> Dict[str, int]:
    return {
        faction: get_role_trust(trust, faction)
        for faction in trust
    }