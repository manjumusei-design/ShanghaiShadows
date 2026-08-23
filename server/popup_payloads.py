import json
from typing import Any, Dict, List


def journal_payload(ctx: Any, generation: int) -> Dict[str, Any]:
    from .journal import (
        JOURNAL_CONVERSATION_LIMIT,
        JOURNAL_RECENT_HOURS,
        collect_recent_events,
        format_journal_summary,
        normalize_conversation_history,
        project_journal_intel,
        project_testimonies,
        format_testimony_summary,
    )

    player = ctx.session.player
    event_log = getattr(ctx.shared, "event_log", [])
    game_time = ctx.shared.game_time
    events = collect_recent_events(event_log, game_time, hours=JOURNAL_RECENT_HOURS)
    conversations = normalize_conversation_history(
        getattr(player, "conversation_history", []),
        limit=JOURNAL_CONVERSATION_LIMIT,
    )
    rumours = [entry for entry in conversations if entry.get("npc_id") == "_rumor"]
    ordinary_conversations = [entry for entry in conversations if entry.get("npc_id") != "_rumor"]
    intel = getattr(player, "journal_intel", {}) or {}
    active_missions = list(getattr(player, "active_missions", []))
    summary = format_journal_summary(
        event_log,
        game_time,
        conversations,
        intel,
        active_missions,
        mission_manager=getattr(ctx.shared, "mission_manager", None),
        npc_lookup=getattr(ctx.shared.world, "npcs", {}),
    )
    return {
        "generation": generation,
        "events": events,
        "rumours": rumours,
        "conversations": ordinary_conversations,
        "intel": project_journal_intel(intel, npc_lookup=getattr(ctx.shared.world, "npcs", {})),
        "testimonies": project_testimonies(player),
        "testimony_summary": format_testimony_summary(player),
        "tutorial_lessons": dict(getattr(player, "tutorial_journal_lessons", {}) or {}),
        "active_missions": active_missions,
        "summary": summary,
    }


def item_row(item: Any) -> Dict[str, Any]:
    return {
        "id": item.id,
        "instance_id": getattr(item, "instance_id", item.id),
        "name": item.name,
        "description": item.description,
        "category": item.category,
        "rarity": item.rarity,
        "takeable": item.takeable,
        "is_weapon": item.is_weapon,
        "weapon_type": item.weapon_type,
        "courage_bonus": item.courage_bonus,
        "is_armour": item.is_armour,
        "defense_value": item.defense_value,
        "durability": item.durability,
        "max_durability": item.max_durability,
        "mods": list(item.mods),
        "food_value": item.food_value,
        "morale_restore": item.morale_restore,
        "is_container": item.is_container,
        "is_open": item.is_open,
        "locked": item.locked,
        "key_id": item.key_id,
        "opens_container": item.opens_container,
        "is_note": item.is_note,
        "is_map": item.is_map,
        "is_money": item.is_money,
        "is_key": item.is_key,
        "is_quest_item": item.is_quest_item,
        "contraband_risk": item.contraband_risk,
    }


def room_key_for_client(ctx: Any) -> str:
    from .tutorial import get_original_tutorial_room_id
    player = ctx.session.player
    if getattr(player, "in_tutorial", False) and getattr(player, "tutorial_instance_id", ""):
        return get_original_tutorial_room_id(
            player.tutorial_instance_id, player.current_room, ctx.shared
        )
    return player.current_room


async def send_popup(session: Any, msg_type: str, payload: Dict[str, Any]) -> None:
    await session.websocket.send(json.dumps({"type": msg_type, "payload": payload}))


def store_payload(
    vendor_id: str,
    vendor_name: str,
    room_key: str,
    currency: str,
    items: List[Dict[str, Any]],
    black_market_available: bool,
    generation: int,
    wanted_policy: Any = None,
    wallet_fabi_value: int = 0,
) -> Dict[str, Any]:
    payload = {
        "generation": generation,
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "room_key": room_key,
        "currency": currency,
        "wallet_fabi_value": wallet_fabi_value,
        "items": items,
        "black_market_available": black_market_available,
    }
    if wanted_policy is not None:
        payload["wanted_policy"] = {
            "level": wanted_policy.level,
            "ordinary_vendor_refuses": wanted_policy.ordinary_vendor_refuses,
            "black_market_markup": wanted_policy.black_market_markup,
            "patrol_multiplier": wanted_policy.patrol_multiplier,
            "disguise_perception_bonus": wanted_policy.disguise_perception_bonus,
            "curfew_arrest_bonus": wanted_policy.curfew_arrest_bonus,
            "arrest_chance": wanted_policy.arrest_chance,
        }
    return payload


async def close_popup_if_kind(ctx: Any, kind: str, reason: str) -> None:
    open_popup = getattr(ctx.session, "open_popup", None)
    if open_popup and open_popup.get("kind") == kind:
        await ctx.session.send_popup_close(reason)
        ctx.session.clear_open_popup()


def stash_payload(safehouse_name: str, room_key: str, items: List[Any], generation: int) -> Dict[str, Any]:
    return {
        "generation": generation,
        "safehouse_name": safehouse_name,
        "room_key": room_key,
        "retrieval_note": "RETRIEVE withdraws all stored items at once.",
        "items": [item_row(item) for item in items],
    }


def container_payload(container: Any, room_key: str, generation: int, key_item: Any = None, has_key: bool = False) -> Dict[str, Any]:
    from .equipment import ensure_items_identity
    ensure_items_identity(container.container_items)
    payload: Dict[str, Any] = {
        "generation": generation,
        "container_id": container.id,
        "name": container.name,
        "description": container.description,
        "room_key": room_key,
        "is_open": container.is_open,
        "locked": container.locked,
        "items": [item_row(item) for item in container.container_items],
    }
    if container.key_id:
        payload["key_id"] = container.key_id
        payload["key_name"] = key_item.name if key_item else readable_key_name(container.key_id)
        payload["has_key"] = has_key
    return payload


