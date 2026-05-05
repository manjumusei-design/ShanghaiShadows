import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Dict, List

from .npc import get_dialogue
from .parser import Command, parse
from .time_system import EventScheduler, GameTime, time_str
from .trust import apply_trust_delta, exchange_gossip, load_trust_rules
from .world import Item, World


FACTIONS = ["resistance", "kampeitai", "green_gang", "french_concession", "british_concession", "civilian"]

SAVE_PATH = Path("server/data/savegame.json")


@dataclass
class PlayerState:
    name: str = "Stranger"
    current_room: str = "bund_dawn"
    inventory: List[Item] = field(default_factory=list)
    trust: Dict[str, int] = field(default_factory=lambda: {f: 50 for f in FACTIONS})
  

@dataclass
class GameState:
    world: World
    player: PlayerState
    game_time: GameTime
    scheduler: EventScheduler
    trust_rules: Dict[str, object]
    last_curfew_penalty_day: int = 0


class PlayerSession:
    def __init__(self, websocket):
        self.websocket = websocket
        self.running = True

    async def send_display(self, text: str):
        await self.websocket.send(json.dumps({"type": "display", "payload": text}))

    async def send_prompt(self):
        await self.websocket.send(json.dumps({"type": "prompt", "payload": "> "}))


class GameServer:
    def __init__(self):
        world = World()
        player = PlayerState()
        game_time = GameTime()
        scheduler = EventScheduler()
        scheduler.load_from_yaml("server/data/events.yaml")
        trust_rules = load_trust_rules("server/data/trust_rules.yaml")
        self.state = GameState(world=world, player=player, game_time=game_time, scheduler=scheduler, trust_rules=trust_rules)
        self.sessions: Dict[str, PlayerSession] = {}
        self.command_registry: Dict[str, Callable [[PlayerSession, Command], Awaitable[None]]] = {
            "look": self._cmd_look,
            "go": self._cmd_go,
            "take": self._cmd_take,
            "drop": self._cmd_drop,
            "inventory": self._cmd_inventory,
            "talk to": self._cmd_talk_to,
            "wait": self._cmd_wait,
            "help": self._cmd_help,
            "quit": self._cmd_quit,
            "status": self._cmd_status,
            "unknown": self._cmd_unknown,
            "ask": self._cmd_stub,
            "ask about": self._cmd_stub,
            "whisper": self._cmd_stub,
            "give": self._cmd_stub,
            "plant": self._cmd_stub,
            "disguise as": self._cmd_stub,
            "hide": self._cmd_stub,
            "read": self._cmd_stub,
            "use": self._cmd_stub,
            "sleep": self._cmd_stub,
            "journal": self._cmd_stub,
        }
        self.load_snapshot()


