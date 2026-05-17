from dataclasses import dataclass
from typing import Dict, List
import random

import yaml


FACTION_ROLES: Dict[str, List[str]] = {
    "resistance": ["courier", "safehouse", "fighter"],
    "kempeitai": ["informant", "officer", "patrol"],
    "green_gang": ["broker", "enforcer", "smuggler"],
    "french_concession": ["clerks", "police", "merchant"],
    "british": ["dockmaster", "consul", "merchant"],
    "civilian": ["resident", "worker", "vendor"],
}


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
    

def change_trust(trust: TrustMap, key: str, delta: int) -> int:
    if "." in key:
        faction, role = key.split(".", 1)
        if faction not in trust:
            trust[faction] = {}
        prev = trust[faction].get(role, 50)
        trust[faction][role] = max(0, min(100, prev + int(delta)))
        return trust[faction][role] - prev
    
    if key not in trust:
        trust[key] = {}
    changed_total = 0
    for role, prev in trust[key].items():
        trust[key][role] = max(0, min(100, prev + int(delta)))
        changed_total += trust[key][role] - prev
    return changed_total


def apply_trust_delta(player_trust: TrustMap, rule: TrustRule) -> Dict[str, int]:
    changed: Dict[str, int] = {}
    for key, delta in rule.deltas.items():
        changed[key] = change_trust(player_trust, key, int(delta))
    return changed


def summarize_faction_trust(trust: TrustMap) -> Dict[str, int]:
    return {
        faction: get_role_trust(trust, faction)
        for faction in trust
    }


def exchange_gossip(mem_a: List[str], mem_b: List[str], chance: float = 0.2) -> bool:
    if random.random() >= chance:
        return False
    source = None
    target = None
    if mem_a and mem_b:
        source, target = (mem_a, mem_b) if random.random() < 0.5 else (mem_b, mem_a)
    elif mem_a:
        source, target = mem_a, mem_b
    elif mem_b:
        source, target = mem_b, mem_a
    else:
        return False
    memory = random.choice(source)
    if "heard that" not in memory and random.random() < 0.4:
        memory = f"Heard that {memory[0].lower() + memory[1:]}"
    if memory not in target:
        target.append(memory)
        return True
    return False
