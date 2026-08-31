import asyncio
import json
import logging
import random
import re
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, NamedTuple, Optional, TYPE_CHECKING
import yaml

from .config import get_setting, load_dotenv
from .action_result import CommandOutcome, failure, success

ROOM_NOTIFY_TIMEOUT = 0.5
from .economy import can_afford_fabi, earn_fabi_value, spend_fabi_value, wallet_fabi_value
from .curfew import CurfewTrigger, game_clock_total_minutes, resolve_curfew_encounter
from .equipment import confiscate_equipped_disguise, equipped_disguise, equipped_weapon, invalidate_disguise_if_support_lost
from .journal import format_life_retrospective, absorb_death_journal
from .law import (
    adjust_wanted,
    is_curfew,
    record_crime,
    vendor_access,
    wanted_consequences,
)
from .locales import get as loc
from .locales import load_locale
from .npc import Npc, display_topic_label, get_contextual_dialogue, match_topic, get_topic_dialogue, npc_ask_topics
from .npc_memory import npc_memory_system
from .rumors import create_rumour_seed
from .social_consequences import find_consequence_ask_lead, find_consequence_rumour, room_consequence_manifestations
from .parser import Command, parse
from .patrols import is_transient_patrol_id
from .player_data import PlayerData, _reset_player_defaults, grow_stat
from .auth import set_safehouse
from .serialization import _load_yaml, deserialize_item, serialize_item
from .session import Session
from .survival import get_hunger_tier_label
from .stealth import Disguise, StealthSystem, TailingState
from .storylets import ActiveStorylet, StoryletManager, StoryletOption, load_storylets
from .time_system import EventScheduler, GameTime, time_str
from .trust import (apply_trust_delta, change_trust, exchange_gossip, get_role_trust, load_trust_rules, summarize_faction_trust,)
from .victory import (compute_progress, generate_liberation_ending, adjust_influence, predict_ending, fabi_inflation_multiplier, _season_from_day, DAY_LIBERATION, resolve_shared_liberation,)
from .world import DISTRICT_LABELS, Item, World, replace
from .formatting import format_bold, format_bold_italic, semantic_span
from .rewards import grant_catalog_item, validate_catalog_item

logger = logging.getLogger(__name__)


def _drop_npc_loot(room, npc: Npc, player: PlayerData, drop_chance: float = 0.3) -> List[Item]:
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


async def _handle_witness_reactions(ctx, room, npc: Npc, victim_id: str, sound_event=None):
    if not room:
        return

    current_day = ctx.shared.game_time.day
    player_name = ctx.session.player.name
    witnesses = []
    room_witness_ids = _sound_witness_ids(room, victim_id, sound_event)

    for npc_id in room_witness_ids:
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
            await post_display(ctx, f"{semantic_span(witness.name, 'npc')} {reaction}", msg_type="combat")

    if "crime_scene" not in room.tags:
        room.tags.append("crime_scene")
    from .constants import CRIME_SCENE_DURATION_DAYS
    room.crime_scene_until_day = ctx.shared.game_time.day + CRIME_SCENE_DURATION_DAYS

    if witnesses:
        _schedule_witness_propagation(ctx, witnesses, npc.name, victim_id, room)


def _sound_witness_ids(room, victim_id: str, sound_event=None) -> list[str]:
    if not room or sound_event is not None and sound_event.suppress_witnesses:
        return []
    return [npc_id for npc_id in room.npcs if npc_id != victim_id]


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
from .game_world import SharedWorldState, is_named_npc_dead, named_npc_death_record_to_dict, record_named_npc_death
from .combat import resolve_attack, degrade_weapon, degrade_armour, courage_multiplier_for
from .constants import (
    EVENTS_PATH, TRUST_RULES_PATH, DISGUISES_PATH, STORYLETS_PATH,
    OBITUARY_PATH, CHARACTER_NAMES_PATH, CURFEW_MINUTE, STATE_BROADCAST_INTERVAL,
    EVENT_LOG_MAXLEN, WORLD_EVENTS_MAXLEN, CONVERSATION_HISTORY_MAXLEN,
    RICE_BOWL_COST, BAOZI_COST, TEA_COST, PICKPOCKET_BASE,
    MISSION_FABI_RANGE,
    STAT_GAIN_COURAGE_COMBAT, STAT_GAIN_STEALTH_HIDE, STAT_GAIN_PERCEPTION_OBSERVE,
    COMBAT_GROWTH_FACTIONS, WANTED_LEVEL_MAX, SUSPICION_FAILED_STEALTH,
    SEASONAL_PRICE_MULTIPLIER, MessageType,
    ACTIONABLE_SOUND_KINDS,
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


def _context_for_session(ctx: CommandContext, session: Session) -> CommandContext:
    manager = ctx.session_manager
    maker = getattr(manager, "_make_context", None)
    if callable(maker):
        candidate = maker(session)
        if isinstance(candidate, CommandContext):
            return candidate
    room = ctx.shared.world.get_room(session.player.current_room)
    return CommandContext(
        session=session,
        shared=ctx.shared,
        session_manager=manager,
        disguises=ctx.disguises,
        stealth=ctx.stealth,
        storylet_manager=ctx.storylet_manager,
        room=room,
    )


class VendorPurchaseContext(NamedTuple):
    npc_id: str
    npc: Optional[Npc]
    room: Optional[Any]
    shop_inventory: List[Any]
    black_market_items: List[Any]
    trust_score: int
    wanted_policy: Any
    access: Any
    error: str
    error_message: str
    demo_black_market: bool = False


def _vendor_item_id(item_data: Any) -> str:
    if isinstance(item_data, dict):
        return item_data.get("item_id") or item_data.get("id") or ""
    return str(item_data)


def _is_tutorial_vendor_clone(player: Any, vendor_id: str) -> bool:
    instance_id = getattr(player, "tutorial_instance_id", "")
    return bool(
        getattr(player, "in_tutorial", False)
        and instance_id
        and vendor_id.startswith(f"tut_{instance_id}_")
    )


def _deplete_tutorial_vendor_stock(ctx: CommandContext, vendor_id: str, item_id: str) -> None:
    if not _is_tutorial_vendor_clone(ctx.session.player, vendor_id):
        return
    vendor = ctx.shared.world.npcs.get(vendor_id)
    if not vendor:
        return
    from .tutorial import get_canonical_tutorial_npc_id, record_tutorial_vendor_depletion
    canonical_vendor = get_canonical_tutorial_npc_id(
        getattr(ctx.session.player, "tutorial_instance_id", ""), vendor_id,
    )
    for stock_attr in ("shop_inventory", "black_market_items"):
        stock = getattr(vendor, stock_attr, []) or []
        for index, item_data in enumerate(stock):
            if _vendor_item_id(item_data) == item_id:
                del stock[index]
                record_tutorial_vendor_depletion(ctx.session.player, canonical_vendor, item_id)
                return


def validate_vendor_purchase_context(
    ctx: CommandContext,
    vendor_id: str,
    target_id: Optional[str] = None,
) -> VendorPurchaseContext:
    room = _room(ctx)
    if not isinstance(vendor_id, str):
        return VendorPurchaseContext("", None, room, [], [], 0, None, None, "not_here", "")
    npc = ctx.shared.world.npcs.get(vendor_id)
    empty = VendorPurchaseContext(vendor_id, npc, room, [], [], 0, None, None, "not_here", "")
    if not room or not npc or vendor_id not in getattr(room, "npcs", []):
        return empty
    mapped_room = getattr(ctx.shared.world, "npc_locations", {}).get(vendor_id)
    if mapped_room is not None and mapped_room != room.id:
        return empty
    if (
        getattr(npc, "hp", 100) <= 0
        or getattr(npc, "dead", False)
        or is_named_npc_dead(ctx.shared, vendor_id)
    ):
        return empty

    overrides = getattr(ctx.shared, "room_state_overrides", {}).get(room.id, {})
    if overrides.get("shop_closed"):
        return VendorPurchaseContext(
            vendor_id, npc, room, [], [], 0, None, None, "closed",
            overrides.get("closed_reason", "The shop is closed."),
        )

    shop_inventory = list(getattr(npc, "shop_inventory", []) or [])
    black_market_items = list(getattr(npc, "black_market_items", []) or [])
    from .trust import has_faction_perk
    from .tutorial import is_tutorial_black_market_demo_vendor
    demo_black_market = is_tutorial_black_market_demo_vendor(ctx.session.player, vendor_id)
    if black_market_items and not demo_black_market and not has_faction_perk(ctx.session.player.trust, npc.faction):
        black_market_items = []

    vendor_role = str(getattr(npc, "role", "")).lower()
    vendor_capable = vendor_role in {"vendor", "merchant"} or bool(shop_inventory or black_market_items)
    if not vendor_capable:
        return VendorPurchaseContext(
            vendor_id, npc, room, [], [], 0, None, None, "no_stock", "",
        )

    trust_score = get_role_trust(ctx.session.player.trust, npc.faction, None)
    wanted_policy = wanted_consequences(ctx.session.player.wanted_level)
    access = vendor_access(wanted_policy.level, black_market=bool(black_market_items))
    if not access.available and not black_market_items:
        return VendorPurchaseContext(
            vendor_id, npc, room, [], black_market_items, trust_score,
            wanted_policy, access, "wanted", "",
        )
    if not access.available:
        shop_inventory = []

    if target_id is not None:
        if not isinstance(target_id, str):
            return VendorPurchaseContext(
                vendor_id, npc, room, shop_inventory, black_market_items,
                trust_score, wanted_policy, access, "item_unavailable", "",
            )
        if target_id == "newspaper":
            if ctx.session.player.last_newspaper_day == ctx.shared.game_time.day:
                return VendorPurchaseContext(
                    vendor_id, npc, room, shop_inventory, black_market_items,
                    trust_score, wanted_policy, access, "newspaper_unavailable", "",
                )
        else:
            available_ids = {
                _vendor_item_id(item_data)
                for item_data in shop_inventory
            }
            if trust_score >= 70 or demo_black_market:
                available_ids.update(_vendor_item_id(item_data) for item_data in black_market_items)
            if target_id not in available_ids or target_id not in ctx.shared.world.item_catalog:
                return VendorPurchaseContext(
                    vendor_id, npc, room, shop_inventory, black_market_items,
                    trust_score, wanted_policy, access, "item_unavailable", "",
                )

    return VendorPurchaseContext(
        vendor_id, npc, room, shop_inventory, black_market_items,
        trust_score, wanted_policy, access, "", "", demo_black_market,
    )


def _sanitize_slot_name(raw: str) -> str:
    import re
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", raw.strip().lower()).strip("_")
    return cleaned or "default"


def _normalize_back_room_ledger(player, server_cycle: int) -> None:
    if player.black_market_purchase_cycle != server_cycle:
        player.black_market_purchases = {}
        player.black_market_purchase_cycle = server_cycle


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
    import re
    q = re.sub(r"^(?:a|an|the)\s+", "", name.lower().strip())
    for item in items:
        if item.name.lower() == q or item.id.lower() == q:
            return item
    for item in items:
        if q in item.name.lower() or q in item.id.lower():
            return item
    return None


def find_item_exact(name: str, items: List[Item]) -> Optional[Item]:
    q = (name or "").lower().strip()
    for item in items:
        identity = getattr(item, "instance_id", "") or ""
        if identity and identity.lower() == q:
            return item
    return find_item_by_name(name, items)


def find_item_by_instance(target_id: str, items: List[Item]) -> Optional[Item]:
    q = (target_id or "").strip()
    for item in items:
        identity = getattr(item, "instance_id", "") or ""
        if identity == q:
            if q == item.id and sum(1 for other in items if other.id == item.id) > 1:
                return None
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
        hint = get_tutorial_hint(p, shared=ctx.shared)
        if hint:
            return hint
        stage = getattr(p, 'tutorial_stage', 0)
        if stage < 95:
            return "Complete the tutorial to learn the basics."
    if p.active_missions:
        mm = ctx.shared.mission_manager
        mission = mm.missions.get(p.active_missions[0].get("mission_id")) if mm else None
        if mission:
            return f"Mission: {mission.title}."
    return "Find work: seek a faction contact (MISSIONS AVAILABLE) and build trust to sway the Liberation."


def _topic_hint(npc) -> str:
    topics = [display_topic_label(npc, t) for t in npc_ask_topics(npc)]
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


async def _handle_room_hint_query(ctx: CommandContext, room):
    hints = getattr(room, "hints", [])
    if not hints:
        await post_display(ctx, loc("room_hints.no_hints").format(room=room.title), msg_type="ambient")
        return
    
    discovered = ctx.session.player.discovered_room_hints
    room_discovered = discovered.get(room.id, [])
    
    undiscovered = [h for h in hints if h not in room_discovered]
    
    if not undiscovered:
        await post_display(ctx, loc("room_hints.already_discovered").format(room=room.title), msg_type="ambient")
        return
    
    import random
    hint = random.choice(undiscovered)
    
    if room.id not in ctx.session.player.discovered_room_hints:
        ctx.session.player.discovered_room_hints[room.id] = []
    ctx.session.player.discovered_room_hints[room.id].append(hint)
    
    await post_display(ctx, loc("room_hints.discovered").format(room=room.title, hint=hint), msg_type="discovery")


_TERMINAL_GUIDANCE_FAMILIES = (
    "vendor",
    "loose_item",
    "container",
    "safe_room",
    "immediate_danger",
)


def _visible_terminal_guidance_families(ctx: CommandContext, room) -> list[str]:
    if not room or getattr(ctx.session.player, "in_tutorial", False):
        return []

    families = []
    for npc_id in getattr(room, "npcs", []):
        npc = ctx.shared.world.npcs.get(npc_id)
        if not npc or is_named_npc_dead(ctx.shared, npc_id):
            continue
        role = str(getattr(npc, "role", "")).lower()
        if role in {"vendor", "merchant"} or getattr(npc, "shop_inventory", None) or getattr(npc, "black_market_items", None):
            if "vendor" not in families:
                families.append("vendor")
        if _is_authority_npc(npc) and "immediate_danger" not in families:
            families.append("immediate_danger")

    visible_items = [item for item in getattr(room, "items", []) if not getattr(item, "concealed", False)]
    if any(getattr(item, "is_container", False) for item in visible_items):
        families.append("container")
    if any(getattr(item, "takeable", False) and not getattr(item, "is_container", False) for item in visible_items):
        families.append("loose_item")
    if getattr(room, "safe_room", False):
        families.append("safe_room")
    if getattr(ctx.session, "_patrol_warning_signature", None) and "immediate_danger" not in families:
        families.append("immediate_danger")
    return [family for family in _TERMINAL_GUIDANCE_FAMILIES if family in families]


def _terminal_guidance_marker(player, family: str, recovery: bool = False) -> list[str]:
    field_name = "terminal_guidance_recovery_seen" if recovery else "terminal_guidance_first_seen"
    markers = getattr(player, field_name, None)
    if not isinstance(markers, list):
        markers = []
        setattr(player, field_name, markers)
    return markers


def _mark_terminal_guidance(player, family: str, recovery: bool = False) -> bool:
    if family not in _TERMINAL_GUIDANCE_FAMILIES:
        return False
    markers = _terminal_guidance_marker(player, family, recovery)
    if family in markers:
        return False
    markers.append(family)
    return True


async def _emit_terminal_guidance(ctx: CommandContext, room) -> None:
    cycle = int(getattr(ctx.shared, "server_cycle", 1))
    if getattr(ctx.session.player, "terminal_guidance_cycle", cycle) != cycle:
        ctx.session.player.terminal_guidance_first_seen = []
        ctx.session.player.terminal_guidance_recovery_seen = []
        ctx.session.player.terminal_guidance_cycle = cycle
    for family in _visible_terminal_guidance_families(ctx, room):
        if _mark_terminal_guidance(ctx.session.player, family):
            await post_display(ctx, loc(f"terminal_guidance.{family}.first"), msg_type="system")
            return


def _visible_item(ctx: CommandContext, target: str):
    room = _room(ctx)
    if not room or not target:
        return None
    return find_item_exact(target, [item for item in room.items if not getattr(item, "concealed", False)])


def _visible_vendor(ctx: CommandContext, target: str):
    npc_id = resolve_npc(ctx, target)
    if not npc_id:
        return None
    npc = ctx.shared.world.npcs.get(npc_id)
    if not npc or is_named_npc_dead(ctx.shared, npc_id):
        return None
    role = str(getattr(npc, "role", "")).lower()
    if role not in {"vendor", "merchant"} and not getattr(npc, "shop_inventory", None) and not getattr(npc, "black_market_items", None):
        return None
    return npc


def _terminal_recovery_family(ctx: CommandContext, cmd, result) -> str:
    if result.succeeded or getattr(ctx.session.player, "in_tutorial", False):
        return ""
    room = _room(ctx)
    if not room:
        return ""
    verb = getattr(cmd, "verb", "")
    direct = getattr(cmd, "direct_obj", "") or ""
    if verb == "buy from" and _visible_vendor(ctx, direct):
        return "vendor"
    if verb in {"take", "read", "eat", "drop"} and direct and _visible_item(ctx, direct):
        return "loose_item"
    if verb in {"open", "take from"}:
        target = direct if verb == "open" else (getattr(cmd, "indirect_obj", "") or "")
        item = _visible_item(ctx, target)
        if item and getattr(item, "is_container", False):
            return "container"
    if verb == "claim" and getattr(room, "safe_room", False):
        return "safe_room"
    if verb == "hide" and "immediate_danger" in _visible_terminal_guidance_families(ctx, room):
        return "immediate_danger"
    return ""


async def _record_terminal_recovery(ctx: CommandContext, cmd, result) -> None:
    cycle = int(getattr(ctx.shared, "server_cycle", 1))
    if getattr(ctx.session.player, "terminal_guidance_cycle", cycle) != cycle:
        ctx.session.player.terminal_guidance_first_seen = []
        ctx.session.player.terminal_guidance_recovery_seen = []
        ctx.session.player.terminal_guidance_cycle = cycle
    family = _terminal_recovery_family(ctx, cmd, result)
    if family and _mark_terminal_guidance(ctx.session.player, family, recovery=True):
        await post_display(ctx, loc(f"terminal_guidance.{family}.recovery"), msg_type="system")


def _item_tag(item) -> str:
    if item.food_value > 0:
        return "food: EAT"
    if item.is_weapon:
        return "weapon: ATTACK"
    if item.is_armour:
        return "armour: EQUIP"
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
        acts.append("EQUIP/REMOVE it")
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
        is_disabled = option.disabled if hasattr(option, "disabled") else option.get("disabled", False)
        if is_disabled:
            lines.append(f"    {_option_text(option)}")
        else:
            lines.append(f"{idx}. {_option_text(option)}")
    return "\n".join(lines)


def _bfs_find_path(world: World, start_room_id: str, target_room_id: str) -> List[str]:
    from .pathfinding import a_star_find_path, make_cost_fn
    cost_fn = make_cost_fn(world.rooms)
    return a_star_find_path(world.rooms, start_room_id, target_room_id, cost_fn)


def room_npcs(ctx: CommandContext) -> List[str]:
    room = _room(ctx)
    return room.npcs if room else []


def _update_npc_sound_memory(npc, source_room_id: str, intensity: int, sound_type: str, game_time, sound_event=None) -> None:
    bb = getattr(npc, "_blackboard", None)
    if bb is None:
        from .behavior_tree import Blackboard
        bb = Blackboard()
        npc._blackboard = bb
    game_minute = game_time.minute + game_time.day * 1440 if game_time else 0
    target_room_id = getattr(sound_event, "investigator_target_room_id", "") if sound_event else source_room_id
    bb.set("last_heard_sound", {
        "room_id": target_room_id,
        "investigator_target_room_id": target_room_id,
        "intensity": intensity,
        "type": sound_type,
        "minute": game_minute,
        "actionable": sound_type in ACTIONABLE_SOUND_KINDS,
    })
    bb.set("heard_hostile_sound", npc.faction == "kempeitai" and intensity >= 2)


def _elect_sound_investigator(shared, heard_rooms_detailed):
    best = None
    for room_id, _perceived, hops in heard_rooms_detailed:
        room = shared.world.rooms.get(room_id)
        if not room:
            continue
        for npc_id in room.npcs:
            npc = shared.world.npcs.get(npc_id)
            if not (npc and _is_authority_npc(npc)):
                continue
            key = (hops, npc_id)
            if best is None or key < best[0]:
                best = (key, room_id)
    if best is None:
        return None
    (hops, npc_id), hearing_room = best
    return npc_id, hearing_room, hops


def _grant_sound_investigation(npc, source_room_id: str, game_time, kind: str) -> None:
    bb = getattr(npc, "_blackboard", None)
    if bb is None:
        from .behavior_tree import Blackboard
        bb = Blackboard()
        npc._blackboard = bb
    game_minute = game_time.minute + game_time.day * 1440 if game_time else 0
    bb.set("sound_investigation", {
        "event_id": f"{source_room_id}:{game_minute}:{kind}",
        "source_room": source_room_id,
        "phase": "travel",
        "approach_direction": "",
    })


async def play_sound(ctx: CommandContext, name: str, volume: float = 0.7) -> None:
    if getattr(ctx.session, "audio_enabled", False):
        await ctx.session.send_audio(name, volume=volume)


MESSAGE_TYPE_SOUNDS = {
    MessageType.SUCCESS: ("success", 0.5),
    MessageType.DISCOVERY: ("discovery", 0.6),
}


def _normalize_message_type_for_audio(msg_type):
    if isinstance(msg_type, MessageType):
        return msg_type
    if isinstance(msg_type, str):
        try:
            return MessageType(msg_type)
        except ValueError:
            return None
    return None


async def post_display(ctx: CommandContext, text: str, msg_type: str = None, instant_reveal: bool = False, chime: bool = True) -> None:
    await ctx.session.send_display(
        text if text.endswith("\n") else text + "\n",
        msg_type=msg_type,
        instant_reveal=instant_reveal,
    )
    sound_pair = MESSAGE_TYPE_SOUNDS.get(_normalize_message_type_for_audio(msg_type))
    if chime and sound_pair and getattr(ctx.session, "audio_enabled", False):
        await ctx.session.send_audio(sound_pair[0], volume=sound_pair[1])

_EVENT_TAG_PATTERN = re.compile(r"</?[biu]>")

def log_event(ctx: CommandContext, text: str, *, player_side: bool = True) -> None:
    from collections import deque

    text = _EVENT_TAG_PATTERN.sub("", text)

    if player_side:
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


def _record_crime(ctx: CommandContext, increase: int = 1, *, publish_rumor: bool = True) -> int:
    before = ctx.session.player.wanted_level
    level = record_crime(ctx.session.player, day=ctx.shared.game_time.day, increase=increase)
    if publish_rumor and level > before:
        from .rumors import publish_wanted_rumor
        publish_wanted_rumor(ctx.shared, ctx.session.player, level, ctx.shared.game_time.day)
    return level


def _generate_player_action_rumor(ctx: CommandContext, action_type: str, target: str = "", faction: str = "", room_id: str = "") -> None:
    if ctx.session.player.in_tutorial:
        return

    import uuid
    player_name = ctx.session.player.name
    day = ctx.shared.game_time.day
    occurrence = uuid.uuid4().hex

    room = _room(ctx)
    district = ""
    if room:
        district = room.id.split("_")[0].replace("_", " ").title()

    rumor_templates = {
        "kill": {
            "text": f"Someone killed {target}. Word spreads fast.",
            "factions": [faction] if faction else ["civilian"],
        },
        "kill_important": {
            "text": f"{target} was found dead. People talk about who might have done it.",
            "factions": [faction] if faction else ["civilian", "green_gang"],
        },
        "pickpocket_failed": {
            "text": f"A pickpocket was caught near {target}. Locals are watching their pockets.",
            "factions": ["civilian", "green_gang"],
        },
        "disguise_seen": {
            "text": f"A suspicious figure was seen in {target}. No one knows who it really was.",
            "factions": ["kempeitai", "gmd"],
        },
        "curfew_violation": {
            "text": f"Someone was spotted out after curfew near {target}. The Kempeitai are asking questions.",
            "factions": ["kempeitai", "civilian"],
        },
        "theft": {
            "text": f"Items have gone missing from {target}. A thief is rumored to be active.",
            "factions": ["civilian", "green_gang"],
        },
        "kempeitai_killed": {
            "text": f"A Kempeitai officer was killed. The occupation forces are on edge.",
            "factions": ["kempeitai", "gmd", "ccp"],
        },
        "violent_assault": {
            "text": f"There was violence involving {target}. Witnesses whisper about it.",
            "factions": [faction] if faction else ["civilian"],
        },
        "burden_gift": {
            "text": f"{target} entrusted something to a stranger. People wonder what was given.",
            "factions": [faction] if faction else ["civilian", "green_gang"],
        },
        "mission_complete": {
            "text": f"{target} scored a victory in the district. Word is spreading.",
            "factions": [faction] if faction else ["civilian"],
        },
        "high_wanted": {
            "text": f"The Kempeitai are hunting someone in {target}. Keep your head down.",
            "factions": ["kempeitai", "civilian"],
        },
    }

    template = rumor_templates.get(action_type)
    if not template:
        return

    rumor_text = template["text"]
    target_factions = template["factions"]

    from .rumors import grant_observation, publish_event_rumor
    current_faction = target_factions[0] if target_factions else "civilian"
    record_id = publish_event_rumor(
        ctx.shared,
        event_type=action_type,
        text=rumor_text,
        location=room.id if room else room_id,
        district=getattr(room, "district", "") if room else "",
        witnesses=room.npcs if room else [],
        faction_context=current_faction,
        created_day=day,
        source_npc_id="",
        occurrence=occurrence,
    )
    grant_observation(ctx.session.player, record_id, "", day, [record_id])


def record_conversation(ctx: CommandContext, npc_id: str, player_input: str, npc_response: str):
    ctx.session.player.conversation_history.append({
        "npc_id": npc_id,
        "player_input": player_input,
        "npc_response": npc_response,
        "time": ctx.shared.game_time.minute,
        "day": ctx.shared.game_time.day,
    })


def mark_npc_met(ctx: CommandContext, npc_id: str) -> None:
    if not npc_id:
        return
    from .tutorial import get_canonical_tutorial_npc_id

    stable_npc_id = get_canonical_tutorial_npc_id(
        getattr(ctx.session.player, "tutorial_instance_id", ""), npc_id
    )
    ctx.session.player.met_npc_ids.add(stable_npc_id)


def summary_trust_lines(ctx: CommandContext) -> List[str]:
    summary = summarize_faction_trust(ctx.session.player.trust)
    return [f"- {faction}: {value}" for faction, value in sorted(summary.items())]


def disguise_bonus(ctx: CommandContext) -> int:
    resolved = equipped_disguise(ctx.session.player, ctx.disguises)
    return resolved[1].bonus if resolved else 0


def _is_authority_npc(npc) -> bool:
    return npc.faction in ("kempeitai",) or '_patrol_' in npc.id or getattr(npc, 'role', '') in ('guard', 'officer')


def _confiscate_disguise(ctx: CommandContext) -> None:
    confiscate_equipped_disguise(ctx.session.player)


def _check_food_preference(npc: Npc, food) -> int:
    FACTION_CULTURE_PREFS = {
        "ccp": ["chinese"],
        "gmd": ["chinese", "western"],
        "kempeitai": ["japanese"],
        "green_gang": ["chinese"],
        "civilian": ["chinese", "universal"],
        "british": ["western"],
        "french_concession": ["western"],
    }

    food_culture = getattr(food, 'culture', '').lower() if hasattr(food, 'culture') else ''

    if not food_culture:
        return 0

    preferred = FACTION_CULTURE_PREFS.get(npc.faction, [])

    if food_culture in preferred:
        return 5

    if food_culture == "universal":
        return 2

    return -2


async def _resolve_command_curfew(ctx: CommandContext, room=None):
    resolver_ctx = ctx._replace(room=room) if room is not None and isinstance(ctx, CommandContext) else ctx
    return await resolve_curfew_encounter(resolver_ctx, CurfewTrigger.DISGUISE_EXPOSURE)


async def _check_disguise_on_entry(ctx: CommandContext, room) -> None:
    from .constants import get_season
    from .stealth import PierceStage
    from .tutorial import note_tutorial_disguise_pierce

    season = get_season(ctx.shared.game_time.day)
    resolved = equipped_disguise(ctx.session.player, ctx.disguises)
    if not resolved:
        return
    _, active_disguise = resolved
    bonus = active_disguise.bonus
    wanted = ctx.session.player.wanted_level

    for npc_id in room.npcs:
        npc = ctx.shared.world.npcs.get(npc_id)
        if not npc:
            continue
        stage = ctx.stealth.disguise_pierce_check(npc, bonus, wanted, season)
        await note_tutorial_disguise_pierce(ctx, npc, stage)
        if stage == PierceStage.EXPOSED:
            await play_sound(ctx, "alert", 0.6)
            was_kempeitai = active_disguise.apparent_faction == "kempeitai"
            if _is_authority_npc(npc):
                _record_crime(ctx)
            _confiscate_disguise(ctx)
            await post_display(ctx, loc("disguise.pierced_combat").format(npc=npc.name), msg_type="combat")
            if was_kempeitai and is_curfew(ctx.shared.game_time.minute) and not room.indoors:
                await post_display(ctx, loc("disguise.pierced_curfew_entry").format(npc=npc.name), msg_type=MessageType.WARNING)
                await _resolve_command_curfew(ctx, room)
            elif _is_authority_npc(npc):
                await _attack_npc(ctx, npc.id)
            elif is_curfew(ctx.shared.game_time.minute) and not room.indoors:
                await post_display(ctx, loc("disguise.pierced_curfew_entry").format(npc=npc.name), msg_type=MessageType.WARNING)
                await _resolve_command_curfew(ctx, room)
            else:
                await post_display(ctx, loc("disguise.pierced_entry").format(npc=npc.name), msg_type=MessageType.WARNING)
            return
        elif stage == PierceStage.CHALLENGE:
            await post_display(ctx, loc("disguise.challenge_entry").format(npc=npc.name), msg_type=MessageType.WARNING)
            npc.suspicion = min(100, npc.suspicion + 20)
            return
        elif stage == PierceStage.SUSPICION:
            await post_display(ctx, loc("disguise.suspicion_entry").format(npc=npc.name), msg_type=MessageType.WARNING)
            npc.suspicion = min(100, npc.suspicion + 10)
            return


async def _check_disguise_on_talk(ctx: CommandContext, npc: Npc) -> bool:
    from .constants import get_season
    from .stealth import PierceStage
    from .tutorial import note_tutorial_disguise_pierce

    season = get_season(ctx.shared.game_time.day)
    resolved = equipped_disguise(ctx.session.player, ctx.disguises)
    if not resolved:
        return False
    _, active_disguise = resolved
    bonus = active_disguise.bonus
    wanted = ctx.session.player.wanted_level

    stage = ctx.stealth.disguise_pierce_check(npc, bonus, wanted, season)
    await note_tutorial_disguise_pierce(ctx, npc, stage)
    if stage == PierceStage.EXPOSED:
        await play_sound(ctx, "alert", 0.6)
        was_kempeitai = active_disguise.apparent_faction == "kempeitai"
        if _is_authority_npc(npc):
            _record_crime(ctx)
        _confiscate_disguise(ctx)
        await post_display(ctx, loc("disguise.pierced_combat").format(npc=npc.name), msg_type="combat")
        room = _room(ctx)
        if was_kempeitai and is_curfew(ctx.shared.game_time.minute) and room and not room.indoors:
            await post_display(ctx, loc("disguise.pierced_curfew_talk").format(npc=npc.name), msg_type=MessageType.WARNING)
            await _resolve_command_curfew(ctx, room)
        elif _is_authority_npc(npc):
            await _attack_npc(ctx, npc.id)
        else:
            if is_curfew(ctx.shared.game_time.minute) and room and not room.indoors:
                await post_display(ctx, loc("disguise.pierced_curfew_talk").format(npc=npc.name), msg_type=MessageType.WARNING)
                await _resolve_command_curfew(ctx, room)
            else:
                await post_display(ctx, loc("disguise.pierced_talk").format(npc=npc.name), msg_type=MessageType.WARNING)
        return True
    elif stage == PierceStage.CHALLENGE:
        await post_display(ctx, loc("disguise.challenge_talk").format(npc=npc.name), msg_type=MessageType.WARNING)
        npc.suspicion = min(100, npc.suspicion + 25)
        return True
    elif stage == PierceStage.SUSPICION:
        await post_display(ctx, loc("disguise.suspicion_talk").format(npc=npc.name), msg_type=MessageType.WARNING)
        npc.suspicion = min(100, npc.suspicion + 15)
        return False
    return False


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


async def apply_action_trust(ctx: CommandContext, action: str, visible_room_npcs: Optional[List[str]] = None, dynamic_vars: Optional[Dict[str, str]] = None):
    rule = ctx.shared.trust_rules.get(action)
    if not rule:
        return
    changed, notifications = apply_trust_delta(
        ctx.session.player.trust,
        rule,
        dynamic_vars=dynamic_vars,
        last_trust_interaction=ctx.session.player.last_trust_interaction,
        current_day=ctx.shared.game_time.day,
        player_flags=ctx.session.player.flags,
    )
    if getattr(rule, "visible", False):
        if getattr(rule, "feedback", ""):
            await post_display(ctx, rule.feedback, msg_type=MessageType.PLAYER_STATUS)
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
            await post_display(ctx, msg, msg_type=MessageType.PLAYER_STATUS)

    for notif in notifications:
        if notif.startswith("perk_unlocked:"):
            _, faction, perk_name = notif.split(":", 2)
            await post_display(ctx, loc("perk_unlocked").format(faction=faction.upper(), perk_name=perk_name), msg_type=MessageType.EVENT)
        elif notif.startswith("perk_lost:"):
            _, faction, perk_name = notif.split(":", 2)
            await post_display(ctx, loc("perk_lost").format(faction=faction.upper(), perk_name=perk_name), msg_type=MessageType.WARNING)


AMBIENCE_BY_ROOM = (
    ("temple_bell", ("temple", "shrine")),
    ("villager_murmur", ("market", "market_stall")),
    ("ambient_city", ("street",)),
)


def _room_ambience(room) -> str | None:
    if room is None or getattr(room, "indoors", False):
        return None
    tags = {str(tag).lower() for tag in getattr(room, "tags", [])}
    district = str(getattr(room, "district", "") or "").lower()
    title = str(getattr(room, "title", "") or "").lower()
    for name, keywords in AMBIENCE_BY_ROOM:
        if any(keyword in tags or keyword in district or keyword in title for keyword in keywords):
            return name
    return None


async def _sync_street_ambience(ctx: CommandContext, room) -> None:
    target = _room_ambience(room)
    current = getattr(ctx.session, "_audio_ambience_name", None)
    if target == current:
        return
    if current:
        await ctx.session.send_audio(f"{current}_stop")
    if target:
        await ctx.session.send_audio(f"{target}_start", volume=0.5, loop=True)
    ctx.session._audio_ambience_name = target


async def _sync_rain_audio(ctx: CommandContext, weather: str, is_indoors: bool) -> None:
    target = None
    if weather == "rain":
        target = "rain_indoor" if is_indoors else "rain"
    active = getattr(ctx.session, "_audio_rain_variant", None)
    if target == active:
        return
    if active:
        await ctx.session.send_audio(f"{active}_stop")
    if target:
        volume = 0.35 if target == "rain_indoor" else 1.0
        await ctx.session.send_audio(f"{target}_start", volume=volume, loop=True)
    ctx.session._audio_rain_variant = target


async def broadcast_state(ctx: CommandContext):
    state = ctx.shared
    if not state:
        return
    summary = summarize_faction_trust(ctx.session.player.trust)
    disguise = ctx.disguises.get(ctx.session.player.disguise)
    room = _room(ctx)
    active_missions_data = []
    wanted_policy = wanted_consequences(ctx.session.player.wanted_level)
    mm = state.mission_manager
    if mm and ctx.session.player.active_missions:
        for active in ctx.session.player.active_missions:
            mission = mm.missions.get(active["mission_id"])
            if mission:
                objectives = active.get("objectives_progress", [])
                objective_text = []
                current_total = 0
                target_total = 0
                for objective in objectives:
                    current = int(objective.get("current", 0))
                    target = int(objective.get("count", 0))
                    current_total += current
                    target_total += target
                    objective_type = str(objective.get("type", "objective")).replace("_", " ")
                    objective_text.append(
                        f"{objective_type} {objective.get('target', '')} ({current}/{target})"
                    )
                active_missions_data.append({
                    "mission_id": mission.id,
                    "title": mission.title,
                    "faction": getattr(mission, 'faction', ''),
                    "objectives": objective_text,
                    "progress": {
                        "current": current_total,
                        "target": target_total,
                    },
                })
    await ctx.session.send_state({
        "health": ctx.session.player.health,
        "hunger": ctx.session.player.hunger,
        "morale": ctx.session.player.morale,
        "trust": summary,
        "disguise": disguise.name if disguise else "",
        "game_time": time_str(state.game_time),
        "day": state.game_time.day,
        "weather": state.weather,
        "season": _season_from_day(state.game_time.day),
        "curfew_active": is_curfew(state.game_time.minute),
        "progress_percent": compute_progress(state.game_time.day),
        "ccp_influence": state.ccp_influence,
        "gmd_influence": state.gmd_influence,
        "money_fabi": ctx.session.player.money_fabi,
        "money_silver": ctx.session.player.money_silver,
        "money_military_yen": ctx.session.player.money_military_yen,
        "wallet_fabi_value": wallet_fabi_value(ctx.session.player),
        "safe_room": room.safe_room if room else False,
        "wanted_level": ctx.session.player.wanted_level,
        "wanted_policy": {
            "level": wanted_policy.level,
            "ordinary_vendor_refuses": wanted_policy.ordinary_vendor_refuses,
            "black_market_markup": wanted_policy.black_market_markup,
            "patrol_multiplier": wanted_policy.patrol_multiplier,
            "disguise_perception_bonus": wanted_policy.disguise_perception_bonus,
            "curfew_arrest_bonus": wanted_policy.curfew_arrest_bonus,
            "arrest_chance": wanted_policy.arrest_chance,
        },
        "hidden": getattr(ctx.session.player, 'hidden', False),
        "active_missions": active_missions_data,
        "completions": build_completions(ctx),
    })


    if getattr(ctx.session, 'audio_enabled', False):
        weather = getattr(state, 'weather', 'clear')
        current_room = ctx.shared.world.rooms.get(ctx.session.player.current_room)
        is_indoors = getattr(current_room, 'indoors', False) if current_room else False

        await _sync_rain_audio(ctx, weather, is_indoors)

        if weather == "fog" and not getattr(ctx.session, '_audio_fog_active', False):
            volume = 0.3 if is_indoors else 0.3
            await ctx.session.send_audio('fog_start', volume=volume, loop=True)
            ctx.session._audio_fog_active = True
        elif weather != "fog" and getattr(ctx.session, '_audio_fog_active', False):
            await ctx.session.send_audio('fog_stop')
            ctx.session._audio_fog_active = False

        if weather == "snow" and not getattr(ctx.session, '_audio_snow_active', False):
            volume = 0.3 if is_indoors else 0.5
            await ctx.session.send_audio('snow_start', volume=volume, loop=True)
            ctx.session._audio_snow_active = True
        elif weather != "snow" and getattr(ctx.session, '_audio_snow_active', False):
            await ctx.session.send_audio('snow_stop')
            ctx.session._audio_snow_active = False

        if weather == "storm" and not getattr(ctx.session, '_audio_storm_active', False):
            volume = 0.3 if is_indoors else 0.8
            await ctx.session.send_audio('storm_start', volume=volume, loop=True)
            ctx.session._audio_storm_active = True
        elif weather != "storm" and getattr(ctx.session, '_audio_storm_active', False):
            await ctx.session.send_audio('storm_stop')
            ctx.session._audio_storm_active = False

        await _sync_street_ambience(ctx, current_room)


async def broadcast_to_room(ctx: CommandContext, text: str, exclude_username: str = "", msg_type: str = None):
    room_id = ctx.session.player.current_room
    for session in ctx.session_manager.get_players_in_room(room_id):
        if session.username != exclude_username:
            await session.send_display(text, msg_type=msg_type)


def _check_money(player: PlayerData, fabi_cost: int) -> bool:
    return can_afford_fabi(player, fabi_cost)


def _spend_money(player: PlayerData, fabi_amount: int):
    spend_fabi_value(player, fabi_amount)


def _earn_money(player: PlayerData, fabi_amount: int):
    earn_fabi_value(player, fabi_amount)


async def _handle_mission_objectives(ctx: CommandContext, event_type: str, target_id: str, item_id: str = None):
    mm = ctx.shared.mission_manager
    if not mm:
        return
    completed = mm.update_objectives(ctx.session.player, event_type, target_id, item_id=item_id)
    for mid in completed:
        mission = mm.complete(ctx.session.player, mid)
        if mission:
            await _award_mission_rewards(ctx, mission)


async def _degrade_and_notify_weapon(ctx: CommandContext, weapon, attack_succeeded: bool):
    if weapon:
        broken, msg = degrade_weapon(weapon, attack_succeeded)
        if msg:
            await post_display(ctx, msg, msg_type="combat")
        if broken:
            await post_display(ctx, loc("combat.weapon_broken").format(name=semantic_span(weapon.name, "item")), msg_type="combat")
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
    result = any(i.key_id == container.key_id for i in player.inventory)
    logger.debug("_has_key_for_container: container=%s key_id=%s result=%s", container.id, container.key_id, result)
    return result


def _consume_key(player: PlayerData, key_id: str) -> Optional[Item]:
    for i, item in enumerate(player.inventory):
        if item.key_id == key_id:
            return player.inventory.pop(i)
    return None


def _find_player_in_room(ctx: CommandContext, name: str) -> Optional[Session]:
    target_username = (name or "").strip().casefold()
    for s in ctx.session_manager.get_players_in_room(ctx.session.player.current_room):
        if s.username.casefold() == target_username:
            return s
    return None


_CACHED_VERBS: Optional[List[str]] = None


def _dedup(seq):
    seen = set()
    return [x for x in seq if not (x in seen or seen.add(x))]


def _tutorial_ask_topics(player, npc_id: str) -> Optional[List[str]]:
    from .tutorial import (
        STAGE_ACTIONS,
        get_canonical_tutorial_npc_id,
        normalize_to_actionable_stage,
        tutorial_blocks_world_events,
    )

    if not tutorial_blocks_world_events(player):
        return None
    action = STAGE_ACTIONS.get(normalize_to_actionable_stage(player), {})
    if action.get("verb") != "ask":
        return None
    expected_npc_id = action.get("from_npc", "")
    canonical_npc_id = get_canonical_tutorial_npc_id(
        getattr(player, "tutorial_instance_id", ""), npc_id
    )
    if canonical_npc_id != expected_npc_id:
        return None
    topics = action.get("topics")
    if isinstance(topics, list):
        return list(topics)
    required_indirect = action.get("required_indirect")
    return [required_indirect] if required_indirect else []


def _eligible_ask_topics(ctx: CommandContext, npc_id: str, npc, room) -> List[str]:
    tutorial_topics = _tutorial_ask_topics(ctx.session.player, npc_id)
    if tutorial_topics is not None:
        return tutorial_topics
    topics = list(npc_ask_topics(npc))
    consequence_lead = find_consequence_ask_lead(ctx.shared, npc_id, room.id, "") if room else None
    if consequence_lead and consequence_lead["ask_topic"] not in topics:
        topics.append(consequence_lead["ask_topic"])
    return topics


def _ask_topic_prompt(npc, topics: List[str]) -> str:
    labels = _dedup(display_topic_label(npc, topic) for topic in topics)
    if labels:
        return f'{_short_name(npc.name)} can tell you about: {", ".join(labels)}.'
    return f'{_short_name(npc.name)} has nothing to share.'


def _matches_ask_topic(raw: str, npc, topics: List[str]) -> bool:
    normalized_raw = _normalize_text(raw)
    return any(
        normalized_raw in {_normalize_text(topic), _normalize_text(display_topic_label(npc, topic))}
        for topic in topics
    )


from .command_schema import COMMAND_DEFS as _COMMAND_DEFS

COMMAND_SCHEMA: Dict[str, List[Dict[str, str]]] = {
    verb: list(definition["slots"]) for verb, definition in _COMMAND_DEFS.items() if definition["slots"]
}

_MATCH_POLICY: Dict[str, str] = {
    "verbs": "prefix",
    "exits": "prefix",
    "topics": "prefix",
    "players": "prefix",
    "disguises": "prefix",
    "stop_targets": "prefix",
    "npcs": "prefix_then_substring",
    "items": "prefix_then_substring",
    "take_items": "prefix_then_substring",
    "inventory_items": "prefix_then_substring",
    "containers": "prefix_then_substring",
}


def build_completions(ctx: CommandContext) -> Dict[str, Any]:
    global _CACHED_VERBS
    if _CACHED_VERBS is None:
        _CACHED_VERBS = [v for v in build_command_registry().keys() if v not in ("unknown", "stub")]
    npcs: List[str] = []
    items: List[str] = []
    take_items: List[str] = []
    inventory_items: List[str] = []
    containers: List[str] = []
    exits: List[str] = []
    topics: List[str] = []
    ask_topics: Dict[str, List[str]] = {}
    disguises: List[str] = []
    for item in ctx.session.player.inventory:
        if not item.disguise_id:
            continue
        disguise = ctx.disguises.get(item.disguise_id)
        if disguise:
            disguises.append(disguise.id.replace("_", " "))
    room = _room(ctx)
    if room:
        exits = list(room.exits.keys())
        for npc_id in room.npcs:
            npc = ctx.shared.world.npcs.get(npc_id)
            if npc and npc.name:
                npcs.append(npc.name.lower())
                tutorial_topics = _tutorial_ask_topics(ctx.session.player, npc.id)
                if tutorial_topics is not None:
                    npc_topics = [display_topic_label(npc, topic) for topic in tutorial_topics]
                else:
                    npc_topics = [display_topic_label(npc, topic) for topic in npc_ask_topics(npc)]
                    consequence_lead = find_consequence_ask_lead(ctx.shared, npc.id, room.id, "")
                    if consequence_lead:
                        label = display_topic_label(npc, consequence_lead["ask_topic"])
                        if label not in npc_topics:
                            npc_topics.append(label)
                ask_topics[npc.name.lower()] = _dedup(npc_topics)
                for topic in npc_topics:
                    if topic not in topics:
                        topics.append(topic)
        for item in room.items:
            if item.name:
                items.append(item.name.lower())
                if item.takeable:
                    take_items.append(item.name.lower())
                if item.is_container:
                    containers.append(item.name.lower())
    for item in ctx.session.player.inventory:
        if item.name:
            items.append(item.name.lower())
            inventory_items.append(item.name.lower())
            if item.is_container:
                containers.append(item.name.lower())
    players = []
    if ctx.session_manager:
        for s in ctx.session_manager.get_players_in_room(ctx.session.player.current_room):
            if s.player and s.username != ctx.session.username:
                players.append(s.username.lower())
    return {
        "verbs": list(_CACHED_VERBS),
        "npcs": _dedup(npcs),
        "items": _dedup(items),
        "take_items": _dedup(take_items),
        "inventory_items": _dedup(inventory_items),
        "containers": _dedup(containers),
        "exits": _dedup(exits),
        "topics": _dedup(topics),
        "ask_topics": ask_topics,
        "players": _dedup(players),
        "disguises": _dedup(disguises),
        "stop_targets": ["tail"],
        "grammar": {verb: slots for verb, slots in COMMAND_SCHEMA.items() if verb in _CACHED_VERBS},
        "match_policy": dict(_MATCH_POLICY),
    }


def _get_npc_dialogue(ctx: CommandContext, npc: Npc, context_type: str = "talk") -> str:
    return get_contextual_dialogue(npc, ctx.session.player.trust, context_type,
                                   player_relationships=ctx.session.player.relationships,
                                   wanted_level=ctx.session.player.wanted_level,
                                   player_morale=ctx.session.player.morale,
                                   player_flags=ctx.session.player.flags)


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
    from .content_validation import ContentValidationError

    try:
        document = _load_yaml(CHARACTER_NAMES_PATH)
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ContentValidationError):
        return "Chen Wei"

    names = document.get("names") if isinstance(document, dict) else None
    if not isinstance(names, dict):
        return "Chen Wei"

    gender = random.choice(["male", "female", "neutral"])
    name_list = names.get(gender)
    if not isinstance(name_list, list):
        return "Chen Wei"
    usable_names = [name for name in name_list if isinstance(name, str) and name.strip()]
    if not usable_names:
        return "Chen Wei"
    return random.choice(usable_names)


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
    player = ctx.session.player
    room_id = player.current_room
    room = _room(ctx)
    obituary = _generate_obituary(player, death_message, ctx.shared.game_time.day)
    retrospective = format_life_retrospective(ctx.shared.event_log, player.name)
    from .serialization import serialize_item
    from .lifecycle import (
        archive_player_death,
        attempt_authorized_session_save,
        authorized_session_save_key,
        build_death_event,
        close_session_cleanly,
        replay_death_projection,
    )
    event = None
    if authorized_session_save_key(ctx.session):
        event = build_death_event(
            ctx.session,
            day=ctx.shared.game_time.day,
            cause=death_message,
            last_words=last_words,
            room_id=room_id,
            inherited=[serialize_item(item) for item in player.inventory],
            predecessor={
                "name": player.name,
                "day": ctx.shared.game_time.day,
                "obituary": obituary,
                "last_words": last_words,
                "retrospective": retrospective,
            },
        )
    death_flag_added = "player_died" not in player.flags
    if death_flag_added:
        player.flags.append("player_died")
    death_projection_succeeded = attempt_authorized_session_save(ctx.session, death_projection=True)
    if event is not None and not death_projection_succeeded:
        if death_flag_added:
            player.flags.remove("player_died")
        return
    if event is not None:
        archive_player_death(ctx.session, event)
        if room_id:
            replay_death_projection(ctx.shared, event)
    create_rumour_seed(
        event_type="player_death",
        location=room_id or "",
        district=getattr(room, 'district', '') if room else "",
        witnesses=list(room.npcs) if room else [],
        faction_context="civilian",
        description=f"{player.name} has died: {death_message}",
        shared=ctx.shared,
        occurrence=ctx.session.username,
    )
    end_screen = f"""THE END

{death_message}
"""
    if last_words:
        end_screen += f'\nLast words: "{last_words}"\n'
    end_screen += "\nThe city endures.\n"
    await post_display(ctx, end_screen, msg_type="system")
    await close_session_cleanly(ctx.session_manager, ctx.session, send_goodbye=False)


