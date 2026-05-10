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
    seconds_since_autosave: int = 0


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
        load_dotenv()
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

    def _summary_trust_lines(self, context: SessionContext) -> List[str]:
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
        if context.state.game_time.minute % 60 != 0:
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
            self._apply_action_trust(context, "out_after_curfew", room.npcs)
            context.state.last_curfew_penalty_day = context.state.game_time.day
            self._log_event(context, "You were seen outside after curfew.")
            await self._post_display(context, "The curfew is in force. Faces turn away from you in the dark as everyone hurriedly scurries back to their residence.")

    async def _check_planted_evidence(self, context: SessionContext):
        if not context.state.planted_evidence:
            return
        remaining = []
        for planted in context.state.planted_evidence:
            room = context.state.world.get_room(str(planted["room_id"]))
            target = str(planted.get("target", "")).lower()
            triggered = False
            if room:
                for npc_id in room.npcs:
                    npc = context.state.world.npcs.get(npc_id)
                    if not npc:
                        continue
                    if not target or target in npc.faction.lower() or target in npc.role.lower() or target in npc.name.lower():
                        event_text = f"Your planted {planted['item_name']} in {room.title} has stirred suspicion."
                        self._log_event(context, event_text)
                        context.state.rumour_mill.setdefault(npc.faction, []).append(event_text)
                        await self._post_display(context, event_text)
                        triggered = True
                        break
            if not triggered:
                remaining.append(planted)
        context.state.planted_evidence = remaining

    async def _process_tailing(self, context: SessionContext):
        tail = context.state.tailing_state
        if not tail:
            return
        current_total = (context.state.game_time.day - 1) * 1440 + context.state.game_time.minute
        if current_total - tail.last_checked_minute < 5:
            return
        tail.last_checked_minute = current_total
        tail.elapsed_minutes += 5
        target = context.state.world.npcs.get(tail.target_npc_id)
        if not target:
            context.state.tailing_state = None
            await self._post_display(context, "Your target has vanished into the city's folds.")
            return
        success, _ = self.stealth.tail_check(
            tail,
            target,
            context.state.player.stealth_skill,
            self._disguise_bonus(context),
            context.state.player.hidden,
        )
        if not success and tail.distance <= 0:
            context.state.tailing_state = None
            self._log_event(context, f"{target.name} spotted you while you were tailing them.")
            await self._post_display(context, f"{target.name} glances over a shoulder, slows, and knows exactly what you are doing.")
            return
        target_room = context.state.world.npc_locations.get(target.id)
        if success and target_room and context.state.player.current_room != target_room:
            context.state.player.current_room = target_room
            context.state.player.hidden = False
            await self._post_display(context, f"You shadow {target.name} and keep them in sight.")

    async def _check_newspaper(self, context: SessionContext):
        if context.state.game_time.minute != 360:
            return
        if context.state.last_newspaper_day == context.state.game_time.day:
            return
        context.state.last_newspaper_day = context.state.game_time.day
        newspaper = await self._generate_newspaper(context)
        context.state.player.newspapers.append(newspaper)
        item = Item(
            id=f"newspaper_day_{context.state.game_time.day}",
            name=f"Shanghai Times, Day {context.state.game_time.day}",
            description="A folded sheet of fresh newsprint, still smelling faintly of ink.",
            readable_text=newspaper["body"],
        )
        context.state.player.inventory.append(item)
        self._log_event(context, "A new newspaper edition reached you at dawn.")
        await self._post_display(context, "At dawn a newspaper runner slips a fresh edition into your hands.")

    async def _generate_newspaper(self, context: SessionContext) -> Dict[str, object]:
        recent = context.state.player.world_events[-8:] or ["A quiet night passed with only whispers in the lanes."]
        prompt = (
            "You are the editor of the Shanghai Times in occupied Shanghai, November 1938. "
            "Write four propaganda-tinged headlines with one-sentence summaries. "
            "Respond as strict JSON with key 'headlines', where each headline has 'title' and 'summary'. "
            f"Player timeline events: {recent}"
        )
        result = await self.ai_client.chat_json(
            [{"role": "user", "content": prompt}],
            timeout_seconds=4.0,
        )
        if result and isinstance(result.get("headlines"), list):
            lines = []
            for row in result["headlines"][:4]:
                title = str(row.get("title", "Late Edition")).strip()
                summary = str(row.get("summary", "")).strip()
                lines.append(f"{title}\n{summary}")
            body = "\n\n".join(lines)
        else:
            fallback = recent[-4:]
            blocks = []
            for idx, event in enumerate(fallback, start=1):
                blocks.append(f"Headline {idx}\nOfficials insist order holds after reports that {event.lower()}")
            body = "\n\n".join(blocks)
        return {"day": context.state.game_time.day, "body": body}

    async def _maybe_trigger_storylet(self, context: SessionContext):
        active = self.storylet_manager.maybe_trigger(context.state)
        if not active:
            return
        context.state.active_storylet = active
        lines = [active.narrative]
        for idx, option in enumerate(active.options, start=1):
            lines.append(f"{idx}. {option.text}")
        await self._post_display(context, "\n".join(lines))

    async def _resolve_storylet_choice(self, context: SessionContext, text: str):
        active = context.state.active_storylet
        if not active:
            return
        try:
            choice = int(text.strip())
        except ValueError:
            await context.session.send_prompt("Choose 1-" + str(len(active.options)) + ": ")
            return
        if choice < 1 or choice > len(active.options):
            await context.session.send_prompt("Choose 1-" + str(len(active.options)) + ": ")
            return
        option = active.options[choice - 1]
        await self._apply_storylet_effects(context, option.effects)
        context.state.storylet_history.append(active.storylet_id)
        followup = option.followup_storylet
        context.state.active_storylet = None
        if followup and followup in self.storylet_manager.storylets:
            storylet = self.storylet_manager.storylets[followup]
            context.state.active_storylet = ActiveStorylet(
                storylet_id=storylet.id,
                narrative=storylet.narrative,
                options=storylet.options,
            )
            lines = [storylet.narrative]
            for idx, followup_option in enumerate(storylet.options, start=1):
                lines.append(f"{idx}. {followup_option.text}")
            await self._post_display(context, "\n".join(lines))
        else:
            await self._cmd_look(context, Command(verb="look", raw="look"))

    async def _apply_storylet_effects(self, context: SessionContext, effects: Dict[str, object]):
        for flag in effects.get("set_flag", [] if isinstance(effects.get("set_flag"), list) else [effects.get("set_flag")]):
            if flag and flag not in context.state.player.flags:
                context.state.player.flags.append(str(flag))
        for flag in effects.get("clear_flag", [] if isinstance(effects.get("clear_flag"), list) else [effects.get("clear_flag")]):
            if flag in context.state.player.flags:
                context.state.player.flags.remove(flag)
        for trust_key, delta in effects.get("change_trust", {}).items():
            change_trust(context.state.player.trust, trust_key, int(delta))
        for item_id in effects.get("add_item", [] if isinstance(effects.get("add_item"), list) else [effects.get("add_item")]):
            if item_id:
                item = context.state.world.clone_item(str(item_id))
                if item:
                    context.state.player.inventory.append(item)
        for item_id in effects.get("remove_item", [] if isinstance(effects.get("remove_item"), list) else [effects.get("remove_item")]):
            if item_id:
                item = self._find_item_by_name(str(item_id), context.state.player.inventory)
                if item:
                    context.state.player.inventory.remove(item)
        for flag_event in effects.get("log_event", [] if isinstance(effects.get("log_event"), list) else [effects.get("log_event")]):
            if flag_event:
                self._log_event(context, str(flag_event))
        for npc_id, room_id in effects.get("move_npc", {}).items():
            if npc_id in context.state.world.npcs and room_id in context.state.world.rooms:
                context.state.world.place_npc(npc_id, room_id)
        for npc_id, room_id in effects.get("spawn_npc", {}).items():
            if npc_id in context.state.world.npcs and room_id in context.state.world.rooms:
                context.state.world.place_npc(npc_id, room_id)


    async def _advance_time_one_minute(self, context: SessionContext):
        context.state.game_time.minute += 1
        if context.state.game_time.minute >= 1440:
            context.state.game_time.minute = 0
            context.state.game_time += 1
        context.state.scheduler.process(
            context.state.game_time,
            lambda msg: asyncio.create_task(self._post_display(context,msg)),
        )
        self._move_npcs_if_hour_changed(context)
        self._process_gossip(context)
        await self._check_planted_evidence(context)
        await self._process_tailing(context)
        await self._check_curfew_penalty(context)
        await self._check_newspaper(context)
        if context.state.game_time.minute % 15 == 0:
            await self._maybe_trigger_storylet(context)

    async def tick_loop(self):
        while True:
            await asyncio.sleep(1)
            for context in list(self.sessions.values()):
                if not context.state or not context.session.running:
                    continue
            await self._advance_time_one_minute(context)
            context.seconds_since_autosave += 1
            if context.seconds_since_autosave >=300:
                self.save_slot(context)
                context.seconds_since_autosave = 0

    async def handle_client(self, websocket):
        session = PlayerSession(websocket)
        client_id = f"{websocket.remote_address}"
        context = SessionContext(session=session)
        self.sessions[client_id] = context
        await session.send_display("Shanghai Shadows\nEnter save slot codename to continue.\n")
        await session.send_prompt("slot> ")

        try:
            async for message in websocket:
                text = message.strip()
                if not context.state:
                    if not text:
                        await session.send_prompt("slot> ")
                        continue
                    context.slot_name = _sanitize_slot_name(text)
                    context.state = self.load_slot(context.slot_name)
                    await session.send_display(f"Loaded slot '{context.slot_name}'.\n")
                    await self._cmd_look(context, Command(verb="look", raw="lok"))
                    await session.send_prompt()
                    continue

                if context.state.active_storylet:
                    await self._resolve_storylet_choice(context, text)
                    if session.running:
                        await session.send_prompt()
                    continue

                cmd = parse(text)
                if cmd.verb == "pass":
                    await session.send_prompt()
                    continue
                handler = self.command_registry.get(cmd.verb, self._cmd_unknown)
                await handler(context, cmd)
                if session.running:
                    await session.send_prompt()
        except Exception as exc:
            print(f"Client {client_id} disconnected: {exc}")
        finally:
            if context.state:
                self.save_slot(context)
            self.sessions.pop(client_id, None)

    async def _cmd_look(self, context: SessionContext, cmd: Command):
        room = self._room(context)
        if not room:
            await self._post_display(context, "You are nowhere.")
            return
        await self._post_display(context, context.state.world.format_room(room.id))

    async def _cmd_go(self, context: SessionContext, cmd: Command):
        direction = cmd.direct_obj
        if not direction:
            await self._post_display(context, "Go where?")
            return
        room = self._room(context)
        if not room:
            await self._post_display(context, "You are nowhere.")
            return
        dest = room.exits.get(direction)
        if not dest: 
            await self._post_display(context, "You can't go that way.")
            return
        context.state.player.current_room = dest
        context.state.player.hidden = False
        self._log_event(context, f"You moved {direction} into {dest}.")
        await self._cmd_look(context, cmd)
        await self._maybe_trigger_storylet(context)

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
                

