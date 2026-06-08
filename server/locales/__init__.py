from pathlib import Path
from typing import Dict

import yaml


_strings: Dict[str, str] = {}


def load_locale(lang: str = "en"):
    global _strings
    path = Path(__file__).parent / f"{lang}.yaml"
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    _strings = data


def get(key: str, default: str = "") -> str:
    return _strings.get(key, default or key)