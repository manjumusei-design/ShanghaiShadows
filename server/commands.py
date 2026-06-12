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
from .player_data import PlayerData, _reset_player_defaults
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


def find_npc_by_name(ctx: CommandContext, name: str, npc_ids: List[str]) -> Optional[str]:
    q = name.lower().strip()
    for npc_id in npc_ids:
        npc = ctx.shared.world.npcs.get(npc_id)
        if npc and (q in npc.name.lower() or q in npc.id.lower()):
            return npc_id
    return None


def resolve_npc(ctx: CommandContext, name: str) -> Optional[str]:
    room = _room(ctx)
    return find_npc_by_name(ctx, name, room.npcs if room else [])


def _bfs_find_path(world: World, start_room_id: str, target_room_id: str) -> List[str]:
    queue = deque([(start_room_id, [])])
    visited = {start_room_id}

    while queue:
        current_room_id, path = queue.popleft()

        if current_room_id == target_room_id:
            return path

        room = world.rooms.get(current_room_id)
        if not room:
            continue

        for direction, dest_id in room.exits.items():
            if dest_id not in visited:
                visited.add(dest_id)
                queue.append((dest_id, path + [direction]))

    return []


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
    room = _room(ctx)
    active_missions_data = []
    mm = state.mission_manager
    if mm and ctx.session.player.active_missions:
        for active in ctx.session.player.active_missions:
            mission = mm.missions.get(active["mission_id"])
            if mission:
                active_missions_data.append({
                    "mission_id": mission.id,
                    "title": mission.title,
                    "objectives": active.get("objectives_progress", []),
                })
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
        "gmd_influence": state.gmd_influence,
        "money_fabi": ctx.session.player.money_fabi,
        "money_silver": ctx.session.player.money_silver,
        "safe_room": room.safe_room if room else False,
        "active_missions": active_missions_data,
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


async def _degrade_and_notify_weapon(ctx: CommandContext, weapon, attack_succeeded: bool):
    if weapon:
        broken = degrade_weapon(weapon, attack_succeeded)
        if broken:
            await post_display(ctx, loc("combat.weapon_broken").format(name=weapon.name))
            if weapon in ctx.session.player.inventory:
                ctx.session.player.inventory.remove(weapon)


def _find_container(ctx: CommandContext, name: str) -> Optional[Item]:
    room = _room(ctx)
    if not room:
        return None
    item = find_item_by_name(name, room.items + ctx.session.player.inventory)
    if item and item.is_container:
        return item
    return None


def _has_key_for_container(player: PlayerData, container: Item) -> bool:
    if not container.key_id:
        return False
    return any(i.key_id == container.key_id for i in player.inventory)


def _find_player_in_room(ctx: CommandContext, name: str) -> Optional[Session]:
    for s in ctx.session_manager.get_players_in_room(ctx.session.player.current_room):
        if s.username == name or s.player.name.lower() == name.lower():
            return s
        return None
    

_CACHED_VERBS: Optional[List[str]] = None


def build_completions(ctx: CommandContext) -> List[str]:
    global _CACHED_VERBS
    if _CACHED_VERBS is None:
        _CACHED_VERBS = [v for v in build_command_registry().keys() if v not in ("unknown", "stub")]
    verbs = list(_CACHED_VERBS)
    room = _room(ctx)
    if room:
        verbs.extend(room.exits.keys())
        for npc_id in room.npcs:
            npc = ctx.shared.world.npcs.get(npc_id)
            if npc:
                verbs.append(npc.name.lower())
    return verbs


def _get_npc_dialogue(ctx: CommandContext, npc: Npc, context_type: str = "talk") -> str:
    return get_contextual_dialogue(npc, ctx.session.player.trust, context_type)


_OBITUARY_TEMPLATES: Optional[List[dict]] = None


def _get_obituary_templates() -> List[dict]:
    global _OBITUARY_TEMPLATES
    if _OBITUARY_TEMPLATE is None:
        _OBITUARY_TEMPLATES = _load_yaml(OBITUARY_PATH).get("templates", [])
    return _OBITUARY_TEMPLATES


def _select_obituary(context: dict) -> str:
    from .victory import _select_template
    best = _select_template(_get_obituary_templates(), context)
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


def _apply_inherited_trust(adjustments: dict) -> TrustMap:
    base_trust = default_trust()
    for key, delta in adjustments.items():
        change_trust(base_trust, key, int(delta))
    return base_trust


def _generate_obituary(player: PlayerData, death_message: str, game_day: int) -> str:
    high_trust_factions = [f for f, roles in player.trust.items() if any(v > 70 for v in roles.values())]
    cause = "starvation" if player.hunger <= 0 else "illness" if player.health <= 0 else "execution"
    if player.arrested:
        cause = "cell"
    key_events = player.world_events[-5:] if player.world_events else ["A quiet life in Shanghai"]
    deed = key_events[-1] if key_events else "small acts of survival"
    faction = high_trust_factions[0] if high_trust_factions else "civilian"
    tpl_context = {
        "name": player.name,
        "date": f"day {game_day}",
        "cause": cause,
        "deed": deed,
        "faction": faction,
    }
    return _select_obituary(tpl_context)


