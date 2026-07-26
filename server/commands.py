import asyncio
import random
from collections import deque
import time
from copy import replace
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, TYPE_CHECKING

from .journal import collect_recent_events, format_journal, format_life_retrospective, absorb_death_journal
from .locales import get as loc
from .npc import Npc, get_contextual_dialogue, match_topic, get_topic_dialogue, npc_ask_topics
from .npc_memory import npc_memory_system
from .parser import Command, parse
from .player_data import PlayerData, grow_stat
from .auth import set_safehouse
from .serialization import _load_yaml, deserialize_item, serialize_item
from .session import Session
from .storylets import ActiveStorylet, StoryletManager, load_storylets
from .trust import change_trust, apply_trust_delta, summarize_faction_trust, exchange_gossip
from .time_system import time_str
from .victory import check_victory_conditions, apply_time_skip, compute_progress, _season_from_day, _select_template, adjust_influence, fabi_inflation_multiplier, predict_ending
from .world import Item, World, replace
from .game_world import SharedWorldState
from .combat import resolve_attack, degrade_weapon, degrade_armour
from .constants import (
    OBITUARY_PATH, BACKGROUNDS_PATH, CURFEW_MINUTE,
    EVENT_LOG_MAXLEN, WORLD_EVENTS_MAXLEN,
    HUNGER_DECAY_RATE, HUNGER_HEALTH_DAMAGE, LOW_HUNGER_THRESHOLD,
    RICE_BOWL_COST, BAOZI_COST, TEA_COST, PICKPOCKET_BASE,
    NURSE_COST, NURSE_HEAL,
    STAT_GAIN_COURAGE_COMBAT, STAT_GAIN_STEALTH_HIDE, STAT_GAIN_PERCEPTION_OBSERVE,
    COMBAT_GROWTH_FACTIONS, WANTED_LEVEL_MAX, SUSPICION_FAILED_STEALTH,
    SEASONAL_PRICE_MULTIPLIER, BLACK_MARKET_LISTING_EXPIRE_DAYS,
    MessageType,
)
from .economy import economy_system, DISTRICT_TO_REGION
from .tutorial import advance_tutorial

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

def _npc_source(ctx: CommandContext):
    return ctx.shared.world.npcs if ctx.shared else {}

from .pathfinding import vector_to_compass as _vector_to_compass

async def _auto_go(ctx: CommandContext, room_id: str):
    ctx.session.player.current_room = room_id
    if room_id not in getattr(ctx.session.player, 'map_revealed', []):
        ctx.session.player.map_revealed.append(room_id)
    ctx.session.player.hidden = False
    await cmd_look(ctx, Command(verb="look"))
    if getattr(ctx.session.player, 'in_tutorial', False) and not room_id.startswith("refugee_entry_"):
        ctx.session.player.in_tutorial = False
        ctx.session.player.tutorial_stage = 41
        ctx.session.player.health = 100
        ctx.session.player.hunger = 100
        ctx.session.player.morale = 100
        if "tutorial_complete" not in ctx.session.player.flags:
            ctx.session.player.flags.append("tutorial_complete")
        from .auth import set_tutorial_complete
        try:
            set_tutorial_complete(ctx.session.username)
        except Exception:
            pass
        _strip_to_rice(ctx)
        log_event(ctx, "Tutorial complete. Welcome to Shanghai.")

def _strip_to_rice(ctx: CommandContext):
    player = ctx.session.player
    player.inventory = []
    rice = ctx.shared.world.item_catalog.get("rice_bowl")
    if rice:
        player.inventory.append(replace(rice))

def _notify_tutorial_confirmation(ctx: CommandContext, item_id: Optional[str] = None):
    player = ctx.session.player
    if not getattr(player, 'in_tutorial', False):
        return

    from .tutorial import tutorial_set_confirmation, STAGE_ACTIONS
    stage = getattr(player, 'tutorial_stage', 0)
    action = STAGE_ACTIONS.get(stage, {})

    if action.get('require_both'):
        if not hasattr(player, '_tutorial_items_obtained'):
            player._tutorial_items_obtained = {}
        obtained = player._tutorial_items_obtained.setdefault(stage, [])

        if item_id:
            normalized = _normalize_text(item_id)
            for existing in obtained:
                if _normalize_text(existing) == normalized:
                    return  # Already tracked
            obtained.append(item_id)
        needed = [action.get('target'), action.get('alt_target')]
        needed_normalized = [_normalize_text(n) for n in needed if n]
        obtained_normalized = [_normalize_text(o) for o in obtained]
        matched = 0
        for need in needed_normalized:
            for got in obtained_normalized:
                if need in got or got in need:
                    matched += 1
                    break

        if matched >= len(needed_normalized):
            tutorial_set_confirmation(player, stage)
    else:
        tutorial_set_confirmation(player, stage)

def _topic_hint(npc, asked: List[str] = None, in_tutorial: bool = False, tutorial_stage: int = 0) -> str:
    topics = npc_ask_topics(npc, in_tutorial=in_tutorial, tutorial_stage=tutorial_stage)
    if asked: 
        topics = [t for t in topics if t not in asked]
    return ", ".join(topics) if topics else "the city, the war, or work"

def find_item_by_name(name: str, items: List[Item]) -> Optional[Item]:
    q = name.lower().strip()
    for item in items:
        if item.name.lower() == q or item.id.lower() == q:
            return item
    for item in items:
        if q in item.name.lower() or q in item.id.lower():
            return item
    return None


def _normalize_text(s: str) -> str:
    import re
    s = re.sub(r"\b(the|a|an)\b", " ", (s or "").lower())
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(s.split())


def find_npc_by_name(ctx: CommandContext, name: str, npc_ids: List[str]) -> Optional[str]:
    q = _normalize_text(name)
    if not q:
        return None
    for npc_id in npc_ids:
        npc = ctx.shared.world.npcs.get(npc_id)
        if not npc:
            continue
        if q in _normalize_text(npc.name) or q in npc_id.lower() or _normalize_text(npc_id) in q:
            return npc_id
    return None


def resolve_npc(ctx: CommandContext, name: str) -> Optional[str]:
    room = _room(ctx)
    return find_npc_by_name(ctx, name, room.npcs if room else [])


def _short_name(name: str) -> str:
    return (name or "").split(",")[0].strip()


def _current_objective(ctx: CommandContext) -> str:
    p = ctx.session.player
    if "tutorial_complete" not in p.flags:
        if "tutorial_step_2" in p.flags:
            return "Deliver the folded note to Sister Mei at the chapel in the French Concession."
        if "tutorial_step_1" in p.flags:
            return "Find Old Wu at his noodle stand in the Old City (north to the Commercial district, then south into the Old City)."
        return "Take the ration card the stranger on the Bund offers."
    if p.active_missions:
        mm = ctx.shared.mission_manager
        mission = mm.missions.get(p.active_missions[0].get("mission_id")) if mm else None
        if mission:
            return f"Mission: {mission.title}."
    return "Find work: seek a faction contact (MISSIONS AVAILABLE) and build trust to sway the Liberation."


def _topic_hint(npc) -> str:
    topics = npc_ask_topics(npc)
    return ", ".join(topics) if topics else "the city, the war, or work"


def _story_direction(ctx: CommandContext, npc) -> str:
    p = ctx.session.player
    if "tutorial_complete" not in p.flags:
        return ""
    if not p.active_missions and not p.completed_missions:
        short = _short_name(npc.name)
        return (
            f'{short} glances both ways and lowers their voice. "Look. The city chews up '
            f'people who stand still. If you want to matter, there are people hiring. Factions. '
            f"The underground, Chungking's people, even the Green Gang. Find their contacts in "
            f'the teahouses and back rooms. Ask for work. The occupation will not end on its own."'
        )
    return ""


def _room_action_hint(ctx: CommandContext, room) -> str:
    hints = []
    if room.npcs:
        npc = ctx.shared.world.npcs.get(room.npcs[0])
        if npc:
            hints.append(f"TALK TO or ASK {_short_name(npc.name)} ABOUT something")
    if room.items:
        hints.append("TAKE an item here")
    pending = ctx.shared.active_room_storylets.get(room.id)
    if pending and not pending.get("resolved"):
        hints.append("respond to the situation here (type a number)")
    if room.exits:
        hints.append("GO " + "/".join(room.exits.keys()))
    hints.append("SEARCH")
    hints.append("STATUS")
    return "You can: " + ", ".join(hints) + "."


def _item_tag(item) -> str:
    if item.food_value > 0:
        return "food: EAT"
    if item.is_weapon:
        return "weapon: ATTACK"
    if item.is_armour:
        return "armour: WEAR"
    if item.is_container:
        return "container: OPEN"
    if item.is_key:
        return "key: UNLOCK"
    if item.is_map:
        return "map: READ"
    if item.is_money:
        return "money"
    return "DROP/SELL"


