from dataclasses import dataclass
from typing import Dict, List
import random

import yaml


@dataclass
class TrustRule:
    action: str
    deltas: Dict[str, int]
    visible: bool = False
    

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


def apply_trust_delta(player_trust: Dict[str, int], rule: TrustRule) -> Dict[str, int]:
    changed: Dict[str, int] = {}
    for faction, delta in rule.deltas.items():
        prev = player_trust.get(faction, 50)
        player_trust[faction] = max(0, min(100, prev + int(delta)))
        changed[faction] = player_trust[faction] - prev
    return changed


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
    if memory not in target: target.append(memory)
    return True