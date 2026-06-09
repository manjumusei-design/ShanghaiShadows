import asyncio
import random
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, NamedTuple, Optional, TYPE_CHECKING
import yaml

from .config import get_setting, load_dotenv
from .journal import collect_recent_events, format_journal, format_life_retrospective
from .locales import get as loc
from .locales import load_locale
from .npc import Npc, get_contextual_dialogue
from .parser import Command, parse
from .player_data import PlayerData
from .serialization import _load_yaml, deserialize_item, serialize_item
from .session import Session
from .stealth import Disguise, StealthSystem, TailingState
from .storylets import ActiveStorylet, StoryletManager, load_storylets
from .time_system import EventScheduler, GameTime, time_str
from .trust import (TrustMap, apply_trust_delta, change_trust, default_trust, exchange_gossip, get_role_trust, load_trust_rules, migrate_resistance_to_ccp_gmd, summarize_faction_trust,)
from .victory import (check_victory_conditions, compile_legacy_narrative, compute_progress, generate_liberation_ending, generate_time_skip_summary, adjust_influence, apply_time_skip,)
from .world import Item, World, replace
from .game_world import SharedWorldState
from .combat import resolve_attack, degrade_weapon, degrade_armour
from .constants import (
    EVENTS_PATH, TRUST_RULES_PATH, DISGUISES_PATH, STORYLETS_PATH,
    OBITUARY_PATH, BACKGROUNDS_PATH, CURFEW_MINUTE, STATE_BROADCAST_INTERVAL,
    EVENT_LOG_MAXLEN, WORLD_EVENTS_MAXLEN, CONVERSATION_HISTORY_MAXLEN,
    HUNGER_DECAY_RATE, HUNGER_HEALTH_DAMAGE, LOW_HUNGER_THRESHOLD,
    RICE_BOWL_COST, BAOZI_COST, TEA_COST, PICKPOCKET_BASE,
    MISSION_FABI_RANGE, NURSE_COST, NURSE_HEAL,
)

if TYPE_CHECKING:
    from .session_manager import SessionManager

SAVES_DIR = Path("server/data/saves")


class CommandContext(NamedTuple):
    session: Session
    shared: SharedWorldState
    session_manager: "SessionManager"
    disguises: Dict[str, Disguise]
    stealth: StealthSystem
    storylet_manager: StoryletManager
    room: Optional[Any]


def _sanitize_slot_name(raw: str) -> str:
    import re
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", raw.strip().lower()).strip("_")
    return cleaned or "default"


def _room(ctx: CommandContext):
    return ctx.shared.world.get_room(ctx.session.player.current_room) if ctx.shared else None


def find_item_by_name(name: str, items: List[Item]) -> Optional[Item]:
    q = name.lower().strip()
    for item in items:
        if item.name.lower() == q or item.id.lower() == q:
            return item
    for item in items:
        if q in item.name.lower() or q in item.id.lower():
            return item
    return None


def find_npc_by_name(ctx: CommandContext, name: str, npcs: List[str]) -> Optional[str]:
    q = name.lower().strip()
    for npc_id in npc_ids:
        npc = ctx.shared.world.npcs.get(npc_id)
        if npc and (q in npc.name.lower() or q in npc.id.lower()):
            return npc_id
    return None


def resolve_npc(ctx: CommandContext, name: str) -> Optional[str]:
    room = _room(ctx)
    return find_npc_by_name(ctx, name, room.npcs if room else [])


def room_npcs(ctx: CommandContext) -> List[str]:
    room = _room(ctx)
    return room.npcs if room else []


async def post_display(ctx: CommandContext, text: str) -> None:
    await ctx.session.send_display(text if text.endswith("\n") else text + "\n")


def log_event(ctx: CommandContext, text: str) -> None:
    from collections import deque

    if not isinstance(ctx.session.player.world_events, deque) or ctx.session.player.world_events.maxlen != WORLD_EVENTS_MAXLEN:
        ctx.session.player.world_events = deque(ctx.session.player.world_events, maxlen=WORLD_EVENTS_MAXLEN)
    ctx.session.player.world_events.append(text)

    if not isinstance(ctx.shared.event_log, deque) or ctx.shared.event_log.maxlen != EVENT_LOG_MAXLEN:
        ctx.shared.event_log = deque(ctx.shared.event_log, maxlen=EVENT_LOG_MAXLEN)
    ctx.shared.event_log.append({
        "day": ctx.shared.game_time.day,
        "minute": ctx.shared.game_time.minute,
        "text": text,
    })


def record_conversation(ctx: CommandContext, npc_id: str, player_input: str, npc_response: str):
    ctx.session.player.conversation_history.append({
        "npc_id": npc_id,
        "player_input": player_input,
        "npc_response": npc_response,
        "time": ctx.shared.game_time.minute,
        "day": ctx.shared.game_time.day,
    })


def summary_trust_lines(ctx: CommandContext) -> List[str]:
    summary = summarize_faction_trust(ctx.session.player.trust)
    return [f"- {faction}: {value}" for faction, value in sorted(summary.items())]


def disguise_bonus(ctx: CommandContext) -> int:
    disguise = ctx.disguises.get(ctx.session.player.disguise)
    return disguise.bonus if disguise else 0