async def handle_player_death(ctx: CommandContext, death_message: str):
    from .save_manager import save_player
    obituary = _generate_obituary(ctx.session.player, death_message, ctx.shared.game_time.day)
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
    from .save_manager import save_player, save_world_state
    skip_days = apply_time_skip(ctx.shared)
    skip_summary = generate_time_skip_summary(
        skip_days,
        ctx.shared.ccp_influence, ctx.shared.gmd_influence,
    )

    background = _generate_background()

    new_trust = _apply_inherited_trust(background.get("trust_adjustments", {}))

    _reset_player_defaults(ctx.session.player, background)
    ctx.session.player.trust = new_trust

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


async def trigger_ending(ctx: CommandContext, ending_type: str):
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


def check_death_conditions(ctx: CommandContext) -> tuple[bool, str]:
    player = ctx.session.player
    if player.health <= 0:
        return True, loc("death.health")

    if player.arrested:
        kempeitai_trust = get_role_trust(player.trust, "kempeitai", None)
        if kempeitai_trust < 25:
            return True, loc("death.arrest")
    return False, ""


def _effects_as_list(val):
    if isinstance(val, list):
        return val
    return [val] if val else []


def _apply_effect_flags(player: PlayerData, effects: Dict[str, object]) -> None:
    for flag in _effects_as_list(effects.get("set_flag")):
        if flag and flag not in player.flags:
            player.flags.append(str(flag))
    for flag in _effects_as_list(effects.get("clear_flag")):
        if flag in player.flags:
            player.flags.remove(flag)


def _apply_effect_trust(player: PlayerData, effects: Dict[str, object]) -> None:
    for trust_key, delta in effects.get("change_trust", {}).items():
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
            shared.ccp_influence, shared.gmd_influence, faction_key, int(delta)
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

    visible_players = []
    hidden_players_detected = []
    someone_watching = False

    for session in ctx.session_manager.get_players_in_room(room.id):
        if session.username == ctx.session.username:
            continue

        player = session.player
        if player.hidden:
            perception_check = ctx.session.player.perception + random.randint(1, 20)
            stealth_dc = player.stealth_skill + 10

            if perception_check >= stealth_dc:
                hidden_players_detected.append(player.name)
            elif ctx.session.player.perception >= 40:
                someone_watching = True
        else:
            visible_players.append(player.name)

    if visible_players:
        names = ", ".join(visible_players)
        room_text += f"\n\nAlso here: {names}."

    await post_display(ctx, room_text)

    if hidden_players_detected:
        for name in hidden_players_detected:
            await ctx.session.send_display(f"You notice {name} hiding in the shadows.\n")
    elif someone_watching:
        await ctx.session.send_display("You sense someone watching you.\n")

    await ctx.session.send_completions(build_completions(ctx))


async def cmd_go(ctx: CommandContext, cmd: Command):
    direction = cmd.direct_obj
    if not direction:
        await post_display(ctx, loc("cmd_go.no_direction"))
        return
    room = _room(ctx)
    if not room:
        await post_display(ctx, loc("cmd_go.nowhere"))
        return

    ctx.session.player.map_revealed = getattr(ctx.session.player, 'map_revealed', [])

    dest = room.exits.get(direction)
    if not dest:
        target_name = direction.lower()
        target_room = None
        for room_id in ctx.session.player.map_revealed:
            r = ctx.shared.world.rooms.get(room_id)
            if r and (target_name == r.id.lower() or target_name in r.title.lower() or target_name in r.name.lower() if hasattr(r, 'name') else False):
                target_room = r
                break

        if target_room:
            path = _bfs_find_path(ctx.shared.world, room.id, target_room.id)
            if path:
                await post_display(ctx, f"Auto-pathing to {target_room.title}... ({len(path)} steps)")
                for step in path:
                    if ctx.session.player.health <= 0:
                        await post_display(ctx, "Too injured to continue.")
                        break
                    if ctx.session.player.hunger < 10:
                        await post_display(ctx, "Too hungry to continue.")
                        break

                    current_room = _room(ctx)
                    if current_room:
                        for npc_id in current_room.npcs:
                            npc = ctx.shared.world.npcs.get(npc_id)
                            if npc and npc.faction == "kempeitai":
                                await post_display(ctx, "Hostile forces block your path.")
                                return

                    step_cmd = Command(verb="go", direct_obj=step, raw=f"go {step}")
                    await cmd_go(ctx, step_cmd)
                    await asyncio.sleep(0.1)
                return

        await post_display(ctx, loc("cmd_go.no_exit"))
        return

    ctx.session.player.current_room = dest
    if dest not in ctx.session.player.map_revealed:
        ctx.session.player.map_revealed.append(dest)
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


