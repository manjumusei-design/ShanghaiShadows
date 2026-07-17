from dataclasses import dataclass, fields
from typing import Type, Dict, Set, Any, Optional
import warnings


def filter_to_dataclass(data: Dict, cls: Type, exclude: Optional[Set[str]] = None, overrides: Optional[Dict[str, Any]] = None, warn_unknown: bool = False) -> Dict[str, Any]:
    exclude_set = exclude or set()
    allowed_fields = cls.__datclass_fields__.keys()

    if warn_unknown:
        unknown = set(data.keys()) - allowed_fields - exclude_set
        if unknown:
            cls_name = cls.__name__
            warnings.warn(
                f"filter_to_dataclass: UNKNOWN FIELDS WERE DROPPED for {cls_name}: {unknown}",
                UserWarning,
                stacklevel=3
            )


    filtered = {
        k: v for k, v in data.items()
        if k in allowed_fields and k not in exclude_set
    }
    if overrides:
        filtered.update(overrides)
    return filtered