def _item_action_hint(item, carried: bool) -> str:
    acts = []
    if not carried:
        acts.append("TAKE it")
    if item.food_value > 0:
        acts.append("EAT it")
    if item.is_weapon:
        acts.append("use it in ATTACK")
    if item.is_armour:
        acts.append("WEAR/REMOVE it")
    if item.is_container:
        acts.append("OPEN/PUT IN/TAKE FROM it")
    if item.is_map and item.map_districts:
        acts.append("READ it to reveal " + ", ".join(item.map_districts))
    if carried:
        acts.append("DROP or SELL it")
    return ("You can: " + ", ".join(acts) + ".") if acts else ""


def _option_text(option) -> str:
    return option.text if hasattr(option, "text") else option.get("text", "")


def _pending_room_event(ctx: CommandContext, room) -> str:
    rs = ctx.shared.active_room_storylets.get(room.id)
    if not rs or rs.get("resolved"):
        return ""
    narrative = rs.get("narrative")
    if not narrative and rs.get("storylet_id"):
        storylet = ctx.storylet_manager.storylets.get(rs["storylet_id"])
        if storylet:
            narrative = storylet.narrative
    lines = [narrative] if narrative else ["Something is afoot here."]
    for idx, option in enumerate(rs.get("options", []), start=1):
        lines.append(f"{idx}. {_option_text(option)}")
    return "\n".join(lines)


def _bfs_find_path(world: World, start_room_id: str, target_room_id: str) -> List[str]:
    from .pathfinding import a_star_find_path, make_cost_fn
    cost_fn = make_cost_fn(world.rooms)
    return a_star_find_path(world.rooms, start_room_id, target_room_id, cost_fn)


def room_npcs(ctx: CommandContext) -> List[str]:
    room = _room(ctx)
    return room.npcs if room else []


def _update_npc_sound_memory(npc, source_room_id: str, intensity: int, sound_type: str, game_time) -> None:
    bb = getattr(npc, "_blackboard", None)
    if bb is None:
        from .behavior_tree import Blackboard
        bb = Blackboard()
        npc._blackboard = bb
    game_minute = game_time.minute + game_time.day * 1440 if game_time else 0
    bb.set("last_heard_sound", {
        "room_id": source_room_id,
        "intensity": intensity,
        "type": sound_type,
        "minute": game_minute,
    })
    hostile_factions = {"kempeitai"}
    bb.set("heard_hostile_sound", npc.faction in hostile_factions and intensity >= 2)


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


def _trust_tier_message(key: str, old: int, new: int) -> str:
    def tier(v):
        if v < 30:
            return "hostile"
        if v < 70:
            return "neutral"
        return "friendly"
    if tier(old) == tier(new):
        return ""
    faction = key.split(".", 1)[0].upper().replace("_", " ")
    if tier(new) == "friendly":
        return loc("trust.up.friendly").format(faction=faction)
    if tier(new) == "hostile":
        return loc("trust.down.hostile").format(faction=faction)
    if tier(old) == "friendly":
        return loc("trust.down.friendly").format(faction=faction)
    return loc("trust.up.hostile").format(faction=faction)


async def apply_action_trust(ctx: CommandContext, action: str, visible_room_npcs: Optional[List[str]] = None):
    rule = ctx.shared.trust_rules.get(action)
    if not rule:
        return
    changed = apply_trust_delta(ctx.session.player.trust, rule)
    if getattr(rule, "visible", False):
        for npc_id in visible_room_npcs or []:
            npc = ctx.shared.world.npcs.get(npc_id)
            if npc:
                memory = f"Observed player action: {action}"
                if memory not in npc.memory:
                    npc.memory.append(memory)
    for key, new_val in changed.items():
        delta = int(rule.deltas.get(key, 0))
        msg = _trust_tier_message(key, new_val - delta, new_val)
        if msg:
            await post_display(ctx, msg)


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

    if getattr(ctx.session, 'audio_enabled', False):
        weather = getattr(state, 'weather', 'clear')
        weather_key = f"_audio_weather_{weather}"
        if weather == "rain" and not getattr(ctx.session, '_audio_rain_active', False):
            await ctx.session.websocket.send('{"type":"audio","sound":"rain_start"}')
            ctx.session._audio_rain_active = True
        elif weather != "rain" and getattr(ctx.session, '_audio_rain_active', False):
            await ctx.session.websocket.send('{"type":"audio","sound":"rain_stop"}')
            ctx.session._audio_rain_active = False


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


def _dedup(seq):
    seen = set()
    return [x for x in seq if not (x in seen or seen.add(x))]


def build_completions(ctx: CommandContext) -> Dict[str, List[str]]:
    global _CACHED_VERBS
    if _CACHED_VERBS is None:
        _CACHED_VERBS = [v for v in build_command_registry().keys() if v not in ("unknown", "stub")]
    npcs: List[str] = []
    items: List[str] = []
    exits: List[str] = []
    room = _room(ctx)
    if room:
        exits = list(room.exits.keys())
        for npc_id in room.npcs:
            npc = ctx.shared.world.npcs.get(npc_id)
            if npc and npc.name:
                npcs.append(npc.name.lower())
        for item in room.items:
            if item.name:
                items.append(item.name.lower())
    for item in ctx.session.player.inventory:
        if item.name:
            items.append(item.name.lower())
    return {"verbs": list(_CACHED_VERBS), "npcs": _dedup(npcs), "items": _dedup(items), "exits": _dedup(exits)}


def _get_npc_dialogue(ctx: CommandContext, npc: Npc, context_type: str = "talk") -> str:
    return get_contextual_dialogue(npc, ctx.session.player.trust, context_type)


_OBITUARY_TEMPLATES: Optional[List[dict]] = None


def _get_obituary_templates() -> List[dict]:
    global _OBITUARY_TEMPLATES
    if _OBITUARY_TEMPLATES is None:
        _OBITUARY_TEMPLATES = _load_yaml(OBITUARY_PATH).get("templates", [])
    return _OBITUARY_TEMPLATES


def _select_obituary(context: dict) -> str:
    from .victory import _select_template
    best = _select_template(_get_obituary_templates(), context)
    if best:
        return best["text"].format(**context)
    return "{name} passed in occupied Shanghai. The city endures."


def _generate_character_name() -> str:
    names = _load_yaml(BACKGROUNDS_PATH).get("names", {})
    import random
    gender = random.choice(["male", "female", "neutral"])
    name_lists = names.get(gender, ["Chen Wei"])
    return random.choice(name_lists)


def _derive_death_cause(player: PlayerData, death_message: str) -> str:
    msg = death_message.lower()
    if player.hunger <= 0:
        return "starvation"
    if player.arrested:
        if any(k in msg for k in ("execute", "tribunal", "sentence", "shot")):
            return "execution"
        return "cell"
    if "betray" in msg:
        return "betrayal"
    if any(k in msg for k in ("raid", "sweep")):
        return "raid"
    if any(k in msg for k in ("crossfire", "caught in")):
        return "crossfire"
    if any(k in msg for k in ("attack", "strike", "gunshot", "shot", "kill", "combat", "fight", "blade", "fist")):
        return "combat"
    if player.health <= 0:
        return "illness"
    return "execution"


def _derive_deed(player: PlayerData) -> str:
    if any("kempeitai" in e.lower() and ("eliminated" in e.lower() or "killed" in e.lower()) for e in player.world_events):
        return "the killing of an occupation officer"

    if player.completed_missions:
        return "their work for the underground"

    high_trust = [f for f, roles in player.trust.items() if any(v > 70 for v in roles.values())]
    if high_trust:
        faction_name = {"ccp": "the resistance", "gmd": "the Republic's cause", "kempeitai": "the occupation"}.get(high_trust[0], "their allies")
        return f"their loyalty to {faction_name}"
    if len(player.world_events) > 15:
        return "small kindnesses in hard times"
    return "quiet acts of survival"


def _generate_obituary(player: PlayerData, death_message: str, game_day: int) -> str:
    high_trust_factions = [f for f, roles in player.trust.items() if any(v > 70 for v in roles.values())]
    cause = _derive_death_cause(player, death_message)
    faction = high_trust_factions[0] if high_trust_factions else "civilian"
    tpl_context = {
        "name": player.name,
        "date": f"day {game_day}",
        "cause": cause,
        "deed": _derive_deed(player),
        "faction": faction,
    }
    return _select_obituary(tpl_context)