async def trigger_ending(ctx: CommandContext, ending_type: str = ""):
    session_manager = getattr(ctx, "session_manager", None)
    if session_manager is None:
        session_manager = type("EndingSessionManager", (), {})()
        session_manager.sessions = {ctx.session.username: ctx.session}
        session_manager._shared_liberation_in_progress = False
    return await resolve_shared_liberation(ctx.shared, session_manager)


def check_death_conditions(ctx: CommandContext) -> tuple[bool, str]:
    player = ctx.session.player
    if player.health <= 0:
        return True, loc("death.health")
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


def _apply_effect_trust(player: PlayerData, effects: Dict[str, object], current_day: Optional[int] = None) -> None:
    for trust_key, delta in effects.get("change_trust", {}).items():
        change_trust(
            player.trust,
            trust_key,
            int(delta),
            last_trust_interaction=player.last_trust_interaction,
            current_day=current_day,
            player_flags=player.flags,
        )


def _apply_effect_items(player: PlayerData, world: World, effects: Dict[str, object]) -> None:
    for item_id in _effects_as_list(effects.get("add_item")):
        if item_id:
            grant_catalog_item(world, player.inventory, str(item_id))
    for item_id in _effects_as_list(effects.get("give_item")):
        if item_id:
            grant_catalog_item(
                world,
                player.inventory,
                str(item_id),
                contraband=bool(effects.get("is_black_market")),
            )
    for item_id in _effects_as_list(effects.get("remove_item")):
        if item_id:
            item = find_item_by_name(str(item_id), player.inventory)
            if item:
                player.inventory.remove(item)
                invalidate_disguise_if_support_lost(player, item)


def _apply_effect_money(player: PlayerData, effects: Dict[str, object]) -> bool:
    spend_fabi = int(effects.get("spend_fabi", 0) or 0)
    spend_silver = int(effects.get("spend_silver", 0) or 0)
    fabi_cost = spend_fabi + 10 * spend_silver
    if not can_afford_fabi(player, fabi_cost):
        return False
    spend_military_yen = effects.get("spend_military_yen")
    if spend_military_yen is not None:
        cost = int(spend_military_yen)
        if player.money_military_yen < cost:
            return False
    if fabi_cost:
        spend_fabi_value(player, fabi_cost)
    if spend_military_yen is not None:
        player.money_military_yen -= int(spend_military_yen)
    gain_fabi = int(effects.get("gain_fabi", 0) or 0)
    gain_silver = int(effects.get("gain_silver", 0) or 0)
    if gain_fabi or gain_silver:
        earn_fabi_value(player, gain_fabi + 10 * gain_silver)
    gain_military_yen = effects.get("gain_military_yen")
    if gain_military_yen is not None:
        player.money_military_yen += int(gain_military_yen)
    return True


def _apply_effect_events(ctx: CommandContext, effects: Dict[str, object], *, player_side: bool = True) -> None:
    for flag_event in _effects_as_list(effects.get("log_event")):
        if flag_event:
            log_event(ctx, str(flag_event), player_side=player_side)


def _apply_effect_npcs(world: World, effects: Dict[str, object]) -> None:
    for key in ("move_npc", "spawn_npc"):
        for npc_id, room_id in effects.get(key, {}).items():
            if npc_id in world.npcs and room_id in world.rooms:
                world.place_npc(npc_id, room_id)


async def _apply_effect_specials(ctx: CommandContext, effects: Dict[str, object], *, player_side: bool = True) -> bool:
    if "kill_player" in effects:
        death_reason = effects.get("death_reason", "You have met your end in Shanghai.")
        asyncio.create_task(handle_player_death(ctx, death_reason))
        return True

    if "arrest_player" in effects:
        if player_side:
            ctx.session.player.arrested = True
        log_event(ctx, "You have been arrested.", player_side=player_side)
        if player_side:
            await post_display(ctx, loc("death.arrest_message"), msg_type="system")

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


async def apply_storylet_effects(ctx: CommandContext, effects: Dict[str, object], *, player_side: bool = True, active=None):
    if active is not None and not storylet_resolution_owned(active):
        return False
    player = ctx.session.player
    shared = ctx.shared
    world = shared.world
    effects = _normalize_effects(effects)
    for key in ("add_item", "give_item"):
        for item_id in _effects_as_list(effects.get(key)):
            if item_id:
                validate_catalog_item(world, str(item_id))

    mission_action = effects.get("mission_offer_action")
    if mission_action:
        mission_id = str(effects.get("mission_id", ""))
        manager = getattr(shared, "mission_manager", None)
        if not manager:
            await post_display(ctx, "Mission offers are unavailable right now.", msg_type="system")
            return False
        resolved, message = manager.resolve_offer(
            player,
            mission_id,
            mission_action,
            shared.game_time.day,
            world=shared,
            current_hour=shared.game_time.hour,
        )
        if not resolved:
            await post_display(ctx, message, msg_type="system")
            return False
        if mission_action == "accept":
            mission = manager.missions[mission_id]
            log_event(ctx, f"Accepted mission: {mission.title}")
        if active is not None:
            active.resolution_committed = True
        await post_display(ctx, message, msg_type="system")
        return True

    if "purchase_newspaper" in effects:
        purchased = await _purchase_newspaper(ctx, str(effects["purchase_newspaper"]), active=active)
        if active is not None and purchased:
            active.resolution_committed = True
        return purchased

    if effects.get("is_black_market"):
        _normalize_back_room_ledger(player, ctx.shared.server_cycle)
        give_item = str(effects.get("give_item", ""))
        if (
            give_item
            and player.black_market_purchase_cycle == ctx.shared.server_cycle
            and give_item in player.black_market_purchases
        ):
            await post_display(ctx, loc("cmd_buy_from.already_purchased"), msg_type="system")
            return False

    if not _apply_effect_money(player, effects):
        cost = effects.get("spend_fabi", 0) or effects.get("spend_military_yen", 0)
        currency = "fabi" if effects.get("spend_fabi") else "military yen"
        await post_display(ctx, loc("cmd_buy.no_money").format(cost=cost, currency=currency), msg_type=MessageType.PLAYER_ACTION)
        return False

    if effects.get("cost_fabi"):
        cost = int(effects.get("cost_fabi", 0))
        if not spend_fabi_value(player, cost):
            await post_display(ctx, loc("wanted.green_gang_deal_no_money").format(name="the dealer"), msg_type=MessageType.PLAYER_ACTION)
            return False
    if active is not None:
        active.resolution_committed = True
    if effects.get("reduce_wanted"):
        reduce_amount = int(effects.get("reduce_wanted", 0))
        adjust_wanted(player, -reduce_amount)

    _apply_effect_flags(player, effects)
    _apply_effect_trust(player, effects, current_day=ctx.shared.game_time.day)
    _apply_effect_items(player, world, effects)
    purchase = effects.get("purchase")
    if isinstance(purchase, dict):
        await post_display(
            ctx,
            "You bought {item} from {vendor} for {price} {currency}.".format(
                item=semantic_span(purchase.get("item", "the item"), "item"),
                vendor=semantic_span(purchase.get("vendor", "the vendor"), "npc"),
                price=purchase.get("price", 0),
                currency=purchase.get("currency", "fabi"),
            ),
            msg_type=MessageType.SUCCESS,
            chime=False,
        )
        await play_sound(ctx, "coin_clink", 0.7)
        if resolution_aborted(active):
            return False
        if effects.get("is_black_market"):
            give_item = str(effects.get("give_item", ""))
            if give_item:
                _normalize_back_room_ledger(player, ctx.shared.server_cycle)
                player.black_market_purchases[give_item] = 1
                player.black_market_purchase_cycle = ctx.shared.server_cycle
    _apply_effect_events(ctx, effects, player_side=player_side)
    _apply_effect_npcs(world, effects)
    _apply_effect_stats(player, effects)

    if await _apply_effect_specials(ctx, effects, player_side=player_side):
        return True
    if resolution_aborted(active):
        return False

    await _refresh_inventory_if_open(ctx)
    if resolution_aborted(active):
        return False
    _apply_effect_influence(shared, effects)
    return True


async def maybe_trigger_storylet(ctx: CommandContext):
    from .tutorial import tutorial_blocks_world_events
    if tutorial_blocks_world_events(ctx.session.player):
        return
    active = ctx.storylet_manager.maybe_trigger_for_player(ctx.session.player, ctx.shared)
    if not active:
        return
    import logging
    logging.getLogger(__name__).info("Storylet triggered for %s: %s (room=%s)", ctx.session.username, active.storylet_id, ctx.session.player.current_room)
    await _display_storylet(ctx, active)


def claim_storylet_resolution(active: ActiveStorylet) -> bool:
    if active.resolved or getattr(active, "resolution_started", False):
        return False
    active.resolution_started = True
    return True


def storylet_resolution_owned(active: ActiveStorylet) -> bool:
    return getattr(active, "resolution_started", False) and not getattr(active, "resolved", False)


def resolution_aborted(active) -> bool:
    return active is not None and not getattr(active, "resolution_started", False)


def is_storylet_choice_input(active: ActiveStorylet, text: str) -> bool:
    raw = text.strip()
    if raw.isdigit():
        return 1 <= int(raw) <= len(active.options)
    normalized = raw.casefold()
    return any(
        not getattr(option, "disabled", False)
        and normalized == option.text.strip().casefold()
        for option in active.options
    )


async def _display_storylet(ctx: CommandContext, active: ActiveStorylet):
    from .tutorial import tutorial_blocks_world_events
    if tutorial_blocks_world_events(ctx.session.player):
        active.timer_duration = 0
        active.expires_at = 0.0
        active.blocking = True
    if not active.room_id:
        active.room_id = ctx.session.player.current_room
    if not active.owner_username:
        active.owner_username = ctx.session.username
    if active.timer_duration > 0 and not active.expires_at:
        active.expires_at = active.timer_started_at + active.timer_duration

    lines = [active.narrative]
    for idx, option in enumerate(active.options, start=1):
        if getattr(option, "disabled", False):
            lines.append(f"    {option.text}")
        else:
            formatted = format_bold_italic(option.text)
            lines.append(f"{idx}. {formatted}")

    storylet = ctx.storylet_manager.storylets.get(active.storylet_id)
    if storylet and not storylet.blocking:
        remaining = max(0, active.timer_duration - int(time.time() - active.timer_started_at))
        lines.append(f"\n  [Time remaining: {remaining}s]")

    storylet_options = []
    for opt in active.options:
        storylet_options.append({
            "text": opt.text,
            "effects": getattr(opt, 'effects', {}),
            "followup_storylet": getattr(opt, 'followup_storylet', ''),
            "disabled": getattr(opt, 'disabled', False),
            "disabled_reason": getattr(opt, 'disabled_reason', ''),
        })

    remaining = active.expires_at - time.time() if active.expires_at else active.timer_duration
    timer_warning = bool(active.timer_duration > 0 and remaining <= 30)

    await ctx.session.send_storylet(
        storylet_id=active.storylet_id,
        narrative=active.narrative,
        options=storylet_options,
        timer_duration=active.timer_duration,
        timer_warning=timer_warning,
        expires_at=active.expires_at,
        turns=active.turns,
    )

    await play_sound(ctx, "storylet", 0.5)

    if active.scope == "room":
        for session in ctx.session_manager.get_players_in_room(active.room_id):
            if session.username == active.owner_username:
                continue
            await session.send_storylet(
                storylet_id=active.storylet_id,
                narrative=active.narrative,
                options=storylet_options,
                timer_duration=active.timer_duration,
                timer_warning=timer_warning,
                expires_at=active.expires_at,
                read_only=True,
                turns=active.turns,
            )



async def _handle_tutorial_choice(ctx: CommandContext, option):
    player = ctx.session.player
    effects = getattr(option, "effects", {}) or {}
    flag = effects.get("flag", "")
    
    if flag == "start_tutorial":
        from .tutorial import restart_tutorial
        previous_room = ctx.shared.world.get_room(player.current_room)
        if previous_room and player.username in previous_room.players:
            previous_room.players.remove(player.username)
        restart_tutorial(player, ctx.shared)
        tutorial_room = ctx.shared.world.get_room(player.current_room)
        if tutorial_room and player.username not in tutorial_room.players:
            tutorial_room.players.append(player.username)
        
        if hasattr(ctx, 'session_manager') and ctx.session_manager and hasattr(ctx.session_manager, '_send_map_data'):
            await ctx.session_manager._send_map_data(ctx.session)

        await cmd_look(ctx, Command(verb="look", raw="look", instant_reveal=True))
        from .tutorial import _emit_stage_entry
        await _emit_stage_entry(ctx)
    else:
        from .tutorial import _send_graduation_cue, graduate_tutorial_player
        message = "Skipping tutorial. Welcome to Shanghai."
        await graduate_tutorial_player(ctx, message, send_handoff=False)
        await cmd_look(ctx, Command(verb="look", raw="look"))
        
        if hasattr(ctx, 'session_manager') and ctx.session_manager and hasattr(ctx.session_manager, '_send_map_data'):
            await ctx.session_manager._send_map_data(ctx.session)
        await _send_graduation_cue(ctx, message)


async def _resolve_neglect(ctx: CommandContext, active: ActiveStorylet):
    from .storylet_cancellation import apply_neglect
    await apply_neglect(ctx, active, announce=True)