async def cmd_drop(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_drop.no_target"))
        return
    item = find_item_by_name(cmd.direct_obj, ctx.session.player.inventory)
    if not item:
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
        await post_display(ctx, loc("cmd_inventory.empty"))
        return
    lines = [loc("cmd_inventory.header")]
    for item in ctx.session.player.inventory:
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
        armour = _get_worn_armour(ctx.session.player)
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
    await post_display(ctx, f"You fall in behind {target.name} and try not to be remembered.")


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
    if cmd.direct_obj:
        from .save_manager import get_archived_journal
        character_name = cmd.direct_obj
        archived = get_archived_journal(character_name, ctx.shared)
        if not archived:
            await post_display(ctx, f"No archived journal found for {character_name}.")
            return
        lines = [f"=== Archived Journal: {character_name} ===", ""]
        for event in archived[-20:]:
            lines.append(event)
        await post_display(ctx, "\n".join(lines))
        return

    recent = collect_recent_events(ctx.shared.event_log, ctx.shared.game_time, hours=24)
    if not recent:
        await post_display(ctx, loc("cmd_journal.blank"))
        return
    entry = format_journal(ctx.shared.event_log, ctx.shared.game_time)
    header = f"--- Journal Entry, {time_str(ctx.shared.game_time)} ---"
    journal_lines = [header, entry]

    mm = ctx.shared.mission_manager
    if mm and ctx.session.player.active_missions:
        journal_lines.append("\n\n=== Active Missions ===")
        for active in ctx.session.player.active_missions:
            mission = mm.missions.get(active["mission_id"])
            if mission:
                progress_lines = []
                for prog in active["objectives_progress"]:
                    status = "DONE" if prog["current"] >= prog["count"] else f"{prog['current']}/{prog['count']}"
                    progress_lines.append(f"  {prog['type']} {prog['target']}: {status}")
                journal_lines.append(f"[{mission.id}] {mission.title}")
                journal_lines.extend(progress_lines)

    await post_display(ctx, "\n".join(journal_lines))


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

    target_session = _find_player_in_room(ctx, target_name)

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
    target_session = _find_player_in_room(ctx, target_name)

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


async def cmd_sell(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_sell.no_target"))
        return
    item = find_item_by_name(cmd.direct_obj, ctx.session.player.inventory)
    if not item:
        await post_display(ctx, loc("cmd_sell.not_held"))
        return

    sell_price = 0
    if item.is_weapon:
        sell_price = item.courage_bonus
    elif item.is_armour:
        sell_price = item.defense_value

    if sell_price == 0:
        await post_display(ctx, loc("cmd_sell.no_value"))
        return

    ctx.session.player.inventory.remove(item)
    _earn_money(ctx.session.player, sell_price)
    log_event(ctx, f"You sold {item.name} for {sell_price} fabi.")
    await post_display(ctx, loc("cmd_sell.success").format(name=item.name, price=sell_price))


async def cmd_pickpocket(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_pickpocket.no_target"))
        return
    npc_id = resolve_npc(ctx, cmd.direct_obj)
    if not npc_id:
        await post_display(ctx, loc("cmd_pickpocket.not_here"))
        return

    npc = ctx.shared.world.npcs.get(npc_id)
    if not npc:
        await post_display(ctx, loc("cmd_pickpocket.not_here"))
        return

    success, amount = _pickpocket_roll(ctx.session.player.stealth_skill, npc.perception)
    if success:
        _earn_money(ctx.session.player, amount)
        log_event(ctx, f"You pickpocketed {npc.name} for {amount} fabi.")
        apply_action_trust(ctx, f"pickpocket_{npc.faction}.{npc.role}", room_npcs(ctx))
        await post_display(ctx, loc("cmd_pickpocket.success").format(name=npc.name, amount=amount))
    else:
        log_event(ctx, f"You were caught pickpocketing {npc.name}.")
        apply_action_trust(ctx, f"caught_pickpocket_{npc.faction}.{npc.role}", room_npcs(ctx))
        ctx.session.player.hidden = False
        await post_display(ctx, loc("cmd_pickpocket.caught").format(name=npc.name))
        await broadcast_to_room(ctx, f"{ctx.session.player.name} is caught pickpocketing {npc.name}!")


async def cmd_equip(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_equip.no_target"))
        return
    item = find_item_by_name(cmd.direct_obj, ctx.session.player.inventory)
    if not item:
        await post_display(ctx, loc("cmd_equip.not_held"))
        return

    if item.is_armour:
        ctx.session.player.worn_armour_id = item.id
        await post_display(ctx, loc("cmd_equip.armour").format(name=item.name, defense=item.defense_value))
    elif item.is_weapon:
        await post_display(ctx, loc("cmd_equip.weapon_ready").format(name=item.name))
    else:
        await post_display(ctx, loc("cmd_equip.not_equipable"))


async def cmd_unequip(ctx: CommandContext, cmd: Command):
    if not ctx.session.player.worn_armour_id:
        await post_display(ctx, loc("cmd_unequip.nothing"))
        return

    armour = await _get_worn_armour(ctx.session.player)
    ctx.session.player.worn_armour_id = ""
    if armour:
        await post_display(ctx, loc("cmd_unequip.success").format(name=armour.name))
    else:
        await post_display(ctx, loc("cmd_unequip.not_found"))


async def cmd_heal(ctx: CommandContext, cmd: Command):
    room = _room(ctx)
    if not room or not room.nurse_available:
        await post_display(ctx, loc("cmd_heal.not_available"))
        return

    hour = ctx.shared.game_time.minute // 60
    if room.nurse_hours and hour not in room.nurse_hours:
        await post_display(ctx, loc("cmd_heal.wrong_hours"))
        return

    if not _check_money(ctx.session.player, NURSE_COST):
        await post_display(ctx, loc("cmd_heal.no_money").format(cost=NURSE_COST))
        return

    _spend_money(ctx.session.player, NURSE_COST)
    ctx.session.player.health = min(100, ctx.session.player.health + NURSE_HEAL)
    log_event(ctx, f"You were treated by a nurse for {NURSE_COST} fabi.")
    await post_display(ctx, loc("cmd_heal.success").format(heal=NURSE_HEAL))


async def _award_mission_rewards(ctx: CommandContext, mission):
    if not mission:
        return
    reward = mission.rewards
    player = ctx.session.player
    if reward.money_fabi > 0:
        _earn_money(player, reward.money_fabi)
    if reward.money_silver > 0:
        player.money_silver += reward.money_silver
    if reward.health_restore > 0:
        player.health = min(100, player.health + reward.health_restore)
    if reward.morale_restore > 0:
        player.morale = min(100, player.morale + reward.morale_restore)
    for trust_key, delta in reward.trust.items():
        change_trust(player.trust, trust_key, delta)
    if reward.add_flag:
        player.flags.append(reward.add_flag)
    if reward.add_item:
        item = ctx.shared.world.clone_item(reward.add_item)
        if item:
            player.inventory.append(item)
    reward_lines = []
    if reward.money_fabi > 0:
        reward_lines.append(f"+{reward.money_fabi} fabi")
    if reward.money_silver > 0:
        reward_lines.append(f"+{reward.money_silver} silver")
    if reward.health_restore > 0:
        reward_lines.append(f"+{reward.health_restore} health")
    if reward.morale_restore > 0:
        reward_lines.append(f"+{reward.morale_restore} morale")
    if reward.trust:
        reward_lines.append("trust improved")
    reward_text = ", ".join(reward_lines) if reward_lines else "nothing tangible"

    log_event(ctx, f"Mission complete: {mission.title}")
    await post_display(ctx, f"Mission complete: {mission.title}\nRewards: {reward_text}")


async def cmd_missions(ctx: CommandContext, cmd: Command):
    mm = ctx.shared.mission_manager
    if not mm:
        await post_display(ctx, loc("cmd_missions.unavailable"))
        return

    sub = cmd.direct_obj or ""
    if sub == "available":
        available = mm.get_available(ctx.session.player)
        if not available:
            await post_display(ctx, loc("cmd_missions.no_available"))
            return
        lines = [loc("cmd_missions.available_header")]
        for m in available:
            lines.append(f"  [{m.id}] {m.title} (faction: {m.faction}, min trust: {m.min_trust})")
        await post_display(ctx, "\n".join(lines))
    elif sub == "accept":
        mission_id = cmd.indirect_obj or ""
        if not mission_id:
            await post_display(ctx, loc("cmd_missions.accept_which"))
            return
        if mm.accept(ctx.session.player, mission_id, ctx.shared.game_time.day):
            mission = mm.missions.get(mission_id)
            log_event(ctx, f"Accepted mission: {mission.title}")
            await post_display(ctx, loc("cmd_missions.accepted").format(title=mission.title))
        else:
            await post_display(ctx, loc("cmd_missions.cannot_accept"))
    elif sub == "abandon":
        mission_id = cmd.indirect_obj or ""
        if not mission_id:
            await post_display(ctx, loc("cmd_missions.abandon_which"))
            return
        if mm.abandon(ctx.session.player, mission_id):
            log_event(ctx, f"Abandoned mission: {mission_id}")
            await post_display(ctx, loc("cmd_missions.abandoned").format(id=mission_id))
        else:
            await post_display(ctx, loc("cmd_missions.not_active"))
    elif sub == "complete":
        mission_id = cmd.indirect_obj or ""
        if not mission_id:
            await post_display(ctx, loc("cmd_missions.complete_which"))
            return
        mission = mm.complete(ctx.session.player, mission_id)
        if mission:
            await _award_mission_rewards(ctx, mission)
        else:
            await post_display(ctx, loc("cmd_missions.cannot_complete"))
    else:
        active = mm.get_active(ctx.session.player)
        if not active:
            await post_display(ctx, loc("cmd_missions.no_active"))
            return
        lines = [loc("cmd_missions.active_header")]
        for a in active:
            mission = mm.missions.get(a["mission_id"])
            if not mission:
                continue
            obj_lines = []
            for prog in a["objectives_progress"]:
                status = "DONE" if prog["current"] >= prog["count"] else f"{prog['current']}/{prog['count']}"
                obj_lines.append(f"    {prog['type']} {prog['target']}: {status}")
            lines.append(f"  [{mission.id}] {mission.title}")
            lines.extend(obj_lines)
        await post_display(ctx, "\n".join(lines))


async def cmd_search(ctx: CommandContext, cmd: Command):
    room = _room(ctx)
    if not room:
        return

    found_hidden = False
    if room.hidden_exits:
        for direction, dest_room_id in room.hidden_exits.items():
            if direction in room.exits:
                continue
            difficulty = 50
            if ctx.session.player.perception >= difficulty:
                room.exits[direction] = dest_room_id
                await post_display(ctx, f"You discover a hidden passage leading {direction}.")
                found_hidden = True
            else:
                await post_display(ctx, f"You sense something to the {direction} but can't find it.")

    if room.hiding_spots and not ctx.session.player.hidden:
        await post_display(ctx, "This room has hiding spots. You could HIDE here.")

    if not found_hidden and not room.hiding_spots:
        await post_display(ctx, "You search the room but find nothing of interest.")


async def cmd_examine(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, "Examine what?")
        return

    room = _room(ctx)
    if not room:
        return

    item = find_item_by_name(cmd.direct_obj, room.items if room else [])
    if item:
        lines = [f"You examine {item.name}."]
        if item.is_weapon:
            lines.append(f"Weapon - Courage bonus: {item.courage_bonus}")
            lines.append(f"Durability: {item.durability}/{item.max_durability if item.max_durability > 0 else '∞'}")
            if item.mods:
                lines.append(f"Mods: {', '.join(item.mods)}")
        elif item.is_armour:
            lines.append(f"Armour - Defense: {item.defense_value}")
            lines.append(f"Durability: {item.durability}/{item.max_durability if item.max_durability > 0 else '∞'}")
        elif item.is_container:
            lines.append(f"Container - {'Locked' if item.locked else 'Unlocked'}")
            if item.container_items:
                lines.append("Contents:")
                for ci in item.container_items:
                    lines.append(f"  - {ci.name}")
        elif item.is_map:
            if item.map_districts:
                lines.append(f"Map showing: {', '.join(item.map_districts)}")
        elif item.is_note:
            lines.append(f"Note: {item.note_text}")
        elif item.is_key:
            if item.opens_container:
                lines.append(f"Key that opens: {item.opens_container}")
        await post_display(ctx, "\n".join(lines))
        return

    npc_id = resolve_npc(ctx, cmd.direct_obj)
    if npc_id:
        npc = ctx.shared.world.npcs.get(npc_id)
        if npc:
            lines = [f"You observe {npc.name}."]
            lines.append(f"Faction: {npc.faction}")
            lines.append(f"Role: {npc.role}")
            if ctx.session.player.perception >= npc.courage:
                lines.append(f"Authority: {npc.authority}")
            else:
                lines.append("You can't assess their authority.")
            await post_display(ctx, "\n".join(lines))
            return

    await post_display(ctx, f"You don't see that here.")


async def cmd_map(ctx: CommandContext, cmd: Command):
    visited = set(ctx.session.player.map_revealed)
    if not visited:
        await post_display(ctx, "You haven't explored enough to draw a map.")
        return

    current_room = ctx.shared.world.get_room(ctx.session.player.current_room)
    if not current_room:
        return

    lines = ["Visited areas:"]
    for room_id in sorted(visited):
        room = ctx.shared.world.get_room(room_id)
        if room:
            marker = "HERE" if room_id == ctx.session.player.current_room else ""
            lines.append(f"- {room.title}{marker}")

    if ctx.session.player.maps_purchased:
        lines.append("\nPurchased maps:")
        for district in ctx.session.player.maps_purchased:
            lines.append(f"- {district}")

    await post_display(ctx, "\n".join(lines))


async def cmd_open(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, "Open what?")
        return

    item = _find_container(ctx, cmd.direct_obj)
    if not item:
        await post_display(ctx, "That's not a container.")
        return

    if item.locked:
        await post_display(ctx, "It's locked.")
        return

    await post_display(ctx, f"You open {item.name}.")
    if item.container_items:
        contents = ", ".join(ci.name for ci in item.container_items)
        await post_display(ctx, f"Inside: {contents}")
    else:
        await post_display(ctx, "It's empty.")


async def cmd_close(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, "Close what?")
        return

    item = _find_container(ctx, cmd.direct_obj)
    if not item:
        await post_display(ctx, "That's not a container.")
        return

    await post_display(ctx, f"You close {item.name}.")


async def cmd_lock(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, "Lock what?")
        return

    item = _find_container(ctx, cmd.direct_obj)
    if not item:
        await post_display(ctx, "That's not a container.")
        return

    if not item.key_id:
        await post_display(ctx, "This container doesn't have a lock.")
        return

    if not _has_key_for_container(ctx.session.player, item):
        await post_display(ctx, "You don't have the key.")
        return

    item.locked = True
    await post_display(ctx, f"You lock {item.name}.")


async def cmd_unlock(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, "Unlock what?")
        return

    item = _find_container(ctx, cmd.direct_obj)
    if not item:
        await post_display(ctx, "That's not a container.")
        return

    if not item.key_id:
        await post_display(ctx, "This container doesn't have a lock.")
        return

    if not _has_key_for_container(ctx.session.player, item):
        await post_display(ctx, "You don't have the key.")
        return

    item.locked = False
    await post_display(ctx, f"You unlock {item.name}.")


async def cmd_put_in(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj or not cmd.indirect_obj:
        await post_display(ctx, "Put what in what?")
        return

    item = find_item_by_name(cmd.direct_obj, ctx.session.player.inventory)
    if not item:
        await post_display(ctx, "You don't have that.")
        return

    container = _find_container(ctx, cmd.indirect_obj)
    if not container:
        await post_display(ctx, "That's not a container.")
        return

    if container.locked:
        await post_display(ctx, "It's locked.")
        return

    ctx.session.player.inventory.remove(item)
    container.container_items.append(item)
    await post_display(ctx, f"You put {item.name} in {container.name}.")


async def cmd_take_from(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj or not cmd.indirect_obj:
        await post_display(ctx, "Take what from what?")
        return

    container = _find_container(ctx, cmd.indirect_obj)
    if not container:
        await post_display(ctx, "That's not a container.")
        return

    if container.locked:
        await post_display(ctx, "It's locked.")
        return

    item = find_item_by_name(cmd.direct_obj, container.container_items)
    if not item:
        await post_display(ctx, "That's not in there.")
        return

    container.container_items.remove(item)
    ctx.session.player.inventory.append(item)
    await post_display(ctx, f"You take {item.name} from {container.name}.")


async def cmd_wear(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, "Wear what?")
        return

    item = find_item_by_name(cmd.direct_obj, ctx.session.player.inventory)
    if not item:
        await post_display(ctx, "You don't have that.")
        return

    if not item.is_armour:
        await post_display(ctx, "You can't wear that.")
        return

    if ctx.session.player.worn_armour_id:
        old_armour = _get_worn_armour(ctx.session.player)
        if old_armour and old_armour.id == item.id:
            await post_display(ctx, "You're already wearing that.")
            return

    ctx.session.player.worn_armour_id = item.id
    await post_display(ctx, f"You put on {item.name}. Defense: +{item.defense_value}.")


async def cmd_remove(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        if not ctx.session.player.worn_armour_id:
            await post_display(ctx, "You aren't wearing anything.")
            return
    else:
        item = find_item_by_name(cmd.direct_obj, ctx.session.player.inventory)
        if not item or item.id != ctx.session.player.worn_armour_id:
            await post_display(ctx, "You aren't wearing that.")
            return

    armour = _get_worn_armour(ctx.session.player)
    ctx.session.player.worn_armour_id = ""
    if armour:
        await post_display(ctx, f"You take off {armour.name}.")
    else:
        await post_display(ctx, "You remove your armour.")


async def cmd_write_note(ctx: CommandContext, cmd: Command):
    text = cmd.indirect_obj or ""
    if not text:
        await post_display(ctx, "Write what on the note?")
        return

    from .world import Item
    note = Item(
        id=f"note_{random.randint(1000, 9999)}",
        name="handwritten note",
        description="A handwritten note.",
        takeable=True,
        is_note=True,
        note_text=text,
    )
    ctx.session.player.inventory.append(note)
    await post_display(ctx, "You write a note.")


async def cmd_leave_note(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj or cmd.direct_obj != "note":
        await post_display(ctx, "Leave what note?")
        return

    note_item = None
    for item in ctx.session.player.inventory:
        if item.is_note:
            note_item = item
            break

    if not note_item:
        await post_display(ctx, "You don't have a note to leave.")
        return

    room = _room(ctx)
    if not room:
        return

    ctx.session.player.inventory.remove(note_item)
    room.items.append(note_item)
    await post_display(ctx, "You leave the note here.")


async def cmd_flee(ctx: CommandContext, cmd: Command):
    if ctx.session.player.hidden:
        await post_display(ctx, "You can't flee while hidden.")
        return

    room = _room(ctx)
    if not room or not room.exits:
        await post_display(ctx, "There's nowhere to flee!")
        return

    direction = random.choice(list(room.exits.keys()))
    ctx.session.player.morale = max(0, ctx.session.player.morale - 5)
    await post_display(ctx, "You panic and run!")
    await cmd_go(ctx, cmd)


async def cmd_take_trishaw(ctx: CommandContext, cmd: Command):
    if cmd.verb == "take trishaw" and cmd.preposition == "to" and cmd.indirect_obj:
        target_district = cmd.indirect_obj.lower()
    else:
        await post_display(ctx, "Take trishaw to where?")
        return

    room = _room(ctx)
    if not room or not room.trishaw_stand:
        await post_display(ctx, "There's no trishaw stand here.")
        return

    hour = ctx.shared.game_time.minute // 60
    if hour < 6 or hour >= 20:
        await post_display(ctx, "Trishaws only run during daytime (6:00-20:00).")
        return

    if not _check_money(ctx.session.player, 5):
        await post_display(ctx, "You can't afford the fare (5 fabi).")
        return

    _spend_money(ctx.session.player, 5)

    target_rooms = [
        r for r in ctx.shared.world.rooms.values()
        if r.tags and target_district in [t.lower() for t in r.tags]
    ]
    if not target_rooms:
        await post_display(ctx, f"No rooms found in {target_district}.")
        return

    dest_room = random.choice(target_rooms)
    old_room_id = ctx.session.player.current_room
    ctx.session.player.current_room = dest_room.id
    ctx.session.player.hidden = False
    log_event(ctx, f"You took a trishaw to {dest_room.title}.")

    await post_display(ctx, f"You pay 5 fabi and take a trishaw to {dest_room.title}.")
    await advance_time_one_minute(ctx)
    for _ in range(29):
        await advance_time_one_minute(ctx)

    await cmd_look(ctx, Command(verb="look"))
    await maybe_trigger_storylet(ctx)


async def cmd_yell(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, "Yell what?")
        return

    message = cmd.direct_obj
    player_name = ctx.session.player.name
    room = _room(ctx)
    if not room:
        return

    rooms_to_notify = [room]
    for direction, dest_id in room.exits.items():
        dest_room = ctx.shared.world.rooms.get(dest_id)
        if dest_room:
            rooms_to_notify.append(dest_room)

    for notify_room in rooms_to_notify:
        kempeitai_found = False
        for npc_id in notify_room.npcs:
            npc = ctx.shared.world.npcs.get(npc_id)
            if npc and npc.faction == "kempeitai" and notify_room != room:
                if hasattr(npc, 'investigating_room_id'):
                    npc.investigating_room_id = room.id
                kempeitai_found = True

        if notify_room == room:
            await broadcast_to_room(ctx, f"{player_name} yells: \"{message}\"!")
        else:
            kempeitai_msg = " You hear footsteps moving toward the noise." if kempeitai_found else ""
            for session in ctx.session_manager.get_players_in_room(notify_room.id):
                await session.send_display(f"You hear someone yell: \"{message}\"!{kempeitai_msg}\n")

    log_event(ctx, f"You yelled: \"{message}\"")


async def cmd_mod_weapon(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj or not cmd.indirect_obj:
        await post_display(ctx, "Mod weapon with what? Usage: mod weapon <weapon> with <mod>")
        return

    weapon_name = cmd.direct_obj
    mod_name = cmd.indirect_obj

    weapon = find_item_by_name(weapon_name, ctx.session.player.inventory)
    if not weapon or not weapon.is_weapon:
        await post_display(ctx, "You don't have that weapon.")
        return

    mod = find_item_by_name(mod_name, ctx.session.player.inventory)
    if not mod or not mod.is_mod:
        await post_display(ctx, "You don't have that mod.")
        return

    weapon.mods = getattr(weapon, 'mods', [])
    weapon.mod_slots = getattr(weapon, 'mod_slots', [])

    if len(weapon.mods) >= len(weapon.mod_slots):
        await post_display(ctx, "That weapon has no free mod slots.")
        return

    def apply_courage_bonus(w, v):
        w.courage_bonus += v

    def apply_stealth_bonus(w, v):
        w.stealth_bonus = getattr(w, 'stealth_bonus', 0) + v

    def apply_perception_bonus(w, v):
        w.perception_bonus = getattr(w, 'perception_bonus', 0) + v

    def apply_durability_bonus(w, v):
        w.max_durability += v

    BONUS_HANDLERS = {
        "courage": apply_courage_bonus,
        "stealth": apply_stealth_bonus,
        "perception": apply_perception_bonus,
        "durability": apply_durability_bonus,
    }

    weapon.mods.append(mod.id)
    handler = BONUS_HANDLERS.get(mod.mod_type)
    if handler:
        handler(weapon, mod.mod_bonus)

    ctx.session.player.inventory.remove(mod)
    log_event(ctx, f"You added {mod.name} to {weapon.name}.")
    await post_display(ctx, f"You attach the {mod.name} to your {weapon.name}. {mod.mod_type} increased by {mod.mod_bonus}.")


async def cmd_memorial(ctx: CommandContext, cmd: Command):
    if not ctx.shared.legacy_book:
        await post_display(ctx, "The legacy book is empty.")
        return

    entries = list(ctx.shared.legacy_book.items())[-20:]
    if not entries:
        await post_display(ctx, "No entries in the legacy book.")
        return

    lines = ["=== Legacy Book ===", ""]
    for name, entry in entries:
        day_of_death = entry.get("day", "Unknown")
        cause = entry.get("cause", "Unknown")
        lines.append(f"{name} - Day {day_of_death}: {cause}")

    await post_display(ctx, "\n".join(lines))


async def advance_time_one_minute(ctx: CommandContext):
    ctx.shared.game_time.minute += 1
    if ctx.shared.game_time.minute >= 1440:
        ctx.shared.game_time.minute = 0
        ctx.shared.game_time.day += 1
    ctx.shared.scheduler.process(
        ctx.shared.game_time,
        lambda msg: asyncio.create_task(post_display(ctx, msg)),
    )
    move_npcs_if_hour_changed(ctx)
    process_gossip(ctx)
    await check_planted_evidence(ctx)
    await process_tailing(ctx)
    await check_curfew_penalty(ctx)
    if ctx.shared.game_time.minute % 15 == 0:
        await maybe_trigger_storylet(ctx)
    if ctx.shared.game_time.minute % 60 == 0 and ctx.shared.game_time.minute > 0:
        mm = ctx.shared.mission_manager
        if mm:
            expired = mm.check_expiry(ctx.session.player, ctx.shared.game_time.day)
            for mid in expired:
                await post_display(ctx, f"Mission {mid} has expired.")
    process_survival_tick(ctx)

    is_dead, death_message = check_death_conditions(ctx)
    if is_dead:
        asyncio.create_task(handle_player_death(ctx, death_message))
        return

    if ctx.shared.game_time.minute == 0:
        ending = check_victory_conditions(
            ctx.shared.game_time.day,
            ctx.shared.ccp_influence,
            ctx.shared.gmd_influence,
        )
        if ending:
            asyncio.create_task(trigger_ending(ctx, ending))
            return


def move_npcs_if_hour_changed(ctx: CommandContext):
    if ctx.shared.game_time.minute % 60 != 0:
        return
    hour = ctx.shared.game_time.minute // 60
    for npc_id, npc in ctx.shared.world.npcs.items():
        room_id = npc.schedule.get(hour)
        if room_id and room_id in ctx.shared.world.rooms:
            old_room_id = ctx.shared.world.npc_locations.get(npc_id)
            if old_room_id:
                old_room = ctx.shared.world.rooms.get(old_room_id)
                if old_room and npc_id in old_room.npcs:
                    old_room.npcs.remove(npc_id)
            if npc_id not in ctx.shared.world.rooms.get(room_id, []).npcs:
                ctx.shared.world.rooms[room_id].npcs.append(npc_id)
            ctx.shared.world.npc_locations[npc_id] = room_id


def process_gossip(ctx: CommandContext):
    for room in ctx.shared.world.rooms.values():
        npc_ids = room.npcs
        if len(npc_ids) < 2:
            continue
        for i in range(len(npc_ids) - 1):
            a = ctx.shared.world.npcs.get(npc_ids[i])
            b = ctx.shared.world.npcs.get(npc_ids[i + 1])
            if not a or not b:
                continue
            if exchange_gossip(a.memory, b.memory, chance=0.25):
                rumor = b.memory[-1] if b.memory else ""
                if rumor:
                    ctx.shared.rumour_mill.setdefault(b.faction, []).append(rumor)
                    ctx.shared.rumour_mill[b.faction] = ctx.shared.rumour_mill[b.faction][-12:]


async def check_planted_evidence(ctx: CommandContext):
    if not ctx.session.player.planted_evidence:
        return
    remaining = []
    for planted in ctx.session.player.planted_evidence:
        room = ctx.shared.world.get_room(str(planted["room_id"]))
        target = str(planted.get("target", "")).lower()
        triggered = False
        if room:
            for npc_id in room.npcs:
                npc = ctx.shared.world.npcs.get(npc_id)
                if not npc:
                    continue
                if not target or target in npc.faction.lower() or target in npc.role.lower() or target in npc.name.lower():
                    event_text = f"Your planted {planted['item_name']} in {room.title} has stirred suspicion."
                    log_event(ctx, event_text)
                    ctx.shared.rumour_mill.setdefault(npc.faction, []).append(event_text)
                    await post_display(ctx, event_text)
                    triggered = True
                    break
        if not triggered:
            remaining.append(planted)
    ctx.session.player.planted_evidence = remaining


async def process_tailing(ctx: CommandContext):
    tail = ctx.session.player.tailing_state
    if not tail:
        return
    current_total = (ctx.shared.game_time.day - 1) * 1440 + ctx.shared.game_time.minute
    if current_total - tail.last_checked_minute < 5:
        return
    tail.last_checked_minute = current_total
    tail.elapsed_minutes += 5
    target = ctx.shared.world.npcs.get(tail.target_npc_id)
    if not target:
        ctx.session.player.tailing_state = None
        await post_display(ctx, loc("cmd_tail.target_vanished"))
        return
    success, _ = ctx.stealth.tail_check(
        tail,
        target,
        ctx.session.player.stealth_skill,
        disguise_bonus(ctx),
        ctx.session.player.hidden,
    )
    if not success and tail.distance <= 0:
        ctx.session.player.tailing_state = None
        log_event(ctx, f"{target.name} spotted you while you were tailing them.")
        await post_display(ctx, f"{target.name} glances over a shoulder, slows, and knows exactly what you are doing.")
        return
    target_room = ctx.shared.world.npc_locations.get(target.id)
    if success and target_room and ctx.session.player.current_room != target_room:
        ctx.session.player.current_room = target_room
        ctx.session.player.hidden = False
        await post_display(ctx, f"You shadow {target.name} and keep them in sight.")


async def check_curfew_penalty(ctx: CommandContext):
    if ctx.shared.game_time.minute < CURFEW_MINUTE:
        return
    if ctx.session.player.last_curfew_penalty_day == ctx.shared.game_time.day:
        return
    room = _room(ctx)
    if room and not room.indoors:
        apply_action_trust(ctx, "out_after_curfew", room.npcs)
        ctx.session.player.last_curfew_penalty_day = ctx.shared.game_time.day
        log_event(ctx, "You were seen outside after curfew.")
        await post_display(ctx, loc("curfew.warning"))


def process_survival_tick(ctx: CommandContext):
    ctx.session.player.hunger = max(0, ctx.session.player.hunger - HUNGER_DECAY_RATE)
    if ctx.session.player.hunger <= LOW_HUNGER_THRESHOLD:
        ctx.session.player.health = max(0, ctx.session.player.health - HUNGER_HEALTH_DAMAGE)
        if ctx.shared.game_time.minute % 30 == 0:
            asyncio.create_task(post_display(ctx, loc("hunger.cramps")))
    if ctx.session.player.hunger > 80 and ctx.shared.game_time.minute % 60 == 0:
        ctx.session.player.health = min(100, ctx.session.player.health + 1)


_COMMAND_REGISTRY = None


def build_command_registry() -> Dict[str, Callable]:
    global _COMMAND_REGISTRY
    if _COMMAND_REGISTRY is None:
        _COMMAND_REGISTRY = {
            "look": cmd_look,
            "go": cmd_go,
            "take": cmd_take,
            "drop": cmd_drop,
            "inventory": cmd_inventory,
            "talk to": cmd_talk_to,
            "ask about": cmd_ask_about,
            "wait": cmd_wait,
            "help": cmd_help,
            "quit": cmd_quit,
            "status": cmd_status,
            "disguise as": cmd_disguise_as,
            "tail": cmd_tail,
            "hide": cmd_hide,
            "plant": cmd_plant,
            "read": cmd_read,
            "journal": cmd_journal,
            "ask": cmd_stub,
            "whisper": cmd_whisper,
            "give": cmd_give,
            "use": cmd_stub,
            "eat": cmd_eat,
            "sleep": cmd_sleep,
            "rest": cmd_rest,
            "bond": cmd_bond,
            "say": cmd_say,
            "attack": cmd_attack,
            "buy": cmd_buy,
            "sell": cmd_sell,
            "pickpocket": cmd_pickpocket,
            "equip": cmd_equip,
            "unequip": cmd_unequip,
            "heal": cmd_heal,
            "visit nurse": cmd_heal,
            "missions": cmd_missions,
            "flee": cmd_flee,
            "search": cmd_search,
            "examine": cmd_examine,
            "map": cmd_map,
            "wear": cmd_wear,
            "remove": cmd_remove,
            "open": cmd_open,
            "close": cmd_close,
            "lock": cmd_lock,
            "unlock": cmd_unlock,
            "put in": cmd_put_in,
            "take from": cmd_take_from,
            "write note": cmd_write_note,
            "leave note": cmd_leave_note,
            "take trishaw": cmd_take_trishaw,
            "mod weapon": cmd_mod_weapon,
            "yell": cmd_yell,
            "memorial": cmd_memorial,
            "unknown": cmd_stub,
        }
    return _COMMAND_REGISTRY
