import json
from typing import Any, Callable, Dict, Optional

from .action_result import CommandOutcome, failure, success
from .commands import (
    _find_container,
    _room,
    _withdraw_stash_all,
    post_display,
    resolve_storylet_choice,
    validate_vendor_purchase_context,
)
from .locales import get as loc
from .parser import Command
from .popup_payloads import room_key_for_client

STALE_CHOICE = "That choice is no longer available."

VERB_ACTIONS = {
    "eat": "eat",
    "equip": "equip",
    "wear": "wear",
    "remove": "remove",
    "drop": "drop",
    "read": "read",
    "examine": "examine",
}

NOT_HELD_LOC = {
    "eat": "cmd_eat.not_held",
    "equip": "cmd_equip.not_held",
    "wear": "cmd_drop.not_held",
    "drop": "cmd_drop.not_held",
    "read": "cmd_read.not_held",
    "examine": "cmd_drop.not_held",
    "sell": "cmd_sell.not_held",
    "repair": "cmd_repair.weapon_not_found",
}


def parse_popup_action(text: str) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if isinstance(data, dict) and data.get("type") == "popup_action":
        return data
    return None


def _validate_popup(session: Any, data: Dict[str, Any]) -> bool:
    open_popup = getattr(session, "open_popup", None)
    if not open_popup:
        return False
    if data.get("popup") != open_popup.get("kind"):
        return False
    if data.get("generation") != open_popup.get("generation"):
        return False
    return True


def _validate_context(ctx: Any, session: Any, data: Dict[str, Any]) -> bool:
    context = session.open_popup.get("context", {})
    if data.get("room_key") != context.get("room_key"):
        return False
    return room_key_for_client(ctx) == context.get("room_key")


async def _dispatch_verb(ctx: Any, verb: str, cmd: Command) -> CommandOutcome:
    if cmd.raw:
        raw = cmd.raw
    elif verb == "take from":
        raw = f"take {cmd.direct_obj} from {cmd.indirect_obj}"
    else:
        raw = " ".join(part for part in (verb, cmd.direct_obj, cmd.indirect_obj) if part)
    return await ctx.session_manager.dispatch_command(ctx.session, raw)


async def _route_inventory_verb(ctx: Any, session: Any, data: Dict[str, Any]) -> CommandOutcome:
    from .equipment import ensure_inventory_identity
    verb = VERB_ACTIONS.get(data.get("action", ""))
    if not verb:
        await post_display(ctx, STALE_CHOICE)
        return failure("popup_stale_choice")
    ensure_inventory_identity(session.player)
    target_id = data.get("target_id", "")
    if verb == "remove" and target_id == "disguise":
        if not ctx.session.player.disguise:
            await post_display(ctx, loc("cmd_remove.not_worn"))
            return failure("popup_not_worn")
        cmd = Command(verb="remove", direct_obj="disguise")
    else:
        item = next((candidate for candidate in ctx.session.player.inventory if getattr(candidate, "instance_id", candidate.id) == target_id), None)
        if not item:
            await post_display(ctx, loc(NOT_HELD_LOC.get(verb, "cmd_drop.not_held")))
            return failure("popup_not_held")
        item_identity = getattr(item, "instance_id", item.id)
        if verb == "remove" and item_identity not in (
            ctx.session.player.worn_armour_id,
            ctx.session.player.equipped_weapon_id,
            ctx.session.player.equipped_disguise_item_id,
        ):
            await post_display(ctx, loc("cmd_remove.not_worn"))
            return failure("popup_not_worn")
        direct_obj = item.name
        if verb == "remove":
            if item_identity == ctx.session.player.equipped_weapon_id:
                direct_obj = "weapon"
            elif item_identity == ctx.session.player.worn_armour_id:
                direct_obj = "armour"
            elif item_identity == ctx.session.player.equipped_disguise_item_id:
                direct_obj = "disguise"
        cmd = Command(verb=verb, direct_obj=direct_obj if verb == "remove" else item.instance_id)
    return await _dispatch_verb(ctx, verb, cmd)


def _option_matches_target(option: Any, target_id: str) -> bool:
    effects = getattr(option, "effects", {}) or {}
    if effects.get("give_item") == target_id:
        return True
    return target_id == "newspaper" and "purchase_newspaper" in effects