def apply_action_trust(ctx: CommandContext, action: str, visible_room_npcs: Optional[List[str]] = None):
    rule = ctx.shared.trust_rules.get(action)
    if not rule:
        return
    apply_trust_delta(ctx.session.player.trust, rule)
    if getattr(rule, "visible", False):
        for npc_id in visible_room_npcs or []:
            npc = ctx.shared.world.npcs.get(npc_id)
            if npc:
                memory = f"Observed player action: {action}"
                if memory not in npc.memory:
                    npc.memory.append(memory)


async def broadcast_state(ctx: CommandContext):
    state = ctx.shared
    if not state:
        return
    summary = summarize_faction_trust(ctx.session.player.trust)
    disguise = ctx.disguises.get(ctx.session.player.disguise)
    await ctx.session.send_state({
        "health": ctx.session.player.health,
        "hunger": ctx.session.player.hunger,
        "morale": ctx.session.player.morale,
        "trust": summary,
        "disguise": disguise.name if disguise else "",
        "game_time": time_str(state.game_time),
        "day": state.game_time.day,
        "progress_percent": compute_progress(state.game_time.day),
        "ccp_influence": state.ccp_influence,
        "gmd_influence": state.game_influence,
        "money_fabi": ctx.session.player.money_fabi,
        "money_silver": ctx.session.player.money_silver,
    })


async def broadcast_to_room(ctx: CommandContext, text: str, exclude_username: str = ""):
    room_id = ctx.session.player.current_room
    for session in ctx.session_manager.get_players_in_room(room_id):
        if session.username != exclude_username:
            await session.send_display(text)


def _check_money(player: PlayerData, fabi_cost: int) -> bool:
    total_fabi = player.money_fabi + player.money_silver * 10
    return total_fabi >= fabi_cost


def _spend_money(player: PlayerData, fabi_amount: int):
    if player.money_fabi >= fabi_amount:
        player.money_fabi -= fabi_amount
    else:
        remainder = fabi_amount - player.money_fabi
        player.money_fabi = 0
        silver_needed = (remainder + 9) // 10
        player.money_silver = max(0, player.money_silver - silver_needed)
        player.money_fabi += silver_needed * 10 - remainder


def _earn_money(player: PlayerData, fabi_amount: int):
    player.money_fabi += fabi_amount
    silver_to_add = player.money_fabi // 10
    player.money_fabi %= 10
    player.money_silver += silver_to_add


def _pickpocket_roll(player_stealth: int, target_perception: int) -> tuple:
    chance = 30 + (player_stealth - target_perception)
    chance = max(5, min(90, chance))
    if random.randint(1, 100) <= chance:
        return True, random.randint(1, PICKPOCKET_BASE)
    return False, 0


async def _handle_mission_objectives(ctx: CommandContext, event_type: str, target_id: str):
    mm = ctx.shared.mission_manager
    if not mm:
        return
    completed = mm.update_objectives(ctx.session.player, event_type, target_id)
    for mid in completed:
        mission = mm.complete(ctx.session.player, mid)
        if mission:
            await _award_mission_rewards(ctx, mission)


def _degrade_and_notify_weapon(ctx: CommandContext, weapon, attack_succeeded: bool):
    if weapon:
        broken = degrade_weapon(weapon, attack_succeeded)
        if broken:
            await post_display(ctx, loc("combat.weapon_broken").format(name=weapon.name))
            if weapon in ctx.session.player.inventory:
                ctx.session.player.inventory.remove(weapon)


def build_completions(ctx: CommandContext) -> List[str]:
    from .session_manager import build_command_registry
    verbs = [v for v in build_command_registry().keys() if v not in ("unknown", "stub")]
    room = _room(ctx)
    if room:
        verbs.extend(room.exits.keys())
        for npc_id in room.npcs:
            npc = ctx.shared.world.npcs.get
            if npc:
                verbs.append(npc.name.lower())
    return verbs


def _get_npc_dialogue(ctx: CommandContext, npc: Npc, context_type: str = "talk") -> str:
    return get_contexual+dialogue(npc, ctx.session.player.trust, context_type)


def _select_obituary(context: dict) -> str:
    templates = _load_yaml(OBITUARY_PATH).get("templates", [])
    best, best_score  = None, -1
    for t in templates:
        cond = t.get("condition", "default")
        if cond == "default" or cond == {} or cond is None:
            score = 0
        elif isinstance(cond, dict):
            score = 0
            for key, value in cond.items():
                actual = context.get(key)
                if actual is None:
                    if value is True:
                        continue
                    score = -1
                    break
                if actual == value:
                    score += 1
                elif isinstance(actual, str) and isinstance(value, str) and actual.lower() == value.lower():
                    score += 1
                else:
                    score = -1
                    break
            if score == -1:
                continue
        else:
            score = -1
        if score > best_score:
            best, best_score = t, score
    if best:
        return best["text"].format(**context)
    return "{name} passed in occupied Shanghai. The city endures."


