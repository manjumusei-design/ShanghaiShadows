from dataclasses import dataclass, field
from typing import Dict, List
import yaml

from .constants import RUMOR_WINDOW, RUMOR_STEP, RUMORS_PATH
from .dataclass_utils import filter_to_dataclass


@dataclass
class Rumor:
    id: str
    text: str
    faction: List[str] = field(default_factory=list)
    districts: List[str] = field(default_factory=list)


_catalog: Dict[str, Rumor] = {}


def load_rumors(path: str, refresh: bool = False) -> Dict[str, Rumor]:
    if _catalog and not refresh:
        return _catalog
    _catalog.clear()
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    for row in data.get("rumors", []):
        _catalog[row["id"]] = Rumor(**filter_to_dataclass(row, Rumor))
    return _catalog


def compute_active_rumors(catalog: Dict[str, Rumor], day: int, window: int = RUMOR_WINDOW, step: int = RUMOR_STEP) -> List[str]:
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
    