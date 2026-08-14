import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Any


@dataclass
class Session:
    websocket: object
    username: str
    player: object
    running: bool = True
    seconds_since_autosave: int = 0
    seconds_since_state_broadcast: int = 0
    manually_advancing: bool = False
    audio_enabled: bool = True
    open_popup: Dict[str, Any] | None = None
    popup_generation: int = 0
    _patrol_warning_signature: tuple[str, int, int, float | None] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    slot_id: str = ""
    save_key: str = ""
    rumors_panel_generation: int = 0
    clean_close_completed: bool = False
    final_save_completed: bool = False
    final_save_attempted: bool = False
    death_projection_completed: bool = False
    close_attempted: bool = False
    ephemeral: bool = False

    def set_open_popup(self, kind: str, context: Dict[str, Any] | None = None) -> None:
        self.popup_generation += 1
        self.open_popup = {"kind": kind, "generation": self.popup_generation, "context": context or {}}

    def clear_open_popup(self) -> None:
        self.open_popup = None

    async def send_popup_close(self, reason: str) -> None:
        await self.websocket.send(json.dumps({"type": "popup_close", "payload": {"reason": reason}}))
        
    async def send_display(self, text: str, msg_type=None):
        payload = {"type": "display", "payload": text}
        if msg_type is not None:
            if isinstance(msg_type, Enum):
                payload["msg_type"] = msg_type.value
            else:
                payload["msg_type"] = str(msg_type)
        await self.websocket.send(json.dumps(payload))

    async def send_prompt(self, text: str = "> "):
        await self.websocket.send(json.dumps({"type": "prompt", "payload": text}))

    async def send_hint(self, hint_id: str, stage_id: str, payload: str, immediate: bool, room_id: str = ""):
        await self.websocket.send(json.dumps({
            "type": "hint",
            "hint_id": hint_id,
            "stage_id": stage_id,
            "room_id": room_id,
            "payload": payload,
            "immediate": immediate,
        }))

    async def send_hint_clear(self):
        await self.websocket.send(json.dumps({"type": "hint_clear"}))

    async def send_npc_speech(self, speaker_id: str, speaker: str, text: str):
        await self.websocket.send(json.dumps({
            "type": "npc_speech",
            "speaker_id": speaker_id,
            "speaker": speaker,
            "text": text,
        }))

    async def send_state(self, payload: dict):
        await self.websocket.send(json.dumps({"type": "state", **payload}))

    async def send_completions(self, items: Dict[str, List[str]]):
        await self.websocket.send(json.dumps({"type": "completions", "payload": items}))

    async def send_room_players(self, players: List[str]):
        await self.websocket.send(json.dumps({"type": "room_players", "payload": players}))

    async def send_map_data(self, map_data: Dict):
        await self.websocket.send(json.dumps({"type": "map_data", **map_data}))

    async def send_storylet(self, storylet_id: str, narrative: str, options: List[Dict[str, Any]], timer_duration: int = 0, timer_warning: bool = False, expires_at: float = 0.0, read_only: bool = False, turns: List[Dict[str, Any]] | None = None):
        payload = {
            "type": "storylet",
            "storylet_id": storylet_id,
            "narrative": narrative,
            "options": options,
            "timer_duration": timer_duration,
            "timer_warning": timer_warning,
            "expires_at": expires_at,
            "read_only": read_only,
            "turns": turns or [],
        }
        await self.websocket.send(json.dumps(payload))

    async def send_storylet_resolved(self, storylet_id: str) -> None:
        await self.websocket.send(json.dumps({
            "type": "storylet_resolved",
            "storylet_id": storylet_id,
        }))

    async def clear_storylet(self, storylet_id: str) :
        await self.websocket.send(json.dumps({"type": "storylet_resolved", "storylet_id": storylet_id}))

    async def send_room_details(self, room_data: Dict):
        payload = {"type": "room_details", **room_data}
        await self.websocket.send(json.dumps(payload))

    async def send_rumor_web(self, payload: dict) -> None:
        await self.websocket.send(json.dumps({"type": "rumor_web", "payload": payload}))

    async def send_patrol_warning(
            self,
            stage: int,
            seconds_remaining: int,
            expires_at: float | None = None,
            candidate_rooms: List[str] | None = None,
    ):
        await self.websocket.send(json.dumps({
            "type": "patrol_warning",
            "stage": stage,
            "seconds_remaining": seconds_remaining,
            "expires_at": expires_at,
            "candidate_rooms": candidate_rooms or [],
        }))

    async def send_audio(self, sound: str, volume: float = 1.0, loop: bool = False):
        await self.websocket.send(json.dumps({
            "type": "audio",
            "sound": sound,
            "volume": volume,
            "loop": loop
        }))