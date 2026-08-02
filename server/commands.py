import asyncio
import json
import random
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, NamedTuple, Optional, TYPE_CHECKING
import yaml

from .config import get_setting, load_dotenv
from .journal import collect_recent_events, format_journal, format_life_retrospective, absorb_death_journal
from .locales import get as loc
from .locales import load_locale
from .npc import Npc, get_contextual_dialogue, match_topic, get_topic_dialogue, npc_ask_topics
from .npc_memory import npc_memory_system
from .rumors import create_rumour_seed
from .social_consequences import find_consequence_ask_lead, find_consequence_rumour, room_consequence_manifestations
from .parser import Command, parse
from .player_data import PlayerData, _reset_player_defaults, grow_stat
from .auth import set_safehouse
from .serialization import _load_yaml, deserialize_item, serialize_item
from .session import Session
from .stealth import Disguise, StealthSystem, TailingState
from .storylets import ActiveStorylet, StoryletManager, StoryletOption, load_storylets
from .time_system import EventScheduler, GameTime, time_str
from .trust import (apply_trust_delta, change_trust, exchange_gossip, get_role_trust, load_trust_rules, summarize_faction_trust, TrackedRumor,)
from .victory import (check_victory_conditions, compute_progress, generate_liberation_ending, adjust_influence, predict_ending, fabi_inflation_multiplier, _season_from_day, DAY_LIBERATION,)
from .world import DISTRICT_LABELS, Item, World, replace
from .formatting import format_bold, format_bold_italic


def _drop_npc_loot(room, npc: Npc, player: PlayerData, PlayerData, drop_chance: float = 0.3) -> List[Item]:
    if not room:
        return []

    dropped = []
    all_items = (
        list(npc.shop_inventory) +
        list(npc.black_market_items) +
        list(npc.inventory)
    )

    if not all_items:
        return []

    quest_items = []
    regular_items = []
    for item_data in all_items:
        if item_data.get("is_quest_item", False):
            quest_items.append(item_data)
        else:
            regular_items.append(item_data)

    for item_data in quest_items:
        item_id = item_data.get("id", item_data.get("item_id", ""))
        if not item_id:
            continue
        item = Item(
            id=item_id,
            name=item_data.get("name", item_id),
            description=item_data.get("description", ""),
            base_cost=item_data.get("base_cost", item_data.get("cost", 10)),
            category=item_data.get("category", ""),
            is_quest_item=True,
        )
        room.items.append(item)
        dropped.append(item)

    if regular_items and drop_chance > 0:
        max_drops = max(1, round(len(regular_items) * drop_chance))
        num_drops = random.randint(1, min(3, max_drops, len(regular_items)))
        selected = random.sample(regular_items, num_drops)
        for item_data in selected:
            item_id = item_data.get("id", item_data.get("item_id", ""))
            if not item_id:
                continue
            is_contraband = item_data.get("contraband_risk", False)
            item = Item(
                id=item_id,
                name=item_data.get("name", item_id),
                description=item_data.get("description", ""),
                base_cost=item_data.get("base_cost", item_data.get("cost", 10)),
                category=item_data.get("category", ""),
                is_quest_item=item_data.get("is_quest_item", False),
                contraband_risk=is_contraband,
                evidence=is_contraband,
            )
            room.items.append(item)
            dropped.append(item)

    return dropped


async def _handle_witness_reactions(ctx, room, npc: Npc, victim_id: str):
    if not room:
        return

    current_day = ctx.shared.game_time.day
    player_name = ctx.session.player.name
    witnesses = []

    for npc_id in room.npcs:
        if npc_id == victim_id:
            continue
        witness = ctx.shared.world.npcs.get(npc_id)
        if witness:
            witnesses.append(witness)
            npc_memory_system.record_interaction(
                witness,
                player_name,
                "witnessed_murder",
                {"victim": npc.name, "victim_id": victim_id},
                current_day,
            )

    for witness in witnesses:
        reaction = _generate_witness_reaction(witness, ctx.session.player)
        if reaction:
            await post_display(ctx, f"{format_bold(witness.name)} {reaction}", msg_type="combat")

    if "crime_scene" not in room.tags:
        room.tags.append("crime_scene")
    from .constants import CRIME_SCENE_DURATION_DAYS
    room.crime_scene_until_day = ctx.shared.game_time.day + CRIME_SCENE_DURATION_DAYS

    if witnesses:
        _schedule_witness_propagation(ctx, witnesses, npc.name, victim_id, room)


