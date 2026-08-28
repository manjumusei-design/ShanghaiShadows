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


class DeliveryPolicy:
    def __init__(self) -> None:
        self.command_depth: int = 0
        self.semantic_state: Dict[str, str] = {}
        self.ambient_history: Deque[tuple[float, str]] = deque()
        self.ambient_last_delivered: float | None = None
        self.ambient_last_by_key: Dict[str, float] = {}
        self.held_actionable: List[Notice] = []

    def begin_command_response(self) -> None:
        self.command_depth += 1

    def end_command_response(self) -> None:
        self.command_depth = max(0, self.command_depth - 1)

    @property
    def in_command_response(self) -> bool:
        return self.command_depth > 0

    async def deliver(
        self,
        session,
        notice: Notice,
        current_time: float | None = None,
        current_tick: float | None = None,
    ) -> bool:
        if notice.tier is Tier.BACKGROUND:
            return False
        if not self._is_visible(session, notice):
            return False
        if notice.state_token is not None:
            token = self.semantic_state.get(notice.semantic_key)
            if token == notice.state_token:
                return False
            self.semantic_state[notice.semantic_key] = notice.state_token
        if self.in_command_response:
            if notice.tier is Tier.CRITICAL:
                return await self._send(session, notice)
            if notice.tier is Tier.ACTIONABLE:
                self._hold(notice)
            return False
        if notice.tier is Tier.AMBIENT or notice.source == "ambient_events":
            now = self._resolve_time(current_time, current_tick)
            if not self._ambient_allowed(notice.semantic_key, now):
                return False
            self.ambient_last_delivered = now
        return await self._send(session, notice)

    async def flush_actionable(self, session) -> int:
        held = self.held_actionable
        self.held_actionable = []
        delivered = 0
        for notice in held:
            if self._is_visible(session, notice):
                await self._send(session, notice)
                delivered += 1
        return delivered

    def _hold(self, notice: Notice) -> None:
        self.held_actionable = [
            n for n in self.held_actionable if n.semantic_key != notice.semantic_key
        ]
        self.held_actionable.append(notice)
        if len(self.held_actionable) > MAX_HELD_ACTIONABLE:
            del self.held_actionable[0]

    async def _send(self, session, notice: Notice) -> bool:
        instant = notice.tier is TIER.CRITICAL
        if notice.text is not None:
            await session.send_display(notice.text, msg_type=notice.msg_type, instant_reveal=instant)
        if notice.sound is not None:
            if getattr(session, "audio_enabled", False):
                await session.send_audio(notice.sound, volume=notice.sound_volume)
        return True