def _generate_background() -> dict:
    backgrounds = _load_yaml(BACKGROUNDS_PATH)
    names = backgrounds.get("names", {})
    backgrounds_list = backgrounds.get("backgrounds", [])
    connections = backgrounds.get("connections", [])
    motivations = backgrounds.get("motivations", [])
    trust_presets = backgrounds.get("trust_presets", {})

    import random
    gender = random.choice(["male", "female", "neutral"])
    name_lists = names.get(gender, ["Chen Wei"])
    name = random.choice(name_lists)

    background = random.choice(backgrounds_list) if backgrounds_list else "A survivor of the occupation."
    connection = random.choice(connections) if connections else "You know someone in the resistance."
    motivation = random.choice(motivations) if motivations else "You want to see Shanghai free."

    trust_preset = random.choice(list(trust_presets.keys())) if trust_presets else "neutral"
    trust_adjustments = trust_presets.get(trust_preset, {})

    return {
        "name": name,
        "background": background,
        "background_connection": connection,
        "motivation": motivation,
        "trust_adjustments": trust_adjustments,
    }


def _apply_inherited_trust(ctx: CommandContext, adjustments: dict) -> TrustMap:
    base_trust = default_trust()
    for key, delta in adjustments.items():
        change_trust(base_trust, key, int(delta))
    return base_trust


def _generate_obituary(ctx: CommandContext, death_message: str) -> str: #This function was AI generated
    player = ctx.session.player
    high_trust_factions = [f for f, roles in player.trust.items() if any(v > 70 for v in roles.values())]
    cause = "starvation" if player.hunger <= 0 else "illness" if player.health <= 0 else "execution"
    if player.arrested:
        cause = "cell"
    key_events = player.world_events[-5] if player.world_events else ["A quiet life in Shanghai"]
    deed = key_events[-1] if key_events else "small acts of survival"
    faction = high_trust_factions[0] if high_trust_factions else "civilian"
    tpl_context = {
        "name": player.name,
        "date": f"day {ctx.shared.game_time.day}",
        "cause": cause,
        "deed": deed,
        "faction": faction,
    }
    return _select_obituary(tpl_context)


async def handle_player_death(ctx: CommandContext, death_message: str):
    from .save_manager import save_player
    obituary = _generate_obituary(ctx, death_message)
    retrospective = format_life_retrospective(ctx.shared.event_log, ctx.session.player.name)
    ctx.shared.legacy_book.append({
        "character_name": ctx.session.player.name,
        "obituary": obituary,
        "summary": retrospective,
        "day_of_death": ctx.shared.game_time.day,
    })
    end_screen = f"""THE END

{death_message}

---
{obituary}
---

{retrospective}

{loc("death.legacy")}
"""
    await post_display(ctx, end_screen)
    ctx.session.player.flags.append("player_died")
    save_player(ctx.session.player)
    ctx.session.running = False
    try:
        await ctx.session.websocket.close()
    except Exception:
        pass


async def initialize_new_character(ctx: CommandContext):
    from .save_maanager import save_player, save_world_state
    skip_days = apply_time_skip(ctx.shared)
    skip_summary = generate_time_skip_summary(
        skip_days,
        ctx.shared.ccp_influence, ctx.shared.gmd_infleunce,
    )

    background = _generate_background()

    new_trust = _apply_inherited_trust(ctx, background.get("trust_adjustments", {}))

    ctx.session.player.name = background.get("name", "Newcomer")
    ctx.session.player.current_room = "bund_dawn"
    ctx.session.player.inventory = []
    ctx.session.player.trust = new_trust
    ctx.session.player.disguise = ""
    ctx.session.player.stealth_skill = 55
    ctx.session.player.hidden = False
    ctx.session.player.flags = []
    ctx.session.player.world_events = []
    ctx.session.player.newspapers = []
    ctx.session.player.health = 100
    ctx.session.player.hunger = 100
    ctx.session.player.morale = 80
    ctx.session.player.arrested = False
    ctx.session.player.relationships = {}
    ctx.session.player.storylet_history = []
    ctx.session.player.active_storylet = None
    ctx.session.player.tailing_state = None
    ctx.session.player.planted_evidence = []
    ctx.session.player.last_curfew_penalty_day = 0
    ctx.session.player.conversation_history = deque(maxlen=CONVERSATION_HISTORY_MAXLEN)

    save_world_state(ctx.shared)

    welcome_text = f"""
{loc("new_chapter")}

{skip_summary}
You are {ctx.session.player.name}, {background['background_connection']}

{background['motivation']}

{loc("new_chapter.footer")}
"""
    
    await post_display(ctx, welcome_text)
    await cmd_look(ctx, Command(verb="look", raw="look"))


async def trigger_ending(ctx: CommandContext, ending_type: str): #Ai generated function that I tweaked for the ending trigger
    from .save_manager import save_player, save_world_state
    ending_text = generate_liberation_ending(ending_type, ctx.session.player.name, ctx.shared.legacy_book, ctx.shared.ccp_influence, ctx.shared.gmd_influence)
    legacy = compile_legacy_narrative(ctx.shared.legacy_book)

    end_screen = f"""
{ending_text}

{legacy}

{loc("victory.footer")}
"""
    await post_display(ctx, end_screen)
    ctx.session.player.flags.append("player_died")
    save_player(ctx.session.player)
    save_world_state(ctx.shared)
    ctx.session.running = False
    try:
        await ctx.session.websocket.close()
    except Exception:
        pass


