from dataclasses import dataclass
from enum import Enum
from collections import deque
import time
from typing import Deque, Dict, List


AMBIENT_WINDOW_SHORT_SECONDS = 5.0
AMBIENT_WINDOW_SHORT_LIMIT = 1
AMBIENT_WINDOW_LONG_SECONDS = 10.0
AMBIENT_WINDOW_LONG_LIMIT = 1
AMBIENT_SEMANTIC_COOLDOWN_SECONDS = 10.0
MAX_HELD_ACTIONABLE = 3

PLAYER_SOUND_LABELS = {
    "npc_argument": "raised voices",
    "npc_extortion": "frightened voices",
    "npc_intimidation": "harsh warnings",
    "argument": "nearby argument",
    "yell": "shouting",
    "gunshot": "gunshot",
    "melee": "scuffling",
    "confrontation": "disturbance",
}


def player_sound_label(sound_type: str) -> str:
    label = PLAYER_SOUND_LABELS.get(sound_type)
    if label:
        return label
    return "disturbance"


class Tier(Enum):
    CRITICAL = "critical"
    ACTIONABLE = "actionable"
    AMBIENT = "ambient"
    BACKGROUND = "background"


class Locality(Enum):
    ROOM = "room"
    LOCAL = "local"
    DISTRICT = "district"
    CITYWIDE = "citywide"


@dataclass(frozen=True)
class Notice:
    tier: Tier
    locality: Locality
    source: str
    semantic_key: str
    msg_type: str
    text: str | None = None
    sound: str | None = None
    sound_volume: float = 0.6
    state_token: str | None = None
    batch_group: str | None = None
    source_room_id: str | None = None
    source_district: str | None = None