async def handle_player_death(ctx: CommandContext, death_message: str, last_words: str = ""):
    from .save_manager import save_player
    obituary = _generate_obituary(ctx.session.player, death_message, ctx.shared.game_time.day)
    retrospective = format_life_retrospective(ctx.shared.event_log, ctx.session.player.name)
    ctx.shared.legacy_book.append({
        "character_name": ctx.session.player.name,
        "obituary": obituary,
        "summary": retrospective,
        "day_of_death": ctx.shared.game_time.day,
        "last_words": last_words,
    })
    from .auth import deposit_stash
    from .serialization import serialize_item
    if ctx.session.player.inventory:
        deposit_stash(ctx.session.username, [serialize_item(item) for item in ctx.session.player.inventory])
    from .journal import build_death_journal_entry
    room_id = ctx.session.player.current_room
    if room_id:
        entry = build_death_journal_entry(ctx.session.player, ctx.shared.game_time.day, death_message, last_words)
        ctx.shared.death_journals.setdefault(room_id, []).append(entry)
    end_screen = f"""THE END

{death_message}
"""
    if last_words:
        end_screen += f'\nLast words: "{last_words}"\n'
    end_screen += "\nYour name has been added to the memorial. The city endures.\n"
    await post_display(ctx, end_screen)
    ctx.session.player.flags.append("player_died")
    save_player(ctx.session.player)
    ctx.session.running = False
    try:
        await ctx.session.websocket.close()
    except Exception:
        pass


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


def _normalize_effects(effects):
    if isinstance(effects, list):
        canon: Dict[str, object] = {}
        for entry in effects:
            if not isinstance(entry, dict):
                continue
            kind = entry.get("type")
            if kind == "flag":
                canon.setdefault("set_flag", []).append(entry.get("flag"))
            elif kind == "item":
                canon.setdefault("add_item", []).append(entry.get("item_id") or entry.get("id"))
            elif kind in ("health", "morale", "courage"):
                canon[kind] = int(canon.get(kind, 0)) + int(entry.get("value", 0))
        return canon

    canon = dict(effects) if isinstance(effects, dict) else {}
    if "flag" in canon:
        canon.setdefault("set_flag", []).extend(_effects_as_list(canon.pop("flag")))
    for alias, canonical in (("trust", "change_trust"), ("influence", "change_influence")):
        if isinstance(canon.get(alias), dict):
            canon.setdefault(canonical, {}).update(canon.pop(alias))
    return canon


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
        _adjust_shared_influence(shared, faction_key, int(delta))


def _apply_effect_stats(player: PlayerData, effects: Dict[str, object]) -> None:
    for stat in ("health", "morale"):
        if stat in effects:
            setattr(player, stat, max(0, min(100, getattr(player, stat) + int(effects[stat]))))
    if "courage" in effects:
        grow_stat(player, "courage", int(effects["courage"]))


async def apply_storylet_effects(ctx: CommandContext, effects: Dict[str, object]):
    player = ctx.session.player
    shared = ctx.shared
    world = shared.world
    effects = _normalize_effects(effects)

    _apply_effect_flags(player, effects)
    _apply_effect_trust(player, effects)
    _apply_effect_items(player, world, effects)
    _apply_effect_events(ctx, effects)
    _apply_effect_npcs(world, effects)
    _apply_effect_stats(player, effects)

    if await _apply_effect_specials(ctx, effects):
        return

    _apply_effect_influence(shared, effects)


async def maybe_trigger_storylet(ctx: CommandContext):
    active = ctx.storylet_manager.maybe_trigger_for_player(ctx.session.player, ctx.shared)
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
    raw = text.strip()
    choice = None
    try:
        n = int(raw)
        if 1 <= n <= len(active.options):
            choice = n
    except ValueError:
        q = raw.lower()
        for idx, opt in enumerate(active.options, start=1):
            if q and q in opt.text.lower():
                choice = idx
                break
    if choice is None:
        lines = [active.narrative]
        for idx, opt in enumerate(active.options, start=1):
            lines.append(f"{idx}. {opt.text}")
        await post_display(ctx, "\n".join(lines))
        await ctx.session.send_prompt(loc("storylet.choose").format(max=len(active.options)))
        return
    option = active.options[choice - 1]
    await apply_storylet_effects(ctx, option.effects)
    flags = ctx.session.player.flags
    if "tutorial_complete" in flags and "tutorial_handoff_shown" not in flags:
        flags.append("tutorial_handoff_shown")
        handoff = loc("tutorial.handoff")
        room = ctx.shared.world.get_room(ctx.session.player.current_room)
        if room and getattr(room, "safe_room", False):
            handoff += "\n" + loc("tutorial.handoff.claim")
        await post_display(ctx, handoff)
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
    room_text = ctx.shared.world.format_room(
        room.id,
        getattr(ctx.shared, "room_state_overrides", None),
        getattr(ctx.shared, "death_journals", None),
    )

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

    room_text += "\n" + _room_action_hint(ctx, room)
    pending = _pending_room_event(ctx, room)
    if pending:
        room_text += "\n\n" + pending
    room_text += "\nObjective: " + _current_objective(ctx)
    await post_display(ctx, room_text)

    if hidden_players_detected:
        for name in hidden_players_detected:
            await ctx.session.send_display(loc("perception.hidden_player").format(name=name) + "\n")
    elif someone_watching:
        await ctx.session.send_display(loc("perception.someone_watching") + "\n")

    if room.tags and any("police" in t.lower() or "kempeitai" in t.lower() for t in room.tags):
        for session in ctx.session_manager.sessions.values():
            if session.player.wanted_level > 0 and session.player.name != ctx.session.player.name:
                level_desc = ["suspected", "wanted", "MOST WANTED"][min(session.player.wanted_level - 1, 2)]
                await ctx.session.send_display(
                    f"A poster on the wall shows a sketch labelled '{session.player.name}': {level_desc}. "
                    f"Reward: {session.player.wanted_level * 20} fabi.\n"
                )

    if room.tags:
        for tag in room.tags:
            tag_lower = tag.lower()
            if "ccp_safehouse" in tag_lower:
                ccp_inf = ctx.shared.ccp_influence
                if ccp_inf >= 80:
                    key = "safehouse.ccp.high"
                elif ccp_inf >= 60:
                    key = "safehouse.ccp.mid"
                else:
                    key = "safehouse.ccp.bare"
                await ctx.session.send_display(loc(key) + "\n")
            elif "gmd_safehouse" in tag_lower:
                gmd_inf = ctx.shared.gmd_influence
                if gmd_inf >= 80:
                    key = "safehouse.gmd.high"
                elif gmd_inf >= 60:
                    key = "safehouse.gmd.mid"
                else:
                    key = "safehouse.gmd.bare"
                await ctx.session.send_display(loc(key) + "\n")

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
                await post_display(ctx, loc("movement.auto_path.start").format(title=target_room.title, steps=len(path)))
                for step in path:
                    if ctx.session.player.health <= 0:
                        await post_display(ctx, loc("movement.auto_path.halt_injured"))
                        break
                    if ctx.session.player.hunger < 10:
                        await post_display(ctx, loc("movement.auto_path.halt_hungry"))
                        break

                    current_room = _room(ctx)
                    if current_room:
                        for npc_id in current_room.npcs:
                            npc = ctx.shared.world.npcs.get(npc_id)
                            if npc and npc.faction == "kempeitai":
                                await post_display(ctx, loc("movement.auto_path.halt_hostile"))
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
    await post_display(ctx, loc("cmd_take.success").format(name=item.name))
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
    await post_display(ctx, loc("cmd_drop.success").format(name=item.name))


async def cmd_inventory(ctx: CommandContext, cmd: Command):
    if not ctx.session.player.inventory:
        await post_display(ctx, loc("cmd_inventory.empty"))
        return
    lines = [loc("cmd_inventory.header")]
    for item in ctx.session.player.inventory:
        lines.append(f"- {item.name} [{_item_tag(item)}]")
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
    await post_display(ctx, f'{npc.name} says, "{line}"\n\nYou could ASK {_short_name(npc.name)} ABOUT {_topic_hint(npc)}.')
    direction = _story_direction(ctx, npc)
    if direction:
        await post_display(ctx, direction)
    record_conversation(ctx, npc_id, f"Hello, {npc.name}.", line)
    await apply_action_trust(ctx, f"talk_to_{npc.faction}.{npc.role}", room_npcs(ctx))
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
    topic_key = match_topic(topic)
    known = npc_ask_topics(npc)
    short = _short_name(npc.name)
    hint = _topic_hint(npc)
    if topic_key and topic_key in known:
        line = get_topic_dialogue(npc, topic_key)
        await post_display(ctx, f'{npc.name} says, "{line}"')
        record_conversation(ctx, npc_id, f"Tell me about {topic}.", line)
        await apply_action_trust(ctx, f"ask_about_{npc.faction}.{npc.role}", room_npcs(ctx))
        log_event(ctx, f"You asked {npc.name} about {topic}.")
        await maybe_trigger_storylet(ctx)
    elif topic_key:
        await post_display(ctx, f'{short} shrugs. "Wouldn\'t know about {topic}. Ask me about {hint}."')
    else:
        await post_display(ctx, f'{short} looks blank. "What about? I know about {hint}."')


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
    await post_display(ctx, loc("cmd_wait.done").format(minutes=minutes, time=time_str(ctx.shared.game_time)))