async def resolve_storylet_choice(ctx: CommandContext, text: str):
    import logging
    if not ctx.session.player.active_storylets:
        return failure("storylet_unavailable")
    active = ctx.session.player.active_storylets[0]
    from .storylets import is_storylet_expired
    if is_storylet_expired(active):
        await _resolve_neglect(ctx, active)
        return failure("storylet_expired")
    logging.getLogger(__name__).info("Storylet choice for %s: %s option=%s", ctx.session.username, active.storylet_id, text.strip())
    raw = text.strip()
    choice = int(raw) if raw.isdigit() and 1 <= int(raw) <= len(active.options) else None
    if choice is None:
        normalized = raw.casefold()
        for idx, opt in enumerate(active.options, start=1):
            if not getattr(opt, "disabled", False) and normalized == opt.text.strip().casefold():
                choice = idx
                break
    if choice is None:
        lines = [active.narrative]
        for idx, opt in enumerate(active.options, start=1):
            if getattr(opt, "disabled", False):
                lines.append(f"    {opt.text}")
            else:
                lines.append(f"{idx}. {opt.text}")
        await post_display(ctx, "\n".join(lines), msg_type=MessageType.PLAYER_ACTION)
        await ctx.session.send_prompt(loc("storylet.choose").format(max=len(active.options)))
        return failure("storylet_invalid_choice")
    option = active.options[choice - 1]
    if getattr(option, "disabled", False):
        lines = [active.narrative]
        for idx, opt in enumerate(active.options, start=1):
            if getattr(opt, "disabled", False):
                lines.append(f"    {opt.text}")
            else:
                lines.append(f"{idx}. {opt.text}")
        await post_display(ctx, "\n".join(lines), msg_type=MessageType.PLAYER_ACTION)
        await ctx.session.send_prompt(loc("storylet.choose").format(max=len(active.options)))
        return failure("storylet_disabled_choice")

    if not claim_storylet_resolution(active):
        return failure("storylet_already_resolving")
    try:

        if active.storylet_id == "tutorial_choice":
            await _handle_tutorial_choice(ctx, option)
            ctx.session.player.active_storylets.remove(active)
            await ctx.session.send_storylet_resolved(active.storylet_id)
            return success("storylet_choice", facts={"storylet_choice"})

        try:
            applied = await apply_storylet_effects(ctx, option.effects, active=active)
        except Exception:
            raise
        if applied is not False:
            active.resolution_committed = True
        if getattr(ctx.session, "clean_close_completed", False):
            return failure("storylet_unavailable")
        if applied is False:
            active.resolution_started = False
            return failure("storylet_effect_failed")

        if active.storylet_id.startswith("shop_"):
            effects = getattr(option, "effects", {}) or {}
            _deplete_tutorial_vendor_stock(
                ctx,
                str(effects.get("vendor_id", "")),
                str(effects.get("give_item", "")),
            )

        if option.response_msg:
            await post_display(ctx, option.response_msg, msg_type="npc_dialogue")

        tutorial_event = None
        if (getattr(ctx.session.player, "in_tutorial", False)
                and active.storylet_id.startswith("shop_")):
            from .tutorial import get_canonical_tutorial_npc_id
            effects = getattr(option, "effects", {}) or {}
            purchased_item_id = effects.get("give_item", "")
            vendor_cloned_id = effects.get("vendor_id", "")
            instance_id = getattr(ctx.session.player, "tutorial_instance_id", "")
            canonical_vendor = get_canonical_tutorial_npc_id(instance_id, vendor_cloned_id)
            tutorial_event = {
                "verb": "buy",
                "target": purchased_item_id,
                "indirect": canonical_vendor,
            }
        flags = ctx.session.player.flags
        if "tutorial_complete" in flags and "tutorial_handoff_shown" not in flags:
            flags.append("tutorial_handoff_shown")
            handoff = loc("tutorial.handoff")
            room = ctx.shared.world.get_room(ctx.session.player.current_room)
            if room and getattr(room, "safe_room", False):
                handoff += "\n" + loc("tutorial.handoff.claim")
            await post_display(ctx, handoff, msg_type="tutorial")
        if active.storylet_id not in ctx.session.player.storylet_history:
            ctx.session.player.storylet_history.append(active.storylet_id)
        followup = option.followup_storylet

        active.resolved = True
        if active in ctx.session.player.active_storylets:
            ctx.session.player.active_storylets.remove(active)
        await ctx.session.send_storylet_resolved(active.storylet_id)

        if active.storylet_id.startswith("shop_"):
            from .popup_payloads import close_popup_if_kind
            await close_popup_if_kind(ctx, "store", "resolved")

        await _complete_room_storylet(ctx, active, option.response_msg or option.text)

        if followup and followup in ctx.storylet_manager.storylets:
            storylet = ctx.storylet_manager.storylets[followup]
            timer_started_at = time.time()
            followup_active = ActiveStorylet(
                storylet_id=storylet.id,
                narrative=storylet.narrative,
                options=storylet.options,
                room_id=ctx.session.player.current_room,
                timer_duration=storylet.timer_seconds,
                timer_started_at=timer_started_at,
                speaker_npc=storylet.speaker_npc,
                listener_npc=storylet.listener_npc,
                turns=storylet.turns,
                blocking=storylet.blocking,
                scope=storylet.scope,
                owner_username=ctx.session.username,
                expires_at=timer_started_at + storylet.timer_seconds,
            )
            from .storylets import mark_untimed_for_tutorial
            mark_untimed_for_tutorial(followup_active, ctx.session.player)
            ctx.session.player.active_storylets.append(followup_active)
            await _display_storylet(ctx, followup_active)
        elif ctx.session.player.active_storylets:
            next_active = ctx.session.player.active_storylets[0]
            await _display_storylet(ctx, next_active)
        else:
            await cmd_look(ctx, Command(verb="look", raw="look"))
        return success("storylet_choice", facts={"storylet_choice"}, tutorial_event=tutorial_event)
    except Exception:
        active.resolution_started = False
        raise


async def finalize_committed_resolution(ctx: CommandContext, active: ActiveStorylet) -> None:
    player = ctx.session.player
    if active.storylet_id not in player.storylet_history:
        player.storylet_history.append(active.storylet_id)
    active.resolved = True
    if active in player.active_storylets:
        player.active_storylets.remove(active)
    await _complete_room_storylet(ctx, active, "")


async def _complete_room_storylet(ctx: CommandContext, active: ActiveStorylet, outcome: str) -> None:
    if active.scope != "room":
        return
    if ctx.shared.active_room_storylets.pop(active.room_id, None) is None:
        return
    recipients = []
    for session in ctx.session_manager.get_players_in_room(active.room_id):
        if active.storylet_id not in session.player.storylet_history:
            session.player.storylet_history.append(active.storylet_id)
        if session.username == active.owner_username:
            continue
        recipients.append(session)
    if not recipients:
        return

    async def notify(session):
        await session.clear_storylet(active.storylet_id)
        await session.send_display(
            f"{active.owner_username} resolves the situation: {outcome}",
            msg_type="event",
        )

    try:
        await asyncio.wait_for(
            asyncio.gather(*(notify(session) for session in recipients), return_exceptions=True),
            timeout=ROOM_NOTIFY_TIMEOUT,
        )
    except Exception:
        pass

async def _send_room_details(ctx: CommandContext, room) -> None:
    from .stealth_requirements import hide_requirement_for_room
    room_npcs = []
    for npc_id in room.npcs:
        npc = ctx.shared.world.npcs.get(npc_id)
        if npc:
            room_npcs.append({
                "id": npc_id,
                "name": npc.name,
                "faction": getattr(npc, 'faction', ''),
                "standing": getattr(npc, 'standing', ''),
                "description": getattr(npc, 'description', '')
            })

    room_items = []
    for item in room.items:
        room_items.append({
            "id": item.id,
            "name": item.name,
            "description": getattr(item, 'description', ''),
            "takeable": getattr(item, 'takeable', True)
        })

    from .popup_payloads import room_key_for_client
    room_id_for_client = room_key_for_client(ctx)

    await ctx.session.send_room_details({
        "room_id": room_id_for_client,
        "title": room.title,
        "tags": room.tags or [],
        "npcs": room_npcs,
        "items": room_items,
        "exits": room.exits or {},
        "district": room.district if hasattr(room, 'district') else '',
            "indoors": room.indoors if hasattr(room, 'indoors') else False,
            "hiding_spots": len(room.hiding_spots) if hasattr(room, 'hiding_spots') and isinstance(room.hiding_spots, list) else (1 if hasattr(room, 'hiding_spots') and room.hiding_spots else 0),
            "hide_requirement": hide_requirement_for_room(room),
            "safe": room.safe_room if hasattr(room, 'safe_room') else False,
    })


