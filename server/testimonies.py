from typing import Any, Dict, Iterable, List


SUPPORTED_TESTIMONY_SOURCE_TYPES = {
    "world",
    "container",
    "merchant",
    "mission",
    "bond",
    "storylet",
}
TESTIMONY_SOURCE_BADGES = {
    "world": "Found",
    "container": "Found",
    "merchant": "Reprint",
    "mission": "Mission",
    "bond": "BOND",
    "storylet": "Storylet",
}
ALLOWED_TESTIMONY_EFFECTS = {"morale_bonus", "patrol_intel"}
PROHIBITED_TESTIMONY_EFFECTS = {
    "damage",
    "defense",
    "courage_bonus",
    "money_fabi",
    "money_silver",
    "money_military_yen",
    "trust_change",
    "faction_standing",
    "combat_power",
}


def _field(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def testimony_metadata(item: Any) -> Dict[str, Any] | None:
    provenance = _field(item, "testimony_provenance", {}) or {}
    if not isinstance(provenance, dict):
        provenance = {}
    testimony_id = str(_field(item, "testimony_id", provenance.get("id", "")) or "")
    if not testimony_id:
        return None
    source_type = str(_field(item, "testimony_source_type", provenance.get("source_type", "")) or "")
    source = str(_field(item, "testimony_source", provenance.get("source", "")) or "")
    declared_badge = str(_field(item, "testimony_source_badge", provenance.get("source_badge", "")) or "")
    badge = TESTIMONY_SOURCE_BADGES.get(source_type, declared_badge)
    return {
        "id": testimony_id,
        "title": str(_field(item, "testimony_title", provenance.get("title", "")) or _field(item, "name", "")),
        "date": str(_field(item, "testimony_date", provenance.get("date", "")) or ""),
        "place": str(_field(item, "testimony_place", provenance.get("place", "")) or ""),
        "writer": str(_field(item, "testimony_writer", provenance.get("writer", "")) or ""),
        "perspective": str(_field(item, "testimony_perspective", provenance.get("perspective", "")) or ""),
        "source": source,
        "source_type": source_type,
        "source_badge": badge,
        "text": str(_field(item, "readable_text", provenance.get("text", "")) or ""),
        "reprint": bool(_field(item, "testimony_reprint", False)),
    }


def validate_testimony_item(item: Any) -> Dict[str, Any] | None:
    metadata = testimony_metadata(item)
    if metadata is None:
        return None
    required = ("title", "date", "place", "writer", "source", "source_type", "source_badge", "text")
    declared_badge = str(_field(item, "testimony_source_badge", "") or "")
    if any(not metadata[field] for field in required) or not declared_badge:
        raise ValueError(f"malformed testimony provenance: {metadata['id']}")
    if metadata["source_type"] not in SUPPORTED_TESTIMONY_SOURCE_TYPES:
        raise ValueError(f"unsupported testimony source type: {metadata['id']}")
    is_reprint = metadata["source_type"] == "merchant" or metadata["reprint"]
    if is_reprint and "reprint" not in declared_badge.lower():
        raise ValueError(f"unlabelled testimony reprint: {metadata['id']}")
    if metadata["source_type"] != "merchant" and metadata["reprint"]:
        raise ValueError(f"invalid testimony reprint source: {metadata['id']}")
    effects = _field(item, "on_read_effects", {}) or {}
    invalid = set(effects) & PROHIBITED_TESTIMONY_EFFECTS
    invalid.update(set(effects) - ALLOWED_TESTIMONY_EFFECTS - {"once"})
    if invalid:
        raise ValueError(f"prohibited testimony effects: {metadata['id']}")
    return metadata


def validate_testimony_items(items: Iterable[Any]) -> List[Dict[str, Any]]:
    seen = set()
    validated = []
    for item in items:
        metadata = validate_testimony_item(item)
        if metadata is None:
            continue
        if metadata["id"] in seen:
            raise ValueError(f"duplicate testimony id: {metadata['id']}")
        seen.add(metadata["id"])
        validated.append(metadata)
    return validated


def normalize_testimony_archive(entries: Any) -> List[Dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    result = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        testimony_id = str(entry.get("id", "") or "")
        if not testimony_id or testimony_id in seen:
            continue
        seen.add(testimony_id)
        result.append(dict(entry))
    return result