async def cmd_status(ctx: CommandContext, cmd: Command):
    disguise = ctx.disguises.get(ctx.session.player.disguise)
    lines = [time_str(ctx.shared.game_time)]
    lines.append("Season: " + _season_from_day(ctx.shared.game_time.day).capitalize())
    lines.append("Objective: " + _current_objective(ctx))
    lines.append(f"Health: {ctx.session.player.health}/100")
    lines.append(f"Hunger: {int(ctx.session.player.hunger)}/100")
    lines.append(f"Morale: {ctx.session.player.morale}/100")
    lines.append(f"Courage: {ctx.session.player.courage}")
    lines.append(f"Money: {ctx.session.player.money_silver} silver, {ctx.session.player.money_fabi} fabi")
    lines.append(f"Disguise: {disguise.name if disguise else 'none'}")
    lines.append(f"Stealth skill: {ctx.session.player.stealth_skill}")
    if ctx.session.player.worn_armour_id:
        armour = _get_worn_armour(ctx.session.player)
        if armour:
            lines.append(f"Armour: {armour.name} (def {armour.defense_value}, dur {armour.durability})")
    if ctx.session.player.wanted_level > 0:
        chance = 15 + min(WANTED_LEVEL_MAX, ctx.session.player.wanted_level) * 20
        lines.append(loc("status.wanted").format(level=ctx.session.player.wanted_level, chance=chance))
    lines.append("Trust:")
    lines.extend(summary_trust_lines(ctx))
    ccp_inf = ctx.shared.ccp_influence
    gmd_inf = ctx.shared.gmd_influence
    leader, leader_val = ("CCP", ccp_inf) if ccp_inf >= gmd_inf else ("GMD", gmd_inf)
    _ENDING_TIDE = {
        "ccp_uprising": "The tide favours the Communist underground.",
        "gmd_return": "The tide favours the Nationalist return.",
        "unity": "The factions walk a knife's edge toward unity.",
        "balance": "The outcome hangs in the balance.",
    }
    lines.append(f"Liberation draws near: {leader} stands at {leader_val}/100 influence.")
    lines.append(f"CCP influence: {ccp_inf}  GMD influence: {gmd_inf}")
    lines.append(_ENDING_TIDE[predict_ending(ccp_inf, gmd_inf)])
    if ctx.session.player.flags:
        lines.append("Flags: " + ", ".join(sorted(ctx.session.player.flags)))
    kills = [f for f in ctx.session.player.flags if f.startswith("historical_kill:")]
    if kills:
        lines.append(f"Assassinations: {len(kills)}")
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
    await post_display(ctx, loc("cmd_disguise_as.success").format(name=disguise.name, description=disguise.description))


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
    await post_display(ctx, loc("cmd_tail.start").format(name=target.name))


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
        await post_display(ctx, loc("cmd_hide.success"))
        grow_stat(ctx.session.player, "stealth_skill", STAT_GAIN_STEALTH_HIDE)
    else:
        _raise_nearby_suspicion(ctx, SUSPICION_FAILED_STEALTH)
        log_event(ctx, "You failed to hide cleanly.")
        await post_display(ctx, loc("cmd_hide.fail"))


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
    await post_display(ctx, loc("cmd_plant.success").format(name=item.name))


async def _read_death_journal(ctx: CommandContext, cmd: Command):
    room = ctx.room
    entries = ctx.shared.death_journals.get(room.id, []) if room else []
    if not entries:
        await post_display(ctx, loc("cmd_read.no_journal"))
        return
    query = _normalize_text(cmd.direct_obj.replace("journal", " ").replace("notebook", " "))
    if query:
        matches = [e for e in entries if query in _normalize_text(e["character_name"])]
        if len(matches) == 1:
            chosen = matches[0]
        elif len(matches) > 1:
            names = ", ".join(f"{e['character_name']} (Day {e['day_of_death']})" for e in matches)
            await post_display(ctx, loc("cmd_read.journal_ambiguous").format(names=names))
            return
        else:
            await post_display(ctx, loc("cmd_read.journal_no_match").format(name=cmd.direct_obj))
            return
    else:
        chosen = entries[-1]
    added = absorb_death_journal(ctx.session.player.conversation_history, chosen)
    log_event(ctx, f"You read the journal of {chosen['character_name']}, recovering {added} notes.")
    await post_display(ctx, loc("cmd_read.journal_absorbed").format(name=chosen["character_name"], n=added))