async def cmd_look(ctx: CommandContext, cmd: Command):
    from .trust import get_faction_perks, TRUST_TIER_NEUTRAL, get_role_trust
    room = _room(ctx)
    if not room:
        await post_display(ctx, loc("cmd_look.nowhere"), msg_type=MessageType.ERROR)
        return

    look_count = ctx.session.player.rooms_looked.get(room.id, 0)
    is_second_look = look_count >= 1
    ctx.session.player.rooms_looked[room.id] = look_count + 1

    tutorial_blocked = {}
    if getattr(ctx.session.player, "in_tutorial", False):
        from .tutorial import blocked_exits_for_room, normalize_to_actionable_stage
        stage = normalize_to_actionable_stage(ctx.session.player)
        original_room_id = room.id
        if getattr(ctx.session.player, "tutorial_instance_id", ""):
            from .tutorial import get_original_tutorial_room_id
            original_room_id = get_original_tutorial_room_id(
                ctx.session.player.tutorial_instance_id, room.id, ctx.shared)
        tutorial_blocked = blocked_exits_for_room(original_room_id, stage)

    arrival_text = getattr(ctx.session.player, "_pending_arrival_text", "")
    if arrival_text:
        try:
            del ctx.session.player._pending_arrival_text
        except AttributeError:
            arrival_text = ""

    room_text = ctx.shared.world.format_room(
        room.id,
        getattr(ctx.shared, "room_state_overrides", None),
        getattr(ctx.shared, "death_journals", None),
        game_hour=ctx.shared.game_time.hour,
        weather=getattr(ctx.shared, "weather", "clear"),
        game_day=ctx.shared.game_time.day,
        detailed=is_second_look,
        district_control=getattr(ctx.shared, "district_control", {}),
        season=_season_from_day(ctx.shared.game_time.day),
        blocked_exits=tutorial_blocked or None,
        arrival_text=arrival_text,
        reveal_faction=not getattr(ctx.session.player, "in_tutorial", False),
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

    manifestations = room_consequence_manifestations(ctx.shared, room.id)
    if manifestations:
        room_text += "\n\n" + " ".join(manifestations)

    if not getattr(ctx.session.player, "in_tutorial", False):
        pending = _pending_room_event(ctx, room)
        if pending:
            room_text += "\n\n" + pending
    await post_display(ctx, room_text, msg_type=MessageType.ROOM_DESCRIPTION, instant_reveal=getattr(cmd, "instant_reveal", False))

    await _send_room_details(ctx, room)
    await _emit_terminal_guidance(ctx, room)

    room_storylet = ctx.shared.active_room_storylets.get(room.id)
    if room_storylet and not room_storylet.get("resolved", False):
        if room_storylet.get("owner_username") != ctx.session.username:
            options = [
                {
                    "text": option.text,
                    "effects": getattr(option, "effects", {}),
                    "followup_storylet": getattr(option, "followup_storylet", ""),
                    "disabled": getattr(option, "disabled", False),
                    "disabled_reason": getattr(option, "disabled_reason", ""),
                }
                for option in room_storylet.get("options", [])
            ]
            expires_at = room_storylet.get("expires_at", 0.0)
            await ctx.session.send_storylet(
                storylet_id=room_storylet["storylet_id"],
                narrative=room_storylet.get("narrative", "Something is happening here."),
                options=options,
                timer_duration=max(0, int(expires_at - time.time())) if expires_at else 0,
                expires_at=expires_at,
                read_only=True,
                turns=room_storylet.get("turns", []),
            )

    if hidden_players_detected:
        for name in hidden_players_detected:
            await post_display(ctx, loc("perception.hidden_player").format(name=name), msg_type=MessageType.DISCOVERY)
    elif someone_watching:
        await post_display(ctx, loc("perception.someone_watching"), msg_type=MessageType.DISCOVERY)

    perks = get_faction_perks(ctx.session.player.trust)
    for faction, perk_data in perks.items():
        if "reveal_rooms" in perk_data:
            for hidden_room_id in perk_data["reveal_rooms"]:
                if hidden_room_id not in ctx.session.player.map_revealed:
                    ctx.session.player.map_revealed.append(hidden_room_id)

    if room.hidden_exits:
        ccp_trust = get_role_trust(ctx.session.player.trust, "ccp", None)
        gmd_trust = get_role_trust(ctx.session.player.trust, "gmd", None)
        for direction, dest_id in room.hidden_exits.items():
            dest_room = ctx.shared.world.rooms.get(dest_id)
            if dest_room and "ccp_safehouse" in dest_room.tags and ccp_trust >= TRUST_TIER_NEUTRAL:
                if direction not in room.exits:
                    room.exits[direction] = dest_id
            elif dest_room and "gmd_safehouse" in dest_room.tags and gmd_trust >= TRUST_TIER_NEUTRAL:
                if direction not in room.exits:
                    room.exits[direction] = dest_id

    if room.tags and any("police" in t.lower() or "kempeitai" in t.lower() for t in room.tags):
        for session in ctx.session_manager.sessions.values():
            if session.player.wanted_level > 0 and session.player.name != ctx.session.player.name:
                level_desc = ["suspected", "wanted", "MOST WANTED"][min(session.player.wanted_level - 1, 2)]
                await ctx.session.send_display(
                    f"A poster on the wall shows a sketch labelled '{session.player.name}': {level_desc}. "
                    f"Reward: {session.player.wanted_level * 20} fabi.\n",
                    msg_type=MessageType.EVENT,
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
                await ctx.session.send_display(loc(key) + "\n", msg_type=MessageType.AMBIENT)
            elif "gmd_safehouse" in tag_lower:
                gmd_inf = ctx.shared.gmd_influence
                if gmd_inf >= 80:
                    key = "safehouse.gmd.high"
                elif gmd_inf >= 60:
                    key = "safehouse.gmd.mid"
                else:
                    key = "safehouse.gmd.bare"
                await ctx.session.send_display(loc(key) + "\n", msg_type=MessageType.AMBIENT)

    await ctx.session.send_completions(build_completions(ctx))
    return success("look", facts={"room_looked"}, tutorial_event={"verb": "look"})


async def cmd_go(ctx: CommandContext, cmd: Command):
    from .trust import has_faction_perk

    ctx.session._weapon_attack_count = 0

    if ctx.session.player.active_storylets:
        for active in list(ctx.session.player.active_storylets):
            if active.room_id == ctx.session.player.current_room:
                await _resolve_neglect(ctx, active)
        ctx.session.player.active_storylets = [a for a in ctx.session.player.active_storylets if not a.resolved]

    direction = cmd.direct_obj
    if not direction:
        await post_display(ctx, loc("cmd_go.no_direction"), msg_type=MessageType.PLAYER_ACTION)
        return failure("go_no_direction")
    room = _room(ctx)
    if not room:
        await post_display(ctx, loc("cmd_go.nowhere"), msg_type=MessageType.PLAYER_ACTION)
        return failure("go_nowhere")

    if getattr(ctx.session.player, 'in_tutorial', False):
        from .tutorial import normalize_to_actionable_stage
        stage = normalize_to_actionable_stage(ctx.session.player)
        room_id = room.id
        if hasattr(ctx.session.player, "tutorial_instance_id"):
            from .tutorial import get_original_tutorial_room_id
            room_id = get_original_tutorial_room_id(
                ctx.session.player.tutorial_instance_id, room.id, ctx.shared
            )
        from .tutorial import blocked_exits_for_room, live_npc_exit_blocks
        room_blocked = blocked_exits_for_room(room_id, stage)
        room_blocked.update(live_npc_exit_blocks(ctx.session.player, ctx.shared, room_id))
        if direction.lower() in room_blocked:
            reason = room_blocked[direction.lower()]
            await post_display(ctx, f"You cannot go that way yet. {reason}", msg_type="tutorial")
            return failure("go_blocked")

    ctx.session.player.map_revealed = getattr(ctx.session.player, 'map_revealed', [])

    dest = room.exits.get(direction)
    if not dest:
        if getattr(ctx.session.player, "in_tutorial", False):
            from .tutorial import STAGE_ACTIONS, get_original_tutorial_room_id
            stage = getattr(ctx.session.player, "tutorial_stage", 0)
            action = STAGE_ACTIONS.get(stage, {})
            original_room_id = get_original_tutorial_room_id(
                getattr(ctx.session.player, "tutorial_instance_id", ""), room.id, ctx.shared
            )
            if (
                action.get("verb") == "go"
                and action.get("target") == direction
                and action.get("room_id") == original_room_id
            ):
                return failure("go_no_exit")
        from .parser import DIRECTIONS as _DIRECTION_TOKENS
        if direction.strip().lower() in _DIRECTION_TOKENS:
            target_room = None
        else:
            target_name = direction.lower()
            target_room = None
            from .world import is_public_map_room
            revealed = set(ctx.session.player.map_revealed)
            candidate_ids = list(ctx.shared.world.rooms)
            if getattr(ctx.session.player, "in_tutorial", False):
                instance_id = getattr(ctx.session.player, "tutorial_instance_id", "")
                clone_map = ctx.shared.tutorial_room_clones.get(instance_id, {})
                candidate_ids = list(clone_map.values())
            for room_id in candidate_ids:
                r = ctx.shared.world.rooms.get(room_id)
                if not r or not (is_public_map_room(r) or room_id in revealed):
                    continue
                display_id = room_id
                if getattr(ctx.session.player, "in_tutorial", False):
                    from .tutorial import get_original_tutorial_room_id
                    display_id = get_original_tutorial_room_id(
                        ctx.session.player.tutorial_instance_id, room_id, ctx.shared
                    )
                if (target_name == display_id.lower() or target_name in r.title.lower() or
                        (hasattr(r, 'name') and target_name in r.name.lower())):
                    target_room = r
                    break

        if target_room:
            if target_room.id == room.id:
                await post_display(ctx, "You are already there.", msg_type="tutorial" if getattr(ctx.session.player, "in_tutorial", False) else "ambient")
                return success("go_already_there")
            path = _bfs_find_path(ctx.shared.world, room.id, target_room.id)
            if path:
                await post_display(ctx, loc("movement.auto_path.start").format(title=target_room.title, steps=len(path)), msg_type="ambient")
                prev_district = room.district
                for i, step in enumerate(path):
                    if ctx.session.player.health <= 0:
                        await post_display(ctx, loc("movement.auto_path.halt_injured"), msg_type="ambient")
                        return failure("go_auto_path_stopped")
                    if ctx.session.player.hunger < 10:
                        await post_display(ctx, loc("movement.auto_path.halt_hungry"), msg_type="ambient")
                        return failure("go_auto_path_stopped")

                    current_room = _room(ctx)
                    if current_room:
                        for npc_id in current_room.npcs:
                            npc = ctx.shared.world.npcs.get(npc_id)
                            if npc and npc.faction == "kempeitai":
                                await post_display(ctx, loc("movement.auto_path.halt_hostile"), msg_type="ambient")
                                return failure("go_auto_path_hostile")

                    pre_hop_room_id = None
                    if getattr(ctx.session.player, "in_tutorial", False) and hasattr(ctx.session.player, "tutorial_instance_id"):
                        from .tutorial import get_original_tutorial_room_id
                        pre_hop = _room(ctx)
                        if pre_hop:
                            pre_hop_room_id = get_original_tutorial_room_id(
                                ctx.session.player.tutorial_instance_id, pre_hop.id, ctx.shared
                            )

                    step_cmd = Command(verb="go", direct_obj=step, raw=f"go {step}", suppress_render=True)
                    step_result = await cmd_go(ctx, step_cmd)
                    if not step_result.succeeded:
                        await post_display(ctx, loc("movement.auto_path.halt_blocked"), msg_type="ambient")
                        return failure("go_auto_path_blocked")

                    if pre_hop_room_id is not None and step_result.data.get("tutorial_event"):
                        from .tutorial import TutorialEvent, record_tutorial_event
                        event_data = step_result.data["tutorial_event"]
                        event = TutorialEvent(
                            event_data.get("verb") or "go",
                            event_data.get("target", step),
                            event_data.get("indirect", ""),
                            pre_hop_room_id,
                            succeeded=True,
                        )
                        await record_tutorial_event(ctx, event)
                        manager = getattr(ctx, "session_manager", None)
                        if manager is not None and hasattr(manager, "_send_map_data"):
                            await manager._send_map_data(ctx.session)

                    new_room = _room(ctx)
                    if new_room:
                        if i < len(path) - 1:
                            game_hour = ctx.shared.game_time.hour
                            is_night = game_hour < 6 or game_hour >= 20

                            transition_key = "movement.transition.default"
                            room_tags = getattr(new_room, 'tags', [])
                            room_district = getattr(new_room, 'district', '')

                            if is_night:
                                transition_key = "movement.transition.night"
                            elif any(t in room_tags for t in ["market", "market_stall"]):
                                transition_key = "movement.transition.market"
                            elif "market" in room_district.lower() if room_district else False:
                                transition_key = "movement.transition.market"
                            elif any(t in room_tags for t in ["dock", "docks", "warehouse"]):
                                transition_key = "movement.transition.docks"
                            elif "dock" in room_district.lower() if room_district else False:
                                transition_key = "movement.transition.docks"
                            elif any(t in room_tags for t in ["indoor", "building", "shop", "tea_house"]):
                                transition_key = "movement.transition.indoors"
                            else:
                                transition_key = "movement.transition.streets"

                            await post_display(ctx, loc(transition_key), msg_type="ambient")
                        if new_room.district and new_room.district != prev_district:
                            district_name = DISTRICT_LABELS.get(new_room.district, new_room.district.replace("_", " ").title())
                            await post_display(ctx, loc("movement.auto_path.district_change").format(district=district_name), msg_type="ambient")
                            prev_district = new_room.district
                        if i == len(path) - 1:
                            await post_display(ctx, loc("movement.auto_path.arrive").format(title=new_room.title), msg_type="ambient")

                await cmd_look(ctx, Command(verb="look", suppress_render=False))
                await asyncio.sleep(0.1)
                return success(
                    "go_auto_path",
                    facts={"movement"},
                )

        await post_display(ctx, loc("cmd_go.no_exit"), msg_type=MessageType.PLAYER_ACTION)
        return failure("go_no_exit")

    dest_room = ctx.shared.world.rooms.get(dest)
    if dest_room and "checkpoint" in dest_room.tags:
        if not has_faction_perk(ctx.session.player.trust, "green_gang"):
            pass

    if dest_room and dest_room.safe_room and wanted_consequences(ctx.session.player.wanted_level).npc_may_flee:
        room_faction = None
        if "ccp_safehouse" in dest_room.tags:
            room_faction = "ccp"
        elif "gmd_safehouse" in dest_room.tags:
            room_faction = "gmd"
        elif "green_gang_safehouse" in dest_room.tags:
            room_faction = "green_gang"
        elif "kempeitai_safehouse" in dest_room.tags:
            room_faction = "kempeitai"

        if room_faction:
            trust_score = get_role_trust(ctx.session.player.trust, room_faction, None)
            if trust_score >= 70:
                pass
            else:
                await post_display(ctx, loc("wanted.safe_room_deny"), msg_type=MessageType.WARNING)
                return failure("go_safe_room_denied")
        else:
            await post_display(ctx, loc("wanted.safe_room_deny"), msg_type=MessageType.WARNING)
            return failure("go_safe_room_denied")

    if getattr(ctx.session.player, 'in_tutorial', False) and hasattr(ctx.session.player, 'tutorial_instance_id'):
        from .tutorial import get_cloned_room_id
        cloned_dest = get_cloned_room_id(ctx.session.player.tutorial_instance_id, dest, ctx.shared)
        if cloned_dest != dest and ctx.shared.world.get_room(cloned_dest):
            dest = cloned_dest
    ctx.session.player.current_room = dest
    await ctx.session.clear_patrol_warning()
    ctx.session.player.rooms_looked.clear()
    ctx.session.player._last_movement_tick = ctx.shared.game_time.minute
    if dest not in ctx.session.player.map_revealed:
        ctx.session.player.map_revealed.append(dest)
    if getattr(ctx.session.player, "in_tutorial", False):
        from .tutorial import update_tutorial_resume_state
        update_tutorial_resume_state(ctx.session.player, ctx.shared)
        clock = getattr(ctx.session_manager, "world_clock", None)
        if clock is not None:
            clock.trigger_sanctioned_tutorial_meetings()
    ctx.session.player.hidden = False
    log_event(ctx, f"You moved {direction} into {dest}.")
    if getattr(ctx.session, 'audio_enabled', False):
        if getattr(ctx.session, '_movement_single_footstep', False):
            await ctx.session.send_audio('footsteps_once', volume=0.4)
        else:
            await ctx.session.send_audio('footsteps', volume=0.4)
    if not getattr(ctx.session.player, "in_tutorial", False) and not ctx.session.player.escape_charge_available:
        from .auth import resolve_spawn_room
        claimed_safehouse = resolve_spawn_room(ctx.session.username)
        if claimed_safehouse and dest == claimed_safehouse:
            ctx.session.player.escape_charge_available = True
    await _handle_mission_objectives(ctx, "visit_room", dest)

    if getattr(ctx.session.player, "in_tutorial", False):
        from .tutorial import STAGE_ACTIONS as _GO_STAGES_TRANS
        stage = getattr(ctx.session.player, "tutorial_stage", 0)
        stage_action = _GO_STAGES_TRANS.get(stage, {})
        trans_narration = stage_action.get("narration", "")
        if trans_narration:
            await ctx.session.send_display(trans_narration, msg_type=MessageType.ROOM_DESCRIPTION)

    if getattr(ctx.session.player, "in_tutorial", False):
        from .tutorial import STAGE_ACTIONS as _GO_STAGES
        stage = getattr(ctx.session.player, "tutorial_stage", 0)
        next_action = _GO_STAGES.get(stage + 1, {})
        stage_id = next_action.get("stage_id", "")
        if stage_id:
            entries = getattr(ctx.session.player, "tutorial_entries_emitted", None)
            if entries is None:
                entries = set()
                ctx.session.player.tutorial_entries_emitted = entries
            if stage_id not in entries:
                ctx.session.player._pending_arrival_text = next_action.get("arrival_text", "")

    if not cmd.suppress_render:
        await cmd_look(ctx, cmd)

    if ctx.session.player.disguise and dest_room:
        await _check_disguise_on_entry(ctx, dest_room)

    await _inspect_contraband_at_checkpoint(ctx, dest_room)

    if wanted_consequences(ctx.session.player.wanted_level).level >= WANTED_LEVEL_MAX:
        await _check_kempeitai_attack_on_sight(ctx)

    await maybe_trigger_storylet(ctx)
    return success(
        "go",
        facts={"movement"},
        tutorial_event={"verb": "go", "target": direction},
    )


async def _inspect_contraband_at_checkpoint(ctx: CommandContext, room) -> None:
    if not room or "checkpoint" not in getattr(room, "tags", []):
        return
    authority_present = any(
        (npc := ctx.shared.world.npcs.get(npc_id)) and npc.faction == "kempeitai"
        for npc_id in room.npcs
    )
    if not authority_present:
        return
    contraband = [
        item for item in ctx.session.player.inventory
        if getattr(item, "contraband_risk", False) or getattr(item, "evidence", False)
    ]
    if not contraband:
        return
    from .constants import BLACK_MARKET_DETECTION_CHANCE, WANTED_LEVEL_MAX
    if random.randint(1, 100) > BLACK_MARKET_DETECTION_CHANCE:
        return
    confiscated = contraband[0]
    ctx.session.player.inventory.remove(confiscated)
    invalidate_disguise_if_support_lost(ctx.session.player, confiscated)
    _record_crime(ctx)
    log_event(ctx, f"Kempeitai confiscated {confiscated.name} at a checkpoint.")
    await post_display(
        ctx,
        f"Kempeitai search you at the checkpoint and confiscate {confiscated.name}. Wanted level increased.",
        msg_type="event",
    )


def _mod_candidates(player: Any) -> List[Item]:
    from .equipment import ensure_inventory_identity
    ensure_inventory_identity(player)
    return [item for item in player.inventory if getattr(item, "is_mod", False)]


def _compatible_mod_weapons(player: Any, mod: Item) -> List[Item]:
    slots = getattr(mod, "id", "")
    candidates = []
    for weapon in player.inventory:
        if not weapon.is_weapon:
            continue
        weapon_slots = getattr(weapon, "mod_slots", []) or []
        if slots not in weapon_slots:
            continue
        if len(getattr(weapon, "mods", []) or []) >= len(weapon_slots):
            continue
        if mod.id == "extended_magazine" and weapon.weapon_type != "firearm":
            continue
        candidates.append(weapon)
    return candidates


def _repairable_weapons(player: Any) -> List[Item]:
    from .equipment import ensure_inventory_identity
    ensure_inventory_identity(player)
    out = []
    for weapon in player.inventory:
        if not weapon.is_weapon:
            continue
        if weapon.durability == -1 or weapon.max_durability <= 0:
            continue
        if weapon.durability >= weapon.max_durability:
            continue
        out.append(weapon)
    return out


def _selling_vendor(ctx: CommandContext):
    room = _room(ctx)
    if not room:
        return None
    from .economy import economy_system as _econ
    for npc_id in room.npcs:
        npc = ctx.shared.world.npcs.get(npc_id)
        if not npc:
            continue
        stock = list(getattr(npc, "shop_inventory", []) or []) + list(getattr(npc, "black_market_items", []) or [])
        if not stock:
            continue
        represented_categories = {
            _econ.get_item_category(_vendor_item_id(entry))
            for entry in stock
            if _vendor_item_id(entry)
        }
        return npc, stock, represented_categories
    return None


def _sellable_items(ctx: CommandContext) -> List[Item]:
    from .equipment import ensure_inventory_identity
    from .economy import economy_system as _econ
    player = ctx.session.player
    ensure_inventory_identity(player)
    vendor = _selling_vendor(ctx)
    if not vendor:
        return []
    represented_categories = vendor[2]
    equipped_ids = {
        player.equipped_weapon_id,
        player.worn_armour_id,
        player.equipped_disguise_item_id,
    }
    out = []
    for item in player.inventory:
        if not item.takeable or item.is_quest_item:
            continue
        if item.instance_id in equipped_ids:
            continue
        if _econ.get_item_category(item.id) not in represented_categories:
            continue
        out.append(item)
    return out


async def _open_item_action_chooser(
    ctx: CommandContext,
    action: str,
    title: str,
    rows: List[Dict[str, Any]],
    stage: str = "",
    note: str = "",
    context: Optional[Dict[str, Any]] = None,
    confirm_target: str = "",
) -> None:
    from .popup_payloads import item_action_payload, room_key_for_client, send_popup
    room_key = room_key_for_client(ctx)
    merged = {"room_key": room_key, "expected_action": action}
    if context:
        merged.update(context)
    ctx.session.set_open_popup("action", merged)
    await send_popup(ctx.session, "action_menu", item_action_payload(
        action,
        title,
        room_key,
        ctx.session.open_popup["generation"],
        rows,
        stage=stage,
        note=note,
        confirm_target=confirm_target,
    ))


def _action_row(item_or_journal: Any, disabled: bool = False, disabled_reason: str = "") -> Dict[str, Any]:
    from .popup_payloads import action_item_row
    return action_item_row(item_or_journal, disabled=disabled, disabled_reason=disabled_reason)


async def cmd_take(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        room = _room(ctx)
        candidates = []
        if room:
            from .equipment import ensure_items_identity
            ensure_items_identity(room.items)
            at_capacity = len(ctx.session.player.inventory) >= ctx.session.player.max_inventory
            reason = loc("cmd_take.inventory_full") if at_capacity else ""
            candidates = [
                _action_row(item, disabled=at_capacity, disabled_reason=reason)
                for item in room.items if item.takeable
            ]
        if not candidates:
            await post_display(ctx, "There is nothing here to take.", msg_type=MessageType.PLAYER_ACTION)
            return failure("take_no_candidates")
        await _open_item_action_chooser(ctx, "take", loc("cmd_take.no_target"), candidates)
        return success("take_chooser", facts={"chooser_opened"})
    room = _room(ctx)
    item = find_item_exact(cmd.direct_obj, room.items if room else [])
    if not item:
        await post_display(ctx, loc("cmd_take.not_here"), msg_type=MessageType.PLAYER_ACTION)
        return failure("take_not_here")
    if not item.takeable:
        await post_display(ctx, loc("cmd_take.not_takeable"), msg_type=MessageType.PLAYER_ACTION)
        return failure("take_not_takeable")
    if len(ctx.session.player.inventory) >= ctx.session.player.max_inventory:
        await post_display(ctx, loc("cmd_take.inventory_full"), msg_type=MessageType.PLAYER_ACTION)
        return failure("take_inventory_full")

    try:
        room.items.remove(item)
    except ValueError:
        await post_display(ctx, loc("cmd_take.already_taken"), msg_type=MessageType.PLAYER_ACTION)
        return failure("take_already_taken")
    ctx.session.player.inventory.append(item)
    await ctx.session.send_completions(build_completions(ctx))
    await _send_room_details(ctx, room)
    log_event(ctx, f"You took {item.name}.")
    await _handle_mission_objectives(ctx, "collect_item", item.id)
    await post_display(ctx, loc("cmd_take.success").format(name=semantic_span(item.name, "item")), msg_type=MessageType.PLAYER_ACTION)
    await play_sound(ctx, "item_pickup", 0.6)
    await maybe_trigger_storylet(ctx)
    return success(
        "take",
        facts={"item_taken"},
        tutorial_event={"verb": "take", "target": item.id or item.name},
    )


async def cmd_drop(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        from .equipment import ensure_inventory_identity
        ensure_inventory_identity(ctx.session.player)
        candidates = [_action_row(item) for item in ctx.session.player.inventory]
        if not candidates:
            await post_display(ctx, "You have nothing to drop.", msg_type=MessageType.PLAYER_ACTION)
            return failure("drop_no_candidates")
        await _open_item_action_chooser(ctx, "drop", loc("cmd_drop.no_target"), candidates)
        return success("drop_chooser", facts={"chooser_opened"})
    item = find_item_exact(cmd.direct_obj, ctx.session.player.inventory)
    if not item:
        await post_display(ctx, loc("cmd_drop.not_held"), msg_type=MessageType.PLAYER_ACTION)
        return failure("drop_not_held")
    if item.is_weapon:
        ctx.session._weapon_attack_count = 0
    ctx.session.player.inventory.remove(item)
    invalidate_disguise_if_support_lost(ctx.session.player, item)
    await _refresh_inventory_if_open(ctx)
    room = _room(ctx)
    if room:
        room.items.append(item)
        await _send_room_details(ctx, room)
    await ctx.session.send_completions(build_completions(ctx))
    log_event(ctx, f"You dropped {item.name}.")
    await post_display(ctx, loc("cmd_drop.success").format(name=semantic_span(item.name, "item")), msg_type=MessageType.PLAYER_ACTION)
    return success("drop", facts={"item_dropped"})


async def _refresh_popup_if_open(ctx: CommandContext, kind: str, payload: Dict[str, Any]) -> None:
    open_popup = getattr(ctx.session, "open_popup", None)
    if not open_popup or open_popup.get("kind") != kind:
        return
    from .popup_payloads import send_popup
    await send_popup(ctx.session, f"{kind}_menu", payload)


async def _refresh_inventory_if_open(ctx: CommandContext) -> None:
    from .popup_payloads import inventory_payload
    open_popup = getattr(ctx.session, "open_popup", None)
    if not open_popup or open_popup.get("kind") != "inventory":
        return
    await _refresh_popup_if_open(ctx, "inventory", inventory_payload(
        ctx.session.player, open_popup.get("generation", 0),
    ))


async def _refresh_equipment_if_open(ctx: CommandContext) -> None:
    from .popup_payloads import equipment_payload
    open_popup = getattr(ctx.session, "open_popup", None)
    if not open_popup or open_popup.get("kind") != "equipment":
        return
    await _refresh_popup_if_open(ctx, "equipment", equipment_payload(
        ctx.session.player, open_popup.get("generation", 0),
    ))


async def _open_equipment_popup(ctx: CommandContext) -> None:
    from .popup_payloads import equipment_payload, send_popup
    ctx.session.set_open_popup("equipment", {})
    await send_popup(ctx.session, "equipment_menu", equipment_payload(
        ctx.session.player, ctx.session.open_popup["generation"],
    ))


def _container_key_item(ctx: CommandContext, container):
    if not container.key_id:
        return None
    return ctx.shared.world.item_catalog.get(container.key_id)


async def _open_container_popup(ctx: CommandContext, container) -> None:
    from .popup_payloads import container_payload, room_key_for_client, send_popup
    room_key = room_key_for_client(ctx)
    ctx.session.set_open_popup("container", {"room_key": room_key, "container_id": container.id})
    await send_popup(ctx.session, "container_menu", container_payload(
        container, room_key, ctx.session.open_popup["generation"],
        key_item=_container_key_item(ctx, container),
        has_key=_has_key_for_container(ctx.session.player, container),
    ))


async def _refresh_container_if_open(ctx: CommandContext, container) -> None:
    from .popup_payloads import container_payload
    open_popup = getattr(ctx.session, "open_popup", None)
    if not open_popup or open_popup.get("kind") != "container":
        return
    if open_popup.get("context", {}).get("container_id") != container.id:
        return
    await _refresh_popup_if_open(ctx, "container", container_payload(
        container,
        open_popup.get("context", {}).get("room_key", ""),
        open_popup.get("generation", 0),
        key_item=_container_key_item(ctx, container),
        has_key=_has_key_for_container(ctx.session.player, container),
    ))


async def _close_container_popup_if_open(ctx: CommandContext, container_id: str, reason: str) -> None:
    open_popup = getattr(ctx.session, "open_popup", None)
    if open_popup and open_popup.get("kind") == "container" and open_popup.get("context", {}).get("container_id") == container_id:
        await ctx.session.send_popup_close(reason)
        ctx.session.clear_open_popup()


async def cmd_inventory(ctx: CommandContext, cmd: Command):
    from .popup_payloads import inventory_payload, send_popup
    ctx.session.set_open_popup("inventory", {})
    await send_popup(ctx.session, "inventory_menu", inventory_payload(
        ctx.session.player, ctx.session.open_popup["generation"],
    ))
    return success("inventory", facts={"inventory_opened"}, tutorial_event={"verb": "inventory"})


async def _maybe_grant_testimony_keepsake(ctx: CommandContext, npc: Npc) -> None:
    if npc.id not in {"liu_wei", "sister_wang", "dr_zhao", "black_market_seller", "captain_ishikawa"}:
        return
    relationship = _get_relationship(ctx, npc.id)
    if relationship.get("friendship", 0) < 70:
        return
    reward_flag = f"bond_testimony:{npc.id}"
    if reward_flag in ctx.session.player.flags:
        return
    reward_items = {
        "liu_wei": ("testimony_liu_wei",),
        "sister_wang": ("testimony_sister_wang",),
        "dr_zhao": ("testimony_dr_zhao", "testimony_dr_zhao_parcel"),
        "black_market_seller": ("testimony_lao_jin", "testimony_lao_jin_key"),
        "captain_ishikawa": ("testimony_captain_ishikawa",),
    }
    granted = []
    for item_id in reward_items[npc.id]:
        item = ctx.shared.world.clone_item(item_id)
        if item:
            ctx.session.player.inventory.append(item)
            granted.append(item)
    if not granted:
        return
    ctx.session.player.flags.append(reward_flag)
    await post_display(ctx, f"{semantic_span(npc.name, 'npc')} entrusts you with a testimony kept from safer days.", msg_type="npc_dialogue")
    for item in granted:
        await post_display(ctx, f"You receive {semantic_span(item.name, 'item')}.", msg_type="npc_dialogue")
    log_event(ctx, f"{npc.name} entrusted you with a testimony keepsake.")


async def _maybe_green_gang_wanted_offer(ctx: CommandContext, npc) -> None:
    import random
    from .trust import get_role_trust
    from .storylets import ActiveStorylet, StoryletOption
    
    current_day = ctx.shared.game_time.day
    if ctx.session.player.last_wanted_favor_day == current_day:
        return
    
    trust_score = get_role_trust(ctx.session.player.trust, "green_gang", npc.role)
    if trust_score < 30:
        return
    
    cost = 50 + (ctx.session.player.wanted_level * 25)
    
    offer_storylet = ActiveStorylet(
        storylet_id=f"green_gang_wanted_offer_{npc.id}",
        narrative=loc("wanted.green_gang_offer").format(name=npc.name, cost=cost),
        options=[
            StoryletOption(
                text=f"DEAL ({cost} fabi)",
                effects={"reduce_wanted": 1, "cost_fabi": cost}
            ),
            StoryletOption(
                text="No deal",
                effects={}
            )
        ],
        room_id=ctx.session.player.current_room
    )

    ctx.session.player.active_storylets.append(offer_storylet)
    await _display_storylet(ctx, offer_storylet)
    ctx.session.player.flags.append(f"green_gang_offer_{npc.id}_{current_day}")


async def cmd_talk_to(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_talk_to.no_target"), msg_type=MessageType.PLAYER_ACTION)
        return
    npc_id = resolve_npc(ctx, cmd.direct_obj)
    if not npc_id:
        await post_display(ctx, loc("cmd_talk_to.not_here"), msg_type=MessageType.PLAYER_ACTION)
        return
    npc = ctx.shared.world.npcs[npc_id]

    if ctx.session.player.disguise:
        pierced = await _check_disguise_on_talk(ctx, npc)
        if pierced:
            return

    from .tutorial import (STAGE_ACTIONS, TutorialEvent, stage_accepts_event,
                           tutorial_blocks_world_events, tutorial_dialogue_for_stage)
    if tutorial_blocks_world_events(ctx.session.player):
        room = _room(ctx)
        action = STAGE_ACTIONS.get(getattr(ctx.session.player, "tutorial_stage", 0), {})
        advancing = stage_accepts_event(
            action,
            TutorialEvent(
                "talk to",
                cmd.direct_obj or "",
                cmd.indirect_obj or "",
                room.id if room else "",
            ),
            ctx.session.player,
        )
        if advancing:
            mark_npc_met(ctx, npc_id)
            return success(
                "talk_to",
                facts={"npc_talked"},
                tutorial_event={"verb": "talk to", "target": cmd.direct_obj or ""},
            )
        td_lines = tutorial_dialogue_for_stage(ctx.session.player, npc_id, ctx.shared.world)
        if td_lines:
            line = random.choice(td_lines)
            await ctx.session.send_npc_speech(npc_id, npc.name, line)
            record_conversation(ctx, npc_id, f"Hello, {npc.name}.", line)
            mark_npc_met(ctx, npc_id)
            return success(
                "talk_to",
                facts={"npc_talked"},
                tutorial_event={"verb": "talk to", "target": cmd.direct_obj or ""},
            )

    line = _get_npc_dialogue(ctx, npc, "greeting")
    room = _room(ctx)
    lead = find_consequence_ask_lead(ctx.shared, npc_id, room.id, "") if room else None
    topic_hint = display_topic_label(npc, lead["ask_topic"]) if lead else _topic_hint(npc)
    await post_display(ctx, f'{semantic_span(npc.name, "npc")} says, "{line}"\n\nYou could ASK {_short_name(npc.name)} ABOUT {topic_hint}.', msg_type="npc")
    direction = _story_direction(ctx, npc)
    if direction:
        await post_display(ctx, direction, msg_type="npc")
    record_conversation(ctx, npc_id, f"Hello, {npc.name}.", line)
    mark_npc_met(ctx, npc_id)
    await apply_action_trust(ctx, f"talk_to_{npc.faction}.{npc.role}", room_npcs(ctx))
    log_event(ctx, f"You spoke with {npc.name}.")

    chain = ctx.storylet_manager.check_narrative_chain(npc_id, ctx.session.player, ctx.shared)
    if chain:
        effects = chain.effects
        if effects:
            from .trust import change_trust
            for flag in effects.get("set_flag", []):
                if flag and flag not in ctx.session.player.flags:
                    ctx.session.player.flags.append(str(flag))
            for flag in effects.get("clear_flag", []):
                if flag in ctx.session.player.flags:
                    ctx.session.player.flags.remove(flag)
            for trust_key, delta in effects.get("change_trust", {}).items():
                change_trust(
                    ctx.session.player.trust,
                    trust_key,
                    int(delta),
                    last_trust_interaction=ctx.session.player.last_trust_interaction,
                    current_day=getattr(ctx.shared, "day", 1),
                    player_flags=ctx.session.player.flags,
                )
            for event in effects.get("log_event", []):
                log_event(ctx, event)
        if chain.feedback:
            await post_display(ctx, chain.feedback, msg_type="npc")

    await _handle_mission_objectives(ctx, "talk_to_npc", npc_id)
    await _offer_mission_from_npc(ctx, npc_id, npc.name)
    if npc.faction == "green_gang" and wanted_consequences(ctx.session.player.wanted_level).ordinary_vendor_refuses:
        await _maybe_green_gang_wanted_offer(ctx, npc)
    return success(
        "talk_to",
        facts={"npc_talked"},
        tutorial_event={"verb": "talk to", "target": cmd.direct_obj or ""},
    )


async def _offer_mission_from_npc(ctx: CommandContext, npc_id: str, npc_name: str) -> None:
    manager = getattr(ctx.shared, "mission_manager", None)
    if not manager or ctx.session.player.active_storylets:
        return
    offers = manager.offer_for_giver(
        ctx.session.player,
        npc_id,
        world=ctx.shared,
        current_day=ctx.shared.game_time.day,
        current_hour=ctx.shared.game_time.hour,
    )
    if not offers:
        return
    mission = offers[0]
    active = ActiveStorylet(
        storylet_id=f"mission_offer:{mission.id}",
        narrative=f'{npc_name} has work that may matter. "{mission.description}"',
        options=[
            StoryletOption(
                text=f"Accept: {mission.title}",
                effects={"mission_offer_action": "accept", "mission_id": mission.id},
            ),
            StoryletOption(
                text="Decline", effects={"mission_offer_action": "decline", "mission_id": mission.id}
            ),
            StoryletOption(
                text="Not now", effects={"mission_offer_action": "defer", "mission_id": mission.id}
            ),
        ],
        room_id=ctx.session.player.current_room,
        timer_duration=0,
        scope="player",
        owner_username=ctx.session.username,
    )
    ctx.session.player.active_storylets.append(active)
    await _display_storylet(ctx, active)


async def cmd_ask_about(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_ask_about.no_target"), msg_type=MessageType.PLAYER_ACTION)
        return

    from .tutorial import (STAGE_ACTIONS, TutorialEvent, stage_accepts_event,
                           tutorial_blocks_world_events, tutorial_dialogue_for_stage)
    if tutorial_blocks_world_events(ctx.session.player):
        npc_id = resolve_npc(ctx, cmd.direct_obj)
        if npc_id:
            npc = ctx.shared.world.npcs[npc_id]
            room = _room(ctx)
            action = STAGE_ACTIONS.get(getattr(ctx.session.player, "tutorial_stage", 0), {})
            advancing = stage_accepts_event(
                action,
                TutorialEvent(
                    "ask",
                    cmd.direct_obj or "",
                    cmd.indirect_obj or "",
                    room.id if room else "",
                ),
                ctx.session.player,
            )
            if advancing:
                mark_npc_met(ctx, npc_id)
                return success(
                    "ask",
                    facts={"asked"},
                    tutorial_event={"verb": "ask", "target": cmd.direct_obj or "", "indirect": cmd.indirect_obj or ""},
                )
            tutorial_topics = _eligible_ask_topics(ctx, npc_id, npc, room)
            if cmd.indirect_obj and not _matches_ask_topic(cmd.indirect_obj, npc, tutorial_topics):
                await post_display(ctx, _ask_topic_prompt(npc, tutorial_topics), msg_type="npc_dialogue")
                return failure("ask_unanswered")
            td_lines = tutorial_dialogue_for_stage(ctx.session.player, npc_id, ctx.shared.world, topic=cmd.indirect_obj or "")
            if td_lines:
                line = random.choice(td_lines)
                await ctx.session.send_npc_speech(npc_id, npc.name, line)
                record_conversation(ctx, npc_id, f"Tell me about {display_topic_label(npc, cmd.indirect_obj or '...')}.", line)
                mark_npc_met(ctx, npc_id)
                return success(
                    "ask",
                    facts={"asked"},
                    tutorial_event={"verb": "ask", "target": cmd.direct_obj or "", "indirect": cmd.indirect_obj or ""},
                )

    if not cmd.indirect_obj:
        npc_id = resolve_npc(ctx, cmd.direct_obj)
        if not npc_id:
            await post_display(ctx, loc("cmd_ask_about.not_here"), msg_type=MessageType.PLAYER_ACTION)
            return
        npc = ctx.shared.world.npcs[npc_id]
        if getattr(ctx.session.player, "in_tutorial", False):
            from .tutorial import STAGE_ACTIONS, normalize_to_actionable_stage
            stage = normalize_to_actionable_stage(ctx.session.player)
            curated = STAGE_ACTIONS.get(stage, {}).get("topics") or []
            if curated:
                await post_display(ctx, "Topics: " + ", ".join(display_topic_label(npc, t) for t in curated), msg_type="npc_dialogue")
                return
        room = _room(ctx)
        await post_display(ctx, _ask_topic_prompt(npc, _eligible_ask_topics(ctx, npc_id, npc, room)), msg_type="npc_dialogue")
        return
    
    topic = cmd.indirect_obj
    topic_lower = topic.lower().strip()
    if topic_lower in ("this place", "here", "this room", "this area", "the room", "the area"):
        room = _room(ctx)
        if room:
            await _handle_room_hint_query(ctx, room)
        else:
            await post_display(ctx, "You are nowhere.", msg_type=MessageType.PLAYER_ACTION)
        return
    
    npc_id = resolve_npc(ctx, cmd.direct_obj)
    if not npc_id:
        await post_display(ctx, loc("cmd_ask_about.not_here"), msg_type=MessageType.PLAYER_ACTION)
        return
    npc = ctx.shared.world.npcs[npc_id]
    short = _short_name(npc.name)
    topic_key = match_topic(topic, npc)
    room = _room(ctx)
    eligible_topics = _eligible_ask_topics(ctx, npc_id, npc, room)
    known = npc_ask_topics(npc)
    consequence_lead = find_consequence_ask_lead(ctx.shared, npc_id, room.id, topic) if room else None
    if consequence_lead:
        line = consequence_lead.get("ask_response")
        await post_display(ctx, f'{semantic_span(npc.name, "npc")} says, "{line}"', msg_type="npc_dialogue")
        record_conversation(ctx, npc_id, f"Tell me about {display_topic_label(npc, consequence_lead['ask_topic'])}.", line)
        mark_npc_met(ctx, npc_id)
        player = ctx.session.player
        player.journal_intel.setdefault(npc_id, {})[f"consequence: {consequence_lead['category']}"] = {
            "day": ctx.shared.game_time.day,
            "npc_name": npc.name,
        }
        log_event(ctx, f"You asked {npc.name} about {display_topic_label(npc, consequence_lead['ask_topic'])}.")
        return

    if topic_key == "rumor":
        from .rumors import ask_trace
        social_rumour = find_consequence_rumour(ctx.shared, npc_id)
        trace_result = None
        if social_rumour:
            consequence_record_id = social_rumour.get("rumor_record_id")
            if consequence_record_id:
                trace_result = ask_trace(ctx.shared, ctx.session.player, npc_id, consequence_record_id)
        if trace_result is None:
            for held_id in sorted(getattr(npc, "rumor_observations", {}) or {}):
                trace_result = ask_trace(ctx.shared, ctx.session.player, npc_id, held_id)
                if trace_result:
                    break
        if trace_result:
            record = trace_result["record"]
            parts = [f'{npc.name} says, "I heard that {record["text"]}"']

            player_name = ctx.session.player.name.lower()
            player_in_memory = any(player_name in m.lower() for m in npc.memory if m)
            if player_in_memory:
                parts.append(f'  {npc.name} eyes you narrowly. "Wait, that sounds familiar. Were you involved?"')

            source_npc_id = record.get("source_npc_id", "")
            if source_npc_id and source_npc_id != npc_id:
                source_npc = ctx.shared.world.npcs.get(source_npc_id)
                source_name = source_npc.name if source_npc else source_npc_id
                parts.append(f"  Heard from {source_name}.")
            if record.get("hop_count", 0) > 0:
                parts.append(f"  Passed through {record['hop_count']} {'person' if record['hop_count'] == 1 else 'people'}.")
            if record.get("origin_faction") and record.get("origin_faction") != record.get("current_faction"):
                parts.append(f"  Originally attributed to {record['origin_faction']}, now said to be {record['current_faction']}.")
            elif record.get("current_faction"):
                parts.append(f"  Attributed to {record['current_faction']}.")
            await post_display(ctx, "\n".join(parts), msg_type="npc_dialogue")
            record_conversation(ctx, npc_id, "Where did you hear that?", record["text"])
            mark_npc_met(ctx, npc_id)
            await apply_action_trust(ctx, f"ask_about_{npc.faction}.{npc.role}", room_npcs(ctx))
            log_event(ctx, f"You asked {npc.name} about rumors.")
            await maybe_trigger_storylet(ctx)
        else:
            await post_display(ctx, f'{short} shakes their head. "I haven\'t heard anything worth repeating."', msg_type="npc_dialogue")
        return

    if topic_key and topic_key in known:
        line = get_topic_dialogue(npc, topic_key)
        await post_display(ctx, f'{semantic_span(npc.name, "npc")} says, "{line}"', msg_type="npc_dialogue")
        record_conversation(ctx, npc_id, f"Tell me about {display_topic_label(npc, topic_key)}.", line)
        mark_npc_met(ctx, npc_id)
        await apply_action_trust(ctx, f"ask_about_{npc.faction}.{npc.role}", room_npcs(ctx))
        log_event(ctx, f"You asked {npc.name} about {display_topic_label(npc, topic_key)}.")
        if npc_id not in ctx.session.player.asked_topics:
            ctx.session.player.asked_topics[npc_id] = []
        if topic_key not in ctx.session.player.asked_topics[npc_id]:
            ctx.session.player.asked_topics[npc_id].append(topic_key)
        player = ctx.session.player
        player.journal_intel[npc_id] = player.journal_intel.get(npc_id, {})
        player.journal_intel[npc_id][topic_key] = {
            "day": ctx.shared.game_time.day,
            "npc_name": npc.name,
        }
        await maybe_trigger_storylet(ctx)
        return success(
            "ask",
            facts={"asked"},
            tutorial_event={"verb": "ask", "target": cmd.direct_obj or "", "indirect": cmd.indirect_obj or ""},
        )
    else:
        await post_display(ctx, _ask_topic_prompt(npc, eligible_topics), msg_type="npc_dialogue")
    return failure("ask_unanswered")


def _move_npc_to_room(npc_id: str, room_id: str, shared) -> None:
    old_room_id = shared.npc_locations.get(npc_id, '')
    old_room = shared.world.get_room(old_room_id) if old_room_id else None
    if old_room and npc_id in old_room.npcs:
        old_room.npcs.remove(npc_id)
    new_room = shared.world.get_room(room_id)
    if new_room and npc_id not in new_room.npcs:
        new_room.npcs.append(npc_id)
    shared.npc_locations[npc_id] = room_id


def _return_npc_after_storylet(ctx: CommandContext, active: ActiveStorylet) -> None:
    return


def cleanup_storylet_speakers(ctx: CommandContext) -> None:
    for active in list(ctx.session.player.active_storylets):
        _return_npc_after_storylet(ctx, active)


async def _advance_time_manual(ctx: CommandContext, minutes: int):
    ctx.session.manually_advancing = True
    try:
        for _ in range(minutes):
            await advance_time_one_minute(ctx)
    finally:
        ctx.session.manually_advancing = False
    if not is_curfew(ctx.shared.game_time):
        for session in ctx.session_manager.sessions.values():
            await session.clear_patrol_warning()


async def cmd_status(ctx: CommandContext, cmd: Command):
    wanted_policy = wanted_consequences(ctx.session.player.wanted_level)
    disguise = ctx.disguises.get(ctx.session.player.disguise)
    lines = [time_str(ctx.shared.game_time)]
    lines.append("Season: " + _season_from_day(ctx.shared.game_time.day).capitalize())
    lines.append("Objective: " + _current_objective(ctx))
    lines.append(f"Health: {ctx.session.player.health}/100")
    hunger_value = int(ctx.session.player.hunger)
    hunger_tier = get_hunger_tier_label(ctx.session.player.hunger)
    lines.append(f"Hunger: {hunger_value}/100 ({hunger_tier})")
    lines.append(f"Morale: {ctx.session.player.morale}/100")
    lines.append(f"Courage: {ctx.session.player.courage}")
    lines.append(
        f"Money: {wallet_fabi_value(ctx.session.player)} fabi-value "
        f"({ctx.session.player.money_silver} silver, {ctx.session.player.money_fabi} fabi, "
        f"{ctx.session.player.money_military_yen} military yen)"
    )
    lines.append(f"Disguise: {disguise.name if disguise else 'none'}")
    lines.append(f"Stealth skill: {ctx.session.player.stealth_skill}")
    world_rooms = [room for room_id, room in ctx.shared.world.rooms.items() if not room_id.startswith("p_")]
    zone_count = len({room.district for room in world_rooms if room.district})
    visited_rooms = len({room_id for room_id in ctx.session.player.map_revealed if room_id in ctx.shared.world.rooms})
    lines.append(f"Map: {visited_rooms}/{len(world_rooms)} rooms discovered across {zone_count} zones")
    if ctx.session.player.worn_armour_id:
        armour = _get_worn_armour(ctx.session.player)
        if armour:
            lines.append(f"Armour: {armour.name} (def {armour.defense_value}, dur {armour.durability})")
    if wanted_policy.level > 0:
        lines.append(loc("status.wanted").format(level=wanted_policy.level, chance=wanted_policy.arrest_chance))
    if getattr(ctx.session.player, "custody_until", -1) >= 0:
        remaining = max(0, ctx.session.player.custody_until - game_clock_total_minutes(ctx.shared.game_time))
        lines.append(f"Custody: released in {remaining} minutes")
    lines.append("Trust:")
    lines.extend(summary_trust_lines(ctx))
    ccp_inf = ctx.shared.ccp_influence
    gmd_inf = ctx.shared.gmd_influence
    leader, leader_val = ("CCP", ccp_inf) if ccp_inf >= gmd_inf else ("GMD", gmd_inf)
    _ENDING_TIDE = {
        "ccp_uprising": "The tide favours the Communist underground.",
        "gmd_return": "The tide favours the Nationalist return.",
        "unity": "The factions walk a knife's edge toward unity.",
        "default_liberation": "The outcome awaits a common liberation.",
    }
    lines.append(f"Liberation draws near: {leader} stands at {leader_val}/100 influence.")
    lines.append(f"CCP influence: {ccp_inf}  GMD influence: {gmd_inf}")
    lines.append(_ENDING_TIDE[predict_ending(ccp_inf, gmd_inf)])
    kills = [f for f in ctx.session.player.flags if f.startswith("historical_kill:")]
    if kills:
        lines.append(f"Assassinations: {len(kills)}")
    await post_display(ctx, "\n".join(lines), msg_type=MessageType.PLAYER_STATUS)
    return success("status", facts={"status_read"}, tutorial_event={"verb": "status"})


def _get_relationship(ctx: CommandContext, npc_id: str) -> Dict[str, int]:
    if npc_id not in ctx.session.player.relationships:
        ctx.session.player.relationships[npc_id] = {"friendship": 0, "fear": 0, "indebtedness": 0}
    return ctx.session.player.relationships[npc_id]


def _modify_relationship(ctx: CommandContext, npc_id: str, changes: Dict[str, int]):
    rel = _get_relationship(ctx, npc_id)
    for key, delta in changes.items():
        if key in rel:
            rel[key] = max(0, min(100, rel[key] + delta))


def _check_npc_hostility(npc, player_name: str, current_day: int, npc_faction: str) -> Optional[str]:
    from .npc_memory import npc_memory_system

    memory = npc.player_memories.get(player_name)
    if not memory:
        return None

    crime_types = {
        'witnessed_crime', 'witnessed_murder', 'witnessed_theft',
        'witnessed_attack', 'witnessed_kill', 'caught_pickpocketing',
        'observed_suspicious_behavior'
    }
    for interaction in memory.interactions:
        days_since = current_day - interaction['day']
        if days_since > 3:
            continue
        if interaction['type'] in crime_types:
            personality = (npc.personality_traits or {}).get('integrity', 50) if hasattr(npc, 'personality_traits') else 50
            if personality >= 70:
                return loc("cmd_bond.rejected_witness_honest")
            else:
                return loc("cmd_bond.rejected_witness_default")

    faction_attack_types = {'attacked', 'witnessed_attack', 'witnessed_kill', 'harmed_friend'}
    for interaction in memory.interactions:
        days_since = current_day - interaction['day']
        if days_since > 3:
            continue
        if interaction['type'] in faction_attack_types:
            details = interaction.get('details', {})
            target_faction = details.get('target_faction', '')
            if target_faction == npc_faction:
                return loc("cmd_bond.rejected_faction_attack")

    return None


async def cmd_disguise_as(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_disguise_as.no_target"), msg_type=MessageType.PLAYER_ACTION)
        return
    query = cmd.direct_obj.lower().replace(" ", "_")
    disguise = ctx.disguises.get(query)
    if not disguise:
        await post_display(ctx, loc("cmd_disguise_as.not_found"), msg_type=MessageType.PLAYER_ACTION)
        return
    item = next((candidate for candidate in ctx.session.player.inventory if candidate.disguise_id == disguise.id), None)
    if item is None:
        await post_display(ctx, loc("cmd_disguise_as.not_found"), msg_type=MessageType.PLAYER_ACTION)
        return failure("disguise_item_not_held")
    from .equipment import ensure_inventory_identity
    ensure_inventory_identity(ctx.session.player)
    disguise_changed = ctx.session.player.disguise != disguise.id
    ctx.session.player.equipped_disguise_item_id = item.instance_id
    ctx.session.player.disguise = disguise.id
    log_event(ctx, f"You adopted the disguise of {disguise.name}.")
    await post_display(ctx, loc("cmd_disguise_as.success").format(name=disguise.name, description=disguise.description), msg_type=MessageType.PLAYER_ACTION)
    if disguise_changed:
        await play_sound(ctx, "disguise_equip", 0.6)

    room = _room(ctx)
    if room and room.npcs:
        for npc_id in room.npcs:
            npc = ctx.shared.world.npcs.get(npc_id)
            if npc and npc.perception >= 50:
                _generate_player_action_rumor(ctx, "disguise_seen", target=room.title)
                break
    return success(
        "disguise_as",
        facts={"disguised"},
        tutorial_event={"verb": "disguise as", "target": cmd.direct_obj or ""},
    )


async def cmd_tail(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_tail.no_target"), msg_type=MessageType.PLAYER_ACTION)
        return
    npc_id = resolve_npc(ctx, cmd.direct_obj)
    if not npc_id:
        await post_display(ctx, loc("cmd_tail.not_here"), msg_type=MessageType.PLAYER_ACTION)
        return
    ctx.session.player.tailing_state = ctx.stealth.start_tail(npc_id)
    ctx.session.player.tailing_state.last_checked_minute = (ctx.shared.game_time.day - 1) * 1440 + ctx.shared.game_time.minute
    target = ctx.shared.world.npcs[npc_id]
    resolved = equipped_disguise(ctx.session.player, ctx.disguises)
    if resolved:
        from .equipment import resolve_disguised_tail_pierce
        from .law import wanted_consequences
        from .stealth import PierceStage
        stage = resolve_disguised_tail_pierce(
            ctx.session.player,
            target,
            resolved[1],
            wanted_bonus=wanted_consequences(ctx.session.player.wanted_level).disguise_perception_bonus,
            stealth=ctx.stealth,
        )
        if stage == PierceStage.CHALLENGE:
            ctx.session.player.tailing_state = None
            await post_display(ctx, f"{semantic_span(target.name, 'npc')} turns and challenges you. You break off the tail.", msg_type=MessageType.WARNING)
            return failure("tail_challenged")
        if stage == PierceStage.EXPOSED:
            await play_sound(ctx, "alert", 0.6)
            ctx.session.player.tailing_state = None
            _confiscate_disguise(ctx)
            await post_display(ctx, f"{semantic_span(target.name, 'npc')} sees through your disguise. The disguise is confiscated.", msg_type=MessageType.WARNING)
            return failure("tail_exposed")
        if stage == PierceStage.SUSPICION:
            await post_display(ctx, f"{semantic_span(target.name, 'npc')} studies you, but keeps moving.", msg_type=MessageType.WARNING)
    log_event(ctx, f"You began tailing {target.name}.")
    await post_display(ctx, loc("cmd_tail.start").format(name=semantic_span(target.name, "npc")), msg_type=MessageType.PLAYER_ACTION)
    return success(
        "tail",
        facts={"tailing"},
        tutorial_event={"verb": "tail", "target": cmd.direct_obj or ""},
    )


async def cmd_stop_tail(ctx: CommandContext, cmd: Command):
    from .equipment import end_tailing

    if end_tailing(ctx.session.player):
        await post_display(ctx, loc("cmd_stop_tail.done"), msg_type=MessageType.PLAYER_ACTION)
        return success(
            "stop",
            facts={"tail_broken_off"},
            tutorial_event={"verb": "stop", "target": "tail"},
        )
    await post_display(ctx, loc("cmd_stop_tail.inactive"), msg_type=MessageType.PLAYER_ACTION)
    return failure("stop_tail_inactive")


async def cmd_hide(ctx: CommandContext, cmd: Command):
    ctx.session.player.activity_counters["times_hidden"] = ctx.session.player.activity_counters.get("times_hidden", 0) + 1
    room = _room(ctx)
    from .stealth_requirements import hide_requirement_for_room
    hide_succeeded = ctx.session.player.stealth_skill >= hide_requirement_for_room(room)
    ctx.session.player.hidden = hide_succeeded
    if hide_succeeded:
        log_event(ctx, "You found a place to hide.")
        await post_display(ctx, loc("cmd_hide.success"), msg_type=MessageType.PLAYER_ACTION)
        await play_sound(ctx, "hide", 0.5)
        grow_stat(ctx.session.player, "stealth_skill", STAT_GAIN_STEALTH_HIDE)
        return success(
            "hide",
            facts={"hidden"},
            tutorial_event={"verb": "hide"},
        )
    else:
        _raise_nearby_suspicion(ctx, SUSPICION_FAILED_STEALTH)
        log_event(ctx, "You failed to hide cleanly.")
        await post_display(ctx, loc("cmd_hide.fail"), msg_type=MessageType.PLAYER_ACTION)
        return failure("hide_failed")


async def cmd_unhide(ctx: CommandContext, cmd: Command):
    if not ctx.session.player.hidden:
        await post_display(ctx, loc("cmd_unhide.inactive"), msg_type=MessageType.PLAYER_ACTION)
        return failure("unhide_inactive")
    ctx.session.player.hidden = False
    log_event(ctx, "You step out of hiding.")
    await play_sound(ctx, "hide", 0.5)
    await post_display(ctx, "You step out into the open.", msg_type=MessageType.PLAYER_ACTION)
    return success("unhide", facts={"unhidden"})


async def _purchase_newspaper(ctx: CommandContext, vendor_name: str, *, active=None) -> bool:
    from .newspaper import NEWSPAPER_COST_FABI, purchase_newspaper

    room = _room(ctx)
    if not room:
        await post_display(ctx, "You are nowhere.", msg_type=MessageType.PLAYER_ACTION)
        return False

    current_day = ctx.shared.game_time.day
    if ctx.session.player.last_newspaper_day == current_day:
        await post_display(ctx, "You have already purchased a newspaper today.", msg_type=MessageType.WARNING)
        return False

    if not can_afford_fabi(ctx.session.player, NEWSPAPER_COST_FABI):
        await post_display(ctx, f"A newspaper costs {NEWSPAPER_COST_FABI} fabi. You have {wallet_fabi_value(ctx.session.player)} fabi-value.", msg_type=MessageType.PLAYER_ACTION)
        return False

    room_id = room.id.lower()
    player_district = room_id.split("_")[0] if "_" in room_id else room_id
    from .rumors import newspaper_projections
    all_rumors, active_rumor_ids, rumour_mill = newspaper_projections(ctx.shared, ctx.session.player)
    world_decisions = list(ctx.shared.world_decisions) if hasattr(ctx.shared, "world_decisions") else []
    named_npc_deaths = {
        npc_id: named_npc_death_record_to_dict(record)
        for npc_id, record in sorted(getattr(ctx.shared, "named_npc_deaths", {}).items())
    }

    try:
        newspaper = await purchase_newspaper(
            player=ctx.session.player,
            game_day=current_day,
            player_district=player_district,
            all_rumors=all_rumors,
            active_rumor_ids=active_rumor_ids,
            world_decisions=world_decisions,
            named_npc_deaths=named_npc_deaths,
            rumour_mill=rumour_mill,
            ai_client=getattr(ctx.shared, "ai_client", None),
            active=active,
            shared=ctx.shared,
        )
    except Exception:
        await post_display(ctx, "The newspaper press cannot produce an issue right now.", msg_type=MessageType.PLAYER_ACTION)
        return False
    if newspaper is None:
        await post_display(ctx, "You cannot purchase a newspaper right now.", msg_type=MessageType.PLAYER_ACTION)
        return False
    log_event(ctx, f"You bought a newspaper from {vendor_name} for {NEWSPAPER_COST_FABI} fabi.")
    await post_display(ctx, f"You bought a newspaper from {vendor_name} for {NEWSPAPER_COST_FABI} fabi.", msg_type="system")
    await play_sound(ctx, "coin_clink", 0.7)
    return True


async def cmd_plant(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_plant.no_target"), msg_type=MessageType.PLAYER_ACTION)
        return failure("plant_no_target")
    item = find_item_exact(cmd.direct_obj, ctx.session.player.inventory)
    if not item:
        await post_display(ctx, loc("cmd_plant.not_held"), msg_type=MessageType.PLAYER_ACTION)
        return failure("plant_not_held")
    target = cmd.indirect_obj or cmd.preposition or ""
    if not target:
        await post_display(ctx, "Plant this on whom?", msg_type=MessageType.PLAYER_ACTION)
        return failure("plant_missing_target")
    room = _room(ctx)

    from .constants import get_season
    season = get_season(ctx.shared.game_time.day)

    target_npc = None
    target_perception = 50
    if target:
        npc_id = resolve_npc(ctx, target)
        if npc_id:
            target_npc = ctx.shared.world.npcs.get(npc_id)
            if target_npc:
                target_perception = target_npc.perception

    observers = []
    if room:
        for npc_id in room.npcs:
            npc = ctx.shared.world.npcs.get(npc_id)
            if npc and npc != target_npc:
                observers.append(npc)

    success, _ = ctx.stealth.stealth_check(
        player_stealth=ctx.session.player.stealth_skill,
        target_perception=target_perception,
        difficulty_modifier=5,
        room_indoors=room.indoors if room else False,
        observers=observers,
        target_npc=target_npc,
        season=season,
        player_hidden=ctx.session.player.hidden,
        hunger=ctx.session.player.hunger,
    )

    if not success:
        _raise_nearby_suspicion(ctx, SUSPICION_FAILED_STEALTH)
        if target_npc:
            target_npc.suspicion = min(100, getattr(target_npc, "suspicion", 0) + 20)
        log_event(ctx, f"You tried to plant {item.name} but were noticed.")
        await post_display(ctx, loc("cmd_plant.spotted").format(name=item.name), msg_type=MessageType.WARNING)
        return

    ctx.session.player.inventory.remove(item)
    invalidate_disguise_if_support_lost(ctx.session.player, item)
    ctx.session.player.planted_evidence.append(
        {
            "room_id": room.id if room else ctx.session.player.current_room,
            "item_id": item.id,
            "item_name": item.name,
            "target": target,
        }
    )
    log_event(ctx, f"You planted {item.name} for {target or 'whoever finds it'}.")
    await post_display(ctx, loc("cmd_plant.success").format(name=item.name), msg_type="discovery")

    if room:
        current_day = ctx.shared.game_time.day
        for npc_id in room.npcs:
            npc = ctx.shared.world.npcs.get(npc_id)
            if npc:
                npc_memory_system.record_interaction(
                    npc, ctx.session.player.name, "observed_suspicious_behavior",
                    {"action": "plant", "item": item.name, "target": target}, current_day
                )


def _death_journal_claimed(event_id: str) -> bool:
    from .auth import _get_db
    db = _get_db()
    claim = db.get_death_journal_claim(event_id) if db is not None else None
    return claim is not None


async def _read_death_journal(ctx: CommandContext, cmd: Command):
    room = ctx.room
    entries = ctx.shared.death_journals.get(room.id, []) if room else []
    if not entries:
        await post_display(ctx, loc("cmd_read.no_journal"), msg_type=MessageType.PLAYER_ACTION)
        return failure("read_journal_empty")
    direct = cmd.direct_obj or ""
    chosen = next((e for e in entries if e.get("event_id") and e["event_id"] in direct), None)
    query = None
    if chosen is None:
        query = _normalize_text(direct.replace("journal", " ").replace("notebook", " "))
    if query:
        matches = [e for e in entries if query in _normalize_text(e["character_name"])]
        if len(matches) == 1:
            chosen = matches[0]
        elif len(matches) > 1:
            names = ", ".join(f"{e['character_name']} (Day {e['day_of_death']})" for e in matches)
            await post_display(ctx, loc("cmd_read.journal_ambiguous").format(names=names), msg_type=MessageType.PLAYER_ACTION)
            return failure("read_journal_ambiguous")
        else:
            await post_display(ctx, loc("cmd_read.journal_no_match").format(name=cmd.direct_obj), msg_type=MessageType.PLAYER_ACTION)
            return failure("read_journal_no_match")
    elif chosen is None:
        chosen = entries[-1]
    event_id = chosen.get("event_id", "")
    if event_id:
        from .lifecycle import claim_death_journal
        claimed = claim_death_journal(ctx.session, ctx.shared, event_id)
        if claimed is None:
            log_event(ctx, f"You read the journal of {chosen['character_name']}, but its knowledge is already claimed.")
            await post_display(ctx, f"The journal of {chosen['character_name']} yields nothing new; its knowledge has already been claimed.", msg_type=MessageType.DISCOVERY)
            return success("read_journal", facts={"journal_absorbed"})
        added = len(claimed.get("conversations", []))
    else:
        added = absorb_death_journal(ctx.session.player.conversation_history, chosen)
    log_event(ctx, f"You read the journal of {chosen['character_name']}, recovering {added} notes.")
    await post_display(ctx, loc("cmd_read.journal_absorbed").format(name=chosen["character_name"], n=added), msg_type=MessageType.DISCOVERY)
    return success("read_journal", facts={"journal_absorbed"})


async def cmd_read(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        from .equipment import ensure_inventory_identity
        ensure_inventory_identity(ctx.session.player)
        rows = []
        for item in ctx.session.player.inventory:
            if item.readable_text:
                rows.append(_action_row(item))
        if getattr(ctx.session.player, "newspapers", None):
            rows.append(_action_row({
                "identity": "newspaper",
                "name": "newspaper",
                "description": "A purchased newspaper.",
            }))
        room = ctx.room
        if room:
            for entry in ctx.shared.death_journals.get(room.id, []) or []:
                event_id = entry.get("event_id", "")
                claimed = bool(event_id) and _death_journal_claimed(event_id)
                rows.append(_action_row({
                    "event_id": event_id,
                    "name": f"{entry.get('character_name', 'unknown')}'s journal",
                    "description": f"The journal of {entry.get('character_name', 'unknown')}, who died on Day {entry.get('day_of_death', '?')}.",
                }, disabled=claimed, disabled_reason="knowledge already claimed" if claimed else ""))
        if not rows:
            await post_display(ctx, "You have nothing to read.", msg_type=MessageType.PLAYER_ACTION)
            return failure("read_no_candidates")
        await _open_item_action_chooser(ctx, "read", loc("cmd_read.no_target"), rows)
        return success("read_chooser", facts={"chooser_opened"})
    target = cmd.direct_obj.lower()
    from .equipment import ensure_inventory_identity
    ensure_inventory_identity(ctx.session.player)
    item = find_item_exact(cmd.direct_obj, ctx.session.player.inventory)
    if item is None and ("journal" in target or "notebook" in target):
        return await _read_death_journal(ctx, cmd)
    if item is None and target == "newspaper":
        from .newspaper import format_newspaper_for_display
        if not ctx.session.player.newspapers:
            await post_display(ctx, "You have no purchased newspaper to read.", msg_type=MessageType.PLAYER_ACTION)
            return failure("read_newspaper_empty")
        await post_display(ctx, format_newspaper_for_display(ctx.session.player.newspapers[-1]), msg_type=MessageType.DISCOVERY)
        return success("read", facts={"newspaper_read"})
    if not item:
        await post_display(ctx, loc("cmd_read.not_held"), msg_type=MessageType.PLAYER_ACTION)
        return failure("read_not_held")
    if item.id == "newspaper":
        from .newspaper import format_newspaper_for_display
        if not ctx.session.player.newspapers:
            await post_display(ctx, "You have no purchased newspaper to read.", msg_type=MessageType.PLAYER_ACTION)
            return failure("read_newspaper_empty")
        await post_display(ctx, format_newspaper_for_display(ctx.session.player.newspapers[-1]), msg_type=MessageType.DISCOVERY)
        return success("read", facts={"newspaper_read"})
    if not item.readable_text:
        await post_display(ctx, loc("cmd_read.nothing_written"), msg_type=MessageType.PLAYER_ACTION)
        return failure("read_nothing_written")

    effects = getattr(item, 'on_read_effects', {}) or {}
    read_flag = f"testimony_read:{item.id}"
    first_read = read_flag not in ctx.session.player.flags
    if item.is_map and item.map_districts:
        for room_id, room in ctx.shared.world.rooms.items():
            if room.district in item.map_districts and room_id not in ctx.session.player.map_revealed:
                ctx.session.player.map_revealed.append(room_id)
    if effects and (not effects.get('once') or first_read):
        if 'morale_penalty' in effects:
            ctx.session.player.morale = max(0, ctx.session.player.morale - effects['morale_penalty'])
        if 'morale_bonus' in effects:
            ctx.session.player.morale = min(100, ctx.session.player.morale + effects['morale_bonus'])
        if 'trust_change' in effects:
            for trust_key, delta in effects['trust_change'].items():
                change_trust(ctx.session.player.trust, trust_key, delta)
        if 'unlock_contact' in effects:
            contact = effects['unlock_contact']
            if contact not in ctx.session.player.flags:
                ctx.session.player.flags.append(contact)
        if 'unlock_mission' in effects:
            mission_id = effects['unlock_mission']
            if mission_id not in ctx.session.player.flags:
                ctx.session.player.flags.append(f"mission_available_{mission_id}")
        patrol_intel = effects.get('patrol_intel')
        if patrol_intel:
            source = str(patrol_intel.get('source', item.id))
            ctx.session.player.journal_intel.setdefault(source, {})['patrol testimony'] = {
                'day': ctx.shared.game_time.day,
                'source': source,
                'text': item.readable_text,
            }
    if effects.get('once') and first_read:
        ctx.session.player.flags.append(read_flag)

    from .journal import record_testimony_read
    record_testimony_read(ctx.session.player, item, ctx.shared.game_time.day)

    await post_display(ctx, item.readable_text, msg_type=MessageType.DISCOVERY)
    return success("read", facts={"read_document"}, tutorial_event={"verb": "read", "target": item.id})


async def cmd_journal(ctx: CommandContext, cmd: Command):
    if cmd.direct_obj:
        from .save_manager import get_archived_journal
        character_name = cmd.direct_obj
        archived = get_archived_journal(character_name, ctx.shared)
        if not archived:
            await post_display(ctx, loc("cmd_journal.no_archive").format(name=character_name), msg_type=MessageType.PLAYER_ACTION)
            return
        lines = [f"=== Archived Journal: {character_name} ===", ""]
        for event in archived[-20:]:
            if isinstance(event, dict):
                lines.append(str(event.get("text", event)))
            else:
                lines.append(str(event))
        await post_display(ctx, "\n".join(lines), msg_type=MessageType.DISCOVERY)
        return success("journal_archive", facts={"journal_archive_read"})

    from .journal import format_testimony_summary
    from .popup_payloads import journal_payload, send_popup
    ctx.session.set_open_popup("journal", {})
    payload = journal_payload(ctx, ctx.session.open_popup["generation"])
    await send_popup(ctx.session, "journal_menu", payload)
    await post_display(ctx, format_testimony_summary(ctx.session.player), msg_type=MessageType.DISCOVERY)
    return success("journal", facts={"journal_opened"}, tutorial_event={"verb": "journal"})


_USAGE = {verb: definition["help"] for verb, definition in _COMMAND_DEFS.items() if definition["help"]}


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
    if verb in ("eat", "remove", "drop", "sell", "read", "open", "mod weapon"):
        return ("You carry: " + ", ".join(inv_items) + ".") if inv_items else "You carry nothing."
    if verb in ("go",):
        return ("Exits: " + ", ".join(exits) + ".") if exits else "No way out from here."
    return ""


async def cmd_help(ctx: CommandContext, cmd: Command):
    arg = cmd.raw.lower().strip()
    arg = arg[4:].strip() if arg.startswith("help") else ""
    if arg == "start":
        await post_display(ctx, loc("cmd_help.start"), msg_type=MessageType.SYSTEM)
        return
    if arg:
        match = next((k for k in sorted(_USAGE, key=len, reverse=True) if arg.startswith(k)), None)
        if match:
            text = f"{match.upper()} - {_USAGE[match]}"
            targets = _help_targets(ctx, match)
            if targets:
                text += "\n" + targets
            await post_display(ctx, text, msg_type=MessageType.SYSTEM)
            return
    await post_display(ctx, loc("cmd_help.text"), msg_type=MessageType.SYSTEM)


async def cmd_quit(ctx: CommandContext, cmd: Command):
    from .lifecycle import close_session_cleanly
    await close_session_cleanly(ctx.session_manager, ctx.session, send_goodbye=True)
    return success("quit")


async def cmd_skip_tutorial(ctx: CommandContext, cmd: Command):
    player = ctx.session.player
    
    if not player.in_tutorial:
        await post_display(ctx, loc("cmd_skip_tutorial.not_in_tutorial"), msg_type=MessageType.PLAYER_ACTION)
        return
    
    if "tutorial_skip_pending" in player.flags:
        player.flags.remove("tutorial_skip_pending")
        from .tutorial import _send_graduation_cue, graduate_tutorial_player
        message = loc("cmd_skip_tutorial.complete")
        await graduate_tutorial_player(ctx, message, send_handoff=False)
        
        await cmd_look(ctx, Command(verb="look"))
        
        if hasattr(ctx, 'session_manager') and ctx.session_manager and hasattr(ctx.session_manager, '_send_map_data'):
            await ctx.session_manager._send_map_data(ctx.session)
        await _send_graduation_cue(ctx, message)
        return
    
    player.flags.append("tutorial_skip_pending")
    await post_display(ctx, loc("cmd_skip_tutorial.confirm"), msg_type="tutorial")


async def consume_food_item(ctx: CommandContext, item):
    if not item:
        await post_display(ctx, loc("cmd_eat.not_held"), msg_type=MessageType.PLAYER_ACTION)
        return failure("eat_not_held")
    food_value = item.food_value
    morale_restore = item.morale_restore
    if food_value == 0:
        await post_display(ctx, loc("cmd_eat.not_food"), msg_type=MessageType.PLAYER_ACTION)
        return failure("eat_not_food")
    ctx.session.player.inventory.remove(item)
    await _refresh_inventory_if_open(ctx)
    hunger_before = ctx.session.player.hunger
    morale_before = ctx.session.player.morale
    ctx.session.player.hunger = min(100, ctx.session.player.hunger + food_value)
    ctx.session.player.morale = min(100, ctx.session.player.morale + morale_restore)
    log_event(ctx, f"You ate {item.name}.")
    await play_sound(ctx, "eat", 0.5)
    feedback = loc("cmd_eat.success").format(name=semantic_span(item.name, "item"))
    lines = [feedback]
    if ctx.session.player.hunger != hunger_before:
        lines.append(f"Hunger: {hunger_before} → {ctx.session.player.hunger}")
    if ctx.session.player.morale != morale_before:
        lines.append(f"Morale: {morale_before} → {ctx.session.player.morale}")
    await post_display(ctx, "\n".join(lines), msg_type=MessageType.PLAYER_STATUS)
    return success("eat", facts={"food_eaten"}, tutorial_event={"verb": "eat", "target": item.id or item.name})


async def cmd_eat(ctx: CommandContext, cmd: Command):
    from .equipment import ensure_inventory_identity
    ensure_inventory_identity(ctx.session.player)
    candidates = [_action_row(item) for item in ctx.session.player.inventory if item.food_value > 0]
    if not candidates:
        await post_display(ctx, "You have nothing to eat.", msg_type=MessageType.PLAYER_ACTION)
        return failure("eat_no_candidates")
    await _open_item_action_chooser(ctx, "eat", loc("cmd_eat.no_target"), candidates)
    from .tutorial import _send_popup_hint
    await _send_popup_hint(ctx)
    return success("eat_chooser", facts={"chooser_opened"})


async def cmd_bond(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_bond.no_target"), msg_type=MessageType.PLAYER_ACTION)
        return
    npc_id = resolve_npc(ctx, cmd.direct_obj)
    if not npc_id:
        await post_display(ctx, loc("cmd_bond.not_here"), msg_type=MessageType.PLAYER_ACTION)
        return

    npc = ctx.shared.world.npcs[npc_id]
    player = ctx.session.player
    current_day = ctx.shared.game_time.day

    is_tutorial = "tutorial_complete" not in player.flags

    trust_score = get_role_trust(player.trust, npc.faction, npc.role)

    if not is_tutorial and trust_score < 30:
        personality = (npc.personality or "").lower()
        if "brave" in personality:
            await post_display(ctx, loc("cmd_bond.rejected_brave"), msg_type=MessageType.NPC_DIALOGUE)
        elif "coward" in personality or "fearful" in personality or "timid" in personality:
            await post_display(ctx, loc("cmd_bond.rejected_cowardly"), msg_type=MessageType.NPC_DIALOGUE)
        elif "corrupt" in personality or "greedy" in personality:
            await post_display(ctx, loc("cmd_bond.rejected_corrupt"), msg_type=MessageType.NPC_DIALOGUE)
        elif "honest" in personality:
            await post_display(ctx, loc("cmd_bond.rejected_honest"), msg_type=MessageType.NPC_DIALOGUE)
        else:
            await post_display(ctx, loc("cmd_bond.rejected_default"), msg_type=MessageType.NPC_DIALOGUE)
        return

    if not is_tutorial:
        hostility_check = _check_npc_hostility(npc, player.name, current_day, npc.faction)
        if hostility_check:
            await post_display(ctx, hostility_check, msg_type=MessageType.NPC_DIALOGUE)
            return

    action = cmd.preposition or cmd.indirect_obj or "share_meal"
    if action == "share_meal":
        food_items = [item for item in ctx.session.player.inventory if item.food_value > 0]
        if not food_items:
            await post_display(ctx, loc("cmd_bond.no_food"), msg_type=MessageType.PLAYER_ACTION)
            return

        food = food_items[0]
        preference_bonus = _check_food_preference(npc, food)
        friendship_gain = 15 + preference_bonus

        ctx.session.player.inventory.remove(food)
        _modify_relationship(ctx, npc_id, {"friendship": friendship_gain, "indebtedness": 5})
        log_event(ctx, f"You shared a meal with {npc.name}.")
        await post_display(ctx, loc("cmd_bond.shared_meal").format(name=semantic_span(food.name, "item"), npc=semantic_span(npc.name, "npc")), msg_type="npc_dialogue")

        food_culture = getattr(food, 'culture', '')
        if food_culture == "japanese" and npc.faction in ("ccp", "civilian"):
            change_trust(
                player.trust,
                npc.faction,
                -2,
                last_trust_interaction=player.last_trust_interaction,
                current_day=current_day,
                player_flags=player.flags,
            )
            await post_display(ctx, loc("cmd_bond.japanese_food_trust_loss").format(npc=npc.name), msg_type="npc_dialogue")
            log_event(ctx, f"Sharing Japanese food with {npc.name} cost faction trust.")

        current_day = ctx.shared.game_time.day
        npc_memory_system.record_interaction(
            npc, ctx.session.player.name, "shared_meal",
            {"food": food.name, "preference_bonus": preference_bonus}, current_day
        )
        await _maybe_grant_testimony_keepsake(ctx, npc)
        return success(
            "bond",
            facts={"meal_shared"},
            tutorial_event={"verb": "bond", "target": npc.name},
        )

    elif action == "gift":
        if not cmd.direct_obj:
            await post_display(ctx, loc("cmd_bond.no_gift"), msg_type=MessageType.PLAYER_ACTION)
            return
        gift_item = find_item_by_name(cmd.direct_obj, ctx.session.player.inventory)
        if not gift_item:
            await post_display(ctx, loc("cmd_bond.not_held"), msg_type=MessageType.PLAYER_ACTION)
            return

        ctx.session.player.inventory.remove(gift_item)
        _modify_relationship(ctx, npc_id, {"friendship": 10, "indebtedness": 3})
        log_event(ctx, f"You gave {gift_item.name} to {npc.name}.")
        await post_display(ctx, f"You give {gift_item.name} to {npc.name}. They seem appreciative.", msg_type="npc_dialogue")

        current_day = ctx.shared.game_time.day
        npc_memory_system.record_interaction(
            npc, ctx.session.player.name, "gift",
            {"item": gift_item.name}, current_day
        )


async def cmd_say(ctx: CommandContext, cmd: Command):
    message = cmd.raw[4:] if cmd.raw.startswith("say ") else ""
    if not message:
        await post_display(ctx, loc("cmd_say.no_message"), msg_type=MessageType.PLAYER_ACTION)
        return
    await broadcast_to_room(ctx, loc("social.say").format(name=ctx.session.player.name, message=message), exclude_username=ctx.session.username, msg_type="social")
    await post_display(ctx, loc("social.say_self").format(message=message), msg_type="social")


async def cmd_whisper(ctx: CommandContext, cmd: Command):
    parts = cmd.raw.split()
    if len(parts) < 3:
        await post_display(ctx, loc("cmd_whisper.no_target"), msg_type=MessageType.PLAYER_ACTION)
        return

    target_name = parts[1]
    message = " ".join(parts[2:]) if len(parts) > 2 else ""

    target_session = _find_player_in_room(ctx, target_name)

    if not target_session:
        await post_display(ctx, f"{target_name} is not here.", msg_type=MessageType.PLAYER_ACTION)
        return

    await target_session.send_display(loc("social.whisper").format(name=ctx.session.player.name, message=message), msg_type=MessageType.SOCIAL)
    await post_display(ctx, loc("social.whisper_self").format(name=target_session.player.name, message=message), msg_type="social")


async def cmd_give(ctx: CommandContext, cmd: Command):
    item_name = cmd.direct_obj if isinstance(cmd.direct_obj, str) else None
    target_name = cmd.indirect_obj if isinstance(cmd.indirect_obj, str) else None
    if not item_name or not target_name:
        parts = cmd.raw.split()
        if len(parts) < 4 or "to" not in parts:
            await post_display(ctx, loc("cmd_give.usage"), msg_type=MessageType.PLAYER_ACTION)
            return failure("give_usage")
        to_index = parts.index("to")
        item_name = item_name or parts[1]
        target_name = target_name or (parts[to_index + 1] if to_index + 1 < len(parts) else "")

    item = find_item_by_name(item_name, ctx.session.player.inventory)
    if not item and isinstance(cmd.direct_obj, str):
        legacy_item_name = cmd.direct_obj.split()[0]
        item = find_item_by_name(legacy_item_name, ctx.session.player.inventory)
    if not item:
        await post_display(ctx, f"You don't have {item_name}.", msg_type=MessageType.PLAYER_ACTION)
        return failure("give_not_held")
    
    target_session = _find_player_in_room(ctx, target_name)
    if target_session:
        ctx.session.player.inventory.remove(item)
        invalidate_disguise_if_support_lost(ctx.session.player, item)
        target_session.player.inventory.append(item)
        log_event(ctx, f"You gave {item.name} to {target_session.player.name}.")
        await post_display(ctx, loc("cmd_give.success").format(item=semantic_span(item.name, "item"), target=semantic_span(target_session.player.name, "npc")), msg_type=MessageType.PLAYER_ACTION)
        await play_sound(ctx, "coin_clink", 0.7)
        await target_session.send_display(loc("cmd_give.received").format(name=semantic_span(ctx.session.player.name, "npc"), item=semantic_span(item.name, "item")), msg_type=MessageType.SOCIAL)
        return success("give", facts={"item_given"})

    npc_id = resolve_npc(ctx, target_name)
    if npc_id:
        npc = ctx.shared.world.npcs.get(npc_id)
        if npc:
            ctx.session.player.inventory.remove(item)
            invalidate_disguise_if_support_lost(ctx.session.player, item)
            await _refresh_inventory_if_open(ctx)
            if not hasattr(npc, 'inventory'):
                npc.inventory = []
            npc.inventory.append(item)
            log_event(ctx, f"You gave {item.name} to {npc.name}.")

            is_contraband = getattr(item, 'contraband_risk', False) or getattr(item, 'evidence', False)
            if is_contraband:
                npc_role = getattr(npc, 'role', '') or ''
                npc_faction = getattr(npc, 'faction', '') or ''
                if npc_faction == 'kempeitai' or (npc_faction == 'civilian' and npc_role not in ('underworld', 'smuggler', 'informant')):
                    await post_display(ctx, f"{npc.name} stares at the {item.name} and calls for the authorities!", msg_type="event")
                    _record_crime(ctx, increase=1)
                    npc.inventory.remove(item)
                    log_event(ctx, f"{npc.name} reported contraband! Wanted +1.")
                else:
                    bonus = 10 if npc_faction == 'green_gang' else 5
                    await post_display(ctx, f"{npc.name} pockets the {item.name} with a knowing nod.", msg_type="social")
                    _modify_relationship(ctx, npc_id, {"friendship": bonus, "trust": bonus})
                    log_event(ctx, f"Gave contraband to {npc.name}. Friendship +{bonus}.")
            else:
                await post_display(ctx, loc("cmd_give.success").format(item=semantic_span(item.name, "item"), target=semantic_span(npc.name, "npc")), msg_type=MessageType.PLAYER_ACTION)
                await play_sound(ctx, "coin_clink", 0.7)
            current_day = ctx.shared.game_time.day
            npc_memory_system.record_interaction(
                npc, ctx.session.player.name, "gave_gift",
                {"item": item.name}, current_day
            )
            _modify_relationship(ctx, npc_id, {"friendship": 5})
            await _handle_mission_objectives(ctx, "deliver_to_npc", npc_id, item_id=item.id)
            return success(
                "give",
                facts={"item_given"},
                tutorial_event={"verb": "give", "target": item.id or item.name, "indirect": target_name},
            )
    
    await post_display(ctx, f"{target_name} is not here.", msg_type=MessageType.PLAYER_ACTION)
    return failure("give_target_not_here")


async def cmd_attack(ctx: CommandContext, cmd: Command):
    ctx.session.player.activity_counters["attacks_performed"] = ctx.session.player.activity_counters.get("attacks_performed", 0) + 1
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_attack.no_target"), msg_type=MessageType.PLAYER_ACTION)
        return

    room = _room(ctx)
    if room and room.safe_room:
        await post_display(ctx, loc("cmd_attack.safe_room"), msg_type="error")
        return

    weapon = _get_equipped_weapon(ctx.session.player)
    courage_mult = courage_multiplier_for(weapon)

    target_name = cmd.direct_obj

    target_session = _find_player_in_room(ctx, target_name)
    if target_session:
        await _attack_player(ctx, target_session, courage_mult)
        return

    npc_id = resolve_npc(ctx, target_name)
    if npc_id:
        return await _attack_npc(ctx, npc_id, courage_mult)

    await post_display(ctx, loc("cmd_attack.not_here").format(name=target_name), msg_type=MessageType.PLAYER_ACTION)


def _get_equipped_weapon(player: PlayerData) -> Optional[Item]:
    return equipped_weapon(player)


def _get_worn_armour(player: PlayerData) -> Optional[Item]:
    from .equipment import equipped_item
    item = equipped_item(player, getattr(player, "worn_armour_id", ""))
    return item if item and item.is_armour else None


def _raise_nearby_suspicion(ctx: CommandContext, amount: int) -> None:
    room = _room(ctx)
    if not room:
        return
    for npc_id in room.npcs:
        npc = ctx.shared.world.npcs.get(npc_id)
        if npc:
            npc.suspicion = min(100, npc.suspicion + amount)


def _adjust_shared_influence(shared: SharedWorldState, faction: str, delta: int, room_id: str = "") -> None:
    district = ""
    if room_id and hasattr(shared, 'world'):
        room = shared.world.get_room(room_id)
        if room and hasattr(room, 'district'):
            district = room.district
    shared.ccp_influence, shared.gmd_influence = adjust_influence(
        shared.ccp_influence, shared.gmd_influence, faction, delta,
        district=district, shared=shared
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
    await post_display(ctx, loc("combat.npc_falls").format(name=semantic_span(npc.name, "npc"), parts=', '.join(parts)), msg_type="combat_narration")

    from .victory import _select_template
    from .newspaper import generate_newspaper

    obit_templates = _get_obituary_templates()

    obit_condition = {
        "faction": npc.faction if hasattr(npc, 'faction') else "civilian",
        "cause": "assassination",
        "historical": True,
    }

    best_template = None
    best_score = -1
    for template in obit_templates:
        cond = template.get("condition", {})
        if not isinstance(cond, dict):
            cond = {"default": True}
        score = 0
        if cond.get("default"):
            score = 0
        else:
            for key, val in cond.items():
                if key == "faction" and val == obit_condition.get("faction"):
                    score += 2
                elif key == "cause" and val == obit_condition.get("cause"):
                    score += 1
                elif key == "historical" and val == obit_condition.get("historical"):
                    score += 1
        if score > best_score:
            best_score = score
            best_template = template

    obituary_text = best_template.get("text", "{name} has died.") if best_template else f"{npc.name} has died."
    obituary_text = obituary_text.format(
        name=npc.name,
        date=f"Day {ctx.shared.game_time.day}",
        cause="assassination",
        deed=f"eliminated by unknown agents",
    )


async def _attack_npc(ctx: CommandContext, npc_id: str, courage_mult: float = 1.0):
    if is_named_npc_dead(ctx.shared, npc_id):
        await post_display(ctx, loc("cmd_attack.already_dead").format(name=npc_id), msg_type=MessageType.PLAYER_ACTION)
        return failure("attack_already_dead")

    npc = ctx.shared.world.npcs.get(npc_id)
    if not npc:
        await post_display(ctx, loc("cmd_attack.not_here").format(name=npc_id), msg_type=MessageType.PLAYER_ACTION)
        return failure("attack_no_target")

    player = ctx.session.player
    weapon = _get_equipped_weapon(player)
    armour = _get_worn_armour(player)
    room = _room(ctx)
    from .pathfinding import emit_sound
    attack_kind = "gunshot" if getattr(weapon, "weapon_type", "") == "firearm" else "melee"
    attack_sound = emit_sound(
        room.id if room else "",
        attack_kind,
        intensity=5 if attack_kind == "gunshot" else 2,
        weapon=weapon,
        hidden=player.hidden,
        weather=getattr(ctx.shared, "weather", "clear"),
        game_time=ctx.shared.game_time,
        range_multiplier=courage_mult,
        source_actor_id=player.username,
    )

    if (getattr(player, "in_tutorial", False)
            and getattr(player, "tutorial_stage", 0) == 22):
        await post_display(ctx, "You need a clearer read on the soldier before you commit.", msg_type=MessageType.TUTORIAL)
        from .tutorial import _send_tutorial_hint, STAGE_ACTIONS as _AS_STAGES
        _as_action = _AS_STAGES.get(22, {})
        if _as_action:
            await _send_tutorial_hint(ctx, 22, _as_action, force_immediate=True)
        return

    if (getattr(player, "in_tutorial", False)
            and getattr(player, "tutorial_stage", 0) in (30, 31, 32, 33, 34)
            and getattr(npc, "id", "").endswith("tutorial_kempeitai_officer")):
        await post_display(ctx, "The officer is not your target. Stay focused on the mission.", msg_type=MessageType.TUTORIAL)
        from .tutorial import _send_tutorial_hint, STAGE_ACTIONS as _OS_STAGES
        stage = player.tutorial_stage
        _os_action = _OS_STAGES.get(stage, {})
        if _os_action:
            await _send_tutorial_hint(ctx, stage, _os_action, force_immediate=True)
        return

    if getattr(player, "in_tutorial", False) and not getattr(player, "tutorial_death_warning_shown", False):
        from .combat import compute_effective_courage, counter_damage_for
        effective, _parts, _defence, _morale = compute_effective_courage(
            player.courage, weapon, player.hidden, None, player.morale, courage_multiplier=courage_mult,
        )
        worst_case = counter_damage_for(npc.authority - effective)
        if worst_case >= player.health:
            player.tutorial_death_warning_shown = True
            await post_display(ctx, "A failed attack may kill you permanently.", msg_type="warning")

    result = resolve_attack(
        attacker_courage=player.courage,
        attacker_weapon=weapon,
        target_authority=npc.authority,
        target_armour=None,
        attacker_hidden=player.hidden,
        attacker_morale=player.morale,
        courage_multiplier=courage_mult,
    )
    result.sound_event = attack_sound

    if hasattr(result, 'breakdown') and result.breakdown:
        await post_display(ctx, f"[{result.breakdown}]", msg_type="combat")

    for msg in result.messages:
        await post_display(ctx, msg, msg_type="combat")

    current_day = ctx.shared.game_time.day

    npc_memory_system.record_interaction(
        npc, player.name, "attacked",
        {"damage": result.target_damage, "won": result.won}, current_day
    )
    
    if result.won:
        from .npc import trigger_npc_distress
        await trigger_npc_distress(npc, player, room, ctx.shared.world, ctx, result.sound_event)
        npc.hp = max(0, npc.hp - result.target_damage)
        if attack_kind == "melee":
            await play_sound(ctx, "melee_hit", 0.6)
        if npc.hp <= 0:
            from .tutorial import tutorial_blocks_world_events
            tutorial_kill = npc_id.startswith("tut_") or tutorial_blocks_world_events(ctx.session.player)

            log_event(ctx, f"You eliminated {format_bold(npc.name)}.")
            await apply_action_trust(ctx, f"kill_{npc.faction}.{npc.role}", room_npcs(ctx))

            if npc.faction == "kempeitai":
                _record_crime(ctx, publish_rumor=not tutorial_kill and not is_transient_patrol_id(npc_id))
                if not tutorial_kill:
                    _adjust_shared_influence(ctx.shared, "ccp", 2)
                log_event(ctx, "The occupation will not forget this. Your face is remembered.")
                if not tutorial_kill and wanted_consequences(ctx.session.player.wanted_level).level >= WANTED_LEVEL_MAX:
                    room = _room(ctx)
                    district = room.id.split("_")[0].replace("_", " ").title() if room else "the city"
                    _generate_player_action_rumor(ctx, "high_wanted", target=district)
                import random
                loot_amount = random.randint(5, 15)
                ctx.session.player.money_military_yen += loot_amount
                await post_display(ctx, f"You find {loot_amount} military yen on the body.", msg_type="discovery")

            dropped_items = _drop_npc_loot(room, npc, ctx.session.player)
            if dropped_items:
                item_names = ", ".join(i.name for i in dropped_items)
                await post_display(ctx, f"Dropped items: {item_names}", msg_type="discovery")
                await broadcast_to_room(ctx, f"{npc.name} drops {item_names}.", exclude_username=ctx.session.username, msg_type="event")

            from .constants import CORPSE_DECAY_DAYS
            corpse = Item(
                id=f"corpse_{npc_id}",
                name=f"corpse of {npc.name}",
                description=loc("combat.corpse_created").format(name=npc.name),
                takeable=False,
                is_corpse=True,
                corpse_npc_id=npc_id,
                decay_day=ctx.shared.game_time.day + CORPSE_DECAY_DAYS,
            )
            all_npc_items = (
                list(npc.shop_inventory) +
                list(npc.black_market_items) +
                list(npc.inventory)
            )
            dropped_ids = {i.id for i in dropped_items}
            for item_data in all_npc_items:
                item_id = item_data.get("id", item_data.get("item_id", ""))
                if item_id and item_id not in dropped_ids:
                    remaining_item = Item(
                        id=item_id,
                        name=item_data.get("name", item_id),
                        description=item_data.get("description", ""),
                        base_cost=item_data.get("base_cost", item_data.get("cost", 10)),
                        category=item_data.get("category", ""),
                    )
                    if not hasattr(corpse, 'container_items') or corpse.container_items is None:
                        corpse.container_items = []
                    corpse.container_items.append(remaining_item)
            room.items.append(corpse)

            if npc.faction in COMBAT_GROWTH_FACTIONS:
                grow_stat(player, "courage", STAT_GAIN_COURAGE_COMBAT)
                await post_display(ctx, loc("combat.hardened"), msg_type="combat_narration")
            if npc.is_historical_figure:
                await _apply_historical_kill(ctx, npc)
            if not tutorial_kill:
                recorded = record_named_npc_death(
                    ctx.shared,
                    npc_id=npc_id,
                    npc_name=npc.name,
                    npc_faction=npc.faction,
                    room_id=room.id if room else "",
                    day=ctx.shared.game_time.day,
                    minute=ctx.shared.game_time.minute,
                    cause="combat",
                    killer_slot_id=ctx.session.slot_id,
                    historical=bool(getattr(npc, "is_historical_figure", False)),
                    faction_leader=bool(getattr(npc, "faction_leader", False)),
                )
                if recorded is not None:
                    room_id = room.id if room else ""
                    district = getattr(room, 'district', '') if room else ""
                    witness_ids = _sound_witness_ids(room, npc_id, result.sound_event)
                    witnesses = [w.id for w in (ctx.shared.world.npcs.get(nid) for nid in witness_ids) if w]
                    from .rumors import grant_observation
                    record_id = create_rumour_seed(
                        event_type="npc_killed",
                        location=room_id,
                        district=district,
                        witnesses=witnesses,
                        faction_context=npc.faction,
                        description=f"{npc.name} was killed by {player.name} in {district or room_id}.",
                        shared=ctx.shared,
                        occurrence=recorded.event_id,
                    )
                    if record_id:
                        grant_observation(ctx.session.player, record_id, "", ctx.shared.game_time.day, [record_id])
                elif room and npc_id in room.npcs:
                    room.npcs.remove(npc_id)
            elif room and npc_id in room.npcs:
                room.npcs.remove(npc_id)
            if not tutorial_kill and hasattr(ctx.shared, 'relationship_system') and ctx.shared.relationship_system is not None:
                ctx.shared.relationship_system.evolve_relationships(
                    npc_id, "npc_killed",
                    {"victim_id": npc_id, "killer_id": player.name},
                    ctx.shared)

            await _handle_witness_reactions(ctx, room, npc, npc_id, sound_event=result.sound_event)

            await _handle_mission_objectives(ctx, "kill_npc", npc_id)
            mm = ctx.shared.milestone_manager
            if mm:
                from .milestones import apply_milestone_effects
                for m in mm.check_action("action_kill_npc"):
                    if apply_milestone_effects(player, m, ctx.shared) and m.narrative:
                        await post_display(ctx, f"\n{m.narrative}\n", msg_type="combat_narration")
            outcome = success(
                "attack",
                facts={"npc_defeated"},
                tutorial_event={"verb": "attack", "target": npc.name},
            )
        else:
            npc.wounded = True
            npc.wound_type = "combat"
            await post_display(ctx, loc("combat.npc_wounded").format(name=semantic_span(npc.name, "npc"), hp=npc.hp), msg_type="combat_narration")
            outcome = failure("attack_npc_wounded")
        await _degrade_and_notify_weapon(ctx, weapon, True)
    else:
        outcome = failure("attack_failed")
        if result.attacker_damaged > 0:
            player.health = max(0, player.health - result.attacker_damaged)
            await play_sound(ctx, "player_hurt", 0.6)
            armour_id = getattr(player, 'worn_armour_id', '')
            if armour_id:
                armour = find_item_by_name(armour_id, player.inventory)
                if armour:
                    destroyed, msg = degrade_armour(armour)
                    if msg:
                        await post_display(ctx, msg, msg_type=MessageType.WARNING)
                    if destroyed:
                        player.inventory.remove(armour)
                        player.worn_armour_id = ""
        await _degrade_and_notify_weapon(ctx, weapon, False)

    await _post_attack_sound(ctx, weapon, room, result.sound_event, f"{player.name} attacks {npc.name}!")
    return outcome


async def _trigger_death(ctx: CommandContext, death_msg: str) -> None:
    if "player_died" in ctx.session.player.flags:
        return
    
    if "friend_saves_player" not in ctx.session.player.flags:
        room = _room(ctx)
        if room:
            for npc_id in room.npcs:
                npc = ctx.shared.world.npcs.get(npc_id)
                if not npc:
                    continue
                rel = ctx.session.player.relationships.get(npc_id, {})
                friendship = rel.get("friendship", 0)
                if friendship >= 50:
                    ctx.session.player.flags.append("friend_saves_player")
                    ctx.session.player.health = 15
                    await play_sound(ctx, "escape_charge", 0.7)
                    await post_display(ctx, f"\n{semantic_span(npc.name, 'npc')} pulls you from the shadows. 'Not today. Go, before they see you.'\n", msg_type="event")
                    await post_display(ctx, f"You narrowly escape death thanks to {semantic_span(npc.name, 'npc')}'s intervention.\n", msg_type="combat_narration")
                    current_day = ctx.shared.game_time.day
                    npc_memory_system.record_interaction(
                        npc, ctx.session.player.name, "saved_player_life",
                        {"location": room.id}, current_day
                    )
                    return
    
    if getattr(ctx.session, "awaiting_last_words", False):
        return
    if "last_words_spoken" not in ctx.session.player.flags:
        await ctx.session.send_display(
            "\nYour vision fades. You have one final breath. Speak your last words:\n",
            msg_type=MessageType.COMBAT,
        )
        await play_sound(ctx, "death", 0.6)
        ctx.session.awaiting_last_words = True
        return
    await handle_player_death(ctx, death_msg)


async def _post_attack_sound(ctx: CommandContext, weapon, room, sound_event=None, broadcast: str = "") -> None:
    player = ctx.session.player
    player.hidden = False
    if broadcast and (sound_event is None or sound_event.locally_visible):
        await broadcast_to_room(ctx, broadcast, exclude_username=ctx.session.username, msg_type=MessageType.COMBAT_NARRATION)
    if sound_event is not None and sound_event.emit_audio and sound_event.effective_range:
        await _propagate_combat_sound(ctx, room, sound_event)
    is_dead, death_msg = check_death_conditions(ctx)
    if is_dead:
        await _trigger_death(ctx, death_msg)


async def _check_kempeitai_attack_on_sight(ctx: CommandContext) -> None:
    room = _room(ctx)
    if not room:
        return
    
    player = ctx.session.player
    for npc_id in room.npcs:
        npc = ctx.shared.world.npcs.get(npc_id)
        if not npc:
            continue
        if npc.faction != "kempeitai":
            continue
        await post_display(ctx, loc("wanted.kempeitai_attack").format(name=semantic_span(npc.name, "npc")), msg_type="combat")
        result = resolve_attack(
            attacker_courage=npc.authority,
            attacker_weapon=None,
            target_authority=player.courage,
            target_armour=_get_worn_armour(player),
            attacker_hidden=False,
            attacker_morale=50,
        )
        if result.won:
            damage = result.target_damage
            player.health = max(0, player.health - damage)
            await play_sound(ctx, "player_hurt", 0.6)
            await post_display(ctx, loc("wanted.kempeitai_damage").format(
                name=format_bold(npc.name), damage=damage, health=player.health
            ), msg_type="combat")
            if player.health <= 0:
                await _trigger_death(ctx, loc("wanted.kempeitai_kill"))
                return
        else:
            await post_display(ctx, loc("wanted.kempeitai_miss").format(name=semantic_span(npc.name, "npc")), msg_type="combat")


async def _propagate_combat_sound(ctx: CommandContext, room, sound_event) -> None:
    from .pathfinding import propagate_sound_detailed
    heard_rooms_detailed = propagate_sound_detailed(
        ctx.shared.world.rooms, sound_event,
    )
    heard_rooms = [(room_id, perceived) for room_id, perceived, _hops in heard_rooms_detailed]
    if getattr(sound_event, "kind", "") in ACTIONABLE_SOUND_KINDS:
        election = _elect_sound_investigator(ctx.shared, heard_rooms_detailed)
        if election:
            _grant_sound_investigation(
                ctx.shared.world.npcs[election[0]], room.id, ctx.shared.game_time, sound_event.kind
            )
    for heard_room_id, perceived_intensity in heard_rooms:
        heard_room = ctx.shared.world.rooms.get(heard_room_id)
        if not heard_room:
            continue
        for npc_id in heard_room.npcs:
            npc = ctx.shared.world.npcs.get(npc_id)
            if npc:
                _update_npc_sound_memory(npc, room.id, perceived_intensity, sound_event.kind, ctx.shared.game_time, sound_event=sound_event)
        noun = sound_event.kind
        if perceived_intensity >= 3:
            msg = f"You hear a loud {noun} nearby!"
        elif perceived_intensity >= 2:
            msg = f"You hear a distant {noun}."
        else:
            msg = f"You hear a muffled {noun} from somewhere nearby."
        for session in ctx.session_manager.get_players_in_room(heard_room_id):
            if getattr(session, 'audio_enabled', True):
                volume = min(1.0, perceived_intensity / sound_event.intensity)
                await session.send_audio(noun, volume=volume, loop=False)
            await session.send_display(msg + "\n", msg_type=MessageType.EVENT if perceived_intensity >= 3 else MessageType.AMBIENT)


async def _attack_player(ctx: CommandContext, target_session: Session, courage_mult: float = 1.0):
    player = ctx.session.player
    target = target_session.player

    weapon = _get_equipped_weapon(player)
    target_armour = _get_worn_armour(target)
    from .pathfinding import emit_sound
    room = _room(ctx)
    attack_kind = "gunshot" if getattr(weapon, "weapon_type", "") == "firearm" else "melee"
    attack_sound = emit_sound(
        room.id if room else "",
        attack_kind,
        intensity=5 if attack_kind == "gunshot" else 2,
        weapon=weapon,
        hidden=player.hidden,
        weather=getattr(ctx.shared, "weather", "clear"),
        game_time=ctx.shared.game_time,
        range_multiplier=courage_mult,
        source_actor_id=player.username,
    )

    result = resolve_attack(
        attacker_courage=player.courage,
        attacker_weapon=weapon,
        target_authority=target.courage,
        target_armour=target_armour,
        attacker_hidden=player.hidden,
        attacker_morale=player.morale,
        courage_multiplier=courage_mult,
    )
    result.sound_event = attack_sound

    if result.won:
        target.health = max(0, target.health - 20)
        if getattr(target_session, "audio_enabled", False):
            await target_session.send_audio("player_hurt", volume=0.6)
        if attack_sound.locally_visible:
            await broadcast_to_room(ctx, loc("combat.player_strikes").format(name=player.name, target=format_bold(target.name)), msg_type="combat_narration")
        log_event(ctx, f"You attacked {target.name}.")
        if target.health <= 0:
            target_context = _context_for_session(ctx, target_session)
            await handle_player_death(target_context, f"You killed {target.name}.")
    else:
        if result.attacker_damaged > 0:
            player.health = max(0, player.health - result.attacker_damaged)
            await play_sound(ctx, "player_hurt", 0.6)
        await post_display(ctx, loc("combat.attack_fails").format(name=semantic_span(target.name, "npc"), target=semantic_span(target.name, "npc")), msg_type="combat_narration")

    await _degrade_and_notify_weapon(ctx, weapon, result.won)

    await _post_attack_sound(ctx, weapon, room, result.sound_event)


async def cmd_buy_from(ctx: CommandContext, cmd: Command):
    from .storylets import ActiveStorylet, StoryletOption
    from .npc import get_role_trust
    from .locales import get as loc

    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_buy_from.no_vendor"), msg_type=MessageType.PLAYER_ACTION)
        return

    npc_id = resolve_npc(ctx, cmd.direct_obj)
    if not npc_id:
        await post_display(ctx, loc("cmd_buy_from.not_here"), msg_type=MessageType.PLAYER_ACTION)
        return

    validation = validate_vendor_purchase_context(ctx, npc_id)
    if validation.error:
        if validation.error == "closed":
            await post_display(ctx, validation.error_message, msg_type=MessageType.WARNING)
        elif validation.error == "no_stock":
            await post_display(ctx, loc("cmd_buy_from.no_stock").format(vendor=validation.npc.name), msg_type=MessageType.PLAYER_ACTION)
        elif validation.error == "wanted":
            await post_display(ctx, loc("cmd_buy_from.wanted_refuse").format(vendor=validation.npc.name), msg_type=MessageType.WARNING)
        else:
            await post_display(ctx, loc("cmd_buy_from.not_here"), msg_type=MessageType.PLAYER_ACTION)
        return

    npc = validation.npc
    room = validation.room
    shop_inventory = validation.shop_inventory
    black_market_items = validation.black_market_items
    trust_score = validation.trust_score
    wanted_policy = validation.wanted_policy
    access = validation.access
    vendor_capable = True
    
    from .economy import DISTRICT_TO_REGION
    from .constants import BLACK_MARKET_MULTIPLIER
    room = ctx.shared.world.get_room(ctx.session.player.current_room)
    room_district = room.district if room else ''
    econ_region = DISTRICT_TO_REGION.get(room_district, 'commercial')
    player_morale = ctx.session.player.morale
    season_mult = SEASONAL_PRICE_MULTIPLIER.get(_season_from_day(ctx.shared.game_time.day), 1.0)
    inflation_mult = fabi_inflation_multiplier(ctx.shared.game_time.day)
    
    shop_items = []
    options = []
    for idx, item_data in enumerate(shop_inventory):
        item_id = item_data.get("item_id") or item_data.get("id") if isinstance(item_data, dict) else item_data
        item_template = ctx.shared.world.item_catalog.get(item_id)
        if not item_template:
            continue

        base_cost = item_data.get("base_cost", 10) if isinstance(item_data, dict) else 10
        tutorial_price = item_data.get("tutorial_price") if isinstance(item_data, dict) else None
        from .economy import economy_system as _econ
        if tutorial_price is not None and _is_tutorial_vendor_clone(ctx.session.player, npc_id):
            final_price = int(tutorial_price)
        else:
            final_price = int(_econ.get_item_price(
                base_cost, item_id, econ_region, npc.faction,
                inflation_rate=inflation_mult, season_multiplier=season_mult,
                trust_score=trust_score, player_morale=player_morale,
                item_rarity=item_template.rarity,
            ))

        item_category = getattr(_econ, 'ITEM_CATEGORIES', {}).get(item_id, 'general')
        uses_military_yen = item_category == 'japanese_goods' or npc.faction == 'kempeitai'
        currency = 'military_yen' if uses_military_yen else 'fabi'
        spend_key = 'spend_military_yen' if uses_military_yen else 'spend_fabi'
        currency_label = 'military yen' if uses_military_yen else 'fabi'

        item_name = item_template.name if item_template.name else item_id
        from .popup_payloads import item_row
        row = item_row(item_template)
        row["price"] = final_price
        row["currency"] = currency
        row["section"] = "regular"
        row["affordable"] = (
            can_afford_fabi(ctx.session.player, final_price)
            if currency == "fabi"
            else ctx.session.player.money_military_yen >= final_price
        )
        shop_items.append(row)

        options.append(StoryletOption(
            text=f"{item_name} — {final_price} {currency_label}",
            effects={
                spend_key: final_price,
                "give_item": item_id,
                "vendor_id": npc_id,
                "purchase": {
                    "item": item_name,
                    "vendor": npc.name,
                    "price": final_price,
                    "currency": currency_label,
                },
            },
        ))
    
    if vendor_capable and not _is_tutorial_vendor_clone(ctx.session.player, npc_id):
        from .newspaper import NEWSPAPER_COST_FABI
        shop_items.append({
            "id": "newspaper",
            "name": "newspaper",
            "description": "",
            "price": NEWSPAPER_COST_FABI,
            "currency": "fabi",
            "section": "newspaper",
            "affordable": can_afford_fabi(ctx.session.player, NEWSPAPER_COST_FABI),
        })
        options.append(StoryletOption(
            text=f"newspaper — {NEWSPAPER_COST_FABI} fabi",
            effects={"purchase_newspaper": npc.name},
        ))

    can_access_black_market = bool(
        black_market_items and (trust_score >= 70 or validation.demo_black_market)
    )
    if can_access_black_market:
        _normalize_back_room_ledger(ctx.session.player, ctx.shared.server_cycle)
        options.append(StoryletOption(
            text="--- " + loc("cmd_buy_from.back_room") + " ---",
            effects={},
            disabled=True,
        ))

        for idx, item_data in enumerate(black_market_items):
            item_id = item_data.get("item_id") or item_data.get("id") if isinstance(item_data, dict) else item_data
            if (
                ctx.session.player.black_market_purchase_cycle == ctx.shared.server_cycle
                and item_id in ctx.session.player.black_market_purchases
            ):
                continue
            item_template = ctx.shared.world.item_catalog.get(item_id)
            if not item_template:
                continue

            base_cost = item_data.get("base_cost", 10) if isinstance(item_data, dict) else 10
            tutorial_price = item_data.get("tutorial_price") if isinstance(item_data, dict) else None
            from .economy import economy_system as _econ
            if tutorial_price is not None and _is_tutorial_vendor_clone(ctx.session.player, npc_id):
                final_price = int(tutorial_price)
            else:
                final_price = int(_econ.get_item_price(
                    base_cost, item_id, econ_region, npc.faction,
                    inflation_rate=inflation_mult, season_multiplier=season_mult,
                    trust_score=trust_score, player_morale=player_morale,
                    item_rarity=item_template.rarity,
                ) * BLACK_MARKET_MULTIPLIER)

            item_category = getattr(_econ, 'ITEM_CATEGORIES', {}).get(item_id, 'general')
            uses_military_yen = item_category == 'japanese_goods' or npc.faction == 'kempeitai'
            currency = 'military_yen' if uses_military_yen else 'fabi'
            spend_key = 'spend_military_yen' if uses_military_yen else 'spend_fabi'
            currency_label = 'military yen' if uses_military_yen else 'fabi'

            item_name = item_template.name if item_template.name else item_id
            from .popup_payloads import item_row
            row = item_row(item_template)
            row["price"] = final_price
            row["currency"] = currency
            row["section"] = "black_market"
            row["affordable"] = (
                can_afford_fabi(ctx.session.player, final_price)
                if currency == "fabi"
                else ctx.session.player.money_military_yen >= final_price
            )
            shop_items.append(row)

            options.append(StoryletOption(
                text=f"{item_name} — {final_price} {currency_label}",
                effects={
                    spend_key: final_price,
                    "give_item": item_id,
                    "vendor_id": npc_id,
                    "is_black_market": True,
                    "item_category": item_category,
                    "purchase": {
                        "item": item_name,
                        "vendor": npc.name,
                        "price": final_price,
                        "currency": currency_label,
                    },
                },
            ))
    
    options.append(StoryletOption(
        text=loc("shop_menu.cancel"),
        effects={},
    ))
    
    narrative = loc("cmd_buy_from.shop_prompt").format(vendor=npc.name)
    if can_access_black_market:
        narrative += "\n\n" + loc("cmd_buy_from.black_market_available")

    shop_storylet = ActiveStorylet(
        storylet_id=f"shop_{npc_id}",
        narrative=narrative,
        options=options,
        room_id=ctx.session.player.current_room,
        timer_duration=300,
        timer_started_at=time.time(),
    )
    from .storylets import mark_untimed_for_tutorial
    mark_untimed_for_tutorial(shop_storylet, ctx.session.player)
    ctx.session.player.active_storylets.append(shop_storylet)

    from .popup_payloads import room_key_for_client, send_popup, store_payload

    room_key = room_key_for_client(ctx)
    ctx.session.set_open_popup("store", {"room_key": room_key, "vendor_id": npc_id})
    shop_currency = shop_items[0]["currency"] if shop_items else "fabi"
    await send_popup(ctx.session, "store_menu", store_payload(
        vendor_id=npc_id,
        vendor_name=npc.name,
        room_key=room_key,
        currency=shop_currency,
        items=shop_items,
        black_market_available=can_access_black_market,
        generation=ctx.session.open_popup["generation"],
        wanted_policy=wanted_policy,
        wallet_fabi_value=wallet_fabi_value(ctx.session.player),
    ))
    return success("buy_from", facts={"shop_opened"})


async def cmd_sell(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        candidates = [_action_row(item) for item in _sellable_items(ctx)]
        if not candidates:
            await post_display(ctx, "You have nothing to sell.", msg_type=MessageType.PLAYER_ACTION)
            return failure("sell_no_candidates")
        await _open_item_action_chooser(ctx, "sell", loc("cmd_sell.no_target"), candidates)
        return success("sell_chooser", facts={"chooser_opened"})
    from .equipment import ensure_inventory_identity
    ensure_inventory_identity(ctx.session.player)
    item = find_item_exact(cmd.direct_obj, ctx.session.player.inventory)
    if not item:
        await post_display(ctx, loc("cmd_sell.not_held"), msg_type=MessageType.PLAYER_ACTION)
        return failure("sell_not_held")

    vendor = _selling_vendor(ctx)
    from .economy import economy_system as _econ, DISTRICT_TO_REGION
    if not vendor:
        await post_display(ctx, loc("cmd_sell.no_value"), msg_type=MessageType.PLAYER_ACTION)
        return failure("sell_no_value")
    npc, _stock, represented_categories = vendor
    if (
        not item.takeable
        or item.is_quest_item
        or item.instance_id in {
            ctx.session.player.equipped_weapon_id,
            ctx.session.player.worn_armour_id,
            ctx.session.player.equipped_disguise_item_id,
        }
        or _econ.get_item_category(item.id) not in represented_categories
    ):
        await post_display(ctx, loc("cmd_sell.no_value"), msg_type=MessageType.PLAYER_ACTION)
        return failure("sell_no_value")

    base_cost = _econ.get_item_base_price(item.id, getattr(ctx.shared.world, "item_catalog", None))
    room = _room(ctx)
    region = DISTRICT_TO_REGION.get(room.district, "commercial") if room else "commercial"
    sell_price = _econ.get_resale_price(
        item, region, npc.faction,
        base_cost=base_cost,
        trust_score=get_role_trust(ctx.session.player.trust, npc.faction, None),
        player_morale=ctx.session.player.morale,
        inflation_rate=fabi_inflation_multiplier(ctx.shared.game_time.day),
        season_multiplier=SEASONAL_PRICE_MULTIPLIER.get(_season_from_day(ctx.shared.game_time.day), 1.0),
    )
    if sell_price <= 0:
        await post_display(ctx, loc("cmd_sell.no_value"), msg_type=MessageType.PLAYER_ACTION)
        return failure("sell_no_value")

    ctx.session.player.inventory.remove(item)
    _earn_money(ctx.session.player, sell_price)
    log_event(ctx, f"You sold {item.name} for {sell_price} fabi.")
    await post_display(ctx, loc("cmd_sell.success").format(name=semantic_span(item.name, "item"), price=sell_price), msg_type=MessageType.PLAYER_ACTION)
    await play_sound(ctx, "coin_clink", 0.7)
    return success("sell", facts={"item_sold"})


async def cmd_pickpocket(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_pickpocket.no_target"), msg_type=MessageType.PLAYER_ACTION)
        return
    npc_id = resolve_npc(ctx, cmd.direct_obj)
    if not npc_id:
        await post_display(ctx, loc("cmd_pickpocket.not_here"), msg_type=MessageType.PLAYER_ACTION)
        return

    npc = ctx.shared.world.npcs.get(npc_id)
    if not npc:
        await post_display(ctx, loc("cmd_pickpocket.not_here"), msg_type=MessageType.PLAYER_ACTION)
        return

    room = _room(ctx)
    from .constants import get_season, PICKPOCKET_BASE
    season = get_season(ctx.shared.game_time.day)

    observers = []
    if room:
        for rid in room.npcs:
            other_npc = ctx.shared.world.npcs.get(rid)
            if other_npc and other_npc != npc:
                observers.append(other_npc)

    success, _ = ctx.stealth.stealth_check(
        player_stealth=ctx.session.player.stealth_skill,
        target_perception=npc.perception,
                difficulty_modifier=0,
        room_indoors=room.indoors if room else False,
        observers=observers,
        target_npc=npc,
        season=season,
        player_hidden=ctx.session.player.hidden,
        hunger=ctx.session.player.hunger,
    )

    if success:
        role_payouts = {"vendor": (5, 15), "merchant": (10, 25), "officer": (15, 25), "civilian": (5, 10)}
        fabi_range = role_payouts.get(getattr(npc, 'role', ''), (5, 10))
        amount = random.randint(*fabi_range)
    else:
        amount = 0
    current_day = ctx.shared.game_time.day
    if success:
        _earn_money(ctx.session.player, amount)
        log_event(ctx, f"You pickpocketed {npc.name} for {amount} fabi.")
        await apply_action_trust(
            ctx,
            "pickpocket",
            room_npcs(ctx),
            dynamic_vars={"victim_faction": npc.faction, "victim_role": npc.role},
        )
        await post_display(ctx, loc("cmd_pickpocket.success").format(name=npc.name, amount=amount), msg_type="discovery")
        npc_memory_system.record_interaction(
            npc, ctx.session.player.name, "pickpocketed",
            {"amount": amount}, current_day
        )
        if random.random() < 0.30 and hasattr(npc, 'inventory') and npc.inventory:
            takeable = [i for i in npc.inventory if getattr(i, 'takeable', True)]
            if takeable:
                stolen_item = random.choice(takeable)
                npc.inventory.remove(stolen_item)
                ctx.session.player.inventory.append(stolen_item)
                await post_display(ctx, f"You also lift {stolen_item.name} from {npc.name}'s pocket.", msg_type="discovery")
    else:
        _raise_nearby_suspicion(ctx, SUSPICION_FAILED_STEALTH)
        log_event(ctx, f"You were caught pickpocketing {npc.name}.")
        await apply_action_trust(
            ctx,
            "caught_pickpocket",
            room_npcs(ctx),
            dynamic_vars={"victim_faction": npc.faction, "victim_role": npc.role},
        )
        ctx.session.player.hidden = False
        _record_crime(ctx)
        npc.suspicion = min(100, npc.suspicion + 50)
        await post_display(ctx, loc("cmd_pickpocket.caught").format(name=npc.name), msg_type=MessageType.WARNING)
        await broadcast_to_room(ctx, loc("cmd_pickpocket.caught_broadcast").format(name=ctx.session.player.name, target=npc.name), msg_type=MessageType.WARNING)

        room = _room(ctx)
        room_name = room.title if room else "the area"
        _generate_player_action_rumor(ctx, "pickpocket_failed", target=room_name)

        npc_memory_system.record_interaction(
            npc, ctx.session.player.name, "caught_pickpocketing",
            {"attempted_amount": amount}, current_day
        )


async def cmd_equip(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        from .popup_payloads import has_any_equipment
        if not has_any_equipment(ctx.session.player):
            await post_display(ctx, "You have nothing to equip.", msg_type=MessageType.PLAYER_ACTION)
            return failure("equip_no_items")
        await _open_equipment_popup(ctx)
        from .tutorial import _send_popup_hint
        await _send_popup_hint(ctx)
        return success("equip_chooser", facts={"chooser_opened"})
    from .equipment import ensure_inventory_identity
    ensure_inventory_identity(ctx.session.player)
    item = next((candidate for candidate in ctx.session.player.inventory if candidate.instance_id == cmd.direct_obj), None)
    if item is None:
        item = find_item_by_name(cmd.direct_obj, ctx.session.player.inventory)
    if not item:
        await post_display(ctx, loc("cmd_equip.not_held"), msg_type=MessageType.PLAYER_ACTION)
        return failure("equip_not_held")

    item_identity = item.instance_id
    if item.disguise_id and item.disguise_id in ctx.disguises:
        active_identity = ctx.session.player.disguise
        if active_identity and item.disguise_id != active_identity:
            await post_display(ctx, loc("cmd_equip.other_disguise"), msg_type=MessageType.PLAYER_ACTION)
            return failure("equip_other_disguise")
        ctx.session.player.equipped_disguise_item_id = item_identity
        await post_display(ctx, loc("cmd_equip.weapon_ready").format(name=semantic_span(item.name, "item")), msg_type=MessageType.PLAYER_ACTION)
    elif item.is_armour:
        worn = _get_worn_armour(ctx.session.player)
        if worn and worn.id == item.id:
            await post_display(ctx, loc("cmd_equip.already"), msg_type=MessageType.PLAYER_ACTION)
            return failure("equip_already_worn")
        ctx.session.player.worn_armour_id = item_identity
        await post_display(ctx, loc("cmd_equip.armour").format(name=semantic_span(item.name, "item"), defense=item.defense_value), msg_type=MessageType.PLAYER_ACTION)
    elif item.is_weapon:
        ctx.session.player.equipped_weapon_id = item_identity
        ctx.session._weapon_attack_count = 0
        await post_display(ctx, loc("cmd_equip.weapon_ready").format(name=semantic_span(item.name, "item")), msg_type=MessageType.PLAYER_ACTION)
    else:
        await post_display(ctx, loc("cmd_equip.not_equipable"), msg_type=MessageType.PLAYER_ACTION)
        return failure("equip_not_equipable")
    await _refresh_inventory_if_open(ctx)
    await _refresh_equipment_if_open(ctx)
    await play_sound(ctx, "item_pickup", 0.6)
    return success(
        "equip",
        facts={"equipment_changed"},
        tutorial_event={"verb": "equip", "target": item.id or item.name},
    )




async def _award_mission_rewards(ctx: CommandContext, mission):
    if not mission:
        return
    reward = mission.rewards
    player = ctx.session.player
    if reward.money_fabi > 0:
        _earn_money(player, reward.money_fabi)
    if reward.money_silver > 0:
        earn_fabi_value(player, reward.money_silver * 10)
    if reward.health_restore > 0:
        player.health = min(100, player.health + reward.health_restore)
    if reward.morale_restore > 0:
        player.morale = min(100, player.morale + reward.morale_restore)
    for trust_key, delta in reward.trust.items():
        change_trust(
            player.trust,
            trust_key,
            delta,
            last_trust_interaction=player.last_trust_interaction,
            current_day=ctx.shared.game_time.day,
            player_flags=player.flags,
        )
    for faction, delta in reward.influence.items():
        _adjust_shared_influence(ctx.shared, faction, delta)
    if reward.add_flag:
        player.flags.append(reward.add_flag)
    if reward.add_item:
        item = ctx.shared.world.clone_item(reward.add_item)
        if item:
            player.inventory.append(item)
    if reward.cross_faction_penalty:
        for trust_key, delta in reward.cross_faction_penalty.items():
            change_trust(
                player.trust,
                trust_key,
                delta,
                last_trust_interaction=player.last_trust_interaction,
                current_day=ctx.shared.game_time.day,
                player_flags=player.flags,
            )
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
    if reward.cross_faction_penalty:
        reward_lines.append("reputation affected")
    reward_text = ", ".join(reward_lines) if reward_lines else "nothing tangible"

    log_event(ctx, f"Mission complete: {mission.title}")
    await post_display(ctx, loc("mission.complete").format(title=mission.title, rewards=reward_text), msg_type=MessageType.SUCCESS)
    room = _room(ctx)
    from .rumors import grant_observation
    record_id = create_rumour_seed(
        event_type="mission_complete",
        location=room.id if room else "",
        district=getattr(room, 'district', '') if room else "",
        witnesses=list(room.npcs) if room else [],
        faction_context=mission.faction if mission.faction else "",
        description=f"Mission '{mission.title}' completed by {player.name} for {mission.faction.upper() if mission.faction else 'unknown'}.",
        shared=ctx.shared,
        occurrence=mission.id,
    )
    if record_id:
        grant_observation(ctx.session.player, record_id, "", ctx.shared.game_time.day, [record_id])


async def cmd_missions(ctx: CommandContext, cmd: Command):
    mm = ctx.shared.mission_manager
    if not mm:
        await post_display(ctx, loc("cmd_missions.unavailable"), msg_type=MessageType.PLAYER_ACTION)
        return

    sub = cmd.direct_obj or ""
    if sub == "available":
        available = mm.get_available(
            ctx.session.player,
            world=ctx.shared,
            current_day=ctx.shared.game_time.day,
            current_hour=ctx.shared.game_time.hour,
        )
        if not available:
            await post_display(ctx, loc("cmd_missions.no_available"), msg_type=MessageType.PLAYER_ACTION)
            return
        lines = [loc("cmd_missions.available_header")]
        for m in available:
            giver = ""
            if m.giver_npc_hint:
                npc = ctx.shared.world.npcs.get(m.giver_npc_hint)
                giver = f" (seek {npc.name})" if npc else f" (seek {m.giver_npc_hint})"
            lines.append(f"  [{m.id}] {m.title} (faction: {m.faction}, min trust: {m.min_trust}){giver}")
        await post_display(ctx, "\n".join(lines), msg_type=MessageType.PLAYER_ACTION)
        await play_sound(ctx, "page_turn", 0.5)
    elif sub == "accept":
        await post_display(ctx, "Mission acceptance is offered through an encounter.", msg_type="system")
    elif sub == "abandon":
        mission_id = cmd.indirect_obj or ""
        if not mission_id:
            await post_display(ctx, loc("cmd_missions.abandon_which"), msg_type=MessageType.PLAYER_ACTION)
            return
        if mm.abandon(ctx.session.player, mission_id):
            log_event(ctx, f"Abandoned mission: {mission_id}")
            await post_display(ctx, loc("cmd_missions.abandoned").format(id=mission_id), msg_type=MessageType.PLAYER_ACTION)
        else:
            await post_display(ctx, loc("cmd_missions.not_active"), msg_type=MessageType.PLAYER_ACTION)
    elif sub == "complete":
        mission_id = cmd.indirect_obj or ""
        if not mission_id:
            await post_display(ctx, loc("cmd_missions.complete_which"), msg_type=MessageType.PLAYER_ACTION)
            return
        mission = mm.complete(ctx.session.player, mission_id)
        if mission:
            await _award_mission_rewards(ctx, mission)
        else:
            await post_display(ctx, loc("cmd_missions.cannot_complete"), msg_type=MessageType.PLAYER_ACTION)
    else:
        active = mm.get_active(ctx.session.player)
        if not active:
            await post_display(ctx, loc("cmd_missions.no_active"), msg_type=MessageType.PLAYER_ACTION)
            return success("missions", facts={"missions_read"}, tutorial_event={"verb": "missions"})
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
        await post_display(ctx, "\n".join(lines), msg_type=MessageType.PLAYER_ACTION)
        return success("missions", facts={"missions_read"}, tutorial_event={"verb": "missions"})


async def cmd_examine(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_examine.no_target"), msg_type=MessageType.PLAYER_ACTION)
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
        lines = [f"You examine {item.name}.", item.description]
        if item.examine_text:
            lines.append(item.examine_text)
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
            if ctx.session.player.in_tutorial and item.is_note:
                ctx.session.player.tutorial_read_note = True
        elif item.is_key:
            if item.opens_container:
                lines.append(f"Key that opens: {item.opens_container}")
        if hasattr(item, 'durability') and item.durability <= 0:
            lines.append("<b>(BROKEN)</b>")
        hint = _item_action_hint(item, carried)
        if hint:
            lines.append(hint)
        await post_display(ctx, "\n".join(lines), msg_type=MessageType.ROOM_DESCRIPTION)
        return success(
            "examine",
            facts={"item_examined"},
            tutorial_event={"verb": "examine", "target": cmd.direct_obj or ""},
        )

    npc_id = resolve_npc(ctx, cmd.direct_obj)
    if npc_id:
        npc = ctx.shared.world.npcs.get(npc_id)
        if npc:
            lines = [f"You observe {npc.name}."]
            perception = ctx.session.player.perception

            if perception >= 30:
                lines.append(f"Faction: {npc.faction}")

            if perception >= 50:
                lines.append(f"Role: {npc.role}")

            if perception >= 70:
                if ctx.session.player.perception >= npc.courage:
                    lines.append(f"Authority: {npc.authority}")
                else:
                    lines.append("You can't assess their authority.")

            if perception >= 90:
                lines.append(f"Courage: {npc.courage}")
                from .trust import get_role_trust, get_trust_tier
                trust_val = get_role_trust(ctx.session.player.trust, npc.faction, npc.role)
                tier = get_trust_tier(trust_val, npc.faction)
                lines.append(f"Trust tier: {tier}")

            if perception < 30:
                lines.append("You can't discern much about them.")

            short = _short_name(npc.name)
            if not getattr(ctx.session.player, "in_tutorial", False):
                lines.append(f"You can: TALK TO {short}, ASK {short} ABOUT <topic>, ATTACK, PICKPOCKET.")
            await post_display(ctx, "\n".join(lines), msg_type=MessageType.ROOM_DESCRIPTION)
            return

    await post_display(ctx, loc("cmd_examine.not_found"), msg_type=MessageType.PLAYER_ACTION)


async def cmd_assess(ctx: CommandContext, cmd: Command):
    from .locales import get as loc
    from .parser import DIRECTIONS

    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_assess.no_target"), msg_type=MessageType.PLAYER_ACTION)
        return

    direction = cmd.direct_obj.strip().lower()
    if direction in DIRECTIONS:
        weapon = _get_equipped_weapon(ctx.session.player)
        if not weapon or "scope" not in weapon.mods:
            await post_display(ctx, "You can't see clearly from here.", msg_type=MessageType.PLAYER_ACTION)
            return

        room = _room(ctx)
        if not room:
            return

        dest_id = room.exits.get(direction)
        if not dest_id:
            await post_display(ctx, loc("cmd_go.nowhere"), msg_type=MessageType.PLAYER_ACTION)
            return

        dest_room = ctx.shared.world.rooms.get(dest_id)
        if not dest_room or not dest_room.npcs:
            await post_display(ctx, "You see no one in that direction.", msg_type=MessageType.PLAYER_ACTION)
            return

        npc_id = dest_room.npcs[0]
        npc = ctx.shared.world.npcs.get(npc_id)
        if not npc:
            await post_display(ctx, "You see no one in that direction.", msg_type=MessageType.PLAYER_ACTION)
            return

        lines = [f"Through your scope, you assess {npc.name} in the {direction} room."]
        lines.append(f"Faction: {npc.faction}")
        lines.append(f"Role: {npc.role}")
        lines.append(f"Authority: {npc.authority}")
        lines.append(f"Courage: {npc.courage}")

        threat_level = "Low"
        if npc.faction == "kempeitai":
            threat_level = "Very High" if npc.role == "officer" else "High"
        elif npc.faction == "green_gang":
            threat_level = "High"
        elif npc.faction in ("ccp", "gmd"):
            threat_level = "Medium"
        elif npc.authority >= 70 or npc.courage >= 70:
            threat_level = "High"
        elif npc.authority >= 40 or npc.courage >= 40:
            threat_level = "Medium"

        lines.append(f"Threat Level: {threat_level}")

        if ctx.session.player.perception >= 70:
            if npc.weapon_id:
                w = ctx.shared.world.items.get(npc.weapon_id)
                if w:
                    lines.append(f"Armed with: {w.name}")

        await post_display(ctx, "\n".join(lines), msg_type=MessageType.DISCOVERY)
        return

    room = _room(ctx)
    if not room:
        return

    target_session = _find_player_in_room(ctx, cmd.direct_obj)
    if target_session:
        target_player = target_session.player
        lines = [f"You assess {target_player.name}."]
        lines.append(f"Health: {target_player.health}")
        lines.append(f"Morale: {target_player.morale}")
        lines.append(f"Courage: {target_player.courage}")
        lines.append(f"Perception: {target_player.perception}")
        await post_display(ctx, "\n".join(lines), msg_type=MessageType.DISCOVERY)
        return success("assess", facts={"assessed"}, tutorial_event={"verb": "assess", "target": cmd.direct_obj or ""})

    npc_id = resolve_npc(ctx, cmd.direct_obj)
    if not npc_id:
        await post_display(ctx, loc("cmd_examine.not_found"), msg_type=MessageType.PLAYER_ACTION)
        return

    npc = ctx.shared.world.npcs.get(npc_id)
    if not npc:
        await post_display(ctx, loc("cmd_examine.not_found"), msg_type=MessageType.PLAYER_ACTION)
        return

    lines = [f"You assess {npc.name}."]

    lines.append(f"Faction: {npc.faction}")
    lines.append(f"Role: {npc.role}")

    lines.append(f"Authority: {npc.authority}")

    lines.append(f"Courage: {npc.courage}")

    threat_level = "Low"
    if npc.faction == "kempeitai":
        threat_level = "Very High" if npc.role == "officer" else "High"
    elif npc.faction == "green_gang":
        threat_level = "High"
    elif npc.faction in ("ccp", "gmd"):
        threat_level = "Medium"
    elif npc.authority >= 70 or npc.courage >= 70:
        threat_level = "High"
    elif npc.authority >= 40 or npc.courage >= 40:
        threat_level = "Medium"

    lines.append(f"Threat Level: {threat_level}")

    if ctx.session.player.perception >= 70:
        if npc.weapon_id:
            weapon = ctx.shared.world.items.get(npc.weapon_id)
            if weapon:
                lines.append(f"Armed with: {weapon.name}")

    short = _short_name(npc.name)
    if not getattr(ctx.session.player, "in_tutorial", False):
        lines.append(f"You can: TALK TO {short}, ASK {short} ABOUT <topic>, ATTACK, PICKPOCKET.")

    await post_display(ctx, "\n".join(lines), msg_type=MessageType.DISCOVERY)
    return success("assess", facts={"assessed"}, tutorial_event={"verb": "assess", "target": cmd.direct_obj or ""})


async def cmd_open(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_open.no_target"), msg_type=MessageType.PLAYER_ACTION)
        return

    item = _find_container(ctx, cmd.direct_obj)
    if not item:
        await post_display(ctx, loc("container.not_container"), msg_type=MessageType.PLAYER_ACTION)
        return

    if (getattr(ctx.session.player, "in_tutorial", False)
            and getattr(item, "id", "").startswith("refugee_iron_safe")
            and getattr(ctx.session.player, "tutorial_stage", 0) < 25):
        await post_display(ctx, "The soldier stands between you and the safe.", msg_type=MessageType.PLAYER_ACTION)
        from .tutorial import _send_tutorial_hint, STAGE_ACTIONS as _OS_STAGES
        stage = ctx.session.player.tutorial_stage
        _os_action = _OS_STAGES.get(stage, {})
        if _os_action:
            await _send_tutorial_hint(ctx, stage, _os_action, force_immediate=True)
        return

    consumed_key = None
    if item.locked:
        if not _has_key_for_container(ctx.session.player, item):
            await post_display(ctx, loc("container.locked"), msg_type=MessageType.PLAYER_ACTION)
            return
        item.locked = False
        consumed_key = _consume_key(ctx.session.player, item.key_id)

    item.is_open = True
    await _open_container_popup(ctx, item)

    await play_sound(ctx, "door", 0.6)
    await post_display(ctx, loc("container.opened").format(name=semantic_span(item.name, "item")), msg_type=MessageType.PLAYER_ACTION)
    if consumed_key:
        await post_display(ctx, loc("container.key_snapped").format(name=semantic_span(consumed_key.name, "item")), msg_type=MessageType.PLAYER_ACTION)
    if item.container_items:
        contents = ", ".join(semantic_span(ci.name, "item") for ci in item.container_items)
        await post_display(ctx, loc("container.contents").format(items=contents), msg_type=MessageType.PLAYER_ACTION)
    else:
        await post_display(ctx, loc("container.empty"), msg_type=MessageType.PLAYER_ACTION)
    return success("open", facts={"container_opened"}, tutorial_event={"verb": "open", "target": cmd.direct_obj or ""})


async def close_container(ctx: CommandContext, container) -> CommandOutcome:
    container.is_open = False
    await _close_container_popup_if_open(ctx, container.id, "closed")
    await post_display(ctx, loc("container.closed").format(name=container.name), msg_type=MessageType.PLAYER_ACTION)
    return success("close", facts={"container_closed"})


async def cmd_take_from(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj or not cmd.indirect_obj:
        await post_display(ctx, loc("cmd_take_from.usage"), msg_type=MessageType.PLAYER_ACTION)
        return failure("take_from_usage")

    container = _find_container(ctx, cmd.indirect_obj)
    if not container:
        await post_display(ctx, loc("container.not_container"), msg_type=MessageType.PLAYER_ACTION)
        return failure("take_from_not_container")

    if container.locked:
        await post_display(ctx, loc("container.locked"), msg_type=MessageType.PLAYER_ACTION)
        return failure("take_from_locked")

    if not container.is_open:
        await post_display(ctx, loc("container.closed").format(name=container.name), msg_type=MessageType.PLAYER_ACTION)
        return failure("take_from_closed")

    item = find_item_exact(cmd.direct_obj, container.container_items)
    if not item:
        await post_display(ctx, loc("container.not_in_there"), msg_type=MessageType.PLAYER_ACTION)
        return failure("take_from_missing")

    max_cap = getattr(ctx.session.player, "max_inventory", 12)
    current_count = len([i for i in ctx.session.player.inventory
                         if not getattr(i, "is_worn", False) and not getattr(i, "is_equipped", False)])
    if current_count >= max_cap:
        await post_display(ctx, loc("cmd_generic.inventory_full"), msg_type=MessageType.PLAYER_ACTION)
        return failure("take_from_inventory_full")

    container.container_items.remove(item)
    ctx.session.player.inventory.append(item)
    await _refresh_inventory_if_open(ctx)
    await _refresh_container_if_open(ctx, container)
    await post_display(ctx, loc("container.take").format(item=semantic_span(item.name, "item"), container=semantic_span(container.name, "item")), msg_type=MessageType.PLAYER_ACTION)
    await play_sound(ctx, "item_pickup", 0.6)
    return success(
        "take_from",
        facts={"item_taken"},
        tutorial_event={"verb": "take from", "target": item.id or item.name, "indirect": container.name},
    )


async def cmd_remove(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        from .popup_payloads import has_any_equipment
        if not has_any_equipment(ctx.session.player):
            await post_display(ctx, loc("cmd_remove.nothing"), msg_type=MessageType.PLAYER_ACTION)
            return
        await _open_equipment_popup(ctx)
        return
    else:
        target = cmd.direct_obj.lower()
        if "armour" in target or ctx.session.player.worn_armour_id:
            worn = _get_worn_armour(ctx.session.player)
            if worn and ("armour" in target or find_item_by_name(cmd.direct_obj, [worn]) is not None):
                ctx.session.player.worn_armour_id = ""
                await _refresh_inventory_if_open(ctx)
                await _refresh_equipment_if_open(ctx)
                await post_display(ctx, loc("cmd_remove.success").format(name=semantic_span(worn.name, "item")), msg_type=MessageType.PLAYER_ACTION)
                return
        if "weapon" in target or ctx.session.player.equipped_weapon_id:
            item = equipped_weapon(ctx.session.player) if "weapon" in target else find_item_by_name(cmd.direct_obj, ctx.session.player.inventory)
            if item and item.instance_id == ctx.session.player.equipped_weapon_id:
                ctx.session.player.equipped_weapon_id = ""
                await _refresh_inventory_if_open(ctx)
                await _refresh_equipment_if_open(ctx)
                await post_display(ctx, f"You unequip {semantic_span(item.name, 'item')}.", msg_type=MessageType.PLAYER_ACTION)
                return
        if "disguise" in target or ctx.session.player.disguise:
            from .tutorial import stage_blocks_disguise_removal
            if getattr(ctx.session.player, "in_tutorial", False) and stage_blocks_disguise_removal(ctx.session.player):
                await post_display(ctx, "This is not the place to discard the uniform.", msg_type=MessageType.PLAYER_ACTION)
                from .tutorial import _send_tutorial_hint, STAGE_ACTIONS as _RM_STAGES
                stage = ctx.session.player.tutorial_stage
                _rm_action = _RM_STAGES.get(stage, {})
                if _rm_action:
                    await _send_tutorial_hint(ctx, stage, _rm_action, force_immediate=True)
                return
            had_disguise = bool(ctx.session.player.disguise)
            if not had_disguise:
                await post_display(ctx, loc("cmd_remove.no_disguise"), msg_type=MessageType.PLAYER_ACTION)
                return failure("remove_no_disguise")
            ctx.session.player.disguise = ""
            ctx.session.player.equipped_disguise_item_id = ""
            await _refresh_inventory_if_open(ctx)
            await _refresh_equipment_if_open(ctx)
            await post_display(ctx, "You remove your disguise.", msg_type=MessageType.PLAYER_ACTION)
            await play_sound(ctx, "disguise_remove", 0.6)
            return success(
                "remove",
                facts={"disguise_removed"},
                tutorial_event={"verb": "remove", "target": "disguise"},
            )

        await post_display(ctx, loc("cmd_remove.not_worn"), msg_type=MessageType.PLAYER_ACTION)
        return failure("remove_not_worn")


async def cmd_write_note(ctx: CommandContext, cmd: Command):
    text = cmd.indirect_obj or ""
    if not text:
        await post_display(ctx, loc("cmd_write_note.no_text"), msg_type=MessageType.PLAYER_ACTION)
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
    await post_display(ctx, loc("cmd_write_note.done"), msg_type=MessageType.PLAYER_ACTION)


async def cmd_leave_note(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj or cmd.direct_obj != "note":
        await post_display(ctx, loc("cmd_leave_note.usage"), msg_type=MessageType.PLAYER_ACTION)
        return

    note_item = None
    for item in ctx.session.player.inventory:
        if item.is_note:
            note_item = item
            break

    if not note_item:
        await post_display(ctx, loc("cmd_leave_note.no_note"), msg_type=MessageType.PLAYER_ACTION)
        return

    room = _room(ctx)
    if not room:
        return

    ctx.session.player.inventory.remove(note_item)
    room.items.append(note_item)
    await post_display(ctx, loc("cmd_leave_note.done"), msg_type=MessageType.PLAYER_ACTION)


async def cmd_yell(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        await post_display(ctx, loc("cmd_yell.no_message"), msg_type=MessageType.PLAYER_ACTION)
        return

    from .pathfinding import emit_sound, propagate_sound_detailed, SOUND_YELL
    from .constants import YELL_THREAT_KEYWORDS, YELL_RESISTANCE_KEYWORDS, YELL_WARNING_KEYWORDS

    message = cmd.direct_obj
    message_lower = message.lower()
    player_name = ctx.session.player.name
    room = _room(ctx)
    if not room:
        return

    threat_keywords = [kw for kw in YELL_THREAT_KEYWORDS if kw in message_lower]
    resistance_keywords = [kw for kw in YELL_RESISTANCE_KEYWORDS if kw in message_lower]
    warning_keywords = [kw for kw in YELL_WARNING_KEYWORDS if kw in message_lower]

    sound_event = emit_sound(
        room.id,
        "yell",
        intensity=SOUND_YELL,
        weather=getattr(ctx.shared, "weather", "clear"),
        game_time=ctx.shared.game_time,
        source_actor_id=ctx.session.username,
    )
    heard_rooms_detailed = propagate_sound_detailed(ctx.shared.world.rooms, sound_event)
    heard_rooms = [(room_id, perceived) for room_id, perceived, _hops in heard_rooms_detailed]
    election = _elect_sound_investigator(ctx.shared, heard_rooms_detailed)
    if election:
        _grant_sound_investigation(
            ctx.shared.world.npcs[election[0]], room.id, ctx.shared.game_time, "yell"
        )

    await broadcast_to_room(ctx, loc("social.yell").format(name=player_name, message=message), msg_type="social")

    for heard_room_id, perceived_intensity in heard_rooms:
        heard_room = ctx.shared.world.rooms.get(heard_room_id)
        if not heard_room:
            continue
        kempeitai_found = False
        for npc_id in heard_room.npcs:
            npc = ctx.shared.world.npcs.get(npc_id)
            if not npc:
                continue
            _update_npc_sound_memory(npc, room.id, perceived_intensity, "yell", ctx.shared.game_time, sound_event=sound_event)
            if npc.faction == "kempeitai":
                kempeitai_found = True

            current_day = ctx.shared.game_time.day
            if threat_keywords and npc.faction not in ("kempeitai", "green_gang"):
                npc_memory_system.record_interaction(
                    npc, player_name, "heard_threat_yell",
                    {"keywords": threat_keywords, "message": message}, current_day
                )
            if resistance_keywords and npc.faction in ("ccp", "gmd"):
                npc_memory_system.record_interaction(
                    npc, player_name, "heard_resistance_yell",
                    {"keywords": resistance_keywords, "message": message}, current_day
                )
            if warning_keywords and npc.faction == "ccp":
                npc_memory_system.record_interaction(
                    npc, player_name, "heard_warning_yell",
                    {"keywords": warning_keywords, "message": message}, current_day
                )

        if perceived_intensity >= 3:
            msg = f'You hear someone yell: "{message}"!'
        elif perceived_intensity >= 2:
            msg = f"You hear a distant yell from nearby."
        else:
            msg = f"You hear a faint noise from somewhere nearby."
        yell_semantic = MessageType.EVENT if (kempeitai_found or perceived_intensity >= 3) else MessageType.AMBIENT
        kempeitai_msg = " You hear footsteps moving toward the noise." if kempeitai_found else ""
        for session in ctx.session_manager.get_players_in_room(heard_room_id):
            if getattr(session, 'audio_enabled', True):
                volume = min(1.0, perceived_intensity / sound_event.intensity)
                await session.send_audio('yell', volume=volume, loop=False)
            await session.send_display(msg + kempeitai_msg + "\n", msg_type=yell_semantic)

    log_event(ctx, f"You yelled: \"{message}\"")
    return success("yell", facts={"yelled"}, tutorial_event={"verb": "yell", "target": cmd.direct_obj or ""})


async def cmd_sound(ctx: CommandContext, cmd: Command):
    arg = (cmd.direct_obj or cmd.preposition or "").lower()
    if arg in ("on", "yes", "true"):
        ctx.session.audio_enabled = True
        await post_display(ctx, loc("cmd_sound.on"), msg_type=MessageType.SYSTEM)
    elif arg in ("off", "no", "false"):
        ctx.session.audio_enabled = False
        await post_display(ctx, loc("cmd_sound.off"), msg_type=MessageType.SYSTEM)
    else:
        current = getattr(ctx.session, 'audio_enabled', False)
        await post_display(ctx, loc("cmd_sound.status").format(state="ON" if current else "OFF"), msg_type=MessageType.SYSTEM)


async def cmd_mod_weapon(ctx: CommandContext, cmd: Command):
    if not cmd.direct_obj:
        candidates = [_action_row(mod) for mod in _mod_candidates(ctx.session.player)]
        if not candidates:
            await post_display(ctx, "You have no compatible mods to attach.", msg_type=MessageType.PLAYER_ACTION)
            return failure("mod_weapon_no_candidates")
        await _open_item_action_chooser(ctx, "mod_weapon", "Attach what?", candidates, stage="mod", context={"expected_stage": "mod"})
        return success("mod_weapon_chooser", facts={"chooser_opened"})
    if not cmd.indirect_obj:
        await post_display(ctx, loc("cmd_mod.usage"), msg_type=MessageType.PLAYER_ACTION)
        return failure("mod_weapon_usage")

    weapon_name = cmd.direct_obj
    mod_name = cmd.indirect_obj

    weapon = find_item_exact(weapon_name, ctx.session.player.inventory)
    if not weapon or not weapon.is_weapon:
        await post_display(ctx, loc("cmd_mod.no_weapon"), msg_type=MessageType.PLAYER_ACTION)
        return failure("mod_weapon_no_weapon")

    mod = find_item_exact(mod_name, ctx.session.player.inventory)
    if not mod or not mod.is_mod:
        await post_display(ctx, loc("cmd_mod.no_mod"), msg_type=MessageType.PLAYER_ACTION)
        return failure("mod_weapon_no_mod")

    if mod.id == "extended_magazine" and weapon.weapon_type != "firearm":
        await post_display(ctx, "An extended magazine only fits a firearm.", msg_type=MessageType.PLAYER_ACTION)
        return failure("mod_weapon_incompatible")

    weapon.mods = getattr(weapon, 'mods', [])
    weapon.mod_slots = getattr(weapon, 'mod_slots', [])

    if len(weapon.mods) >= len(weapon.mod_slots):
        await post_display(ctx, loc("cmd_mod.no_slot"), msg_type=MessageType.PLAYER_ACTION)
        return failure("mod_weapon_no_slot")

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
    await post_display(ctx, loc("cmd_mod.success").format(mod=semantic_span(mod.name, "item"), weapon=semantic_span(weapon.name, "item"), type=mod.mod_type, bonus=mod.mod_bonus), msg_type=MessageType.PLAYER_ACTION)
    return success("mod_weapon", facts={"weapon_modded"})


async def cmd_search(ctx: CommandContext, cmd: Command):
    detail = cmd.direct_obj
    if not detail:
        await post_display(ctx, loc("cmd_search.usage"), msg_type=MessageType.PLAYER_ACTION)
        return

    room = _room(ctx)
    if not room:
        return

    detail_lower = detail.lower()

    is_tutorial_loose_brick = (
        getattr(ctx.session.player, "in_tutorial", False)
        and detail_lower == "loose brick"
        and any(drop.get("signal") == "loose brick" for drop in room.dead_drops)
    )
    base_chance = 100 if is_tutorial_loose_brick else 40 + (ctx.session.player.perception - 30)
    base_chance = max(10, min(100, base_chance))
    if random.randint(1, 100) > base_chance:
        await post_display(ctx, loc("cmd_search.nothing").format(detail=detail), msg_type=MessageType.PLAYER_ACTION)
        return failure("search_failed")

    for drop in room.dead_drops[:]:
        if drop["signal"] == detail_lower:
            recipient = drop.get("recipient", "")
            is_recipient = (
                recipient in (ctx.session.username.lower(), ctx.session.player.name.lower(), "")
            )
            if is_recipient:
                item = drop["item"]
                room.items.append(item)
                room.dead_drops.remove(drop)
                await ctx.session.send_completions(build_completions(ctx))
                await post_display(ctx, loc("cmd_search.found_drop").format(detail=detail, name=item.name), msg_type="discovery")
                await _send_room_details(ctx, room)
                return success(
                    "search",
                    facts={"found_drop"},
                    tutorial_event={"verb": "search", "target": cmd.direct_obj or ""},
                )

    if room.hidden_exits:
        perception_roll = ctx.session.player.perception + random.randint(1, 20)
        for direction, dest_id in room.hidden_exits.items():
            if detail_lower in direction.lower():
                if perception_roll >= 25:
                    room.exits[direction] = dest_id
                    grow_stat(ctx.session.player, "perception", STAT_GAIN_PERCEPTION_OBSERVE)
                    await post_display(ctx, loc("cmd_search.found_exit").format(direction=direction), msg_type="discovery")
                    return success(
                        "search",
                        facts={"found_exit"},
                        tutorial_event={"verb": "search", "target": cmd.direct_obj or ""},
                    )
                else:
                    await post_display(ctx, loc("perception.hidden_exit_sense").format(direction=direction), msg_type="ambient")
                    return
    
    search_signal = getattr(room, "search_signal", "")
    if search_signal and detail_lower == search_signal.lower():
        perception_roll = ctx.session.player.perception + random.randint(1, 20)
        if perception_roll >= 20:
            search_item_id = getattr(room, "search_item", "")
            item = ctx.shared.world.clone_item(search_item_id) if search_item_id else None
            if item is None:
                await post_display(ctx, loc("cmd_search.nothing").format(detail=detail), msg_type=MessageType.PLAYER_ACTION)
                return failure("search_nothing")
            room.items.append(item)
            grow_stat(ctx.session.player, "perception", STAT_GAIN_PERCEPTION_OBSERVE)
            room.search_signal = ""
            await post_display(ctx, loc("cmd_search.found_item").format(detail=detail, name=item.name), msg_type="discovery")
            await _send_room_details(ctx, room)
            return success(
                "search",
                facts={"found_item"},
                tutorial_event={"verb": "search", "target": cmd.direct_obj or ""},
            )
        else:
            await post_display(ctx, loc("room_hints.search_sense").format(detail=detail), msg_type="ambient")
            return failure("search_not_found")

    await post_display(ctx, loc("cmd_search.nothing").format(detail=detail), msg_type=MessageType.PLAYER_ACTION)
    return failure("search_nothing")


async def cmd_rumors(ctx: CommandContext, cmd: Command):
    from .rumors import rumors_panel_payload, send_panel_queue
    ctx.session.rumors_panel_generation += 1
    payload = rumors_panel_payload(
        ctx.shared,
        ctx.session.player,
        generation=ctx.session.rumors_panel_generation,
    )
    await ctx.session.send_rumor_web(payload)
    await send_panel_queue(ctx.session)
    await play_sound(ctx, "page_turn", 0.5)
    return success("rumors", facts={"rumors_read"}, tutorial_event={"verb": "rumors"})


async def advance_time_one_minute(ctx: CommandContext):
    from .tutorial import tutorial_blocks_world_events
    if tutorial_blocks_world_events(ctx.session.player):
        return
    ctx.shared.game_time.minute += 1
    if ctx.shared.game_time.minute >= 1440:
        ctx.shared.game_time.minute = 0
        ctx.shared.game_time.day += 1
        from .economy import economy_system
        economy_system.update_market_conditions(ctx.shared.game_time.day)

    effects = ctx.shared.scheduler.process(
        ctx.shared.game_time,
        lambda msg: asyncio.create_task(post_display(ctx, msg, msg_type=MessageType.AMBIENT)),
    )
    if any(effect.get("curfew_start") for effect in effects):
        await play_sound(ctx, "gong", volume=0.6)
    move_npcs_if_hour_changed(ctx)
    process_gossip(ctx)
    await check_planted_evidence(ctx)
    await process_tailing(ctx)
    if ctx.shared.game_time.minute % 15 == 0:
        await maybe_trigger_storylet(ctx)
    if ctx.shared.game_time.minute % 60 == 0 and ctx.shared.game_time.minute > 0:
        mm = ctx.shared.mission_manager
        if mm:
            expired = mm.check_expiry(ctx.session.player, ctx.shared.game_time.day)
            for mid in expired:
                await post_display(ctx, loc("mission.expired").format(id=mid), msg_type=MessageType.WARNING)
    process_survival_tick(ctx)

    is_dead, death_message = check_death_conditions(ctx)
    if is_dead:
        asyncio.create_task(handle_player_death(ctx, death_message))
        return

    if ctx.shared.game_time.minute == 0:
        asyncio.create_task(resolve_shared_liberation(ctx.shared, ctx.session_manager))
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
    from .rumors import process_gossip_room
    for room in ctx.shared.world.rooms.values():
        if room.id in getattr(ctx.shared, "cloned_tutorial_rooms", {}):
            continue
        process_gossip_room(ctx.shared, room)


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
                    from .rumors import publish_event_rumor
                    publish_event_rumor(
                        ctx.shared,
                        event_type="planted_evidence",
                        text=event_text,
                        location=room.id,
                        district=getattr(room, "district", ""),
                        witnesses=[],
                        faction_context=npc.faction,
                        created_day=ctx.shared.game_time.day,
                    )
                    await post_display(ctx, event_text, msg_type="ambient")
                    triggered = True
                    break
        if not triggered:
            remaining.append(planted)
    ctx.session.player.planted_evidence = remaining


async def process_tailing(ctx: CommandContext):
    from .equipment import advance_tail_clock, resolve_tail_step
    tail = ctx.session.player.tailing_state
    if not tail:
        return
    current_total = (ctx.shared.game_time.day - 1) * 1440 + ctx.shared.game_time.minute
    tail = advance_tail_clock(ctx.session.player, current_total)
    if not tail:
        return
    target = ctx.shared.world.npcs.get(tail.target_npc_id)
    from .constants import get_season
    season = get_season(ctx.shared.game_time.day)
    result = resolve_tail_step(
        ctx.session.player,
        target,
        tail,
        ctx.stealth,
        ctx.disguises,
        wanted_bonus=wanted_consequences(ctx.session.player.wanted_level).disguise_perception_bonus,
        current_room=_room(ctx),
        target_room=ctx.shared.world.npc_locations.get(target.id) if target else "",
        season=season,
    )
    if result.outcome == "vanished":
        await post_display(ctx, loc("cmd_tail.target_vanished"), msg_type="ambient")
    elif result.outcome == "challenge":
        await post_display(ctx, f"{target.name} challenges you and the tail ends.", msg_type="ambient")
    elif result.outcome == "exposed":
        await post_display(ctx, f"{target.name} sees through your disguise. The disguise is confiscated.", msg_type="ambient")
    elif result.outcome == "spotted":
        log_event(ctx, f"{target.name} spotted you while you were tailing them.")
        await post_display(ctx, loc("cmd_tail.spotted").format(name=target.name), msg_type="ambient")
    elif result.outcome == "lost":
        await post_display(ctx, f"You lose {target.name} in the streets.", msg_type="ambient")
    elif result.outcome == "moved":
        await post_display(ctx, loc("cmd_tail.shadowing").format(name=target.name), msg_type="ambient")
    if result.stage.name == "SUSPICION" and result.outcome in ("continued", "moved"):
        await post_display(ctx, f"{target.name} studies you but continues on.", msg_type="ambient")


def process_survival_tick(ctx: CommandContext):
    from .tutorial import tutorial_blocks_world_events
    if tutorial_blocks_world_events(ctx.session.player):
        return
    from .survival import apply_survival_tick
    apply_survival_tick(
        ctx.session.player,
        ctx.shared.game_time.minute,
        ctx.shared.game_time.day,
        send_display=lambda msg, msg_type=MessageType.AMBIENT, ctx=ctx: asyncio.create_task(post_display(ctx, msg, msg_type=msg_type)),
    )


async def cmd_claim(ctx: CommandContext, cmd: Command):
    from .trust import can_claim_faction_safehouse
    room = _room(ctx)
    if not room:
        await post_display(ctx, loc("cmd_claim.nothing"), msg_type=MessageType.PLAYER_ACTION)
        return
    if not getattr(room, "safe_room", False):
        await post_display(ctx, loc("cmd_claim.not_safe"), msg_type=MessageType.WARNING)
        return
    can_claim, error = can_claim_faction_safehouse(
        ctx.session.player.trust,
        getattr(room, "tags", []),
    )
    if not can_claim:
        await post_display(ctx, loc("cmd_claim.faction_low_trust").format(message=error), msg_type=MessageType.PLAYER_ACTION)
        return
    from .tutorial import tutorial_blocks_world_events
    if tutorial_blocks_world_events(ctx.session.player):
        ctx.session.player.claimed_safehouse_id = room.id
    else:
        set_safehouse(ctx.session.username, room.id)
    await post_display(ctx, loc("cmd_claim.success").format(title=room.title), msg_type="system")
    await play_sound(ctx, "success", 0.5)
    return success("claim", facts={"safehouse_claimed"}, tutorial_event={"verb": "claim"})


async def cmd_repair(ctx: CommandContext, cmd: Command):
    from .trust import has_faction_perk, TRUST_TIER_CONNECTED

    room = _room(ctx)
    if not room:
        await post_display(ctx, loc("cmd_repair.nowhere"), msg_type=MessageType.PLAYER_ACTION)
        return failure("repair_nowhere")

    room_tags = getattr(room, "tags", [])
    if "gmd_safehouse" not in room_tags:
        await post_display(ctx, loc("cmd_repair.not_gmd_safehouse"), msg_type=MessageType.PLAYER_ACTION)
        return failure("repair_not_gmd_safehouse")

    weapon_name = cmd.direct_obj
    if not weapon_name:
        candidates = [_action_row(weapon) for weapon in _repairable_weapons(ctx.session.player)]
        if not candidates:
            await post_display(ctx, "You have no damaged weapons to repair.", msg_type=MessageType.PLAYER_ACTION)
            return failure("repair_no_candidates")
        await _open_item_action_chooser(ctx, "repair", "Repair what?", candidates)
        return success("repair_chooser", facts={"chooser_opened"})
    weapon = find_item_exact(weapon_name, ctx.session.player.inventory)
    if not weapon:
        await post_display(ctx, loc("cmd_repair.weapon_not_found"), msg_type=MessageType.PLAYER_ACTION)
        return failure("repair_weapon_not_found")

    if not weapon.is_weapon:
        await post_display(ctx, loc("cmd_repair.not_a_weapon"), msg_type=MessageType.PLAYER_ACTION)
        return failure("repair_not_a_weapon")

    if weapon.durability == -1 or weapon.max_durability <= 0:
        await post_display(ctx, loc("cmd_repair.indestructible"), msg_type=MessageType.PLAYER_ACTION)
        return failure("repair_indestructible")

    if weapon.durability >= weapon.max_durability:
        await post_display(ctx, loc("cmd_repair.already_repaired"), msg_type=MessageType.PLAYER_ACTION)
        return failure("repair_already_repaired")

    is_ally = has_faction_perk(ctx.session.player.trust, "gmd")

    if is_ally:
        weapon.durability = weapon.max_durability
        await post_display(ctx, loc("cmd_repair.ally_success").format(weapon=semantic_span(weapon.name, "item")), msg_type=MessageType.PLAYER_ACTION)
        await play_sound(ctx, "repair", 0.6)
        log_event(ctx, f"Your {weapon.name} was repaired by the GMD armorer for free.")
    else:
        damage = weapon.max_durability - weapon.durability
        cost = damage * 5

        if not can_afford_fabi(ctx.session.player, cost):
            await post_display(ctx, loc("cmd_repair.cannot_afford").format(cost=cost), msg_type=MessageType.PLAYER_ACTION)
            return failure("repair_cannot_afford")

        spend_fabi_value(ctx.session.player, cost)
        weapon.durability = weapon.max_durability
        await post_display(ctx, loc("cmd_repair.paid_success").format(weapon=weapon.name, cost=cost), msg_type="system")
        log_event(ctx, f"Your {weapon.name} was repaired for {cost} fabi.")
    return success("repair", facts={"weapon_repaired"})


async def cmd_season(ctx: CommandContext, cmd: Command):
    from .constants import (
        SEASONAL_MORALE_MODIFIER,
        SEASONAL_STEALTH_MODIFIER,
        SEASONAL_PERCEPTION_MODIFIER,
        SEASONAL_PRICE_MULTIPLIER,
        SEASONAL_PATROL_DENSITY,
        SEASONAL_FOOD_SHORTAGE,
    )
    from .victory import _season_from_day

    current_day = ctx.shared.game_time.day
    season = _season_from_day(current_day)

    lines = [f"Current season: {season.capitalize()} (Day {current_day})"]
    lines.append("")

    modifiers = []

    morale_mod = SEASONAL_MORALE_MODIFIER.get(season, 0)
    if morale_mod != 0:
        sign = "+" if morale_mod > 0 else ""
        modifiers.append(f"{sign}{morale_mod} morale/hour")

    stealth_mod = SEASONAL_STEALTH_MODIFIER.get(season, 0)
    if stealth_mod != 0:
        sign = "+" if stealth_mod > 0 else ""
        modifiers.append(f"{sign}{stealth_mod} stealth")

    perception_mod = SEASONAL_PERCEPTION_MODIFIER.get(season, 0)
    if perception_mod != 0:
        sign = "+" if perception_mod > 0 else ""
        modifiers.append(f"{sign}{perception_mod} perception")

    price_mult = SEASONAL_PRICE_MULTIPLIER.get(season, 1.0)
    if price_mult != 1.0:
        modifiers.append(f"Prices ×{price_mult}")

    patrol_mod = SEASONAL_PATROL_DENSITY.get(season, 1.0)
    if patrol_mod != 1.0:
        modifiers.append(f"Patrol opportunity density ×{patrol_mod}")

    food_shortage = SEASONAL_FOOD_SHORTAGE.get(season, 1.0)
    if food_shortage != 1.0 and food_shortage < 1.0:
        modifiers.append(f"Food restock ×{food_shortage}")

    if modifiers:
        lines.append("Active effects:")
        for mod in modifiers:
            lines.append(f"  - {mod}")
    else:
        lines.append("No active seasonal effects.")

    lines.append("Curfew remains 20:00-06:00. Arrest probability is season-independent.")

    await post_display(ctx, "\n".join(lines), msg_type=MessageType.PLAYER_STATUS)


def _trust_tier(value: int) -> str:
    if value >= 70:
        return "Connected"
    elif value >= 50:
        return "Trusted"
    elif value >= 30:
        return "Neutral"
    else:
        return "Hostile"


async def cmd_bribe(ctx: CommandContext, cmd: Command):
    import random
    from .constants import CURFEW_IMMUNITY_DURATION_MINUTES

    p = ctx.session.player
    current_day = ctx.shared.game_time.day

    target = cmd.direct_obj or ""
    if target.lower() in ("immunity", "curfew", "pass"):
        room = _room(ctx)
        if not is_curfew(ctx.shared.game_time.minute):
            await post_display(ctx, "Curfew immunity is available only during curfew.", msg_type=MessageType.PLAYER_ACTION)
            return failure("bribe_curfew_inactive")
        if not room or room.indoors:
            await post_display(ctx, "You must be outdoors to buy curfew immunity.", msg_type=MessageType.PLAYER_ACTION)
            return failure("bribe_curfew_indoors")
        world = getattr(ctx.shared, "world", None)
        kempeitai_present = any(
            (npc := world.npcs.get(npc_id))
            and not is_named_npc_dead(ctx.shared, npc_id)
            and npc.faction == "kempeitai"
            and world.npc_locations.get(npc_id) == room.id
            for npc_id in getattr(room, "npcs", [])
        ) if world else False
        if not kempeitai_present:
            await post_display(ctx, loc("cmd_bribe.no_kempeitai"), msg_type=MessageType.PLAYER_ACTION)
            return failure("bribe_curfew_no_kempeitai")
        if not can_afford_fabi(p, 100):
            await post_display(ctx, "Curfew immunity costs 100 fabi.", msg_type=MessageType.PLAYER_ACTION)
            return failure("bribe_curfew_cannot_afford")

        spend_fabi_value(p, 100)
        p.curfew_immunity_expires_at = game_clock_total_minutes(ctx.shared.game_time) + CURFEW_IMMUNITY_DURATION_MINUTES
        await post_display(ctx, "The officer nods and slips you a paper. You have curfew immunity for 30 minutes.", msg_type=MessageType.EVENT)
        log_event(ctx, "Purchased 30 minutes of curfew immunity for 100 fabi.")
        return success("bribe_curfew_immunity", facts={"curfew_immunity"})

    if target and not target.isdigit():
        await post_display(ctx, "Choose IMMUNITY, CURFEW, PASS, or a wanted-reduction amount.", msg_type=MessageType.PLAYER_ACTION)
        return failure("bribe_invalid_target")

    if p.wanted_level <= 0:
        await post_display(ctx, loc("cmd_bribe.not_wanted"), msg_type=MessageType.PLAYER_ACTION)
        return failure("bribe_not_wanted")

    if p.last_wanted_bribe_day == current_day:
        await post_display(ctx, loc("cmd_bribe.cooldown"), msg_type=MessageType.PLAYER_ACTION)
        return failure("bribe_wanted_cooldown")

    room = _room(ctx)
    if not room or not room.npcs:
        await post_display(ctx, loc("cmd_bribe.no_kempeitai"), msg_type=MessageType.PLAYER_ACTION)
        return failure("bribe_wanted_no_kempeitai")

    kempeitai_present = False
    for npc_id in room.npcs:
        npc = ctx.shared.world.npcs.get(npc_id)
        if npc and npc.faction == "kempeitai":
            kempeitai_present = True
            break

    if not kempeitai_present:
        await post_display(ctx, loc("cmd_bribe.no_kempeitai"), msg_type=MessageType.PLAYER_ACTION)
        return failure("bribe_wanted_no_kempeitai")

    amount_str = cmd.direct_obj
    if amount_str:
        try:
            amount = int(amount_str)
            if amount < 50 or amount > 100:
                await post_display(ctx, loc("cmd_bribe.invalid_amount"), msg_type=MessageType.PLAYER_ACTION)
                return failure("bribe_wanted_invalid_amount")
        except ValueError:
            await post_display(ctx, loc("cmd_bribe.invalid_amount"), msg_type=MessageType.PLAYER_ACTION)
            return failure("bribe_wanted_invalid_amount")
    else:
        amount = 50

    if not can_afford_fabi(p, amount):
        await post_display(ctx, loc("cmd_bribe.cannot_afford").format(amount=amount), msg_type=MessageType.PLAYER_ACTION)
        return failure("bribe_wanted_cannot_afford")

    spend_fabi_value(p, amount)
    p.last_wanted_bribe_day = current_day

    if random.random() < 0.5:
        adjust_wanted(p, -1)
        await post_display(ctx, loc("cmd_bribe.success").format(amount=amount), msg_type=MessageType.EVENT)
        await play_sound(ctx, "coin_clink", 0.7)
        log_event(ctx, f"Paid {amount} fabi bribe to reduce wanted level to {p.wanted_level}.")
        return success("bribe_wanted_reduction", facts={"wanted_reduced"})
    else:
        _record_crime(ctx)
        await post_display(ctx, loc("cmd_bribe.backfire").format(amount=amount), msg_type=MessageType.WARNING)
        log_event(ctx, f"Bribe backfired! Wanted level increased to {p.wanted_level}.")
        return failure("bribe_wanted_backfire")


async def cmd_favor(ctx: CommandContext, cmd: Command):
    from .trust import get_role_trust
    from .constants import WANTED_LEVEL_MAX

    p = ctx.session.player
    current_day = ctx.shared.game_time.day

    if p.wanted_level <= 0:
        await post_display(ctx, loc("cmd_favor.not_wanted"), msg_type=MessageType.PLAYER_ACTION)
        return

    if p.last_wanted_favor_day == current_day:
        await post_display(ctx, loc("cmd_favor.cooldown"), msg_type=MessageType.PLAYER_ACTION)
        return

    room = _room(ctx)
    if not room:
        await post_display(ctx, loc("cmd_favor.nowhere"), msg_type=MessageType.PLAYER_ACTION)
        return

    room_tags = getattr(room, "tags", [])
    valid_faction = None

    if "ccp_safehouse" in room_tags:
        ccp_trust = get_role_trust(p.trust, "ccp", None)
        if ccp_trust >= 70:
            valid_faction = "ccp"
        else:
            await post_display(ctx, loc("cmd_favor.low_trust").format(faction="CCP", trust=ccp_trust), msg_type=MessageType.PLAYER_ACTION)
            return
    elif "gmd_safehouse" in room_tags:
        gmd_trust = get_role_trust(p.trust, "gmd", None)
        if gmd_trust >= 70:
            valid_faction = "gmd"
        else:
            await post_display(ctx, loc("cmd_favor.low_trust").format(faction="GMD", trust=gmd_trust), msg_type=MessageType.PLAYER_ACTION)
            return
    else:
        await post_display(ctx, loc("cmd_favor.not_safehouse"), msg_type=MessageType.PLAYER_ACTION)
        return

    adjust_wanted(p, -1)
    p.last_wanted_favor_day = current_day

    for role in p.trust.get(valid_faction, {}):
        p.trust[valid_faction][role] = max(0, p.trust[valid_faction][role] - 10)

    await post_display(ctx, loc("cmd_favor.success").format(faction=valid_faction.upper()), msg_type=MessageType.EVENT)
    log_event(ctx, f"Used {valid_faction.upper()} favor to reduce wanted level to {p.wanted_level}.")


async def _withdraw_stash_all(ctx: CommandContext) -> None:
    from .lifecycle import retrieve_successor_stash
    room = _room(ctx)
    try:
        stash, remaining = retrieve_successor_stash(ctx.session, room.id if room else "")
    except ValueError:
        await post_display(ctx, loc("cmd_retrieve.wrong_place"), msg_type=MessageType.PLAYER_ACTION)
        return
    if not stash:
        await post_display(ctx, loc("cmd_retrieve.empty"), msg_type=MessageType.PLAYER_ACTION)
        return
    recovered = [item.name for item in stash]
    await play_sound(ctx, "stash", 0.6)
    await post_display(ctx, loc("cmd_retrieve.success").format(items=', '.join(recovered)), msg_type="discovery")


async def cmd_retrieve(ctx: CommandContext, cmd: Command):
    from .auth import get_stash, resolve_spawn_room
    from .lifecycle import authorized_session_save_key
    from .popup_payloads import room_key_for_client, send_popup, stash_payload
    from .serialization import deserialize_item
    safehouse = resolve_spawn_room(ctx.session.username)
    room = _room(ctx)
    if not safehouse or not room or room.id != safehouse:
        await post_display(ctx, loc("cmd_retrieve.wrong_place"), msg_type=MessageType.PLAYER_ACTION)
        return
    if not authorized_session_save_key(ctx.session):
        await post_display(ctx, loc("cmd_retrieve.wrong_place"), msg_type=MessageType.PLAYER_ACTION)
        return
    room_key = room_key_for_client(ctx)
    ctx.session.set_open_popup("stash", {"room_key": room_key, "safehouse_id": safehouse})
    stash_items = [deserialize_item(data) for data in get_stash(ctx.session.username)]
    await send_popup(ctx.session, "stash_menu", stash_payload(
        safehouse_name=room.title,
        room_key=room_key,
        items=stash_items,
        generation=ctx.session.open_popup["generation"],
    ))


async def cmd_trust(ctx: CommandContext, cmd: Command):
    player = ctx.session.player
    trust = player.trust
    lines = [
        "Your trust levels with each faction are displayed in the sidebar.",
        f"  CCP: {trust.get('ccp', 0)}",
        f"  GMD: {trust.get('gmd', 0)}",
        f"  Green Gang: {trust.get('green_gang', 0)}",
        f"  Kempeitai: {trust.get('kempeitai', 0)}",
        f"  French Concession: {trust.get('french', 0)}",
    ]
    await post_display(ctx, "\n".join(lines), msg_type=MessageType.PLAYER_STATUS)
    return success("trust", facts={"trust_read"}, tutorial_event={"verb": "trust"})


async def cmd_wanted(ctx: CommandContext, cmd: Command):
    player = ctx.session.player
    policy = wanted_consequences(player.wanted_level)
    messages = {
        "neutral": "You are not being hunted.",
        "nervous": "Patrols may stop and question you.",
        "hostile": "Kempeitai are actively searching for you.",
    }
    if policy.npc_may_flee:
        messages["hostile"] = "Kempeitai are actively searching for you. Some witnesses may flee."
    msg = (
        "Your wanted level is shown in the sidebar.\n"
        f"Current wanted level: {policy.level} - {messages[policy.npc_tone]}"
    )
    await post_display(ctx, msg, msg_type=MessageType.PLAYER_STATUS)
    return success("wanted", facts={"wanted_read"}, tutorial_event={"verb": "wanted"})


async def cmd_stub(ctx: CommandContext, cmd: Command):
    await post_display(ctx, loc("cmd.unknown"), msg_type=MessageType.ERROR)


async def cmd_memorial(ctx: CommandContext, cmd: Command):
    lines = ["SHANGHAI MEMORIAL — Those who have fallen:"]
    entries = []

    for player_name, journal in getattr(ctx.shared, 'archived_journals', {}).items():
        if journal:
            day = journal[-1].get("day", 0) if isinstance(journal[-1], dict) else 0
            entries.append((day, f"[Day {day}] {player_name} — their journey ended in Shanghai."))

    mission_targets = {
        objective.target
        for mission in getattr(ctx.shared.mission_manager, "missions", {}).values()
        for objective in mission.objectives
        if objective.type in ("deliver_to_npc", "talk_to_npc", "kill_npc")
    }
    for npc_id, record in sorted(getattr(ctx.shared, "named_npc_deaths", {}).items()):
        notable = bool(
            record.historical
            or record.faction_leader
            or npc_id in mission_targets
        )
        if notable:
            entries.append((record.day, f"[Day {record.day}] {record.npc_name} ({record.npc_faction}), killed."))

    entries.sort(key=lambda x: -x[0])
    for _, entry in entries[:20]:
        lines.append(entry)

    if not entries:
        lines.append("None. The city remembers nothing.")

    await post_display(ctx, "\n".join(lines), msg_type="system")
    return success("memorial", facts={"memorial_read"})


_COMMAND_REGISTRY = None


def build_command_registry() -> Dict[str, Callable]:
    global _COMMAND_REGISTRY
    if _COMMAND_REGISTRY is None:
        _COMMAND_REGISTRY = _build_command_registry()

    return _COMMAND_REGISTRY


def _build_command_registry() -> Dict[str, Callable]:
    handlers = {
            "look": cmd_look,
            "go": cmd_go,
            "take": cmd_take,
            "drop": cmd_drop,
            "inventory": cmd_inventory,
            "talk to": cmd_talk_to,
            "ask about": cmd_ask_about,
            "help": cmd_help,
            "quit": cmd_quit,
            "status": cmd_status,
            "disguise as": cmd_disguise_as,
            "tail": cmd_tail,
        "stop": cmd_stop_tail,
            "hide": cmd_hide,
            "plant": cmd_plant,
            "read": cmd_read,
            "journal": cmd_journal,
            "ask": cmd_ask_about,
            "whisper": cmd_whisper,
            "give": cmd_give,
            "eat": cmd_eat,
            "bond": cmd_bond,
            "say": cmd_say,
            "attack": cmd_attack,
            "buy from": cmd_buy_from,
            "sell": cmd_sell,
            "pickpocket": cmd_pickpocket,
            "equip": cmd_equip,
            "missions": cmd_missions,
            "search": cmd_search,
            "examine": cmd_examine,
            "remove": cmd_remove,
            "open": cmd_open,
            "take from": cmd_take_from,
            "write note": cmd_write_note,
            "leave note": cmd_leave_note,
            "mod weapon": cmd_mod_weapon,
            "yell": cmd_yell,
            "sound": cmd_sound,
            "rumors": cmd_rumors,
            "rumours": cmd_rumors,
            "claim": cmd_claim,
            "retrieve": cmd_retrieve,
            "repair": cmd_repair,
            "unhide": cmd_unhide,
            "season": cmd_season,
            "bribe": cmd_bribe,
            "favor": cmd_favor,
            "assess": cmd_assess,
            "skip tutorial": cmd_skip_tutorial,
            "trust": cmd_trust,
            "wanted": cmd_wanted,
            "memorial": cmd_memorial,
            "unknown": cmd_stub,
        }
    for verb in _COMMAND_DEFS:
        if verb not in handlers:
            raise RuntimeError(f"command schema defines {verb} without a handler")
    for verb in handlers:
        if verb not in _COMMAND_DEFS and verb not in ("unknown", "stub"):
            raise RuntimeError(f"handler {verb} has no command schema definition")
    registry = {verb: handlers[verb] for verb in _COMMAND_DEFS}
    registry["unknown"] = handlers["unknown"]
    return registry


def _durability_snapshot(item):
    durability = getattr(item, "durability", -1) if item else -1
    return (item, durability) if durability > = 0 else None


def _warehouse_attack_feedback_enabled(ctx: CommandContext) -> bool:
    player = ctx.session.player
    if not getattr(player, "in_tutorial", False) or getattr(player, "tutorial_stage", 0) !=25:
        return False
    from .tutorial import get_original_tutorial_room_id
    return get_original_tutorial_room_id(
        getattr(player, "tutorial_instance_id", ""),
        getattr(player, "current_room", ""),
        ctx.shared,
    ) == "refugee_entry_warehouse"


def _warehouse_durability_change(snapshot):
    if not snapshot:
        return None
    item, before = snapshot
    after = getattr(item, "durability", before)
    if after == before:
        return None
    return item, before, after


async def _send_warehouse_durability_feedback(ctx: CommandContext, snapshots) -> None:
    if not _warehouse_attack_feedback_enabled(ctx):
        return
    for change in (_warehouse_durability_change(snapshot) for snapshot in snapshots):
        if not change:
            continue
        item, before, after = change
        name = " ".join(part[:1].upper() + part[1:] for part in item.name.split())
        await post_display(
            ctx,
            f"{name} condition: {before} -> {after}",
            msg_type=MessageType.COMBAT_NARRATION,
        )


GLOBAL_AMBIENCE_SOUND = "ambient_city"
GLOBAL_AMBIENCE_VOLUME = 0.18

async def _sync_global_ambience(ctx: CommandContext) -> None:
    current = getattr(ctx.session, "_audio_global_ambience_name", None)
    if current == GLOBAL_AMBIENCE_SOUND:
        return
    if current:
        await ctx.session.send_audio(f"{current}_stop")
    await ctx.session.send_audio(
        f"{GLOBAL_AMBIENCE_SOUND}_start",
        volume=GLOBAL_AMBIENCE_VOLUME,
        loop=True,
    )
    ctx.session._audio_global_ambience_name = GLOBAL_AMBIENCE_SOUND