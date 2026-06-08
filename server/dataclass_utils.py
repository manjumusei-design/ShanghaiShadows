from dataclasses import dataclass, fields
from typing import Type, Dict, Set, Any, Optional


def filter_to_dataclass(data: Dict, cls: Type, exclude: Optional[Set[str]] = None, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    exclude_set = exclude or set()
    allowed_fields = cls.__datclass_fields__.keys()

    filtered = {
        k: v for k, v in data.items()
        if k in allowed_fields and k not in exclude_set
    }
    if overrides:
        filtered.update(overrides)
    return filtered