import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional

import yaml

from .ai_client import AIClient
from .config import load_dotenv
from .npc import Npc, get_dialogue
from .parser import Command, parse
from .stealth import Disguise, StealthSystem, TailingState
from .storylets import ActiveStorylet, StoryletManager, load_storylets
from .time_system import EventScheduler, GameTime, time_str
from .trust import (TrustMap, apply_trust_delta, change_trust, default_trust, exchange_gossip, get_role_trust, load_trust_rules, summarize_faction_trust,)
from .world import Item, World


EVENTS_PATH = "server/data/events.yaml"
TRUST_RULES_PATH = "server/data/trust_rules.yaml"
DISGUISES_PATH = "server/data/disguises.yaml"
STORYLETS_PATH = "server/data/storylets.yaml"
SAVES_DIR = Path("server/data/saves") 

@dataclass
class PlayerState:
    name: str = "Stranger"
    current_room: str = "bund_dawn"
    inventory: List[Item] = field(default_factory=list)
    trust: TrustMap = field(default_factory=default_trust)
    disguise: str = ""
    stealth_skill: int = 55
    hidden: bool = False
    flags: List[str] = field(default_factory=list)
    world_events: List[str] = field(default_factory=list)
    newspapers: List[Dict[str, object]] = field(default_factory=list)
  

@dataclass
class GameState:
    world: World
    player: PlayerState
    game_time: GameTime
    scheduler: EventScheduler
    trust_rules: Dict[str, object]
    storylet_history: List[str] = field(default_factory=list)
    active_storylet: Optional[ActiveStorylet] = None
    tailing_state: Optional[TailingState] = None
    planted_evidence: List[Dict[str, object]] = field(default_factory=list)
    rumour_mill: Dict[str, List[str]] = field(default_factory=dict)
    last_curfew_penalty_day: int = 0
    last_newspaper_day: int = 0

    def get_trust_value(self, key: str) -> int:
        if "." in key:
            faction, role = key.split(".", 1)
            return get_role_trust(self.player.trust, faction, role)
        return get_role_trust(self.player.trust, key)
    

@dataclass
class SessionContext:
    session: "PlayerSession"
    slot_name: str = ""
    state: Optional[GameState] = None
    seconds_seince_autosave: int = 0


class PlayerSession:
    def __init__(self, websocket):
        self.websocket = websocket
        self.running = True

    async def send_display(self, text: str):
        await self.websocket.send(json.dumps({"type": "display", "payload": text}))

    async def send_prompt(self, text: str = "> "):
        await self.websocket.send(json.dumps({"type": "prompt", "payload": text}))


def _sanitize_slot_name(raw: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", raw.strip().lower()).strip("_")
    return cleaned or "default"


def _serialize_item(item: Item) -> Dict[str, object]:
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "takeable": item.takeable,
        "readable_text": item.readable_text,
        "planted_on": item.planted_on,
    }


def _deserialize_item(row: Dict[str, object]) -> Item:
    return Item(
        id=str(row["id"]),
        name=str(row["name"]),
        description=str(row["description"]),
        takeable=bool(row.get("takeable", True)),
        readable_text=str(row.get("readable_text", "")),
        planted_on=str(row.get("planted_on", "")),
    )


def load_disguises(path: str) -> Dict[str, Disguise]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    disguises: Dict[str, Disguise] = {}
    for row in data.get("disguises", []):
        disguise = Disguise(
            id=row["id"],
            name=row["name"],
            apparent_faction=row["apparent_faction"],
            bonus=int(row.get("bonus", 0)),
            description=row.get("description", ""),
        )
        disguises[disguise.id] = disguise
    return disguises


