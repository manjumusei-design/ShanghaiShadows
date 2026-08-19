import json
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
    return load_strict_yaml(p) or {}


MAX_SERIALIZATION_DEPTH = 3

def serialize_item(item: Item, depth: int = 0) -> Dict[str, Any]:
    from dataclasses import asdict
    if depth > MAX_SERIALIZATION_DEPTH:
        return {"id": item.id, "name": item.name, "description": item.description, "examine_text": item.examine_text, "takeable": item.takeable, "container_truncated": True}
    data = asdict(item)
    if data.get("testimony_date") and not isinstance(data["testimony_date"], str):
        data["testimony_date"] = str(data["testimony_date"])
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
    item = Item(**filter_to_dataclass(row, Item, warn_unknown=True))
    return item