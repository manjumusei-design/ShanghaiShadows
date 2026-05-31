import asyncio
import json
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional

import yaml

from .ai_client import AIClient
from .config import get_setting, load_dotenv
from .journal import collect_recent_events, generate_journal_entry, generate_life_retrospective
from .locales import get as loc
from .locales import load_locale
from .npc import Npc, get_dialogue
from .parser import Command, parse
from .stealth import Disguise, StealthSystem, TailingState
from .storylets import ActiveStorylet, StoryletManager, load_storylets
from .time_system import EventScheduler, GameTime, time_str
from .trust import (TrustMap, apply_trust_delta, change_trust, default_trust, exchange_gossip, get_role_trust, load_trust_rules, migrate_resistance_to_ccp_gmd, summarize_faction_trust,)
from .victory import (check_victory_conditions, compile_legacy_narrative, compute_progress, generate_liberation_newspaper, generate_time_skip_summary, adjust_influence, apply_time_skip,)
from .world import Item, World


EVENTS_PATH = "server/data/events.yaml"
TRUST_RULES_PATH = "server/data/trust_rules.yaml"
DISGUISES_PATH = "server/data/disguises.yaml"
STORYLETS_PATH = "server/data/storylets.yaml"
SAVES_DIR = Path("server/data/saves")
HUNGER_DECAY_RATE = 0.5
HUNGER_HEALTH_DAMAGE = 2
LOW_HUNGER_THRESHOLD = 20
STATE_BROADCAST_INTERVAL = 5

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
    health: int = 100
    hunger: int = 100
    morale: int = 80
    arrested: bool = False
    relationships: Dict[str, Dict[str, int]] = field(default_factory=dict)  # npc_id -> {friendship, fear, indebtedness}


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
    conversation_history: deque = field(default_factory=lambda: deque(maxlen=20))
    event_log: List[Dict] = field(default_factory=list)
    legacy_book: List[Dict] = field(default_factory=list)
    ccp_influence: int = 10
    gmd_influence: int = 15
    
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
    seconds_since_state_broadcast: int = 0


class PlayerSession:
    def __init__(self, websocket):
        self.websocket = websocket
        self.running = True

    async def send_display(self, text: str):
        await self.websocket.send(json.dumps({"type": "display", "payload": text}))

    async def send_prompt(self, text: str = "> "):
        await self.websocket.send(json.dumps({"type": "prompt", "payload": text}))

    async def send_state(self, payload: dict):
        await self.websocket.send(json.dumps)

    async def send_state(self, items: List[str]):
        await self.websocket.send(json.dumps({"type": "completions", "payload": items}))


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
        "food_value": item.food_value,
        "morale_restore": item.morale_restore,
    }


