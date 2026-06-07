import json
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional, TYPE_CHECKING

from .world import Item

if TYPE_CHECKING:
    from .player_data import PlayerData
    from .session import Session
    from .game_world import SharedWorldState


def _load_yaml(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
    

def serialize_item(item: Item) -> Dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "takeable": item.takeable,
        "readable_text": item.readable_text,
        "planted_on": item.planted_on,
        "food_value": item.food_value,
        "morale_restore": item.morale_restore
    }


def deserialize_item(row: Dict[str, Any]) -> Item:
    return Item(
        id=str(row["id"]),
        name=str(row["name"]),
        description=str(row["description"]),
        takeable=bool(row.get("takeable", True)),
        readable_text=str(row.get("readable_text", "")),
        planted_on=str(row.get("planted_on", "")),
        food_value=int(row.get("food_value", 0)),
        morale_restore=int(row.get("morale_restore", 0)),
    )