import random
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Literal, Mapping, TYPE_CHECKING

from .constants import CURFEW_MINUTE
from .equipment import ensure_inventory_identity, equipped_disguise
from .law import calculate_curfew_arrest_chance, is_curfew_minute
from .trust import FACTION_SAFEHOUSE_TRUST, get_role_trust

if TYPE_CHECKING:
    from .commands import CommandContext
    from .player_data import PlayerData
    from .stealth import Disguise
    from .time_system import GameTime
    from .world import Room


class CurfewTrigger(str, Enum):
    PATROL_CONTACT = "patrol_contact"
    DISGUISE_EXPOSURE = "disguise_exposure"


@dataclass(frozen=True)
class CurfewResolution:
    status: Literal[
        "ineligible",
        "immune",
        "already_checked",
        "miss",
        "execution",
        "imprisonment",
        "warning_release",
    ]
    trigger: CurfewTrigger
    night_key: int | None
    chance: int | None
    consumed_roll: bool
    confiscated_item_ids: tuple[str, ...] = ()


def curfew_night_key(game_time: "GameTime") -> int | None:
    minute = int(game_time.minute) % 1440 + int(game_time.minute)


def curfew_night_key(game_time: "GameTime") -> int | None:
    minute = int(game_time.minute) % 1440
    if not is_curfew_minute(minute):
        return None
    if minute >= CURFEW_MINUTE:
        return int(game_time.day)
    return int(game_time.day) - 1


def curfew_immunity_active(player: "PlayerDatta", game_time: "GameTime") -> bool:
    try:
        expiry = int(getattr(player, "curfew_immunity_expires_at", -1))
    except (TypeError, ValueError):
        return False
    return game_clock_total_minutes(game_time) < expiry


def _clamp_percent(value: int) -> int:
    return max(0, min(100, int(value)))


def _has_matching_safehouse(room: "Room", faction: str) -> bool:
    return any(
        FACTION_SAFEHOUSE_TRUST.get(tag, (None, None))[0] == faction
        for tag in getattr(room, "tags", [])
    )


def curfew_arrest_chance(
        player: "PlayerData",
        room: "Room",
        disguises: Mapping[str, "Disguise"],
) -> int:
    base = _clamp_percent(calculate_curfew_arrest_chance(player))
    resolved = equipped_disguise(player, disguises)
    if resolved:
        _, disguise = resolved
        if disguise.apparent_faction == "kempeitai":
            base = int(base * 0.5)
        elif _has_matching_safehouse(room, disguise.apparent_faction):
            base = int(base * 0.7)

    ensure_inventory_identity(player)
    flagged_item_ids = {
        getattr(item, "instance_id", "") or getattr(item, "id", "")
        for item in getattr(player, "inventory", [])
        if getattr(item, "contraband_risk", False) or getattr(item, "evidence", False)
    }
    return _clamp_percent(base + 10 * len(flagged_item_ids))


def _context_room(ctx: "CommandContext"):
    room = getattr(ctx, "room", None)
    if room is not None:
        return room
    player =  ctx.session.player
    world = getattr(ctx.shared, "world", None)
    getter = getattr(world, "get_room", None)
    return getter(player.current_room) if getter else None


def _tutorial_protected(player: "PlayerData") -> bool:
    return bool(
        getattr(player, "in_tutorial", False)
        or getattr(player, "tutorial_choice_pending", False)
    )


def _inventory_instance_ids(player: "PlayerData") -> tuple[str, ...]:
    ensure_inventory_identity(player)
    return tuple(
        getattr(item, "instance_id", "") or getattr(item, "id", "")
        for item in getattr(player, "inventory", [])
    )


def _confiscate_inventory(player: "PlayerData") -> tuple[str, ...]:
    confiscated_item_ids = _inventory_instance_ids(player)
    confiscated = set(confiscated_item_ids)
    player.inventory.clear()
    for field_name in ("equipped_weapon_id", "worn_armour_id", "equipped_disguise_item_id"):
        if getattr(player, field_name, "") in confiscated:
            setattr(player, field_name, "")
    if not player.equipped_disguise_item_id:
        player.disguise = ""
    return confiscated_item_ids


async def _default_advance_minutes(ctx: "CommandContext", minutes: int) -> None:
    from .commands import _advance_time_manual
    await _advance_time_manual(ctx, minutes)


async def _default_execute_player(ctx: "CommandContext", status: str) -> None:
    if not hasattr(ctx, "session_manager"):
        return
    from .commands import handle_player_death
    from .locales import get as loc
    await handle_player_death(ctx, loc("death.execution"))


def _outcome_for_trust(player: "PlayerData") -> str:
    trust = get_role_trust(getattr(player, "trust", {}), "kempeitai", None)
    if trust < 25:
        return "execution"
    if trust < 50:
        return "imprisonment"
    return "warning_release"


async def resolve_curfew_encounter(
    ctx: "CommandContext",
    trigger: "CurfewTrigger",
    *,
    randint: Callable[[int, int], int] = random.randint,
    advance_minutes: Callable[["CommandContext", int], Awaitable[None]] | None = None,
    execute_player: Callable[["CommandContext", str], Awaitable[None]] | None = None,
) -> CurfewResolution:
    trigger = CurfewTrigger(trigger)
    player = ctx.session.player
    game_time = ctx.shared.game_time
    night_key = curfew_night_key(game_time)
    if night_key is None:
        return CurfewResolution("ineligible", trigger, None, None, False)
    room = _context_room(ctx)
    if room is None or getattr(room, "indoors", False):
        return CurfewResolution("ineligible", trigger, night_key, None, False)
    if _tutorial_protected(player):
        return CurfewResolution("ineligible", trigger, night_key, None, False)
    if trigger == CurfewTrigger.PATROL_CONTACT and getattr(player, "hidden", False):
        return CurfewResolution("ineligible", trigger, night_key, None, False)
    if curfew_immunity_active(player, game_time):
        return CurfewResolution("immune", trigger, night_key, None, False)
    if getattr(player, "last_curfew_night_key", None) == night_key:
        return CurfewResolution("already_checked", trigger, night_key, None, False)

    chance = curfew_arrest_chance(player, room, getattr(ctx, "disguises", {}))
    player.last_curfew_night_key = night_key
    roll = randint(1, 100)
    if roll > chance:
        return CurfewResolution("miss", trigger, night_key, chance, True)

    status = _outcome_for_trust(player)
    if status == "execution":
        execute_handler = execute_player or _default_execute_player
        await execute_handler(ctx, status)
        confiscated = ()
    elif status == "imprisonment":
        confiscated = _confiscate_inventory(player)
        advance_handler = advance_minutes or _default_advance_minutes
        await advance_handler(ctx, 1440)
    else:
        from .economy import set_wallet_fabi_value
        set_wallet_fabi_value(player, 0)
        confiscated = ()
    return CurfewResolution(status, trigger, night_key, chance, True, confiscated)