def _deserialize_item(row: Dict[str, object]) -> Item:
    return Item(
        id=str(row["id"]),
        name=str(row["name"]),
        description=str(row["description"]),
        takeable=bool(row.get("takeable", True)),
        readable_text=str(row.get("readable_text", "")),
        planted_on=str(row.get("planted_on", "")),
        food_value=int(row.get("food_value", 0)),
        morale_restore=int(row.get("morale_restore", 0)),
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
        load_locale(get_setting("Locale", "en"))
        SAVES_DIR.mkdir(parents=True, exist_ok=True)
        self.ai_client = AIClient()
        self.disguises = load_disguises(DISGUISES_PATH)
        self.stealth = StealthSystem(self.disguises)
        storylets = load_storylets(STORYLETS_PATH)
        custom_storylets_path = Path("server/data/custom/storylets.yaml")
        if custom_storylets_path.exists():
            storylets.update(load_storylets(str(custom_storylets_path)))
        self.storylet_manager = StoryletManager(storylets)
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
            "ask about": self._cmd_ask_about,
            "whisper": self._cmd_stub,
            "give": self._cmd_stub,
            "use": self._cmd_stub,
            "eat": self._cmd_eat,
            "sleep": self._cmd_sleep,
            "rest": self._cmd_rest,
            "bond": self._cmd_bond,
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

    async def _broadcast_state(self, context: SessionContext):
        state = context.state
        if not state:
            return
        summary = summarize_faction_trust(state.player.trust)
        disguise = self.disguises.get(state.player.disguise)
        await context.session.send_state({
            "health": state.player.health,
            "hunger": state.player.hunger,
            "morale": state.player.morale,
            "trust": summary,
            "disguise": disguise.name if disguise else "",
            "game_time": time_str(state.game_time),
            "day": state.game_time.day,
            "progress_percent": compute_progress(state.game_time.day),
            "ccp_influence": state.ccp_influence,
            "gmd_influence": state.gmd_influence,
        })

    def _build_completions(self, context: SessionContext) -> List[str]:
        verbs = [v for v in self.command_registry if v not in ("unknown", "stub")]
        room = self._room(context)
        if room:
            verbs.extend(room.exits.keys())
            for npc_id in room.npcs:
                npc = context.state.world.npcs.get(npc_id)
                if npc:
                    verbs.append(npc.name.lower())
        return verbs

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
    
    def _resolve_npc(self, context: SessionContext, name: str) -> Optional[str]:
        room = self._room(context)
        return self._find_npc_by_name(context, name, room.npcs if room else[])

    def _room_npcs(self, context: SessionContext) -> List[str]:
        room = self._room(context)
        return room.npcs if room else []

    async def _post_display(self, context: SessionContext, text: str):
        await context.session.send_display(text if text.endswith("\n") else text + "\n")

    def _log_event(self, context: SessionContext, text: str) -> None:
        context.state.player.world_events.append(text)
        context.state.player.world_events = context.state.player.world_events[-50:]
        context.state.event_log.append({
            "day": context.state.game_time.day,
            "minute": context.state.game_time.minute,
            "text": text,
        })
        context.state.event_log = context.state.event_log[-500:]

    def _record_conversation(self, context: SessionContext, npc_id: str, player_input: str, npc_response: str):
        context.state.conversation_history.append({
            "npc_id": npc_id,
            "player_input": player_input,
            "npc_response": npc_response,
            "time": context.state.game_time.minute,
            "day": context.state.game_time.day,
        })
        
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
            await self._post_display(context, loc("curfew.warning"))

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
            await self._post_display(context, loc("cmd_tail.target_vanished"))
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
        await self._post_display(context, loc("newspaper.delivery"))

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
                blocks.append(f"{loc('newspaper.fallback_prefix')} {idx}\nOfficials insist order holds after reports that {event.lower()}")
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
            await context.session.send_prompt(loc("storylet.choose").format(max=len(active.options)))
            return
        if choice < 1 or choice > len(active.options):
            await context.session.send_prompt(loc("storylet.choose").format(max=len(active.options)))
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
        def _as_list(val):
            if isinstance(val, list):
                return val
            return [val] if val else []

        for flag in _as_list(effects.get("set_flag")):
            if flag and flag not in context.state.player.flags:
                context.state.player.flags.append(str(flag))
        for flag in _as_list(effects.get("clear_flag")):
            if flag in context.state.player.flags:
                context.state.player.flags.remove(flag)
        for trust_key, delta in effects.get("change_trust", {}).items():
            change_trust(context.state.player.trust, trust_key, int(delta))
        for item_id in _as_list(effects.get("add_item")):
            if item_id:
                item = context.state.world.clone_item(str(item_id))
                if item:
                    context.state.player.inventory.append(item)
        for item_id in _as_list(effects.get("remove_item")):
            if item_id:
                item = self._find_item_by_name(str(item_id), context.state.player.inventory)
                if item:
                    context.state.player.inventory.remove(item)
        for flag_event in _as_list(effects.get("log_event")):
            if flag_event:
                self._log_event(context, str(flag_event))
        for key in ("move_npc", "spawn_npc"):
            for npc_id, room_id in effects.get(key, {}).items():
                if npc_id in context.state.world.npcs and room_id in context.state.world.rooms:
                    context.state.world.place_npc(npc_id, room_id)
        
        #Ded 
        if "kill_player" in effects:
            death_reason = effects.get("death_reason:, "You have met your end in Shanghai.")
            asnycio.create_task(self._handle_player_death(context, death_reason))
            return

        if "arrest_player" in effects:
            context.state.player.arrested = True
            self._log_event(context, "You have been arrested.")
            await self._post_display(context, loc("death.arrest_message"))

            for faction_key, delta in effects.get("change_influence", {}.items():
                context.state.ccp_influence, context.state.gmd_influence = adjust_influence(
                    context.state.ccp_infuence, context.state.gmd_influence, faction_key, int(delta)
                )

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
        self._process_survival_tick(context)

        #Deathcon
        is_dead, death_message = self._check_death_conditions(context)
        if is dead:
            asyncio.create_task(self._handle_player_death(context, death_message))
            return

        if context.state.game_time.minute == 0:
            ending = check_victory_conditions(
                context.state.game_time.day,
                context.state.ccp_influence,
                context.state.gmd_influence,
            )
            if ending:
                asyncio.create_task(self._trigger_ending(context, ending))
                return

    def _process_survival_tick(self, contexxt: SessionContext):
        context.state.player.hunger = max(0, context.state.player.hunger - HUNGER_DECAY_RATE)
        if context.state.player.hunger <= LOW_HUNGER_THRESHOLD:
            context.state.player_.health = max(0, context.state.player.health - HUNGER_HEALTH_DAMAGE)
            if context.state.game_time.minute % 30 == 0:
                asyncio.create_task(self._post_display(context, loc("hunger.cramps")))
        if context.state.player.hunger > 80 and context.state.game_time.minute % 60 == 20:
            context.state.player.health = min(100, context.state.player.health + 1)

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
            context.seconds_since_state_broadcast += 1
            if context.seconds_since_state_broadcast >= STATE_BROADCAST_INTERVAL:
                await self._broadcast_state(context)
                context.seconds_since_state_broadcast = 0

    async def handle_client(self, websocket):
        session = PlayerSession(websocket)
        client_id = f"{websocket.remote_address}"
        context = SessionContext(session=session)
        self.sessions[client_id] = context
        await session.send_display(loc("greeting"))
        await session.send_prompt(loc("slot_prompt"))

        try:
            async for message in websocket:
                text = message.strip()
                if not context.state:
                    if not text:
                        await session.send_prompt("slot> ")
                        continue
                    context.slot_name = _sanitize_slot_name(text)
                    context.state = self.load_slot(context.slot_name)
                    if "awaiting_new_character" in context.state.player.flags:
                        await self._initialize_new_character(context)
                    await session.send_display(loc("loaded").format(slot=context.slot_name))
                    await self._cmd_look(context, Command(verb="look", raw="lok"))
                    await context.session.send_completions(self._build_completions(context))
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
            await self._post_display(context, loc("cmd_go.no_direction"))
            return
        await self._post_display(context, context.state.world.format_room(room.id))
        await context.sessopm.send_completions(self._build_completions(context))
        
    async def _cmd_go(self, context: SessionContext, cmd: Command):
        direction = cmd.direct_obj
        if not direction:
            await self._post_display(context, loc("cmd_go.no_direction"))
            return
        room = self._room(context)
        if not room:
            await self._post_display(context, loc("cmd_go.nowhere"))
            return
        dest = room.exits.get(direction)
        if not dest: 
            await self._post_display(context, loc("cmd_go.no_exit"))
            return
        context.state.player.current_room = dest
        context.state.player.hidden = False
        self._log_event(context, f"You moved {direction} into {dest}.")
        await self._cmd_look(context, cmd)
        await self._maybe_trigger_storylet(context)

    async def _cmd_take(self, context: SessionContext, cmd: Command):
        if not cmd.direct_obj:
            await self._post_display(context, loc("cmd_take.no_target"))
            return
        room = self._room(context)
        item = self._find_item_by_name(cmd.direct_obj, room.items if room else [])
        if not item:
            await self._post_display(context, loc("cmd_take.not_here"))
            return
        if not item.takeable:
            await self._post_display(context, loc("cmd_take.not_takeable"))
            return
        room.items.remove(item)
        context.state.player.inventory.append(item)
        self._log_event(context, f"You took {item.name}.")
        await self._post_display(context, f"You take {item.name}.")
        await self._maybe_trigger_storylet(context)

    async def _cmd_drop(self, context: SessionContext, cmd: Command):
        if not cmd.direct_obj:
            await self._post_display(context, loc("cmd_drop.no_target"))
            return
        item = self._find_item_by_name(cmd.direct_obj, context.state.player.inventory)
        if not item:
            await self._post_display(context, loc("cmd_drop.not_held"))
            return
        context.state.player.inventory.remove(item)
        room = self._room(context)
        if room:
            room.items.append(item)
        self._log_event(context, f"You dropped {item.name}.")
        await self._post_display(context, f"You drop {item.name}.")
    
    async def _cmd_inventory(self, context: SessionContext, cmd: Command):
        if not context.state.player.inventory:
            await self._post_display(context, loc("cmd_inventory.empty"))
            return
        lines = ["cmd_inventory.header"]
        for item in context.state.player.inventory:
            lines.append(f"- {item.name}")
        await self._post_display(context, "\n".join(lines))
    
    async def _generate_npc_dialogue(self, context: SessionContext, npc: Npc, player_input: str) -> str:
        room = self._room(context)
        memory_context = ""
        if npc.memory:
            memory_context = "Recent memories: " + "; ".join(npc.memory[-3:])
        trust_score = get_role_trust(context.state.player.trust, npc.faction, npc.role)
        trust_desc = "friendly" if trust_score > 70 else "hostile" if trust_score < 30 else "neutral"
        rel = self._get_relationship(context, npc.id)
        rel_context = (
            "You consider this player a friend." if rel["friendship"] > 70
            else "You are somewhat afraid of this player." if rel["fear"] > 70
            else "You feel indebted to this player." if rel["indebtedness"] > 50
            else ""
        )
        prompt = f"""You are {npc.name}, a {npc.role} of the {npc.faction} faction in occupied Shanghai, November 1938.
Personality: {npc.personality}.
Awareness level: {npc.awareness}/100.
Relationship with player: {trust_desc} (trust: {trust_score}/100).
{memory_context}
{rel_context}
Current location: {room.title if rooom else "somewhere in Shanghai"}.
The player says: "{player_input}"
Respond in character, 1-2 sentences maximum. Keep it period-appropriate, emotionally authentic, and consistent with your faction alignment. Do not break character or acknowledge being an AI. """

        try:
            result = await self.ai_client.chat_text([{"role": "user", "content": prompt}], timeout_seconds=3.0)
            if result:
                return result.strip()
        except Exception as e:
            print(f" AI dialogue generation fail: {e}")
        return get_dialogue(npc, context.state.player.trust)
            
    async def _cmd_talk_to(self, context: SessionContext, cmd: Command):
        if not cmd.direct_obj:
            await self._post_display(context, loc("cmd_talk_to.no_target"))
            return
        npc_id = self._resolve_npc(context, cmd.direct_obj)
        if not npc_id:
            await self._post_display(context, loc("cmd_talk_to.not_here"))
            return
        npc = context.state.world.npcs[npc_id]
        line = await self._generate_npc_dialogue(context, npc, f"Hello, {npc.name}.")
        await self._post_display(context, f'{npc.name} says, "{line}"')
        self._record_conversation(context, npc_id, f"Hello, {npc.name}.", line)
        self._apply_action_trust(context, f"talk_to_{npc.faction}.{npc.role}", self._room_npcs(context))
        self._log_event(context, f"You spoke with {npc.name}.")
        await self._maybe_trigger_storylet(context)

    async def _cmd_ask_about(self, context: SessionContext, cmd: Command):
        if not cmd.direct_obj or not cmd.indirect_obj:
            await self._post_display(context, loc("cmd_ask_about.no_target"))
            return
        npc_id = self._resolve_npc(context, cmd.direct_obj)
        if not npc_id:
            await self._post_display(context, loc("cmd_ask_about.not_here"))
            return
        npc = context.state.world.npcs[npc_id]
        topic = cmd.indirect_obj
        line = await self._generate_npc_dialogue(context, npc, f"Tell me about {topic}.")
        await self._post_display(context, f'{npc.name} says, "{line}"')
        self._record_conversation(context, npc_id, f"Tell me about {topic}.", line)
        self._apply_action_trust(context, f"ask_about_{npc.faction}.{npc.role}", self._room_npcs(context))
        self._log_event(context, f"You asked {npc.name} about {topic}.")
        await self._maybe_trigger_storylet(context)

    async def _cmd_wait(self, context: SessionContext, cmd: Command):
        if not cmd.direct_obj:
            await self._post_display(context, loc("cmd_wait.no_duration"))
            return
        try:
            minutes = int(cmd.direct_obj)
        except ValueError:
            await self._post_display(context, loc("cmd_wait.invalid"))
            return
        minutes = max(1, min(minutes, 240))
        for _ in range(minutes):
            await self.advance_time_one_minute(context)
        self. _log_event(context, f"You waited {minutes} minutes.")
        await self._post_display(context, f"You wait {minutes} minutes. It is now {time_str(context.state.game_time)}.")

    async def _cmd_status(self, context: SessionContext, cmd: Command):
        disguise = self.disguises.get(context.state.player.disguise)
        lines = [time_str(context.state.game_time)]
        lines.append(f"Health: {context.state.player.health}/100")
        lines.append(f"Hunger: {context.state.player.hunger}/100")
        lines.append(f"Morale: {context.state.player.morale}/100")
        lines.append(f"Disguise: {disguise.name if disguise else 'none'}")
        lines.append(f"Stealth skill: {context.state.player.stealth_skill}")
        lines.append("Trust:")
        lines.extend(self._summary_trust_lines(context))
        if context.state.player.flags:
            lines.append("Flags: " + ", ".join(sorted(context.state.player.flags)))
        await self._post_display(context, "\n".join(lines))

    def _get_relationship(self, context: SessionContext, npc_id:)
        if npc_id not in context.state.player.relationships:
            context.state.player.relationships[npc_id] = {}
        return context.state.player.relationships[npc_id]

    def _modify_relationship(self, context: SessionContext, npc_id: str, changes: Dict[str, int]):
        rel = self._get_relationship(context, npc_id)
        for key, delta in changes.items():
        if key in rel:
            rel[key] = max(0, min(100, rel[key] + delta))

    async def _cmd_disguise_as(self, context: SessionContext, cmd: Command):
        if not cmd.direct_obj:
            await self._post_display(context, loc("cmd_disguise_as.no_target"))
            return
        query = cmd.direct_obj.lower().replace(" ", "_")
        disguise = self.disguises.get(query)
        if not disguise:
            await self._post_display(context, loc("cmd_disguise_as.not_found"))
            return
        context.state.player.disguise = disguise.id
        self._log_event(context, f"You adopted the disguise of {disguise.name}.")
        await self._post_display(context, f"You settle into the role of {disguise.name}. {disguise.description}")

    async def _cmd_tail(self, context: SessionContext, cmd: Command):
        if not cmd.direct_obj:
            await self._post_display(context, loc("cmd_tail.no_target"))
            return
        npc_id = self._resolve_npc(context, cmd.direct_obj)
        if not npc_id:
            await self._post_display(context, loc("cmd_tail.not_here"))
            return
        context.state.tailing_state = self.stealth.start_tail(npc_id)
        context.state.tailing_state.last_checked_minute = (context.state.game_time.day - 1) * 1440 + context.state.game_time.minute
        target = context.state.world.npcs[npc_id]
        self._log_event(context, f"You began tailing {target.name}.")
        await self._post_display(context, f"You fall in behind {target.name} and try not to be remembered.")

    async def _cmd_hide(self, context: SessionContext, cmd: Command):
        room = self._room(context)
        observers = [context.state.world.npcs[npc_id] for npc_id in room.npcs] if room else []
        success, _ = self.stealth.hide_check(
            context.state.player.stealth_skill,
            self._disguise_bonus(context),
            room.indoors if room else False,
            observers,
        )
        context.state.player.hidden = success
        if success:
            self._log_event(context, "You found a place to hide.")
            await self._post_display(context, "You slip into shadow and become part of the room's silence.")
        else:
            self._log_event(context, "You failed to hide cleanly.")
            await self._post_display(context, "You try to hide, but too many eyes still know where you stand.")
        
    async def _cmd_plant(self, context: SessionContext, cmd: Command):
        if not cmd.direct_obj:
            await self._post_display(context, loc("cmd_plant.no_target"))
            return
        item = self._find_item_by_name(cmd.direct_obj, context.state.player.inventory)
        if not item:
            await self._post_display(context, loc("cmd_plant.not_held"))
            return
        target = cmd.indirect_obj or cmd.preposition or ""
        room = self._room(context)
        context.state.player.inventory.remove(item)
        context.state.planted_evidence.append(
            {
                "room_id": room.id if room else context.state.player.current_room,
                "item_id": item.id,
                "item_name": item.name,
                "target": target,
            }
        )
        self._log_event(context, f"You planted {item.name} for {target or 'whoever finds it'}.")
        await self._post_display(context, f"You leave {item.name} where someone else will one day pay for noticing it.")

    async def _cmd_read(self, context: SessionContext, cmd: Command):
        if not cmd.direct_obj:
            await self._post_display(context, loc("cmd_read.no_target"))
            return
        item = self._find_item_by_name(cmd.direct_obj, context.state.player.inventory)
        if not item:
            await self._post_display(context, loc("cmd_read.not_held"))
            return
        if not item.readable_text:
            await self._post_display(context, loc("cmd_read.nothing_written"))
            return
        await self._post_display(context, item.readable_text)
        
    async def _cmd_journal(self, context: SessionContext, cmd: Command):
        recent = collect_recent_events(context.state.event_log, context.state.game_time, hours=24)
        if not recent:
            await self._post_display(context, loc("cmd_journal.blank"))
            return
        entry = await generate_journal_entry(self.ai_client, recent, context.state.game_time)
        header = f"--- Journal Entry, {time_str(context.state.game_time)} ---"
        await self._post_display(context, f"{header}\n{entry}")

    async def _cmd_help(self, context: SessionContext, cmd: Command):
        await self._post_display(
            context,
            loc("cmd_help.text")
        )

    async def _cmd_quit(self, context: SessionContext, cmd: Command):
        self.save_slot(context)
        await self._post_display(context, loc("cmd_quit.goodbye"))
        context.session.running = False
        await context.session.websocket.close()

    async def _cmd_stub(self, context: SessionContext, cmd: Command):
        await self._post_display(context, loc("cmd_stub.not_implemented").format(verb=cmd.verb.upper()))

    async def _def_cmd_eat(self, context: SessionContext, cmd: Command):
        if not cmd.direct_obj:
            await self._post_display(context, loc("cmd_eat.no_target"))
            return
        item = self._find_item_by_name(cmd.direct_obj, context.state.player.inventory)
        if not item:
            await self._post_display(context, loc("cmd_eat.not_held"))
            return
        food_value = item.food_value
        morale_restore = item.morale_restore
        if food_value == 0:
            await self._post_display(context, loc("cmd_eat.not_food"))
            return
        context.state.player.inventory.remove(item)
        context.state.player.hungry = min(100, context.state.player.hunger + food_value)
        context.state.player.morale = min(100, context.state.player.morale + morale_restore)
        self._log_event(context, f"You ate {item.name}.")
        await self._post_display(context, f"You eat {item.name}. It settles your stomach.")
        
    async def _cmd_sleep(self, context: SessionContext, cmd: Command):
        room = self._room(context)
        if not room or not room.indoors:
            await self._post_display(contexxt, "You need shelter to rest safely.")
            return
        hours = 6
        minutes = hours * 60
        context.state.player.health = min(100, context.state.player.health + 10)
        context.state.player.morale = min(100, context.state.player.morale + 15)
        context.state.player.hunger = max(0, context.state.player.hunger - 20)
        for _ in range(minutes):
            await self._advance_time_one_minute(context)
        self._log_event(context, "You slept for several hours.")
        await self._post_display(context, f"You sleep for {hours} hours and wake refreshed. It is now {time_str(context.state.game_time)}.")
    
    async def _cmd_rest(self, context: SessionContext, cmd: Command): 
        context.state.player.morale = min(100, context.state.player.morale + 5)
        for _ in range(15):
            await self._advance_time_one_minute(context)
        await self._post_display(context, "You rest quietly for fifteen minutes, catching your breath.") # Test since idk how this will work and interact with other users. 

    async def _cmd_bond(self, context: SessionContext, cmd: Command):
        if not cmd.direct_obj:
            await self._post_display(context, "Bond with whom?")
            return
        npc_id = self._resolve_npc(context, cmd.direct_obj)
        if not npc_id:
            await self._post_display(context, "They aren't here.")
            return

        action = cmd.preposition or cmd.indirect_obj or "share_meal"
        if action == "share_meal":
            food_items = [item for item in context.state.player.inventory if item.food_value > 0]
            if not food_items:
                await self._post_display(context, "You have no food to share.")
                return
            food = food_items[0]
            context.state.player.inventory.remove(food)
            self._modify_relationship(context, npc_id, {"friendship": 15, "indebtedness": 5})
            self._log_event(context, f"You shared a meal with {context.state.world.npcs[npc_id].name}.")
            await self._post_display(context, f"You share {food.name}. They seem grateful for the company.")

        elif action == "gift":
            if not cmd.indirect_obj:
                await self._post_display(context, "Gift what item?")
                return
            item = self._find_item_by_name(cmd.indirect_obj, context.state.player.inventory)
            if not item:
                await self._post_display(context, "You don't have that.")
                return
            context.state.player.inventory.remove(item)
            gift_value = 10 if item.readable_text else 20
            self._modify_relationship(context, npc_id, {"friendship": gift_value, "indebtedness": gift_value // 2})
            self._log_event(context, f"You gifted {item.name} to {context.state.world.npcs[npc_id].name}.")
            await self._post_display(context, f"You give {item.name}. Their expression softens.")
        else:
            await self._post_display(context, "Bond actions: SHARE MEAL, GIFT <item>")
        await self._maybe_trigger_storylet(context)

    async def _cmd_unknown(self, context: SessionContext, cmd: Command):
        await self._post_display(context, f"I don't understand '{cmd.raw}'. Try HELP.")

    def save_slot(self, context: SessionContext):
        state = context.state
        if not state or not context.slot_name:
            return
        payload = {
            "player": {
                "name": state.player.name,
                "current_room": state.player.current_room,
                "inventory": [_serialize_item(item) for item in state.player.inventory],
                "trust": state.player.trust,
                "disguise": state.player.disguise,
                "stealth_skill": state.player.stealth_skill,
                "hidden": state.player.hidden,
                "flags": state.player.flags,
                "world_events": state.player.world_events,
                "newspapers": state.player.newspapers,
                "health": state.player.health,
                "hunger": state.player.hunger,
                "morale": state.player.morale,
                "arrested": state.player.arrested,
                "relationships": state.player.relationships,
            },
            "time": {"day": state.game_time.day, "minute": state.game_time.minute},
            "room_items": {
                room_id: [_serialize_item(item) for item in room.items]
                for room_id, room in state.world.rooms.items()
            },
            "npc_locations": state.world.npc_locations,
            "npc_memory": {npc_id: npc.memory for npc_id, npc in state.world.npcs.items()},
            "scheduler": state.scheduler.to_payload(),
            "storylet_history": state.storylet_history,
            "active_storylet": state.active_storylet.storylet_id if state.active_storylet else "",
            "tailing_state": {
                "target_npc_id": state.tailing_state.target_npc_id,
                "distance": state.tailing_state.distance,
                "elapsed_minutes": state.tailing_state.elapsed_minutes,
                "last_checked_minute": state.tailing_state.last_checked_minute,
            } if state.tailing_state else None,
            "planted_evidence": state.planted_evidence,
            "rumour_mill": state.rumour_mill,
            "last_curfew_penalty_day": state.last_curfew_penalty_day,
            "last_newspaper_day": state.last_newspaper_day,
            "conversation_history": state.conversation_history,
            "player_died": player_died" in context.state.player.flags,
        }
        self._save_path(context.slot_name).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _check_death_conditions(self, context: SessionContext) -> tuple[bool, str]:
        player = context.state.player
        if player.health <= 0:
            return True, "You collapse in the cold alley, too weak to continue. Shanghai claims another victim."

        if player.arrested:
            kempeitai_trust = get_role_trust(player.trust, "kempeitai", None)
            if kempeitai_trust < 25:
                return True, "The Kempeitai don't believe your story. They drag you to Bridge House Prison. You will not return."
        return False, ""
    
    async def _generate_obituary(self, context: SessionContext, death_message: str) -> str:
        player = context.state.player

        key_flags = [flag for flag in player.flags if flag.startswith("legacy_")]
        key_events = player.world_events[-5:] if player.world_events else ["A quiet life in Shanghai"]
        cause = "natural causes" if player.health <= 0 else "arrested by authorities"

        prompt = f"""Write a short 1938 Shanghai Times obituary for a person with these characteristics:

Name: {player.name}
Reputation: Respected among: {[f for f, roles in player.trust.items() if any(v > 70 for v in roles.values())]}
Key actions: {key_events}
Cause of death: {cause}

Style requirements:
- Factual and cold, with subtle propaganda undertones
- 2-3 sentences maximum
- Period-appropriate language for 1938 Shanghai
- Mention their likely impact on the community

Respond as plain text, no JSON formatting."""

        try:
            result = await self.ai_client.chat_text([{"role": "user", "content": prompt}], timeout_seconds=4.0)
            if result:
                return result.strip()
        except Exception as e:
            print(f"Obituary generation failed: {e}")
        return f"{player.name}, a resident of Shanghai, passed away recently. They will be remembered by those who knew them."

    async def _handle_player_death(self, context: SessionContext, death_message: str):
        obituary = await self._generate_obituary(context, death_message)
        end_screen = f"""THE END

{death_message}

---
{obituary}
---

Your legacy in Shanghai will be remembered by those who knew you.
"""

        await self._post_display(context, end_screen)
        context.state.player.flags.append("player_died")
        self.save_slot(context)
        context.session.running = False
        await context.session.websocket.close()

    async def _generate_character_background(self, context: SessionContext) -> dict:
        """Generate new character background based on previous character's legacy."""
        previous_player = context.state.player

        high_trust_factions = [f for f, roles in previous_player.trust.items() if any(v > 70 for v in roles.values())]
        low_trust_factions = [f for f, roles in previous_player.trust.items() if any(v < 30 for v in roles.values())]
        legacy_flags = [flag for flag in previous_player.flags if flag.startswith("legacy_")]

        prompt = f"""Generate a character background for a new person starting in occupied Shanghai, November 1938.

Previous character context:
- Name: {previous_player.name}
- Known for helping: {high_trust_factions if high_trust_factions else "no particular faction"}
- Suspicious to: {low_trust_factions if low_trust_factions else "no particular faction"}
- Legacy actions: {legacy_flags if legacy_flags else "nothing remarkable"}

Generate background details:
1. A name (Chinese or European/Japanese)
2. A brief connection to the previous character
3. Starting trust bonuses/penalties based on rumors
4. A personal motivation

Respond as JSON with keys: name, background_connection, trust_adjustments, motivation"""

        try:
            result = await self.ai_client.chat_json([{"role": "user", "content": prompt}], timeout_seconds=4.0)
            if result:
                return result
        except Exception as e:
            print(f"Background generation failed: {e}")

        return {
            "name": "Chen Wei",
            "background_connection": "You heard stories about the previous person who lived here.",
            "trust_adjustments": {},
            "motivation": "Just trying to survive until the war ends."
        }

    def _apply_inherited_trust(self, context: SessionContext,adjustments: dict) -> TrustMap:
        base_trust = default_trust()

        for key, delta in adjustments.items():
            change_trust(base_trust, key, int(delta))
        return base_trust

    async def _initialize_new_character(self, context: SessionContext):
        background = await self._generate_character_background(context)

        new_player = PlayerState(
            name=background.get("name", "Newcomer"),
            current_room="bund_dawn",
            inventory=[],
            trust=self._apply_inherited_trust(context, background.get("trust_adjustments", {})),
            disguise="",
            stealth_skill=55,
            hidden=False,
            flags=[],
            world_events=[],
            newspapers=[],
            health=100,
            hunger=100,
            morale=80,
            arrested=False
        )

        old_player = context.state.player
        context.state.player = new_player
        context.state.conversation_history = deque(maxlen=20)
        context.state.storylet_history = []
        context.state.active_storylet = None
        context.state.tailing_state = None
        context.state.planted_evidence = []
        context.state.last_curfew_penalty_day = 0

        welcome_text = f"""
              A NEW CHAPTER BEGINS

You are {new_player.name}, {background['background_connection']}

{background['motivation']}

The city remembers what came before, and now you must find your own path.
"""

        await self._post_display(context, welcome_text)
        await self._cmd_look(context, Command(verb="look", raw="look"))

    def load_slot(self, slot_name: str) -> GameState:
        state = self._new_state()
        path = self._save_path(slot_name)
        if not path.exists():
            return state
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return state
        
        player_died = data.get("player_died", False)
        if player_died:
            self._load_world_state_only(state, data)
            state.player.flags.append("awaiting_new_character")
        else:
            self._load_complete_state(state, data)
        return state

    def _load_world_state_only(self, state: GameState, data: dict):
        state.game_time.day = int(data.get("time", {}).get("day", 1))
        state.game_time.minute = int(data.get("time", {}).get("minute", 0))
        room_items = data.get("room_items")
        if isinstance(room_items, dict):
            for room in state.world.rooms.values():
                room.items = []
            for room_id, rows in room_items.items():
                room = state.world.rooms.get(room_id)
                if room:
                    room.items = [_deserialize_item(row) for row in rows]

        npc_locations = data.get("npc_locations")
        if isinstance(npc_locations, dict):
            for room in state.world.rooms.values():
                room.npcs = []
            state.world.npc_locations = {}
            for npc_id, room_id in npc_locations.items():
                if npc_id in state.world.npcs and room_id in state.world.rooms:
                    state.world.place_npc(npc_id, room_id)
        for npc_id, memories in data.get("npc_memory", {}).items():
            npc = state.world.npcs.get(npc_id)
            if npc:
                npc.memory = list(memories)
        state.scheduler.load_from_payload(data.get("scheduler", []))
        state.rumour_mill = dict(data.get("rumour_mill", {}))

    def _load_complete_state(self, state: GameState, data: dict):
        self._load_world_state_only(state, data)

        player_data = data.get("player", {})
        state.player.name = player_data.get("name", state.player.name)
        state.player.current_room = player_data.get("current_room", state.player.current_room)
        state.player.inventory = [_deserialize_item(row) for row in player_data.get("inventory", [])]
        state.player.trust = player_data.get("trust", default_trust())
        state.player.disguise = player_data.get("disguise", "")
        state.player.stealth_skill = int(player_data.get("stealth_skill", 55))
        state.player.hidden = bool(player_data.get("hidden", False))
        state.player.flags = list(player_data.get("flags", []))
        state.player.world_events = list(player_data.get("world_events", []))
        state.player.newspapers = list(player_data.get("newspapers", []))
        state.player.health = int(player_data.get("health", 100))
        state.player.hunger = int(player_data.get("hunger", 100))
        state.player.morale = int(player_data.get("morale", 80))
        state.player.arrested = bool(player_data.get("arrested", False))
        state.player.relationships = dict(player_data.get("relationships", {}))
        state.storylet_history = list(data.get("storylet_history", []))
        storylet_id = data.get("active_storylet", "")
        if storylet_id and storylet_id in self.storylet_manager.storylets:
            storylet = self.storylet_manager.storylets[storylet_id]
            state.active_storylet = ActiveStorylet(
                storylet_id=storylet.id,
                narrative=storylet.narrative,
                options=storylet.options,
            )
        tail = data.get("tailing_state")
        if tail:
            state.tailing_state = TailingState(
                target_npc_id=tail["target_npc_id"],
                distance=int(tail.get("distance", 2)),
                elapsed_minutes=int(tail.get("elapsed_minutes", 0)),
                last_checked_minute=int(tail.get("last_checked_minute", 0)),
            )
        state.planted_evidence = list(data.get("planted_evidence", []))
        state.rumour_mill = dict(data.get("rumour_mill", {}))
        state.last_curfew_penalty_day = int(data.get("last_curfew_penalty_day", 0))
        state.last_newspaper_day = int(data.get("last_newspaper_day", 0))
        state.conversation_history = deque(data.get("conversation_history", []), maxlen=20)
        return state