async def cmd_read(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_read.no_target"))
        return
    target = cmd.direct_obj.lower()
    if "journal" in target or "notebook" in target:
        await _read_death_journal(ctx, cmd)
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
            await post_display(ctx, loc("cmd_journal.no_archive").format(name=character_name))
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

    if ctx.session.player.conversation_history:
        journal_lines.append("\n\n=== Recent Conversations ===")
        for conv in list(ctx.session.player.conversation_history)[-10:]:
            if conv.get("npc_id") == "_rumor":
                cname = "street talk"
            else:
                npc_obj = ctx.shared.world.npcs.get(conv.get("npc_id", ""))
                cname = _short_name(npc_obj.name) if npc_obj else conv.get("npc_id", "?")
            cresp = conv.get("npc_response", "")
            journal_lines.append(f'Day {conv.get("day", "?")}, {cname}: "{cresp[:140]}"')

    await post_display(ctx, "\n".join(journal_lines))


_USAGE = {
    "look": "LOOK, or EXAMINE <npc/item> for detail and what you can do with it.",
    "go": "GO <direction> (n/s/e/w/u/d), or GO <room name> to auto-walk. Follow the Routes line between districts.",
    "map": "MAP shows where you have been, grouped by district.",
    "take": "TAKE <item>.",
    "drop": "DROP <item>.",
    "inventory": "INVENTORY (i) lists what you carry, each with its use.",
    "talk to": "TALK TO <name> greets someone and shows what to ASK them about.",
    "ask about": "ASK <name> ABOUT <topic> (try: the city, the war, work, the Kempeitai, the factions).",
    "give": "GIVE <item> TO <name>.",
    "bond": "BOND WITH <name> USING <item> to build trust.",
    "say": "SAY <message> speaks aloud to the room.",
    "whisper": "WHISPER <name> <message>.",
    "yell": "YELL <message> broadcasts to nearby rooms, and draws attention.",
    "hide": "HIDE conceals you. Moving or loud actions break it.",
    "tail": "TAIL <name> follows someone secretly.",
    "disguise as": "DISGUISE AS <faction role> to pass as one of them.",
    "pickpocket": "PICKPOCKET <name> (risky; raises suspicion if caught).",
    "plant": "PLANT <item> ON <name> to frame them.",
    "search": "SEARCH <detail> finds hidden exits or dead drops.",
    "examine": "EXAMINE <npc/item> for detail and what you can do with it.",
    "wear": "WEAR <armour>.",
    "remove": "REMOVE <armour>.",
    "open": "OPEN <container>.",
    "close": "CLOSE <container>.",
    "unlock": "UNLOCK <container> (needs the matching key).",
    "lock": "LOCK <container>.",
    "put in": "PUT <item> IN <container>.",
    "take from": "TAKE <item> FROM <container>.",
    "take trishaw": "TAKE TRISHAW TO <place> fast-travels somewhere you have visited (5 fabi, daytime).",
    "eat": "EAT <food> staves off hunger.",
    "sleep": "SLEEP until dawn (needs a safe, indoor room).",
    "rest": "REST a short while (restores a little morale).",
    "visit nurse": "VISIT NURSE heals 30 health for 20 fabi.",
    "status": "STATUS shows your condition, objective, season, and the Liberation influence tide.",
    "missions": "MISSIONS shows active work; MISSIONS AVAILABLE lists jobs; MISSIONS ACCEPT/COMPLETE/ABANDON <id>.",
    "attack": "ATTACK <name> (courage-based; killing notable figures shifts influence).",
    "buy": "BUY <item> from a vendor.",
    "sell": "SELL <item> for fabi.",
    "flee": "FLEE to a random exit (costs morale).",
    "claim": "CLAIM makes this safe room your respawn safehouse.",
    "retrieve": "RETRIEVE gear stashed at your safehouse.",
    "help": "HELP lists everything; HELP <command> shows how to use one; HELP START for the basics.",
}


def _help_targets(ctx: CommandContext, verb: str) -> str:
    room = _room(ctx)
    if not room:
        return ""
    npc_names = [_short_name(ctx.shared.world.npcs[n].name) for n in room.npcs if ctx.shared.world.npcs.get(n)]
    room_items = [i.name for i in room.items if i.name]
    inv_items = [i.name for i in ctx.session.player.inventory if i.name]
    exits = list(room.exits.keys())

    if verb in ("attack", "talk to", "ask", "ask about", "pickpocket", "tail", "disguise as", "bond", "whisper", "plant"):
        return ("Here: " + ", ".join(npc_names) + ".") if npc_names else "No one here to do that with."
    if verb == "give":
        if not inv_items:
            return "You carry nothing to give."
        return "You could give: " + ", ".join(inv_items) + ("" if not npc_names else ", to: " + ", ".join(npc_names) + ".")
    if verb in ("take", "take from", "search"):
        return ("Here: " + ", ".join(room_items) + ".") if room_items else "Nothing here to take."
    if verb in ("eat", "wear", "remove", "drop", "sell", "read", "open", "mod weapon"):
        return ("You carry: " + ", ".join(inv_items) + ".") if inv_items else "You carry nothing."
    if verb in ("go", "flee"):
        return ("Exits: " + ", ".join(exits) + ".") if exits else "No way out from here."
    return ""


async def cmd_help(ctx: CommandContext, cmd: Command):
    arg = cmd.raw.lower().strip()
    arg = arg[4:].strip() if arg.startswith("help") else ""
    if arg == "start":
        await post_display(ctx, loc("cmd_help.start"))
        return
    if arg:
        match = next((k for k in sorted(_USAGE, key=len, reverse=True) if arg.startswith(k)), None)
        if match:
            text = f"{match.upper()} - {_USAGE[match]}"
            targets = _help_targets(ctx, match)
            if targets:
                text += "\n" + targets
            await post_display(ctx, text)
            return
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
    await post_display(ctx, loc("cmd_stub.not_implemented").format(verb=(cmd.raw.strip() or cmd.verb)))


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
    await post_display(ctx, loc("cmd_eat.success").format(name=item.name))


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
    await post_display(ctx, loc("cmd_sleep.done").format(hours=hours, time=time_str(ctx.shared.game_time)))


async def cmd_rest(ctx: CommandContext, cmd: Command):
    ctx.session.player.morale = min(100, ctx.session.player.morale + 5)
    await _advance_time_manual(ctx, 15)
    await post_display(ctx, loc("cmd_rest.done"))


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
        await post_display(ctx, loc("cmd_bond.shared_meal").format(name=food.name))


async def cmd_say(ctx: CommandContext, cmd: Command):
    message = cmd.raw[4:] if cmd.raw.startswith("say ") else ""
    if not message:
        await post_display(ctx, loc("cmd_say.no_message"))
        return
    await broadcast_to_room(ctx, loc("social.say").format(name=ctx.session.player.name, message=message), exclude_username=ctx.session.username)
    await post_display(ctx, loc("social.say_self").format(message=message))


async def cmd_whisper(ctx: CommandContext, cmd: Command):
    parts = cmd.raw.split()
    if len(parts) < 3:
        await post_display(ctx, loc("cmd_whisper.no_target"))
        return

    target_name = parts[1]
    message = " ".join(parts[2:]) if len(parts) > 2 else ""

    target_session = _find_player_in_room(ctx, target_name)

    if not target_session:
        await post_display(ctx, f"{target_name} is not here.")
        return

    await target_session.send_display(loc("social.whisper").format(name=ctx.session.player.name, message=message))
    await post_display(ctx, loc("social.whisper_self").format(name=target_session.player.name, message=message))


async def cmd_give(ctx: CommandContext, cmd: Command):
    parts = cmd.raw.split()
    if len(parts) < 4 or "to" not in parts:
        await post_display(ctx, loc("cmd_give.usage"))
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
    await post_display(ctx, loc("cmd_give.success").format(item=item.name, target=target_session.player.name))
    await target_session.send_display(loc("cmd_give.received").format(name=ctx.session.player.name, item=item.name))


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

    target_session = _find_player_in_room(ctx, target_name)

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


def _raise_nearby_suspicion(ctx: CommandContext, amount: int) -> None:
    room = _room(ctx)
    if not room:
        return
    for npc_id in room.npcs:
        npc = ctx.shared.world.npcs.get(npc_id)
        if npc:
            npc.suspicion = min(100, npc.suspicion + amount)


def _adjust_shared_influence(shared: SharedWorldState, faction: str, delta: int) -> None:
    shared.ccp_influence, shared.gmd_influence = adjust_influence(
        shared.ccp_influence, shared.gmd_influence, faction, delta
    )


async def _apply_historical_kill(ctx: CommandContext, npc) -> None:
    effects = npc.death_influence
    if not effects:
        return
    parts = []
    for faction, delta in effects.items():
        _adjust_shared_influence(ctx.shared, faction, delta)
        parts.append(f"{faction} +{delta}")
    flag = f"historical_kill:{npc.id}"
    if flag not in ctx.session.player.flags:
        ctx.session.player.flags.append(flag)
    grow_stat(ctx.session.player, "morale", 10)
    await post_display(ctx, loc("combat.npc_falls").format(name=npc.name, parts=', '.join(parts)))


async def _attack_npc(ctx: CommandContext, npc_id: str):
    npc = ctx.shared.world.npcs.get(npc_id)
    if not npc:
        await post_display(ctx, loc("cmd_attack.not_here").format(name=npc_id))
        return

    player = ctx.session.player
    weapon = _get_equipped_weapon(player)
    armour = _get_worn_armour(player)
    result = resolve_attack(
        attacker_courage=player.courage,
        attacker_weapon=weapon,
        target_authority=npc.authority,
        target_armour=None,
        attacker_hidden=player.hidden,
        attacker_morale=player.morale,
    )

    for msg in result.messages:
        await post_display(ctx, msg)

    room = _room(ctx)
    if result.won:
        npc.hp = max(0, npc.hp - result.target_damage)
        if npc.hp <= 0:
            log_event(ctx, f"You eliminated {npc.name}.")
            await apply_action_trust(ctx, f"kill_{npc.faction}.{npc.role}", room_npcs(ctx))
            if npc.faction == "kempeitai":
                ctx.session.player.wanted_level = min(WANTED_LEVEL_MAX, ctx.session.player.wanted_level + 1)
                _adjust_shared_influence(ctx.shared, "ccp", 2)
                log_event(ctx, "The occupation will not forget this. Your face is remembered.")
            if npc.faction in COMBAT_GROWTH_FACTIONS:
                grow_stat(player, "courage", STAT_GAIN_COURAGE_COMBAT)
                await post_display(ctx, loc("combat.hardened"))
            if npc.is_historical_figure:
                await _apply_historical_kill(ctx, npc)
                ctx.shared.world.npcs.pop(npc_id, None)
            ctx.shared.dead_npcs.add(npc_id)
            if room and npc_id in room.npcs:
                room.npcs.remove(npc_id)
            await _handle_mission_objectives(ctx, "kill_npc", npc_id)
            mm = ctx.shared.milestone_manager
            if mm:
                from .milestones import apply_milestone_effects
                for m in mm.check_action("action_kill_npc"):
                    if apply_milestone_effects(player, m, ctx.shared):
                        await post_display(ctx, f"\n{m.narrative}\n")
        else:
            await post_display(ctx, loc("combat.npc_wounded").format(name=npc.name, hp=npc.hp))
        await _degrade_and_notify_weapon(ctx, weapon, True)
    else:
        if result.attacker_damaged > 0:
            player.health = max(0, player.health - result.attacker_damaged)
        await _degrade_and_notify_weapon(ctx, weapon, False)

    await _post_attack_sound(ctx, weapon, room, result.silent, f"{player.name} attacks {npc.name}!")


async def _trigger_death(ctx: CommandContext, death_msg: str) -> None:
    if "player_died" in ctx.session.player.flags:
        return
    if getattr(ctx.session, "awaiting_last_words", False):
        return
    if "last_words_spoken" not in ctx.session.player.flags:
        await ctx.session.send_display(
            "\nYour vision fades. You have one final breath. Speak your last words:\n"
        )
        ctx.session.awaiting_last_words = True
        return
    await handle_player_death(ctx, death_msg)


async def _post_attack_sound(ctx: CommandContext, weapon, room, silent: bool, broadcast: str = "") -> None:
    player = ctx.session.player
    if silent:
        return
    was_hidden = player.hidden
    player.hidden = False
    if broadcast:
        await broadcast_to_room(ctx, broadcast, exclude_username=ctx.session.username)
    intensity, max_dist, noun = _combat_sound_profile(weapon, was_hidden)
    await _propagate_combat_sound(ctx, room, intensity, max_dist, noun)
    is_dead, death_msg = check_death_conditions(ctx)
    if is_dead:
        await _trigger_death(ctx, death_msg)


def _combat_sound_profile(weapon, hidden: bool):
    from .pathfinding import SOUND_GUNSHOT, SOUND_MELEE
    wtype = weapon.weapon_type if weapon else ""
    if wtype == "firearm":
        return SOUND_GUNSHOT, 2 if hidden else 4, "gunshot"
    return SOUND_MELEE, 2, "struggle"


async def _propagate_combat_sound(ctx: CommandContext, room, intensity: int, max_distance: int, noun: str) -> None:
    from .pathfinding import propagate_sound
    heard_rooms = propagate_sound(
        ctx.shared.world.rooms, room.id, intensity,
        max_distance=max_distance, weather=getattr(ctx.shared, "weather", "clear"),
        game_time=ctx.shared.game_time,
    )
    for heard_room_id, perceived_intensity in heard_rooms:
        heard_room = ctx.shared.world.rooms.get(heard_room_id)
        if not heard_room:
            continue
        for npc_id in heard_room.npcs:
            npc = ctx.shared.world.npcs.get(npc_id)
            if npc:
                _update_npc_sound_memory(npc, room.id, perceived_intensity, noun, ctx.shared.game_time)
        if perceived_intensity >= 3:
            msg = f"You hear a loud {noun} nearby!"
        elif perceived_intensity >= 2:
            msg = f"You hear a distant {noun}."
        else:
            msg = f"You hear a muffled {noun} from somewhere nearby."
        for session in ctx.session_manager.get_players_in_room(heard_room_id):
            await session.send_display(msg + "\n")


async def _attack_player(ctx: CommandContext, target_session: Session):
    player = ctx.session.player
    target = target_session.player

    weapon = _get_equipped_weapon(player)
    target_armour = _get_worn_armour(target)

    result = resolve_attack(
        attacker_courage=player.courage,
        attacker_weapon=weapon,
        target_authority=target.courage,
        target_armour=target_armour,
        attacker_hidden=player.hidden,
        attacker_morale=player.morale,
    )

    if result.won:
        target.health = max(0, target.health - 20)
        await broadcast_to_room(ctx, loc("combat.player_strikes").format(name=player.name, target=target.name))
        log_event(ctx, f"You attacked {target.name}.")
        if target.health <= 0:
            await handle_player_death(ctx, f"You killed {target.name}.")
    else:
        if result.attacker_damaged > 0:
            player.health = max(0, player.health - result.attacker_damaged)
        await post_display(ctx, loc("combat.attack_fails").format(name=target.name))

    await _degrade_and_notify_weapon(ctx, weapon, result.won)

    await _post_attack_sound(ctx, weapon, _room(ctx), result.silent)


async def cmd_buy(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_buy.no_target"))
        return
    room = _room(ctx)
    if not room:
        return
    overrides = getattr(ctx.shared, "room_state_overrides", None)
    if overrides:
        override = overrides.get(room.id)
        if override and override.get("shop_closed"):
            await post_display(ctx, override.get("closed_reason", "This shop has closed."))
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

    season_mult = SEASONAL_PRICE_MULTIPLIER.get(_season_from_day(ctx.shared.game_time.day), 1.0)
    fabi_cost = int(fabi_cost * fabi_inflation_multiplier(ctx.shared.game_time.day) * season_mult)

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
        await apply_action_trust(ctx, f"pickpocket_{npc.faction}.{npc.role}", room_npcs(ctx))
        await post_display(ctx, loc("cmd_pickpocket.success").format(name=npc.name, amount=amount))
    else:
        _raise_nearby_suspicion(ctx, SUSPICION_FAILED_STEALTH)
        log_event(ctx, f"You were caught pickpocketing {npc.name}.")
        await apply_action_trust(ctx, f"caught_pickpocket_{npc.faction}.{npc.role}", room_npcs(ctx))
        ctx.session.player.hidden = False
        await post_display(ctx, loc("cmd_pickpocket.caught").format(name=npc.name))
        await broadcast_to_room(ctx, loc("cmd_pickpocket.caught_broadcast").format(name=ctx.session.player.name, target=npc.name))


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

    armour = _get_worn_armour(ctx.session.player)
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
    for faction, delta in reward.influence.items():
        _adjust_shared_influence(ctx.shared, faction, delta)
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
    if reward.influence:
        parts = [f"{delta:+d} {faction.upper()}" for faction, delta in reward.influence.items()]
        reward_lines.append("influence " + ", ".join(parts))
    if reward.trust:
        reward_lines.append("trust improved")
    reward_text = ", ".join(reward_lines) if reward_lines else "nothing tangible"

    log_event(ctx, f"Mission complete: {mission.title}")
    await post_display(ctx, loc("mission.complete").format(title=mission.title, rewards=reward_text))


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
            giver = ""
            if m.giver_npc_hint:
                npc = ctx.shared.world.npcs.get(m.giver_npc_hint)
                giver = f" (seek {npc.name})" if npc else f" (seek {m.giver_npc_hint})"
            lines.append(f"  [{m.id}] {m.title} (faction: {m.faction}, min trust: {m.min_trust}){giver}")
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


async def cmd_examine(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_examine.no_target"))
        return

    room = _room(ctx)
    if not room:
        return

    item = find_item_by_name(cmd.direct_obj, room.items if room else [])
    carried = False
    if not item:
        item = find_item_by_name(cmd.direct_obj, ctx.session.player.inventory)
        carried = True
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
        hint = _item_action_hint(item, carried)
        if hint:
            lines.append(hint)
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
            short = _short_name(npc.name)
            lines.append(f"You can: TALK TO {short}, ASK {short} ABOUT <topic>, ATTACK, PICKPOCKET.")
            await post_display(ctx, "\n".join(lines))
            return

    await post_display(ctx, loc("cmd_examine.not_found"))


async def cmd_map(ctx: CommandContext, cmd: Command):
    from collections import OrderedDict
    from .world import DISTRICT_LABELS

    visited = set(ctx.session.player.map_revealed)
    if not visited:
        await post_display(ctx, loc("cmd_map.not_explored"))
        return

    current = ctx.session.player.current_room
    groups = OrderedDict()
    for room_id in sorted(visited):
        room = ctx.shared.world.get_room(room_id)
        if not room:
            continue
        groups.setdefault(room.district, []).append(room)

    lines = ["Map of explored Shanghai:", ""]
    for district, rooms in groups.items():
        lines.append(DISTRICT_LABELS.get(district, district.title()).title() + ":")
        boxes = []
        for idx, room in enumerate(rooms, 1):
            mark = "*" if room.id == current else " "
            boxes.append(f"[{idx:02d}{mark}]")
        lines.append("  " + "-".join(boxes))
        connectors = []
        for room in rooms:
            for direction, dest_id in room.exits.items():
                dest = ctx.shared.world.get_room(dest_id)
                if dest and dest.district != district and direction in ("north", "south", "up", "down"):
                    arrow = {"north": "^", "south": "v", "up": "^", "down": "v"}[direction]
                    dlabel = DISTRICT_LABELS.get(dest.district, dest.district).title()
                    connectors.append(f"{arrow}{direction}: {dlabel}")
        if connectors:
            lines.append("  " + "  ".join(connectors))
        lines.append("")

    await post_display(ctx, "\n".join(lines))


async def cmd_open(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_open.no_target"))
        return

    item = _find_container(ctx, cmd.direct_obj)
    if not item:
        await post_display(ctx, loc("container.not_container"))
        return

    if item.locked:
        await post_display(ctx, loc("container.locked"))
        return

    await post_display(ctx, loc("container.opened").format(name=item.name))
    if item.container_items:
        contents = ", ".join(ci.name for ci in item.container_items)
        await post_display(ctx, loc("container.contents").format(items=contents))
    else:
        await post_display(ctx, loc("container.empty"))


async def cmd_close(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_close.no_target"))
        return

    item = _find_container(ctx, cmd.direct_obj)
    if not item:
        await post_display(ctx, loc("container.not_container"))
        return

    await post_display(ctx, loc("container.closed").format(name=item.name))


async def cmd_lock(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_lock.no_target"))
        return

    item = _find_container(ctx, cmd.direct_obj)
    if not item:
        await post_display(ctx, loc("container.not_container"))
        return

    if not item.key_id:
        await post_display(ctx, loc("container.no_lock"))
        return

    if not _has_key_for_container(ctx.session.player, item):
        await post_display(ctx, loc("container.no_key"))
        return

    item.locked = True
    await post_display(ctx, loc("container.locked_done").format(name=item.name))


async def cmd_unlock(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_unlock.no_target"))
        return

    item = _find_container(ctx, cmd.direct_obj)
    if not item:
        await post_display(ctx, loc("container.not_container"))
        return

    if not item.key_id:
        await post_display(ctx, loc("container.no_lock"))
        return

    if not _has_key_for_container(ctx.session.player, item):
        await post_display(ctx, loc("container.no_key"))
        return

    item.locked = False
    await post_display(ctx, loc("container.unlocked_done").format(name=item.name))


async def cmd_put_in(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj or not cmd.indirect_obj:
        await post_display(ctx, loc("cmd_put_in.usage"))
        return

    item = find_item_by_name(cmd.direct_obj, ctx.session.player.inventory)
    if not item:
        await post_display(ctx, loc("cmd_generic.not_held"))
        return

    container = _find_container(ctx, cmd.indirect_obj)
    if not container:
        await post_display(ctx, loc("container.not_container"))
        return

    if container.locked:
        await post_display(ctx, loc("container.locked"))
        return

    ctx.session.player.inventory.remove(item)
    container.container_items.append(item)
    await post_display(ctx, loc("container.put").format(item=item.name, container=container.name))


async def cmd_take_from(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj or not cmd.indirect_obj:
        await post_display(ctx, loc("cmd_take_from.usage"))
        return

    container = _find_container(ctx, cmd.indirect_obj)
    if not container:
        await post_display(ctx, loc("container.not_container"))
        return

    if container.locked:
        await post_display(ctx, loc("container.locked"))
        return

    item = find_item_by_name(cmd.direct_obj, container.container_items)
    if not item:
        await post_display(ctx, loc("container.not_in_there"))
        return

    container.container_items.remove(item)
    ctx.session.player.inventory.append(item)
    await post_display(ctx, loc("container.take").format(item=item.name, container=container.name))


async def cmd_wear(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_wear.no_target"))
        return

    item = find_item_by_name(cmd.direct_obj, ctx.session.player.inventory)
    if not item:
        await post_display(ctx, loc("cmd_generic.not_held"))
        return

    if not item.is_armour:
        await post_display(ctx, loc("cmd_wear.cant"))
        return

    if ctx.session.player.worn_armour_id:
        old_armour = _get_worn_armour(ctx.session.player)
        if old_armour and old_armour.id == item.id:
            await post_display(ctx, loc("cmd_wear.already"))
            return

    ctx.session.player.worn_armour_id = item.id
    await post_display(ctx, loc("cmd_wear.success").format(name=item.name, defense=item.defense_value))


async def cmd_remove(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        if not ctx.session.player.worn_armour_id:
            await post_display(ctx, loc("cmd_remove.nothing"))
            return
    else:
        item = find_item_by_name(cmd.direct_obj, ctx.session.player.inventory)
        if not item or item.id != ctx.session.player.worn_armour_id:
            await post_display(ctx, loc("cmd_remove.not_worn"))
            return

    armour = _get_worn_armour(ctx.session.player)
    ctx.session.player.worn_armour_id = ""
    if armour:
        await post_display(ctx, loc("cmd_remove.success").format(name=armour.name))
    else:
        await post_display(ctx, loc("cmd_remove.generic"))


async def cmd_write_note(ctx: CommandContext, cmd: Command):
    text = cmd.indirect_obj or ""
    if not text:
        await post_display(ctx, loc("cmd_write_note.no_text"))
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
    await post_display(ctx, loc("cmd_write_note.done"))


async def cmd_leave_note(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj or cmd.direct_obj != "note":
        await post_display(ctx, loc("cmd_leave_note.usage"))
        return

    note_item = None
    for item in ctx.session.player.inventory:
        if item.is_note:
            note_item = item
            break

    if not note_item:
        await post_display(ctx, loc("cmd_leave_note.no_note"))
        return

    room = _room(ctx)
    if not room:
        return

    ctx.session.player.inventory.remove(note_item)
    room.items.append(note_item)
    await post_display(ctx, loc("cmd_leave_note.done"))


async def cmd_flee(ctx: CommandContext, cmd: Command):
    if ctx.session.player.hidden:
        await post_display(ctx, loc("cmd_flee.hidden"))
        return

    room = _room(ctx)
    if not room or not room.exits:
        await post_display(ctx, loc("cmd_flee.nowhere"))
        return

    direction = random.choice(list(room.exits.keys()))
    ctx.session.player.morale = max(0, ctx.session.player.morale - 5)
    await post_display(ctx, loc("cmd_flee.done"))
    await cmd_go(ctx, cmd)


async def cmd_take_trishaw(ctx: CommandContext, cmd: Command):
    if cmd.verb == "take trishaw" and cmd.preposition == "to" and cmd.indirect_obj:
        target = cmd.indirect_obj.lower()
    else:
        await post_display(ctx, loc("cmd_trishaw.to_where"))
        return

    hour = ctx.shared.game_time.minute // 60
    if hour < 6 or hour >= 20:
        await post_display(ctx, loc("cmd_trishaw.hours"))
        return
    if not _check_money(ctx.session.player, 5):
        await post_display(ctx, loc("cmd_trishaw.no_fare"))
        return

    dest = None
    for rid in set(ctx.session.player.map_revealed):
        r = ctx.shared.world.get_room(rid)
        if r and (target in r.title.lower() or target in r.id.lower()):
            dest = r
            break
    if dest is None:
        candidates = [
            r for r in ctx.shared.world.rooms.values()
            if r.tags and target in [t.lower() for t in r.tags]
        ]
        if not candidates:
            await post_display(ctx, loc("movement.trishaw.no_district").format(district=target))
            return
        dest = random.choice(candidates)

    _spend_money(ctx.session.player, 5)
    ctx.session.player.current_room = dest.id
    ctx.session.player.hidden = False
    log_event(ctx, f"You took a trishaw to {dest.title}.")

    await post_display(ctx, loc("movement.trishaw.ride").format(title=dest.title))
    await _advance_time_manual(ctx, 30)

    await cmd_look(ctx, Command(verb="look"))
    await maybe_trigger_storylet(ctx)


async def cmd_yell(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_yell.no_message"))
        return

    from .pathfinding import propagate_sound, SOUND_YELL

    message = cmd.direct_obj
    player_name = ctx.session.player.name
    room = _room(ctx)
    if not room:
        return

    heard_rooms = propagate_sound(
        ctx.shared.world.rooms, room.id, SOUND_YELL,
        max_distance=3, weather=getattr(ctx.shared, "weather", "clear"),
        game_time=ctx.shared.game_time,
    )

    await broadcast_to_room(ctx, loc("social.yell").format(name=player_name, message=message))

    for heard_room_id, perceived_intensity in heard_rooms:
        heard_room = ctx.shared.world.rooms.get(heard_room_id)
        if not heard_room:
            continue
        kempeitai_found = False
        for npc_id in heard_room.npcs:
            npc = ctx.shared.world.npcs.get(npc_id)
            if not npc:
                continue
            _update_npc_sound_memory(npc, room.id, perceived_intensity, "yell", ctx.shared.game_time)
            if npc.faction == "kempeitai":
                kempeitai_found = True

        if perceived_intensity >= 3:
            msg = f'You hear someone yell: "{message}"!'
        elif perceived_intensity >= 2:
            msg = f"You hear a distant yell from nearby."
        else:
            msg = f"You hear a faint noise from somewhere nearby."
        kempeitai_msg = " You hear footsteps moving toward the noise." if kempeitai_found else ""
        for session in ctx.session_manager.get_players_in_room(heard_room_id):
            await session.send_display(msg + kempeitai_msg + "\n")

    log_event(ctx, f"You yelled: \"{message}\"")


async def cmd_sound(ctx: CommandContext, cmd: Command):
    arg = (cmd.direct_obj or cmd.preposition or "").lower()
    if arg in ("on", "yes", "true"):
        ctx.session.audio_enabled = True
        await post_display(ctx, loc("cmd_sound.on"))
    elif arg in ("off", "no", "false"):
        ctx.session.audio_enabled = False
        await post_display(ctx, loc("cmd_sound.off"))
    else:
        current = getattr(ctx.session, 'audio_enabled', False)
        await post_display(ctx, loc("cmd_sound.status").format(state="ON" if current else "OFF"))


async def cmd_mod_weapon(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj or not cmd.indirect_obj:
        await post_display(ctx, loc("cmd_mod.usage"))
        return

    weapon_name = cmd.direct_obj
    mod_name = cmd.indirect_obj

    weapon = find_item_by_name(weapon_name, ctx.session.player.inventory)
    if not weapon or not weapon.is_weapon:
        await post_display(ctx, loc("cmd_mod.no_weapon"))
        return

    mod = find_item_by_name(mod_name, ctx.session.player.inventory)
    if not mod or not mod.is_mod:
        await post_display(ctx, loc("cmd_mod.no_mod"))
        return

    weapon.mods = getattr(weapon, 'mods', [])
    weapon.mod_slots = getattr(weapon, 'mod_slots', [])

    if len(weapon.mods) >= len(weapon.mod_slots):
        await post_display(ctx, loc("cmd_mod.no_slot"))
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
    await post_display(ctx, loc("cmd_mod.success").format(mod=mod.name, weapon=weapon.name, type=mod.mod_type, bonus=mod.mod_bonus))


async def cmd_hide_for(ctx: CommandContext, cmd: Command):
    raw = cmd.raw
    parts = raw.split()
    if len(parts) < 6 or "in" not in [p.lower() for p in parts]:
        await post_display(ctx, loc("cmd_hide_for.usage"))
        return

    in_idx = next(i for i, p in enumerate(parts) if p.lower() == "in")
    recipient_name = parts[2] if len(parts) > 2 else ""
    item_name = " ".join(parts[3:in_idx])
    signal = " ".join(parts[in_idx + 1:])

    if not item_name or not signal:
        await post_display(ctx, loc("cmd_hide_for.no_detail"))
        return

    room = _room(ctx)
    if not room:
        return

    item = find_item_by_name(item_name, ctx.session.player.inventory)
    if not item:
        await post_display(ctx, loc("cmd_hide_for.no_item").format(item=item_name))
        return

    from .world import replace as copy_item
    drop_item = copy_item(item)
    room.dead_drops.append({
        "item": drop_item,
        "signal": signal.lower(),
        "recipient": recipient_name.lower(),
        "hider": ctx.session.player.name,
    })
    ctx.session.player.inventory.remove(item)
    await post_display(ctx, loc("cmd_hide_for.success").format(name=item.name, signal=signal))


async def cmd_search(ctx: CommandContext, cmd: Command):
    detail = cmd.direct_obj
    if not detail:
        await post_display(ctx, loc("cmd_search.usage"))
        return

    room = _room(ctx)
    if not room:
        return

    detail_lower = detail.lower()

    for drop in room.dead_drops[:]:
        if drop["signal"] == detail_lower:
            recipient = drop.get("recipient", "")
            is_recipient = (
                recipient in (ctx.session.username.lower(), ctx.session.player.name.lower(), "")
            )
            if is_recipient:
                item = drop["item"]
                ctx.session.player.inventory.append(item)
                room.dead_drops.remove(drop)
                await post_display(ctx, loc("cmd_search.found_drop").format(detail=detail, name=item.name))
                return

    if room.hidden_exits:
        perception_roll = ctx.session.player.perception + random.randint(1, 20)
        for direction, dest_id in room.hidden_exits.items():
            if detail_lower in direction.lower():
                if perception_roll >= 25:
                    room.exits[direction] = dest_id
                    grow_stat(ctx.session.player, "perception", STAT_GAIN_PERCEPTION_OBSERVE)
                    await post_display(ctx, loc("cmd_search.found_exit").format(direction=direction))
                    return
                else:
                    await post_display(ctx, loc("perception.hidden_exit_sense").format(direction=direction))
                    return

    await post_display(ctx, loc("cmd_search.nothing").format(detail=detail))


async def cmd_memorial(ctx: CommandContext, cmd: Command):
    if not ctx.shared.legacy_book:
        await post_display(ctx, loc("cmd_memorial.empty"))
        return

    entries = ctx.shared.legacy_book[-20:]
    if not entries:
        await post_display(ctx, loc("cmd_memorial.no_entries"))
        return

    lines = ["Memorial", ""]
    for entry in entries:
        name = entry.get("character_name", "Unknown")
        day = entry.get("day_of_death", "?")
        obituary = entry.get("obituary", "")
        last_words = entry.get("last_words", "")
        lines.append(f"{name}, Day {day}")
        if obituary:
            lines.append(obituary)
        if last_words:
            lines.append(f'  Last words: "{last_words}"')
        lines.append("")

    await post_display(ctx, "\n".join(lines))


async def cmd_rumors(ctx: CommandContext, cmd: Command):
    lines = []
    active = list(getattr(ctx.shared, "active_rumors", []))
    if active:
        from .rumors import load_rumors
        catalog = load_rumors("server/data/custom/rumors.yaml")
        heard = []
        lines += ["Street talk:", ""]
        for rid in active:
            r = catalog.get(rid)
            if r:
                lines.append(f"  {r.text}")
                heard.append(r.text)
        if heard:
            record_conversation(ctx, "_rumor", "What's the word on the street?", " | ".join(heard))
    decisions = getattr(ctx.shared, "world_decisions", None)
    recent = [d for d in decisions if d["day"] >= ctx.shared.game_time.day - 1] if decisions else []
    if recent:
        if lines:
            lines.append("")
        lines += ["Notable events:", ""]
        for d in recent[-10:]:
            dtype = d["decision_type"]
            actor = ctx.shared.world.npcs.get(d["actor_npc_id"])
            name = actor.name if actor else "Someone"
            if dtype == "vendor_shutter":
                lines.append(f"  {name} shuttered their shop on Day {d['day']}; some say they fled the city.")
            elif dtype == "defection":
                old = d.get("effects", {}).get("old_faction", "")
                new = d.get("effects", {}).get("new_faction", "")
                lines.append(f"  {name} has abandoned the {old.upper()} for the {new.upper()}.")
            elif dtype == "extortion":
                lines.append(f"  {name} was seen shaking down a civilian for protection money.")
            else:
                lines.append(f"  {name}, {dtype} on Day {d['day']}.")
    if not lines:
        await post_display(ctx, loc("cmd_rumors.quiet"))
        return
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
                await post_display(ctx, loc("mission.expired").format(id=mid))
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
        await post_display(ctx, loc("cmd_tail.spotted").format(name=target.name))
        return
    target_room = ctx.shared.world.npc_locations.get(target.id)
    if success and target_room and ctx.session.player.current_room != target_room:
        ctx.session.player.current_room = target_room
        ctx.session.player.hidden = False
        await post_display(ctx, loc("cmd_tail.shadowing").format(name=target.name))


async def check_curfew_penalty(ctx: CommandContext):
    if ctx.shared.game_time.minute < CURFEW_MINUTE:
        return
    if ctx.session.player.last_curfew_penalty_day == ctx.shared.game_time.day:
        return
    room = _room(ctx)
    if room and not room.indoors:
        await apply_action_trust(ctx, "out_after_curfew", room.npcs)
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


async def cmd_claim(ctx: CommandContext, cmd: Command):
    room = _room(ctx)
    if not room:
        await post_display(ctx, loc("cmd_claim.nothing"))
        return
    if not getattr(room, "safe_room", False):
        await post_display(ctx, loc("cmd_claim.not_safe"))
        return
    set_safehouse(ctx.session.username, room.id)
    await post_display(ctx, loc("cmd_claim.success").format(title=room.title))


async def cmd_retrieve(ctx: CommandContext, cmd: Command):
    from .auth import resolve_spawn_room, withdraw_stash
    from .serialization import deserialize_item
    from .save_manager import save_player
    safehouse = resolve_spawn_room(ctx.session.username)
    room = _room(ctx)
    if not safehouse or not room or room.id != safehouse:
        await post_display(ctx, loc("cmd_retrieve.wrong_place"))
        return
    stash = withdraw_stash(ctx.session.username)
    if not stash:
        await post_display(ctx, loc("cmd_retrieve.empty"))
        return
    recovered = []
    for data in stash:
        item = deserialize_item(data)
        ctx.session.player.inventory.append(item)
        recovered.append(item.name)
    save_player(ctx.session.player)
    await post_display(ctx, loc("cmd_retrieve.success").format(items=', '.join(recovered)))


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
            "ask": cmd_ask_about,
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
            "sound": cmd_sound,
            "memorial": cmd_memorial,
            "rumors": cmd_rumors,
            "rumours": cmd_rumors,
            "claim": cmd_claim,
            "retrieve": cmd_retrieve,
            "hide for": cmd_hide_for,
            "unknown": cmd_stub,
        }
    return _COMMAND_REGISTRY
