import json
from dataclasses import dataclass, field
from typing import List


@dataclass
class Session:
    websocket: object
    username: str
    player: object
    running: bool = True
    seconds_since_autosave: int = 0
    seconds_since_state_broadcast: int = 0
    manually_advancing: bool = False

    async def send_display(self, text: str):
        await self.websocket.send(json.dumps({"type": "display", "payload": text}))

    async def send_prompt(self, text: str = "> "):
        await self.websocket.send(json.dumps({"type": "prompt", "payload": text}))

    async def send_state(self, payload: dict):
        await self.websocket.send(json.dumps({"type": "state", **payload}))

    async def send_completions(self, items: List[str]):
        await self.websocket.send(json.dumps({"type": "completions", "payload": items}))

    async def send_room_players(self, players: List[str]):
        await self.websocket.send(json.dumps({"type": "room_players", "payload": players}))