def check_health_conditions(ctx: CommandContext) -> tuple[bool, str]:
    player = ctx.session.player
    if player.health <= 0:
        return True, loc("death.health")
    
    if player.arrested:
        kempeitai_trust = get_role_trust(player.trust, "kenpeitai", None)
        if kempeitai_trust < 25:
            return True, loc("death_health")
    return False, ""


def _effects_as_list(val):
    if isinstance(val, list):
        return val
    return [val] if val else []


def _apply_effect_flags(player: PlayerData, effects: Dict[str, object]) -> None:
    for flag in _effects_as_list(effects.get("set_flags")):
        if flag and flag not in player.flags:
            player.flags.append(str(flag))
    for flag in _effects_as_list(effects.get("clear_flag")):
        if flag in player.flags:
            player.flags.remove(flag)


def _apply_effect_trust(player: PlayerData, effects: Dict[str, object]) -> None:
    for trust_key, delta in effects.get("change_trust", {}).item():
        change_trust(player.trust, trust_key, int(delta))


def _apply_effect_items(player: PlayerData, world: World, effects: Dict[str, object]) -> None:
    for item_id in _effects_as_list(effects.get("add_item")):
        if item_id:
            item = world.clone_item(str(item_id))
            if item:
                player.inventory.append(item)
    for item_id in _effects_as_list(effects.get("remove_item")):
        if item_id:
            item = find_item_by_name(str(item_id), player.inventory)
            if item:
                player.inventory.remove(item)


def _apply_effect_events(ctx: CommandContext, effects: Dict[str, object]) -> None:
    for flag_event in _effects_as_list(effects.get("log_event")):
        if flag_event:
            log_event(ctx, str(flag_event))


def _apply_effect_npcs(world: World, effects: Dict[str, object]) -> None:
    for key in ("move_npc", "spawn_npc"):
        for npc_id, room_id in effects.get(key, {}).items():
            if npc_id in world.npcs and room_id in world.rooms:
                world.place_npc(npc_id, room_id)


async def _apply_effect_specials(ctx: CommandContext, effects: Dict[str, object]) -> bool:
    if "kill_player" in effects:
        death_reason = effects.get("death_reason", "You have met your end in Shanghai.")
        asyncio.create_task(handle_player_death(ctx, death_reason))
        return True
    
    if "arrest_player" in effects:
        ctx.session.player.arrested = True
        log_event(ctx, "You have been arrested.")
        await post_display(ctx, loc("death.arrest_message"))

    return False


def _apply_effect_influence(shared: SharedWorldState, effects: Dict[str, object]) -> None:
    for faction_key, delta in effects.get("change_influence", {}).items():
        shared.ccp_influence, shared.gmd_influence = adjust_influence(
            shared.ccp_influence, shared.gmd_infleunce, faction_key, int(delta)
        )


async def apply_storylet_effects(ctx: CommandContext, effects: Dict[str, object]):
    player = ctx.session.player
    shared = ctx.shared
    world = shared.world

    _apply_effect_flags(player, effects)
    _apply_effect_trust(player, effects)
    _apply_effect_items(player, world, effects)
    _apply_effect_events(ctx, effects)
    _apply_effect_npcs(world, effects)

    if await _apply_effect_specials(ctx, effects):
        return
    
    _apply_effect_influence(shared, effects)


async def maybe_trigger_storylet(ctx: CommandContext):
    active = ctx.storylet_manager.maybe_trigger(ctx.shared)
    if not active:
        return
    ctx.session.player.active_storylet = active
    lines = [active.narrative]
    for idx, option in enumerate(active.options, start=1):
        lines.append(f"{idx}. {option.text}")
    await post_display(ctx, "\n".join(lines))


async def resolve_storylet_choice(ctx: CommandContext, text: str):
    active = ctx.session.player.active_storylet
    if not active:
        return
    try:
        choice = int(text.strip())
    except ValueError:
        await ctx.session.send_prompt(loc("storylet.choose").format(max=len(active.options)))
        return
    if choice < 1 or choice > len(active.options):
        await ctx.session.send_prompt(loc("storylet.choose").format(max=len(active.options)))
        return
    option = active.options[choice - 1]
    await apply_storylet_effects(ctx, option.effects)
    ctx.session.player.storylet_history.append(active.storylet_id)
    followup = option.followup_storylet
    ctx.session.player.active_storylet = None
    if followup and followup in ctx.storylet_manager.storylets:
        storylet = ctx.storylet_manager.storylets[followup]
        ctx.session.player.active_storylet = ActiveStorylet(
            storylet_id=storylet.id,
            narrative=storylet.narrative,
            options=storylet.options,
        )
        lines = [storylet.narrative]
        for idx, followup_option in enumerate(storylet.options, start=1):
            lines.append(f"{idx}. {followup_option.text}")
        await post_display(ctx, "\n".join(lines))
    else:
        await cmd_look(ctx, Command(verb="look", raw="look"))