async def _route_buy(ctx: Any, session: Any, data: Dict[str, Any]) -> CommandOutcome:
    if not _validate_context(ctx, session, data):
        await post_display(ctx, STALE_CHOICE)
        return failure("popup_stale_context")
    vendor_id = data.get("context_id", "")
    target_id = data.get("target_id", "")
    validation = validate_vendor_purchase_context(ctx, vendor_id, target_id)
    if validation.error:
        await post_display(ctx, STALE_CHOICE)
        return failure("popup_vendor_unavailable")
    active = next(
        (s for s in ctx.session.player.active_storylets if s.storylet_id == f"shop_{vendor_id}"),
        None,
    )
    if active is None:
        await post_display(ctx, STALE_CHOICE)
        return failure("popup_stale_choice")
    option = next(
        (o for o in active.options if not getattr(o, "disabled", False) and _option_matches_target(o, target_id)),
        None,
    )
    if option is None:
        await post_display(ctx, STALE_CHOICE)
        return failure("popup_stale_choice")
    return await ctx.session_manager.dispatch_command(session, option.text)


async def _route_container_close(ctx: Any, session: Any, data: Dict[str, Any]) -> CommandOutcome:
    if not _validate_context(ctx, session, data):
        await post_display(ctx, STALE_CHOICE)
        return failure("popup_stale_context")
    from .commands import close_container
    container = _find_container(ctx, data.get("context_id", ""))
    if not container:
        await post_display(ctx, loc("container.not_container"))
        return failure("popup_not_container")
    return await close_container(ctx, container)


async def _route_item_action(ctx: Any, session: Any, data: Dict[str, Any]) -> CommandOutcome:
    from .commands import find_item_by_instance
    from .popup_payloads import close_popup_if_kind
    if not _validate_context(ctx, session, data):
        await post_display(ctx, STALE_CHOICE)
        return failure("popup_stale_context")
    action = data.get("action", "")
    target_id = data.get("target_id", "")
    if action == "mod_weapon":
        return await _route_mod_weapon_stage(ctx, session, data)
    if action == "take":
        room = _room(ctx)
        if not room:
            await post_display(ctx, STALE_CHOICE)
            return failure("popup_stale_context")
        item = find_item_by_instance(target_id, room.items)
        if not item:
            await post_display(ctx, STALE_CHOICE)
            return failure("popup_item_missing")
        cmd = Command(verb="take", direct_obj=target_id, raw=f"take {target_id}")
    elif action == "read" and target_id.startswith("journal:"):
        event_id = target_id[len("journal:"):]
        room = _room(ctx)
        entries = ctx.shared.death_journals.get(room.id, []) if room else []
        if not any(entry.get("event_id") == event_id for entry in entries):
            await post_display(ctx, STALE_CHOICE)
            return failure("popup_item_missing")
        cmd = Command(verb="read", direct_obj=f"{event_id} journal", raw=f"read {event_id} journal")
    elif action == "read" and target_id == "newspaper":
        cmd = Command(verb="read", direct_obj="newspaper", raw="read newspaper")
    else:
        item = find_item_by_instance(target_id, session.player.inventory)
        if not item:
            await post_display(ctx, loc(NOT_HELD_LOC.get(action, "cmd_drop.not_held")))
            return failure("popup_not_held")
        if action == "eat":
            from .commands import consume_food_item
            result = await consume_food_item(ctx, item)
            if result.succeeded:
                await close_popup_if_kind(ctx, "action", "resolved")
            return result
        cmd = Command(verb=action, direct_obj=target_id, raw=" ".join(part for part in (action, target_id) if part))
    result = await _dispatch_verb(ctx, action, cmd)
    if result.succeeded:
        await close_popup_if_kind(ctx, "action", "resolved")
    return result


