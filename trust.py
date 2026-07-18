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
