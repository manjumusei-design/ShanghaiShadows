from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple
from uuid import uuid4

from .stealth import Disguise, PierceStage, StealthSystem


@dataclass(frozen=True)
class TailResolution:
    outcome: str
    stage: PierceStage
    moved: bool = False
    gained_stealth: bool = False


def advance_tail_clock(player: Any, current_total: int):
    tail = getattr(player, "tailing_state", None)
    if not tail or current_total - tail.last_checked_minute < 5:
        return None
    tail.last_checked_minute = current_total
    tail.elapsed_minutes += 5
    return tail


def ensure_items_identity(items) -> None:
    counts = {}
    for item in items:
        counts[item.id] = counts.get(item.id, 0) + 1
    for item in items:
        identity = getattr(item, "instance_id", "") or ""
        if not identity:
            item.instance_id = item.id if counts[item.id] == 1 else f"{item.id}:{uuid4().hex}"
        elif identity == item.id and counts[item.id] > 1:
            item.instance_id = f"{item.id}:{uuid4().hex}"


def ensure_inventory_identity(player: Any) -> None:
    inventory = getattr(player, "inventory", [])
    slots = {
        "equipped_weapon_id": getattr(player, "equipped_weapon_id", "") or "",
        "worn_armour_id": getattr(player, "worn_armour_id", "") or "",
        "equipped_disguise_item_id": getattr(player, "equipped_disguise_item_id", "") or "",
    }
    before = {id(item): getattr(item, "instance_id", "") or "" for item in inventory}
    ensure_items_identity(inventory)
    for attr, old_id in slots.items():
        if not old_id:
            continue
        holder = next((item for item in inventory if before.get(id(item)) == old_id), None)
        if holder is not None and holder.instance_id != old_id:
            setattr(player, attr, holder.instance_id)


def equipped_item(player: Any, item_id: str):
    ensure_inventory_identity(player)
    if not item_id:
        return None
    exact = next((item for item in getattr(player, "inventory", []) if item.instance_id == item_id), None)
    return exact


def equipped_weapon(player: Any):
    item = equipped_item(player, getattr(player, "equipped_weapon_id", ""))
    return item if item and item.is_weapon else None


def equipped_disguise(player: Any, disguises: Optional[Mapping[str, Disguise]] = None) -> Optional[Tuple[Any, Disguise]]:
    identity = getattr(player, "disguise", "")
    if not identity or disguises is None:
        return None
    item = equipped_item(player, getattr(player, "equipped_disguise_item_id", ""))
    if not item or item.disguise_id != identity or identity not in disguises:
        return None
    return (item, disguises[identity])


def invalidate_disguise_if_support_lost(player: Any, item: Any) -> bool:
    if not item or getattr(item, "instance_id", "") != getattr(player, "equipped_disguise_item_id", ""):
        return False
    player.equipped_disguise_item_id = ""
    player.disguise = ""
    return True


def confiscate_equipped_disguise(player: Any):
    item_id = getattr(player, "equipped_disguise_item_id", "")
    item = equipped_item(player, item_id)
    if item is not None:
        player.inventory.remove(item)
    player.equipped_disguise_item_id = ""
    player.disguise = ""
    return item


def end_tailing(player: Any) -> bool:
    had_tail = getattr(player, "tailing_state", None) is not None
    player.tailing_state = None
    return had_tail


def resolve_disguised_tail_pierce(
    player: Any,
    target: Any,
    disguise: Disguise,
    *,
    wanted_bonus: int,
    stealth: Optional[StealthSystem] = None,
    season: str = "spring",
) -> PierceStage:
    system = stealth or StealthSystem({})
    target_bonus = 15 if getattr(target, "is_historical_figure", False) or getattr(target, "faction_leader", False) else 0
    defense_bonus = int(getattr(target, "disguise_detection_modifier", 0) or 0)
    wanted_level = max(0, int(wanted_bonus) // 10)
    return system.disguise_pierce_check(
        target,
        disguise.bonus,
        wanted_level,
        season,
        perception_bonus=target_bonus,
        defense_bonus=defense_bonus,
    )


def resolve_tail_step(
    player: Any,
    target: Any,
    tail: Any,
    stealth: StealthSystem,
    disguises: Mapping[str, Disguise],
    *,
    wanted_bonus: int,
    current_room: Any = None,
    target_room: str = "",
    season: str = "spring",
) -> TailResolution:
    if target is None:
        end_tailing(player)
        return TailResolution("vanished", PierceStage.NONE)
    resolved = equipped_disguise(player, disguises)
    if resolved:
        stage = resolve_disguised_tail_pierce(
            player,
            target,
            resolved[1],
            wanted_bonus=wanted_bonus,
            stealth=stealth,
            season=season,
        )
        if stage == PierceStage.CHALLENGE:
            end_tailing(player)
            return TailResolution("challenge", stage)
        if stage == PierceStage.EXPOSED:
            end_tailing(player)
            confiscate_equipped_disguise(player)
            return TailResolution("exposed", stage)
    else:
        stage = PierceStage.NONE
    success, _ = stealth.tail_check(
        tail,
        target,
        player.stealth_skill,
        resolved[1].bonus if resolved else 0,
        player.hidden,
        season=season,
        hunger=player.hunger,
    )
    if not success and tail.distance <= 0:
        end_tailing(player)
        player.world_events.append(f"{target.name} spotted you while you were tailing them.")
        player.world_events = player.world_events[-50:]
        return TailResolution("spotted", stage)
    if success and target_room and player.current_room != target_room:
        if not current_room or target_room not in current_room.exits.values():
            end_tailing(player)
            return TailResolution("lost", stage)
        player.current_room = target_room
        player.hidden = False
        gained = False
        if not tail.stealth_awarded:
            tail.stealth_awarded = True
            from .player_data import grow_stat
            from .constants import STAT_GAIN_STEALTH_TAIL
            grow_stat(player, "stealth_skill", STAT_GAIN_STEALTH_TAIL)
            gained = True
        return TailResolution("moved", stage, moved=True, gained_stealth=gained)
    return TailResolution("continued", stage)
