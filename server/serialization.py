import json
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional, TYPE_CHECKING

from .world import Item
from .dataclass_utils import filter_to_dataclass

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


MAX_SERIALIZATION_DEPTH = 3

def serialize_item(item: Item, depth: int = 0) -> Dict[str, Any]:
    from dataclasses import asdict
    if depth > MAX_SERIALIZATION_DEPTH:
        return {"id": item.id, "name": item.name, "description": item.description, "takeable": item.takeable, "container_truncated": True}
    data = asdict(item)
    if item.is_container:
        data["container_items"] = [serialize_item(i, depth + 1) for i in item.container_items]
    return data


def deserialize_item(row: Dict[str, Any]) -> Item:
    from .world import Item
    container_items = []
    if row.get("is_container", False):
        container_items = [deserialize_item(i) for i in row.get("container_items", [])]
        row = row.copy()
        row["container_items"] = container_items
    return Item(**filter_to_dataclass(row, Item))