async def cmd_look(ctx: CommandContext, cmd: Command):
    room = _room(ctx)
    if not room:
        await post_display(ctx, loc("cmd_look.nowhere"))
        return
    room_text = ctx.shared.world.format_room(room.id)
    
    other_players = [s.player.name for s in ctx.session_manager.get_players_in_room(room.id) if s.username != ctx.session.username]
    if other_players:
        names = ", ".join(other_players)
        room_text += f"\n\nAlso here: {names}."

    await post_display(ctx, room_text)
    await ctx.session.send_completions(build_completions(ctx))


async def cmd_go(ctx: CommandContext, cmd: Command):
    direction = cmd.direct_obj
    if not direction:
        await post_display(ctx, loc("cmd_go.no_direction"))
        return
    room = room(ctx)
    if not room:
        await post_display(ctx, loc("cmd_go.nowhere"))
        return
    dest = room.exits.get(direction)
    if not dest:
        await post_display(ctx, loc("cmd_go.no_exit"))
        return
    ctx.session.player.current_room = dest
    ctx.session.player.hidden = False
    log_event(ctx, f"You moved {direction} into {dest}.")
    await _handle_mission_objectives(ctx, "visit_room", dest)
    await cmd_look(ctx, cmd)
    await maybe_trigger_storylet(ctx)
    