async def _route_mod_weapon_stage(ctx: Any, session: Any, data: Dict[str, Any]) -> CommandOutcome:
    from .commands import (
        _action_row,
        _compatible_mod_weapons,
        find_item_by_instance,
        _open_item_action_chooser,
    )
    from .popup_payloads import close_popup_if_kind
    target_id = data.get("target_id", "")
    stage = data.get("stage", "")
    expected = session.open_popup.get("context", {}).get("expected_stage", "")
    if stage != expected or stage not in ("mod", "weapon", "confirm"):
        await post_display(ctx, STALE_CHOICE)
        return failure("popup_stale_choice")
    if stage == "mod":
        mod = find_item_by_instance(target_id, session.player.inventory)
        if not mod or not getattr(mod, "is_mod", False):
            await post_display(ctx, STALE_CHOICE)
            return failure("popup_item_missing")
        weapons = _compatible_mod_weapons(session.player, mod)
        rows = [_action_row(weapon) for weapon in weapons]
        if not rows:
            await post_display(ctx, "No compatible weapon is available.")
            return failure("mod_weapon_no_weapons")
        await _open_item_action_chooser(ctx, "mod_weapon", "Attach it to what?", rows, stage="weapon", context={"mod_identity": mod.instance_id, "expected_stage": "weapon"})
        return success("mod_weapon_stage", facts={"stage_advanced"})
    mod_identity = session.open_popup.get("context", {}).get("mod_identity", "")
    mod = find_item_by_instance(mod_identity, session.player.inventory)
    if not mod or not getattr(mod, "is_mod", False):
        await post_display(ctx, STALE_CHOICE)
        return failure("popup_stale_choice")
    if stage == "weapon":
        weapon = find_item_by_instance(target_id, session.player.inventory)
        if not weapon or not weapon.is_weapon or weapon not in _compatible_mod_weapons(session.player, mod):
            await post_display(ctx, STALE_CHOICE)
            return failure("popup_item_missing")
        note = f"Permanently attach the {mod.name} to your {weapon.name}?"
        await _open_item_action_chooser(ctx, "mod_weapon", "Confirm attachment", [], stage="confirm", note=note, confirm_target=weapon.instance_id, context={"mod_identity": mod.instance_id, "weapon_identity": weapon.instance_id, "expected_stage": "confirm"})
        return success("mod_weapon_stage", facts={"stage_advanced"})
    weapon_identity = session.open_popup.get("context", {}).get("weapon_identity", "")
    if target_id != weapon_identity:
        await post_display(ctx, STALE_CHOICE)
        return failure("popup_stale_choice")
    weapon = find_item_by_instance(weapon_identity, session.player.inventory)
    if not weapon or not weapon.is_weapon or weapon not in _compatible_mod_weapons(session.player, mod):
        await post_display(ctx, STALE_CHOICE)
        return failure("popup_stale_choice")
    result = await _dispatch_verb(
        ctx,
        "mod weapon",
        Command(verb="mod weapon", direct_obj=weapon_identity, indirect_obj=mod_identity, raw=f"mod weapon {weapon_identity} with {mod_identity}"),
    )
    if result.succeeded:
        await close_popup_if_kind(ctx, "action", "resolved")
    return result


async def _route_retrieve_all(ctx: Any, session: Any, data: Dict[str, Any]) -> CommandOutcome:
    if not _validate_context(ctx, session, data):
        await post_display(ctx, STALE_CHOICE)
        return failure("popup_stale_context")
    await _withdraw_stash_all(ctx)
    from .popup_payloads import close_popup_if_kind
    await close_popup_if_kind(ctx, "stash", "resolved")
    return success("popup_retrieve_all")


async def _route_take_from(ctx: Any, session: Any, data: Dict[str, Any]) -> CommandOutcome:
    from .commands import find_item_by_instance
    from .equipment import ensure_items_identity
    if not _validate_context(ctx, session, data):
        await post_display(ctx, STALE_CHOICE)
        return failure("popup_stale_context")
    container = _find_container(ctx, data.get("context_id", ""))
    if not container:
        await post_display(ctx, loc("container.not_container"))
        return failure("popup_not_container")
    ensure_items_identity(container.container_items)
    target_id = data.get("target_id", "")
    item = find_item_by_instance(target_id, container.container_items)
    if not item:
        await post_display(ctx, loc("container.not_in_there"))
        return failure("popup_item_missing")
    cmd = Command(verb="take from", direct_obj=target_id, indirect_obj=container.name, raw=f"take {target_id} from {container.name}")
    return await _dispatch_verb(ctx, "take from", cmd)


ACTION_ROUTES: Dict[str, Callable] = {
    action: _route_inventory_verb for action in VERB_ACTIONS
}
ACTION_ROUTES.update({
    "buy": _route_buy,
    "take_from": _route_take_from,
    "retrieve_all": _route_retrieve_all,
    "close": _route_container_close,
})

ITEM_ACTION_ROUTES: Dict[str, Callable] = {
    "take": _route_item_action,
    "drop": _route_item_action,
    "eat": _route_item_action,
    "read": _route_item_action,
    "sell": _route_item_action,
    "repair": _route_item_action,
    "mod_weapon": _route_mod_weapon_stage,
}


async def handle_popup_action(session_manager: Any, session: Any, data: Dict[str, Any]) -> CommandOutcome:
    ctx = session_manager._make_context(session)
    if not _validate_popup(session, data):
        await post_display(ctx, STALE_CHOICE)
        return failure("popup_stale_action")
    if data.get("popup") == "action" and data.get("action") != session.open_popup.get("context", {}).get("expected_action", ""):
        await post_display(ctx, STALE_CHOICE)
        return failure("popup_stale_choice")
    routes = ITEM_ACTION_ROUTES if data.get("popup") == "action" else ACTION_ROUTES
    handler = routes.get(data.get("action"))
    if handler is None:
        await post_display(ctx, STALE_CHOICE)
        return failure("popup_unknown_action")
    result = await handler(ctx, session, data)
    if isinstance(result, CommandOutcome):
        return result
    return failure("popup_handler_no_outcome")