def _schedule_witness_propagation(ctx, witnesses: list, victim_name: str, victim_id: str, room) -> None:
    if not hasattr(ctx.shared, 'scheduler'):
        return
    current_minute = ctx.shared.game_time.minute
    for i, witness in enumerate(witnesses[:3]):
        delay = 30 + (i * 30)
        trigger_minute = current_minute + delay
        event_id = f"witness_{witness.id}_{victim_id}_{trigger_minute}"
        ctx.shared.scheduler.schedule(
            event_id, trigger_minute,
            {"type": "witness_report", "witness_id": witness.id,
             "victim_name": victim_name, "victim_id": victim_id,
             "room_district": getattr(room, 'district', ''),
             "day": ctx.shared.game_time.day}
        )


def _generate_witness_reaction(witness: Npc, player) -> Optional[str]:
    import random

    integrity = (witness.personality_traits or {}).get("integrity", 50)
    bravery = (witness.personality_traits or {}).get("bravery", 50)

    reactions = []

    if integrity > 60:
        reactions.extend(["shouts for the police!", "attacks you without hesitation!"])
    if integrity > 60 and bravery > 60:
        reactions.append("attacks with a fury!")
    if bravery < 40:
        reactions.extend(["flees in terror!", "runs away!"])
    if bravery > 60:
        reactions.extend(["stands their ground.", "pulls out a weapon."])

    if witness.faction == "kempeitai":
        reactions.append("shouts: 'You will pay for this!'")
    elif witness.faction in ("ccp", "gmd"):
        reactions.append("nods grimly.")

    if witness.faction == "civilian":
        if bravery < 40:
            pass 
        else:
            reactions.extend(["runs for help!", "covers their mouth in shock."])

    if not reactions:
        return None

    return random.choice(reactions)
from .game_world import SharedWorldState
from .combat import resolve_attack, degrade_weapon, degrade_armour
from .constants import (
    EVENTS_PATH, TRUST_RULES_PATH, DISGUISES_PATH, STORYLETS_PATH,
    OBITUARY_PATH, BACKGROUNDS_PATH, CURFEW_MINUTE, STATE_BROADCAST_INTERVAL,
    EVENT_LOG_MAXLEN, WORLD_EVENTS_MAXLEN, CONVERSATION_HISTORY_MAXLEN,
    HUNGER_DECAY_RATE, HUNGER_HEALTH_DAMAGE, LOW_HUNGER_THRESHOLD,
    RICE_BOWL_COST, BAOZI_COST, TEA_COST, PICKPOCKET_BASE,
    MISSION_FABI_RANGE,
    STAT_GAIN_COURAGE_COMBAT, STAT_GAIN_STEALTH_HIDE, STAT_GAIN_PERCEPTION_OBSERVE,
    COMBAT_GROWTH_FACTIONS, WANTED_LEVEL_MAX, SUSPICION_FAILED_STEALTH,
    SEASONAL_PRICE_MULTIPLIER,
    HUNGER_TIER_SATISFIED, HUNGER_TIER_PECKISH, HUNGER_TIER_HUNGRY,
    HUNGER_TIER_FAMISHED, HUNGER_TIER_STARVING,
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


def _get_hunger_tier_name(hunger: int) -> str:
    if hunger >= HUNGER_TIER_SATISFIED:
        return loc("hunger.tier.satisfied")
    elif hunger >= HUNGER_TIER_PECKISH:
        return loc("hunger.tier.peckish")
    elif hunger >= HUNGER_TIER_HUNGRY:
        return loc("hunger.tier.hungry")
    elif hunger >= HUNGER_TIER_FAMISHED:
        return loc("hunger.tier.famished")
    else:
        return loc("hunger.tier.starving")


def _room(ctx: CommandContext):
    if not ctx.shared:
        return None
    
    player = ctx.session.player
    room_id = player.current_room
    
    if getattr(player, 'in_tutorial', False) and hasattr(player, 'tutorial_instance_id'):
        from .tutorial import get_cloned_room_id
        cloned_id = get_cloned_room_id(
            player.tutorial_instance_id, 
            room_id, 
            ctx.shared
        )
        if cloned_id != room_id:
            return ctx.shared.world.get_room(cloned_id)
    
    return ctx.shared.world.get_room(room_id)


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
    if getattr(p, 'in_tutorial', False):
        from .tutorial import get_tutorial_hint
        hint = get_tutorial_hint(p)
        if hint:
            return hint
        stage = getattr(p, 'tutorial_stage', 0)
        if stage < 95:
            return "Complete the tutorial to learn the basics."