class GameServer:
    def __init__(self):
        load dotenv()
        SAVES_DIR.mkdir(parents=True, exist_ok=True)
        self.ai_client = AIClient()
        self.disguises = load_disguises(DISGUISES_PATH)
        self.stealth = StealthSystem(self.disguises)
        self.storylet_manager = StoryletManager(load_storylets(STORYLETS_PATH))
        self.sessions: Dict[str, SessionContext] = {}
        self.command_registry: Dict[str, Callable[[SessionContext, Command], Awaitable[None]]] = {
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
            "disguise as": self._cmd_disguise_as,
            "tail": self._cmd_tail,
            "hide": self._cmd_hide,
            "plant": self._cmd_plant,
            "read": self._cmd_read,
            "journal": self._cmd_journal,
            "unknown": self._cmd_unknown,
            "ask": self._cmd_stub,
            "ask about": self._cmd_stub,
            "whisper": self._cmd_stub,
            "give": self._cmd_stub,
            "use": self._cmd_stub,
            "sleep": self._cmd_stub,
            "bond": self._cmd_stub,
        }

    def _new_state(self) -> GameState:
        world = World()
        player = PlayerState()
        scheduler = EventScheduler()
        scheduler.load_from_yaml(EVENTS_PATH)
        trust_rules = load_trust_rules(TRUST_RULES_PATH)
        return GameState(
            world=world,
            player=player,
            game_time=GameTime(),
            scheduler=scheduler,
            trust_rules=trust_rules,
        )

    def _room(self, context: SessionContext):
        return context.state.world.get_room(context.state.player.current_room) if context.state else None 

    def _save_path(self, slot_name: str) -> Path:
        return SAVES_DIR / f"{slot_name}.json"
    
    def _find_item_by_name(self, name: str, items: List[Item]) -> Optional[Item]:
        q = name.lower().strip()
        for item in items:
            if item.name.lower() == q or item.id.lower() == q:
                return item
        for item in items:
            if q in item.name.lower() or q in item.id.lower():
                return item
        return None
    
    def _find_npc_by_name(self, context: SessionContext, name: str, npc_ids: List[str]) -> Optional[str]:
        q = name.lower().strip()
        for npc_id in npc_ids:
            npc = context.state.world.npcs.get(npc_id) 
            if npc and (q in npc.name.lower() or q in npc.id.lower()):
                return npc_id
        return None
    
    async def _post_display(self, context: SessionContext, text: str):
        await context.session.send_display(text if text.endswith("\n") else text + "\n")

    def _log_event(self, context: SessionContext, text: str) -> None:
        context.state.player.world_events.append(text)
        context.state.player.world_events = context.state.player.world_events[-50:]

    def _summary_trust_lines(self, context: SessionContext, text: str) -> List[str]:
        summary = summarize_faction_trust(context.state.player.trust)
        return [f"- {faction}: {value}" for faction, value in sorted(summary.items())]

    def _disguise_bonus(self, context: SessionContext) -> int:
        disguise = self.disguises.get(context.state.player.disguise)
        return disguise.bonus if disguise else 0
        
    def _apply_action_trust(self, context: SessionContext, action: str, visible_room_npcs: Optional[List[str]] = None):
        rule = context.state.trust_rules.get(action)
        if not rule:
            return
        apply_trust_delta(context.state.player.trust, rule)
        if getattr(rule, "visible", False):
            for npc_id in visible_room_npcs or []:
                npc = context.state.world.npcs.get(npc_id)
                if npc:
                    memory = f"Observed player action: {action}"
                    if memory not in npc.memory:
                        npc.memory.append(memory)

    def _move_npcs_if_hour_changed(self, context: SessionContext):
        if context.state.game_time.minute % 60 !=0:
            return
        hour = context.state.game_time.minute // 60
        for npc_id, npc in context.state.world.npcs.items():
            room_id = npc.schedule.get(hour)
            if room_id and room_id in context.state.world.rooms:
                context.state.world.place_npc(npc_id, room_id)

    def _process_gossip(self, context: SessionContext):
        for room in context.state.world.rooms.values():
            npc_ids = room.npcs
            if len(npc_ids) < 2:
                continue
            for i in range(len(npc_ids) - 1):
                a = context.state.world.npcs.get(npc_ids[i])
                b = context.state.world.npcs.get(npc_ids[i + 1])
                if not a or not b:
                    continue
                if exchange_gossip(a.memory, b.memory, chance=0.25):
                    rumor = random_memory = b.memory[-1] if b.memory else ""
                    if rumor:
                        context.state.rumour_mill.setdefault(b.faction, []).append(random_memory)
                        context.state.rumour_mill[b.faction] = context.state.rumour_mill[b.faction][-12:]

    async def _check_curfew_penalty(self, context: SessionContext):
        if context.state.game_time.minute < 1260:
            return
        if context.state.last_curfew_penalty_day == context.state.game_time.day:
            return
        room = self._room(context)
        if room and not room.indoors:
            self._apply_action_trust(context, "out after curfew", room.npcs)
            context.state.last_curfew_penalty_day = context.state.game_time.day
            self._log_event(context, "You were seen outside after curfew.")
            await self._post_display(context, "The curfew is in force. Faces turn away from you in the dark as everyone hurriedly scurries back to their residence.")




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

    async def _cmd_look(self, session: PlayerSession, cmd: Command):
        room = self._room()
        if not room: 
            await session.send_display("You are nowhere.\n")
            return
        text = f"{room.title}\n{room.description}\n"
        if room.items:
            text += "You see: " + ", ".join(item.name for item in room.items) + "\n"
        if room.npcs:
            for npc_id in room.npcs:
                npc = self.state.world.npcs.get(npc_id)
                if npc:
                    text += f"{npc.name} is here.\n"
        if room.exits:
            text += "Exits: " + ", ".join(room.exits.keys()) + "\n"
        await session.send_display(text)

    async def _cmd_go(self, session: PlayerSession, cmd: Command):
        direction = cmd.direct_obj
        if not direction:
            await session.send_display ("Go where?\n")
            return
        room = self.room()
        if not room:
            await session.send_display("You are nowhere. \n")
            return
        dest = room.exits.et(direction)
        if not dest:
            await session.send_display("You can't go that way.\n")
            return
        self.state.player.current_room = dest
        await self._cmd_look(session, cmd)

    async def _cmd_take(self, session: PlayerSession, cmd: Command):
        if not cmd. direct_obj:
            await session.send_display("Take what?\n")
            return
        rom = self.room()
        item = self._find_item_by_name(cmd.direct_obj, room.items if room else [])
        if not item:
            await session.send_display("You don't see that here\n")
            return
        if not item.takeable:
            await session.send_display("You can't take that.\n")
            return
        room.items.remove(item)
        self.state.player.inventory.append(item)
        await session.send_display(f"You take {item.name}.\n")

    async def _cmd_drop(self, sessionL PlayerSession, cmdL Command):
        if not cmd.direct_obj:
            await session.send_display("Drop what?\n")
            return
        item = self._find_item_by_name(cmd.direct_obj, self.state.player.inventory)
        if not item:
            await session.send_display("You don't have that.\n")
            return
        self.state.player.inventory.remove(item)
        room = self._room()
        if room:
            room.items.append(item)
        await session.send_display(f"You drop {item.name}.\n")
    
    async def _cmd_inventory(self, session: PlayerSession, cmd: Command):
        if not self.state.player.inventory:
            await session.send_display("You are empty-handed.\n")
            return
        lines = ["You are carrying:"]
        for item in self.state.player.inventory:
            lines.append(f"- {item.name}")
        await session.send_display("\n".join(lines) + "\n")
        
    async def _cmd_talk_to(self, session: PlayerSession, cmd: Command):
        if not cmd.direct_obj:
            await session.send_display("Talk to whom?\n")
            return
        room = self._room()
        npc_id = self._find_npc_by_name(cmd.direct_obj, room.npcs if room else [])
        if not npc_id:
            await session.send_display("They aren't here.\n")
            return
        npc = self.state.world.npcs[npc_id]
        line = get_dialogue(npc, self.state.player.trust)
        await session.send_display(f'{npc.name} says, "{line}"\n')
        self._apply_action_trust(f"talk_to_{npc.faction}", room.npcs if room else [])
        
    async def _cmd_wait(self, session: PlayerSession, cmd: Command):
        if not cmd.direct_obj:
            await session.send_display("Wait how long?\n")
            return
        try:
            minutes = int(cmd.direct_obj)
        except ValueError:
            await session.send_display("You must wait a number of minutes.\n")
            return
        if minutes < 1:
            await session.send_display("Wait at least 1 minute.\n")
            return
        minutes = min(minutes, 240)
        for _ in range(minutes):
            await self._advance_time_one_minute()
        await session.send_display(f"You wait {minutes} minutes. It is now {time_str(self.state.game_time)}.\n")

    async def _cmd_status(self, session: PlayerSession, cmd: Command):
        lines = [f"{time_str(self.state.game_time)}", "Trust:"]
        for faction in FACTIONS:
            lines.append(f"- {faction}: {self.state.player.trust.get(faction, 50)}")
        await session.send_display("\n".join(lines) + "\n")

    async def _cmd_help(self, session: PlayerSession, cmd: Command):
        await session.send_display(
            "Available commands:\n"
            "LOOK, GO <direction>, TAKE <item>, DROP <item>, INVENTORY\n"
            "TALK TO <npc>, WAIT <minutes>, STATUS, HELP, QUIT\n"
        )

    async def _cmd_wait(self, session: PlayerSession, cmd: Command):
        self.save_snapshot()
        await session.send_display("Goodbye.\n")
        session.running = False 
        await session.websocket.close()

    async def _cmd_stub(self, session: PlayerSession, cmd: Command):
        await session.send_display(f"{cmd.verb.upper()} has not been implemented.\n")
        
    async def _cmd_unknown(self, session: PlayerSession, cmd: Command):
        await session.send_display(f"I don't understand '{cmd.raw}'. Try HELP.\n")

    def save_snapshot(self):
        room_items = {rid: [item.id for item in room.items] for rid, room in self.state.world.rooms.items()}
        npc_locations = dict(self.state.world.npc_locations)
        npc_memory = {nid: list(npc.memory) for nid, npc in self.state.world.npcs.items()}
        payload = {
            "player": {
                "name": self.state.player.name,
                "current_room": self.state.player.current_room,
                "inventory": [item.id for item in self.state.player.inventory],
                "trust": self.state.player.trust,
            },
            "time": {"day": self.state.game_time.day, "minute": self.state.game_time.minute},
            "last_curfew_penalty_day": self.state.last_curfew_penalty_day,
            "room_items": room_items,
            "npc_locations": npc_locations,
            "npc_memory": npc_memory,
        }
        SAVE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load_snapshot(self):
        if not SAVE_PATH.exists():
            return
        try:
            data = json.loads(SAVE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return
        
        player_data = data.get("player", {})
        self.state.player.name = player_data.get("name", self.state.player.name)
        self.state.player.current_room = player_data.get("current_room", self.state.player.current_room)
        self.state.player.trust.update(player_data.get("trust", {}))

        items_by_id = {}
        for room in self.state.world.rooms.values():
            for item in room.items:
                items_by_id[item.id] =item
        for item in self.state.player.inventory:
            items_by_id[item.id] = item

        room_item_map = data.get("room_items", {})
        for room_id, item_ids in room_item_map.items():
            room = self.state.world.rooms.get(room_id)
            if not room:
                continue
            room.items = []
            for item_id in item_ids:
                src = items_by_id.get(item_id)
                if src:
                    room.items.append(Item(id=src.id, name=src.name, description=src.description, takeable=src.takeable))

        self.state.player.inventory = []
        for item_id in player_data.get("inventory", []):
            src = items_by_id.get(item_id)
            if src:
                self.state.player.inventory.append(Item(id=src.id, name=src.name, description=src.description, takeable=src.takeable))

        t = data.get("time", {})
        self.state.game_time.day = int(t.get("day", self.state.game_time.day))
        self.state.game_time.minute = int(t.get("minute", self.state.game_time.minute))
        self.state.last_curfew_penalty_day = int(data.get("last_curfew_penalty_day", 0))

        npc_locations = data.get("npc_locations", {})
        for room in self.state.world.rooms.values():
            room.npcs = []
        self.state.world.npc_locations = {}
        for npc_id, room_id in npc_locations.items():
            if npc_id in self.state.world.npcs and room_id in self.state.world.rooms:
                self.state.world.rooms[room_id].npcs.append(npc_id)
                self.state.world.npc_locations[npc_id] = room_id

        for npc_id, memories in data.get("npc_memory", {}).items():
            npc = self.state.world.npcs.get(npc_id)
            if npc:
                npc.memory = list(memories)
                

