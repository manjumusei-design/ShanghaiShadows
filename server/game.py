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

    def _room(self):
        return self.state.world.get_room(self.state.player.current_room)

    async def _broadcast(self, text: str):
        if not self.sessions:
            return
        await asyncio.gather(*(s.send_display(text + "\n") for s in list(self.sessions.values())))

    def _find_item_by_name(self, name: str, items: List[Item]) -> Item | None:
        q = name.lower().strip()
        for item in items:
            if item.name.lower() == q or item.id.lower() == q:
                return item
        for item in items:
            if q in item.name.lower() or q in item.id.lower():
                return item
        return None
    
    def _find_Npc_by_name(self, name: str, npc_ids: List[str]) -> str | None:
        q = name.lower().strip()
        for npc_id in npc_ids:
            npc = self.state.world.npcs.get(npc_id)
            if npc and (q in npc.name.lower() or q in npc.id.lower()):
                return npc_id
        return None
    
    def _apply_action_trust(self, action: str, visible_room_npcs: List[str] | None = None):
        rule = self.state.trust_rules.get(action)
        if not rule:
            return
        apply_trust_delta(self.state.player.trust, rule)
        if getattr(rule, "visible", False):
            for npc_id in (visible_room_npcs or []):
                npc = self.state.world.npcs.get(npc_id)
                if npc:
                    memory = f"Observed player action: {action}"
                    if memory not in npc.memory:
                        npc.memory.append(memory)

    def _move_npcs_if_hour_changed(self):
        if self.state.game_time.minute % 60 != 0:
            return
        hour = self.state.game_time.minute // 60
        for npc_id, npc in self.state.world.npcs.items():
            room_id = npc.schedule.get(hour)
            if not room_id or room_id not in self.state.world.rooms:
                continue
            old = self.state.world.npc_locations.get(npc_id)
            if old == room_id:
                continue
            if old and old in self.state.world.rooms and npc_id in self.state.world.rooms[old].npcs: 
                self.state.world.rooms[old].npcs.remove(npc_id)
            if npc_id not in self.state.world.rooms[room_id].npcs:
                self.state.world.rooms[room_id].npcs.append(npc_id)
            self.state.world.npc_locations[npc_id] = room_id

    def _process_gossip(self):
        for room in self.state.world.rooms.values():
            npc_ids = room.npcs
            if len(npc_ids) < 2:
                continue
            for i in range(len(npc_ids) -1):
                a = self.state.world.npcs.get(npc_ids[i])
                b = self.state.world.npcs.get(npc_ids[i + 1])
                if not a or not b:
                    continue
                exchange_gossip(a.memory, b.memory, chance = 0.25)

    async def _check_curfew_penalty(self):
        if self.state.game_time.minute < 1260:
            return
        if self.state.last_curfew_penalty_day == self.state.game_time.day:
            return
        room = self._room()
        if room and not room.indoors:
            self._apply_action_trust("out_after_curfew", room.npcs)
            self.state.last_curfew_penalty_day = self.state.game_time.day
            await self._broadcast("The curfew is in force. Staying outside has made people trust you less.")

    async def _advance_time_one_minute(self):
        self.state.game_time.minute += 1
        if self.state.game_time.minute >= 1440:
            self.state.game_time.minute = 0
            self.state.game_time.day += 1
        self.state.scheduler.process(self.state.game_time, lambda msg: asyncio.create_task(self._broadcast(msg)))
        self._move_npcs_if_hour_changed()
        self._process_gossip()
        await self._check_curfew_penalty()

    async def tick_loop(self):
        while True:
            await asyncio.sleep(1)
            await self._advance_time_one_minute()
            if self.state.game_time.minute % 10 == 0:
                self.save_snapshot()

    async def handle_client(self, websocket):
        session = PlayerSession(websocket)
        client_id = f"{websocket.remote_address}"
        self.sessions[client_id] = session
        await session.send_display("Shanghai Shadows\n")
        await self._cmd_look(session, Commnad(verb = "look", raw= "look"))
        await session.send_prompt()

        try:
            async for message in websocket:
                text = message.strip()
                if not text:
                    await session.send_prompt()
                    continue

                cmd = parse(text)
                if cmd.verb == "pass":
                    await session.send_prompt()
                    continue
                handler = self.command_registry.get(cmd.verb, self._cmd_unknown)
                await handler(session, cmd)
                if session.running:
                    await session.send_prompt()
        except Exception as exc:
            print(f"Client {client_id} disconnected: {exc}")
        finally:
            self.sessions.pop(client_id, None)
                 