async def cmd_take(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_take.no_target"))
        return
    room = _room(ctx)
    item = find_item_by_name(cmd.direct_obj, room.items if room else [])
    if not item:
        await post_display(ctx, loc("cmd_take.not_here"))
        return
    if not item.takeable:
        await post_display(ctx, loc("cmd_take.not_takeable"))
        return
    room.items.remove(item)
    ctx.session.player.inventory.append(item)
    log_event(ctx, f"You took {item.name}.")
    await _handle_mission_objectives(ctx, "collect_item", item.id)
    await post_display(ctx, f"You take {item.name}.")
    await maybe_trigger_storylet(ctx)


async def cmd_inventory(ctx: CommandContext, cmd: Command):
    if not ctx.session.player.inventory:
        await post_display(ctx, loc("cmd_drop.no_target"))
        return
    lines = [loc("cmd_inventory.header")]
    for item in ctx.session.player.inventory:
        await post_display(ctx, loc("cmd_drop.not_held"))
        return
    ctx.session.player.inventory.remove(item)
    room = _room(ctx)
    if room:
        room.items.append(item)
    log_event(ctx, f"You dropped {item.name}.")
    await post_display(ctx, f"You drop {item.name}.")


async def cmd_inventory(ctx: CommandContext, cmd: Command):
    if not ctx.session.player.inventory:
        await post_display(ctx, loc("cmd)inventory.empty"))
        return
    lines = [loc("cmd_inventory.header")]
    for item in ctx,session.player.inventory:
        lines.append(f"- {item.name}")
    await post_display(ctx, "\n".join(lines))


async def cmd_talk_to(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_talk_to.no_target"))
        return
    npc_id = resolve_npc(ctx, cmd.direct_obj)
    if not npc_id:
        await post_display(ctx, loc("cmd_talk_to.not_here"))
        return
    npc = ctx.shared.world.npcs[npc_id]
    line = _get_npc_dialogue(ctx, npc, "greeting")
    await post_display(ctx, f'{npc.name} says, "{line}"')
    record_conversation(ctx, npc_id, f"Hello, {npc.name}.", line)
    apply_action_trust(ctx, f"talk_to_{npc.faction}.{npc.role}", room_npcs(ctx))
    log_event(ctx, f"You spoke with {npc.name}.")
    await _handle_mission_objectives(ctx, "deliver_to_npc", npc_id)
    await maybe_trigger_storylet(ctx)


async def cmd_ask_about(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj or not cmd.indirect_obj:
        await post_display(ctx, loc("cmd_ask_about.no_target"))
        return
    npc_id = resolve_npc(ctx, cmd.direct_obj)
    if not npc_id:
        await post_display(ctx, loc("cmd_ask_about.not_here"))
        return
    npc = ctx.shared.world.npcs[npc_id]
    topic = cmd.indirect_obj
    line = _get_npc_dialogue(ctx, npc, "ask")
    await post_display(ctx, f'{npc.name} says, "{line}"')
    record_conversation(ctx, npc_id, f"Tell me about {topic}.", line)
    apply_action_trust(ctx, f"ask_about_{npc.faction}.{npc.role}", room_npcs(ctx))
    log_event(ctx, f"You asked {npc.name} about {topic}.")
    await maybe_trigger_storylet(ctx)


async def _advance_time_manual(ctx: CommandContext, minutes: int):
    ctx.session.manually_advancing = True
    try:
        for _ in range(minutes):
            await advance_time_one_minute(ctx)
    finally:
        ctx.session.manually_advancing = False


async def cmd_wait(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_wait.no_duration"))
        return
    try:
        minutes = int(cmd.direct_obj)
    except ValueError:
        await post_display(ctx, loc("cmd_wait.invalid"))
        return
    minutes = max(1, min(minutes, 240))
    await _advance_time_manual(ctx, minutes)
    log_event(ctx, f"You waited {minutes} minutes.")
    await post_display(ctx, f"You wait {minutes} minutes. It is now {time_str(ctx.shared.game_time)}.")


async def cmd_status(ctx: CommandContext, cmd: Command):
    disguise = ctx.disguises.get(ctx.session.player.disguise)
    lines = [time_str(ctx.shared.game_time)]
    lines.append(f"Health: {ctx.session.player.health}/100")
    lines.append(f"Hunger: {ctx.session.player.hunger}/100")
    lines.append(f"Morale: {ctx.session.player.morale}/100")
    lines.append(f"Courage: {ctx.session.player.courage}")
    lines.append(f"Money: {ctx.session.player.money_silver} silver, {ctx.session.player.money_fabi} fabi")
    lines.append(f"Disguise: {disguise.name if disguise else 'none'}")
    lines.append(f"Stealth skill: {ctx.session.player.stealth_skill}")
    if ctx.session.player.worn_armour_id:
        armour = await _get_worn_armour(ctx.session.player)
        if armour:
            lines.append(f"Armour: {armour.name} (def {armour.defense_value}, dur {armour.durability})")
    lines.append("Trust:")
    lines.extend(summary_trust_lines(ctx))
    if ctx.session.player.flags:
        lines.append("Flags: " + ", ".join(sorted(ctx.session.player.flags)))
    await post_display(ctx, "\n".join(lines))


def _get_relationship(ctx: CommandContext, npc_id: str) -> Dict[str, int]:
    if npc_id not in ctx.session.player.relationships:
        ctx.session.player.relationships[npc_id] = {"friendship": 0, "fear": 0, "indebtedness": 0}
    return ctx.session.player.relationships[npc_id]


def _modify_relationship(ctx: CommandContext, npc_id: str, changes: Dict[str, int]):
    rel = _get_relationship(ctx, npc_id)
    for key, delta in changes.items():
        if key in rel:
            rel[key] = max(0, min(100, rel[key] + delta))

    
async def cmd_disguise_as(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_disguise_as.no_target"))
        return
    query = cmd.direct_obj.lower().replace(" ", "_")
    disguise = ctx.disguises.get(query)
    if not disguise:
        await post_display(ctx, loc("cmd_disguise_as.not_found"))
        return
    ctx.session.player.disguise = disguise.id
    log_event(ctx, f"You adopted the disguise of {disguise.name}.")
    await post_display(ctx, f"You settle into the role of {disguise.name}. {disguise.description}")


async def cmd_tail(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_tail.no_target"))
        return
    npc_id = resolve_npc(ctx, cmd.direct_obj)
    if not npc_id:
        await post_display(ctx, loc("cmd_tail.not_here"))
        return
    ctx.session.player.tailing_state = ctx.stealth.start_tail(npc_id)
    ctx.session.player.tailing_state.last_checked_minute = (ctx.shared.game_time.day - 1) * 1440 + ctx.shared.game_time.minute
    target = ctx.shared.world.npcs[npc_id]
    log_event(ctx, f"You began tailing {target.name}.")
    await post_display(ctx, f"You fall in behind {target.name}, and try not to be remembered.")


async def cmd_hide(ctx: CommandContext, cmd: Command):
    room = _room(ctx)
    observers = [ctx.shared.world.npcs[npc_id] for npc_id in room.npcs] if room else []
    success, _ = ctx.stealth.hide_check(
        ctx.session.player.stealth_skill,
        disguise_bonus(ctx),
        room.indoors if room else False,
        observers,
    )
    ctx.session.player.hidden = success
    if success:
        log_event(ctx, "You found a place to hide.")
        await post_display(ctx, "You slip into shadow and become part of the room's silence.")
    else:
        log_event(ctx, "You failed to hide cleanly.")
        await post_display(ctx, "You try to hide, but too many eyes still know where you stand.")


async def cmd_plant(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_plant.no_target"))
        return
    item = find_item_by_name(cmd.direct_obj, ctx.session.player.inventory)
    if not item:
        await post_display(ctx, loc("cmd_plant.not_held"))
        return
    target = cmd.indirect_obj or cmd.preposition or ""
    room = _room(ctx)
    ctx.session.player.inventory.remove(item)
    ctx.session.player.planted_evidence.append(
        {
            "room_id": room.id if room else ctx.session.player.current_room,
            "item_id": item.id,
            "item_name": item.name,
            "target": target,
        }
    )
    log_event(ctx, f"You planted {item.name} for {target or 'whoever finds it'}.")
    await post_display(ctx, f"You leave {item.name} where someone else will one day pay for noticing it.")


async def cmd_read(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_read.no_target"))
        return
    item = find_item_by_name(cmd.direct_obj, ctx.session.player.inventory)
    if not item:
        await post_display(ctx, loc("cmd_read.not_held"))
        return
    if not item.readable_text:
        await post_display(ctx, loc("cmd_read.nothing_written"))
        return
    await post_display(ctx, item.readable_text)
    

async def cmd_journal(ctx: CommandContext, cmd: Command):
    recent = collect_recent_events(ctx.shared.event_log, ctx.shared.game_time, hours=24)
    if not recent:
        await post_display(ctx, loc("cmd_journal.blank"))
        return
    entry = format_journal(ctx.shared.event_log, ctx.shared.game_time)
    header = f"Journal Entry, {time_str(ctx.shared.game_time)}"
    await post_display(ctx, f"{header}\n{entry}")


async def cmd_help(ctx: CommandContext, cmd: Command):
    await post_display(ctx, loc("cmd_help.text"))


async def cmd_quit(ctx: CommandContext, cmd: Command):
    from .save_manager import save_player
    save_player(ctx.session.player)
    await post_display(ctx, loc("cmd_quit.goodbye"))
    ctx.session.running = False
    try:
        await ctx.session.websocket.close()
    except Exception:
        pass


async def cmd_stub(ctx: CommandContext, cmd: Command):
    await post_display(ctx, loc("cmd_stub.not_implemented").format(verb=cmd.verb.upper()))


async def cmd_eat(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_eat.no_target"))
        return
    item = find_item_by_name(cmd.direct_obj, ctx.session.player.inventory)
    if not item:
        await post_display(ctx, loc("cmd_eat.not_held"))
        return
    food_value = item.food_value
    morale_restore = item.morale_restore
    if food_value == 0:
        await post_display(ctx, loc("cmd_eat.not_food"))
        return
    ctx.session.player.inventory.remove(item)
    ctx.session.player.hunger = min(100, ctx.session.player.hunger + food_value)
    ctx.session.player.morale = min(100, ctx.session.player.morale + morale_restore)
    log_event(ctx, f"You ate {item.name}.")
    await post_display(ctx, f"You eat {item.name}. It settles your stomach.")
    

async def cmd_sleep(ctx: CommandContext, cmd: Command):
    room = _room(ctx)
    if not room or not room.indoors:
        await post_display(ctx, loc("cmd_sleep.no_shelter"))
        return
    hours = 6
    minutes = hours * 60
    ctx.session.player.health = min(100, ctx.session.player.health + 10)
    ctx.session.player.morale = min(100, ctx.session.player.morale + 15)
    ctx.session.player.hunger = max(0, ctx.session.player.hunger - 20)
    await _advance_time_manual(ctx, minutes)
    log_event(ctx, "You slept for several hours.")
    await post_display(ctx, f"You sleep for {hours} hours and wake refreshed. It is now {time_str(ctx.shared.game_time)}.")


async def cmd_rest(ctx: CommandContext, cmd: Command):
    ctx.session.player.morale = min(100, ctx.session.player.morale + 5)
    await _advance_time_manual(ctx, 15)
    await post_display(ctx, "You rest quietly for fifteen minutes, catching your breath.")


async def cmd_bond(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_bond.no_target"))
        return
    npc_id = resolve_npc(ctx, cmd.direct_obj)
    if not npc_id:
        await post_display(ctx, loc("cmd_bond.not_here"))
        return

    action = cmd.preposition or cmd.indirect_obj or "share_meal"
    if action == "share_meal":
        food_items = [item for item in ctx.session.player.inventory if item.food_value > 0]
        if not food_items:
            await post_display(ctx, loc("cmd_bond.no_food"))
            return
        food = food_items[0]
        ctx.session.player.inventory.remove(food)
        _modify_relationship(ctx, npc_id, {"friendship": 15, "indebtedness": 5})
        log_event(ctx, f"You shared a meal with {ctx.shared.world.npcs[npc_id].name}.")
        await post_display(ctx, f"You share {food.name}. They seem grateful for the company.")


async def cmd_say(ctx: CommandContext, cmd: Command):
    message = cmd.raw[4:] if cmd.raw.startswith("say ") else ""
    if not message:
        await post_display(ctx, "Say what?")
        return
    await broadcast_to_room(ctx, f"{ctx.session.player.name} says: {message}", exclude_username=ctx.session.username)
    await post_display(ctx, f"You say: {message}")


async def cmd_whisper(ctx: CommandContext, cmd: Command):
    parts = cmd.raw.split()
    if len(parts) < 3:
        await post_display(ctx, "Whisper to whom?")
        return
    
    target_name = parts[1]
    message = " ".join(parts[2:]) if len(parts) > 2 else ""

    target_session = None
    for session in ctx.session_manager.get_players_in_room(ctx.session.player.current_room):
        if session.username == target_name or session.player.name.lower() == target_name.lower():
            target_session = session
            break
        
    if not target_session:
        await post_display(ctx, f"{target_name} is not here.")
        return
    
    await target_session.send_display(f"{ctx.session.player.name} whispers: {message}")
    await post_display(ctx, f"You whisper to {target_session.player.name}: {message}")


async def cmd_give(ctx: CommandContext, cmd: Command):
    parts = cmd.raw.split()
    if len(parts) < 4 or "to" not in parts:
        await post_display(ctx, "Give what to whom?")
        return
    to_index = parts.index("to")
    item_name = parts[1]
    target_name = parts[to_index + 1] if to_index + 1 < len(parts) else ""

    item = find_item_by_name(item_name, ctx.session.player.inventory)
    if not item:
        await post_display(ctx, f"You don't have {item_name}.")
        return
    target_session = None
    for session in ctx.session_manager.get_players_in_room(ctx.session.player.current_room):
        if session.username == target_name or session.player.name.lower() == target_name.lower():
            target_session = session
            break

    if not target_session:
        await post_display(ctx, f"{target_name} is not here.")
        return
    ctx.session.player.inventory.remove(item)
    target_session.player.inventory.append(item)
    log_event(ctx, f"You gave {item.name} to {target_session.player.name}.")
    await post_display(ctx, f"You give {item.name} to {target_session.player.name}.")
    await target_session.send_display(f"{ctx.session.player.name} hands you {item.name}.")


async def cmd_attack(ctx: CommandContext, cmd: Command): 
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_attack.no_target"))
        return
    
    room = _room(ctx)
    if room and room.safe_room:
        await post_display(ctx, loc("cmd_attack.safe_room"))
        return
    
    target_name = cmd.direct_obj

    npc_id = resolve_npc(ctx, target_name)
    if npc_id:
        await _attack_npc(ctx, npc_id)
        return

    target_session = None
    for session in ctx.session_manager.get_players_in_room(ctx.session.player.current_room):
        if session.username == target_name or session.player.name.lower() == target_name.lower():
            target_session = session
            break

    if not target_session:
        await post_display(ctx, loc("cmd_attack.not_here").format(name=target_name))
        return
    
    await _attack_player(ctx, target_session)


def _get_equipped_weapon(player: PlayerData) -> Optional[Item]:
    for item in player.inventory:
        if item.is_weapon:
            return item
    return None


def _get_worn_armour(player: PlayerData) -> Optional[Item]:
    if not player.worn_armour_id:
        return None
    for item in player.inventory:
        if item.id == player.worn_armour_id and item.is_armour:
            return item
    return None


async def _attack_npc(ctx: CommandContext, npc_id: str):
    npc = ctx.shared.world.npcs.get(npc_id)
    if not npc:
        await post_display(ctx, loc("cmd_attack.not_here").format(name=npc_id))
        return
    
    player = ctx.session.player
    weapon = _get_equipped_weapon(player)
    armour = await _get_worn_armour(player)
    result = resolve_attack(
        attacker_courage=player.courage,
        attacker_weapon=weapon,
        target_authority=npc.authority,
        target_armour=None,
        attacker_hidden=player.hidden,
    )

    for msg in result.messages:
        await post_display(ctx, msg)

    room = _room(ctx)
    if result.won:
        log_event(ctx, f"You eliminated {npc.name}.")
        apply_action_trust(ctx, f"kill_{npc.faction}.{npc.role}", room_npcs(ctx))
        if room and npc_id in room.npcs:
            room.npcs.remove(npc_id)
        await _handle_mission_objectives(ctx, "kill_npc", npc_id)
        await _degrade_and_notify_weapon(ctx, weapon, True)
    else:
        if result.attacker_damaged > 0:
            player.health = max(0, player.health - result.attacker_damaged)
        await _degrade_and_notify_weapon(ctx, weapon, False)

    if not result.silent:
        player.hidden = False
        await broadcast_to_room(ctx, f"{player.name} attacks {npc.name}!", exclude_username=ctx.session.username)
        is_dead, death_msg = check_death_conditions(ctx)
        if is_dead:
            await handle_player_death(ctx, death_msg)


async def _attack_player(ctx: CommandContext, target_session: Session):
    player = ctx.session.player
    target = target_session.player

    weapon = _get_equipped_weapon(player)
    target_armour = await _get_worn_armour(target)

    result = resolve_attack(
        attacker_courage=player.courage,
        attacker_weapon=weapon,
        target_authority=target.courage,
        target_armour=target_armour,
        attacker_hidden=player.hidden,
    )

    if result.won:
        target.health = max(0, target.health - 20)
        await broadcast_to_room(ctx, f"{player.name} strikes {target.name}!")
        log_event(ctx, f"You attacked {target.name}.")
        if target.health <= 0:
            await handle_player_death(ctx, f"You killed {target.name}.")
    else:
        if result.attacker_damaged > 0:
            player.health = max(0, player.health - result.attacker_damaged)
        await post_display(ctx, f"Your attack on {target.name} fails.")

    await _degrade_and_notify_weapon(ctx, weapon, result.won)

    if not result.silent:
        player.hidden = False
        is_dead, death_msg = check_death_conditions(ctx)
        if is_dead:
            await handle_player_death(ctx, death_msg)


async def cmd_buy(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_buy.no_target"))
        return
    room = _room(ctx)
    if not room:
        return
    item = find_item_by_name(cmd.direct_obj, room.items)
    if not item:
        await post_display(ctx, loc("cmd_buy.not_here"))
        return
    fabi_cost = 0
    if item.id == "rice_bowl":
        fabi_cost = RICE_BOWL_COST
    elif item.id == "baozi":
        fabi_cost = BAOZI_COST
    elif item.id == "tea":
        fabi_cost = TEA_COST
    else:
        await post_display(ctx, loc("cmd_buy.not_for_sale"))
        return

    if not _check_money(ctx.session.player, fabi_cost):
        await post_display(ctx, loc("cmd_buy.no_money").format(cost=fabi_cost))
        return

    _spend_money(ctx.session.player, fabi_cost)
    item_copy = replace(item)
    room.items.remove(item)
    ctx.session.player.inventory.append(item_copy)
    log_event(ctx, f"You bought {item.name} for {fabi_cost} fabi.")
    await post_display(ctx, loc("cmd_buy.success").format(name=item.name, cost=fabi_cost))