from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
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


TrustMap = Dict[str, Dict[str, int]]


@dataclass
class TrustRule:
    action: str
    deltas: Dict[str, int]
    visible: bool = False
    feedback: str = ""


def default_trust() -> TrustMap:
    return {
        faction: {role: 50 for role in roles}
        for faction, roles in FACTION_ROLES.items()
    }


def load_trust_rules(path: str) -> Dict[str, TrustRule]:
    data = load_strict_yaml(path) or {}
    feedback_by_action = data.get("feedback", {})
    rules: Dict[str, TrustRule] = {}
    for row in data.get("rules", []):
        action = row.get("action")
        if not action:
            continue
        rules[action] = TrustRule(
            action=action,
            deltas=row.get("deltas", {}),
            visible=bool(row.get("visible", False)),
            feedback=str(row.get("feedback", feedback_by_action.get(action, ""))),
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


def exchange_gossip(
    mem_a: List[str],
    mem_b: List[str],
    chance: float = 0.2,
    game_day: int = 1,
    npc_a: "Npc" = None,
    npc_b: "Npc" = None,
    sessions_in_room: Optional[List] = None,
    shared=None,
) -> bool:
    if random.random() >= chance:
        return False
    source = None
    target = None
    source_npc = None
    target_npc = None

    if mem_a and mem_b:
        if random.random() < 0.5:
            source, target = mem_a, mem_b
            source_npc = npc_a
            target_npc = npc_b
        else:
            source, target = mem_b, mem_a
            source_npc = npc_b
            target_npc = npc_a
    elif mem_a:
        source, target = mem_a, mem_b
        source_npc = npc_a
        target_npc = npc_b
    elif mem_b:
        source, target = mem_b, mem_a
        source_npc = npc_b
        target_npc = npc_a
    else:
        return False

    memory = random.choice(source)
    child_id = None
    if shared is not None and source_npc is not None and target_npc is not None:
        from .rumors import gossip_hop_for_memory
        child_id = gossip_hop_for_memory(
            shared,
            source_npc,
            target_npc,
            memory,
            game_day,
            personality=getattr(source_npc, "personality", "") if source_npc else "",
        )
    if child_id is not None:
        child = shared.rumor_records.get(child_id)
        if child is not None:
            memory = child.text

    if "heard that" not in memory and random.random() < 0.4:
        memory = f"Heard that {memory[0].lower() + memory[1:]}"

    if child_id is None and source_npc is not None and target_npc is not None:
        src_faction = getattr(source_npc, 'faction', '')
        tgt_faction = getattr(target_npc, 'faction', '')
        if src_faction and tgt_faction and src_faction != tgt_faction:
            from .rumors import apply_faction_spin
            memory = apply_faction_spin(memory, tgt_faction)

    if memory in target:
        return False
    target.append(memory)

    if sessions_in_room:
        src_name = getattr(source_npc, 'name', 'Someone') if source_npc else 'Someone'
        tgt_name = getattr(target_npc, 'name', 'someone') if target_npc else 'someone'
        from .rumors import push_gossip_to_rumour_panel
        for sess in sessions_in_room:
            push_gossip_to_rumour_panel(sess, src_name, tgt_name, [memory])

    return True


DECAY_GRACE_DAYS = 3      
DECAY_NORMAL = -2        
DECAY_SEVERE = -3         
NEGLECT_THRESHOLD = 7    

TRUST_TIER_HOSTILE = 30    
TRUST_TIER_NEUTRAL = 50    
TRUST_TIER_CONNECTED = 70  

FACTION_SAFEHOUSE_TRUST = {
    "ccp_safehouse": ("ccp", TRUST_TIER_NEUTRAL),   
    "gmd_safehouse": ("gmd", TRUST_TIER_NEUTRAL),   
    "green_gang_safehouse": ("green_gang", TRUST_TIER_NEUTRAL), 
    "kempeitai_safehouse": ("kempeitai", TRUST_TIER_NEUTRAL),   
}

FACTION_PERKS = {
    "ccp": {
        "name": "Hidden Safehouse Network",
        "description": "Additional safe rooms revealed in faction territory.",
        "reveal_rooms": ["hidden_20", "hidden_30", "hidden_40"],
    },
    "gmd": {
        "name": "Weapon Cache Access",
        "description": "Free weapon repair at GMD safehouses.",
    },
    "green_gang": {
        "name": "Smuggling Routes",
        "description": "Bypass certain checkpoints when traveling with Green Gang NPCs.",
    },
    "kempeitai": {
        "name": "Impunity",
        "description": "Wanted level decays 2x faster.",
        "cross_faction_penalty": {"ccp": -10, "gmd": -10},
    },
}


def get_trust_tier(trust_score: int) -> str:
    if trust_score < TRUST_TIER_HOSTILE:
        return "hostile"
    elif trust_score < TRUST_TIER_NEUTRAL:
        return "neutral"
    elif trust_score < TRUST_TIER_CONNECTED:
        return "trusted"
    else:
        return "connected"


def can_claim_faction_safehouse(
    trust: TrustMap,
    room_tags: List[str],
) -> Tuple[bool, Optional[str]]:
    for tag in room_tags:
        if tag in FACTION_SAFEHOUSE_TRUST:
            faction, min_trust = FACTION_SAFEHOUSE_TRUST[tag]
            trust_score = get_role_trust(trust, faction, None)
            if trust_score < min_trust:
                return (False, f"Your standing with {faction.upper()} is not high enough to claim this safehouse. (Need {min_trust}, have {trust_score})")
    return (True, None)


def get_faction_perks(trust: TrustMap) -> Dict[str, Dict]:
    unlocked = {}
    for faction in FACTION_PERKS:
        trust_score = get_role_trust(trust, faction, None)
        if trust_score >= TRUST_TIER_CONNECTED:
            unlocked[faction] = FACTION_PERKS[faction]
    return unlocked


def has_faction_perk(trust: TrustMap, faction: str) -> bool:
    trust_score = get_role_trust(trust, faction, None)
    return trust_score >= TRUST_TIER_CONNECTED


def apply_kempeitai_perk_penalty(trust: TrustMap) -> Dict[str, int]:
    if not has_faction_perk(trust, "kempeitai"):
        return {}

    perk_data = FACTION_PERKS.get("kempeitai", {})
    cross_penalty = perk_data.get("cross_faction_penalty", {})

    applied = {}
    for faction, delta in cross_penalty.items():
        # Only apply if this faction exists in the trust map
        if faction in trust:
            for role in trust[faction]:
                prev = trust[faction][role]
                trust[faction][role] = max(0, prev + delta)
            applied[faction] = delta

    return applied


def record_trust_interaction(
    trust: TrustMap,
    last_trust_interaction: Dict[str, int],
    key: str,
    current_day: int,
) -> None:
    faction = key.split(".", 1)[0] if "." in key else key
    if faction in trust:
        last_trust_interaction[faction] = current_day


def apply_trust_decay(
    trust: TrustMap,
    last_trust_interaction: Dict[str, int],
    current_day: int,
) -> List[Tuple[str, int]]:
    decayed: List[Tuple[str, int]] = []

    for faction in list(trust.keys()):
        last_day = last_trust_interaction.get(faction, 0)
        days_since = current_day - last_day

        if days_since <= DECAY_GRACE_DAYS:
            continue

        if days_since > NEGLECT_THRESHOLD:
            per_role_delta = DECAY_SEVERE
        else:
            per_role_delta = DECAY_NORMAL

        faction_total_delta = 0
        for role in list(trust[faction].keys()):
            prev = trust[faction][role]
            new_val = max(0, prev + per_role_delta)
            actual_delta = new_val - prev
            trust[faction][role] = new_val
            faction_total_delta += actual_delta

        if faction_total_delta != 0:
            decayed.append((faction, faction_total_delta))

    return decayed