def readable_key_name(key_id: str) -> str:
    name = key_id.replace("_", " ").strip()
    if not name:
        return key_id
    return name[0].upper() + name[1:]


def action_item_row(item_or_journal: Any, disabled: bool = False, disabled_reason: str = "") -> Dict[str, Any]:
    if isinstance(item_or_journal, dict):
        identity = item_or_journal.get("identity") or f"journal:{item_or_journal.get('event_id', '')}"
        row: Dict[str, Any] = {
            "identity": identity,
            "instance_id": identity,
            "id": identity,
            "name": item_or_journal.get("name", ""),
            "description": item_or_journal.get("description", ""),
        }
    else:
        row = item_row(item_or_journal)
        row["identity"] = getattr(item_or_journal, "instance_id", item_or_journal.id) or item_or_journal.id
    row["disabled"] = disabled
    row["disabled_reason"] = disabled_reason
    return row


def item_action_payload(
    action: str,
    title: str,
    room_key: str,
    generation: int,
    items: List[Dict[str, Any]],
    stage: str = "",
    note: str = "",
    confirm_target: str = "",
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "generation": generation,
        "room_key": room_key,
        "action": action,
        "title": title,
        "items": items,
    }
    if stage:
        payload["stage"] = stage
    if note:
        payload["note"] = note
    if confirm_target:
        payload["confirm_target"] = confirm_target
    return payload


def _equipped_row(player: Any, item_id: str):
    if not item_id:
        return None
    from .equipment import equipped_item
    item = equipped_item(player, item_id)
    return item_row(item) if item else None


def equipment_payload(player: Any, generation: int) -> Dict[str, Any]:
    from .equipment import equipped_item, ensure_inventory_identity
    ensure_inventory_identity(player)
    equipped_weapon = getattr(player, "equipped_weapon_id", "")
    worn_armour = getattr(player, "worn_armour_id", "")
    disguise_item_id = getattr(player, "equipped_disguise_item_id", "")
    disguise_item = equipped_item(player, disguise_item_id)
    disguise_resolved = disguise_item if disguise_item and disguise_item.disguise_id == getattr(player, "disguise", "") else None
    occupied = (equipped_weapon, worn_armour, disguise_item_id)
    return {
        "generation": generation,
        "weapon": _equipped_row(player, equipped_weapon),
        "armour": _equipped_row(player, worn_armour),
        "disguise": getattr(player, "disguise", "") if disguise_resolved else None,
        "disguise_item_id": disguise_item_id if equipped_item(player, disguise_item_id) else None,
        "eligible": [
            item_row(item) for item in player.inventory
            if (item.is_weapon or item.is_armour or item.disguise_id) and item.instance_id not in occupied
        ],
    }


def has_any_equipment(player: Any) -> bool:
    from .equipment import equipped_item, ensure_inventory_identity
    ensure_inventory_identity(player)
    if getattr(player, "equipped_weapon_id", "") or getattr(player, "worn_armour_id", ""):
        return True
    disguise_item = equipped_item(player, getattr(player, "equipped_disguise_item_id", ""))
    if disguise_item and disguise_item.disguise_id == getattr(player, "disguise", ""):
        return True
    return any(item.is_weapon or item.is_armour or item.disguise_id for item in player.inventory)


def _item_actions(item: Any, player: Any) -> List[str]:
    item_identity = getattr(item, "instance_id", item.id)
    if item_identity == getattr(player, "equipped_weapon_id", ""):
        return ["remove", "examine"]
    if item_identity == getattr(player, "worn_armour_id", ""):
        return ["remove", "examine"]
    if item_identity == getattr(player, "equipped_disguise_item_id", ""):
        return ["remove", "examine"]
    if item.food_value > 0:
        return ["eat", "examine"]
    if item.is_weapon or item.disguise_id:
        return ["equip", "examine"]
    if item.is_armour:
        return ["equip", "examine"]
    if item.is_note or getattr(item, "readable_text", "") or getattr(item, "note_text", ""):
        return ["read", "examine"]
    return ["drop", "examine"]


def inventory_payload(player: Any, generation: int) -> Dict[str, Any]:
    from .economy import wallet_fabi_value
    from .equipment import ensure_inventory_identity
    ensure_inventory_identity(player)
    equipped = {
        "weapon_id": getattr(player, "equipped_weapon_id", "") or None,
        "armour_id": getattr(player, "worn_armour_id", "") or None,
        "disguise": getattr(player, "disguise", "") or None,
        "disguise_item_id": getattr(player, "equipped_disguise_item_id", "") or None,
    }
    items = []
    for item in player.inventory:
        row = item_row(item)
        if getattr(item, "instance_id", item.id) == getattr(player, "equipped_weapon_id", ""):
            row["equipped"] = "weapon"
        elif getattr(item, "instance_id", item.id) == getattr(player, "worn_armour_id", ""):
            row["equipped"] = "armour"
        elif getattr(item, "instance_id", item.id) == getattr(player, "equipped_disguise_item_id", ""):
            row["equipped"] = "disguise"
        else:
            row["equipped"] = None
        row["actions"] = _item_actions(item, player)
        items.append(row)
    return {
        "generation": generation,
        "slots_used": len(player.inventory),
        "slots_max": getattr(player, "max_inventory", 12),
        "equipped": equipped,
        "wallet_fabi_value": wallet_fabi_value(player),
        "money_fabi": player.money_fabi,
        "money_silver": player.money_silver,
        "money_military_yen": player.money_military_yen,
        "items": items,
    }
