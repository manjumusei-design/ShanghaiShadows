from dataclasses import dataclass
from datetime import time
from typing import Any


from .constants import CURFEW_END_HOUR, CURFEW_MINUTE, WANTED_LEVEL_MAX

@dataclass(frozen=True)
class WantedConsequences:
    level: int
    ordinary_vendor_refuses: bool
    black_market_markup: float
    patrol_multiplier: int
    disguise_perception_bonus: int
    curfew_arrest_bonus: int
    arrest_chance: int
    decay_days_safe_room: int
    decay_days_ordinary: int
    npc_tone: str
    npc_may_flee: bool


@dataclass(frozen=True)
class VendorAccessResult:
    available: bool
    markup: float


def wanted_consequences(level: int) -> WantedConsequences:
    bounded = max(0, min(WANTED_LEVEL_MAX, int(level)))
    return WantedConsequences(
        level=bounded,
        ordinary_vendor_refuses=bounded >= 2,
        black_market_markup=1.5,
        patrol_multiplier=2 if bounded >= 2 else 1,
        disguise_perception_bonus=bounded * 10,
        curfew_arrest_bonus=bounded * 20,
        arrest_chance=15 + bounded * 20,
        decay_days_safe_room=2,
        decay_days_ordinary=3,
        npc_tone=("neutral" if bounded == 0 else "nervous" if bounded == 1 else "hostile"),
        npc_may_flee=bounded >= 3,
    )


def is_curfew(value: Any) -> bool:
    if isinstance(value, time):
        minute = value.hour * 60 + value.minute
    elif hasattr(value, "minute"):
        minute = int(value.minute) % 1440
    else:
        minute = int(value) % 1440
    return minute >= CURFEW_MINUTE or minute < CURFEW_END_HOUR * 60


def is_curfew_minute(minute: int) -> bool:
    return is_curfew(minute)


def vendor_access(level: int, *, black_market: bool = False) -> VendorAccessResult:
    policy = wanted_consequences(level)
    if black_market:
        return VendorAccessResult(True, policy.black_market_markup)
    return VendorAccessResult(not policy.ordinary_vendor_refuses, 1.0)


def vendor_access_result(level: int, *, black_market: bool = False) -> VendorAccessResult:
    return vendor_access(level, black_market=black_market)
