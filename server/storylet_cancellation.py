import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Dict, Optional

MAX_APPLIED_CANCELLATIONS = 64
MAX_PENDING_CANCELLATION_INTENTS = 16
RESOLUTION_HANDOFF_TIMEOUT = 1.0

SHARED_EFFECT_KEYS = frozenset({
    "log_event",
    "change_influence",
    "move_npc",
    "spawn_npc",
    "arrest_player",
})

UNSUPPORTED_EFFECT_KEYS = frozenset({
    "kill_player",
    "mission_offer_action",
    "purchase_newspaper",
})

UNRECOVERABLE_NOTICE = "A past moment could not be recovered."


@dataclass(frozen=True)
class StoryletCancellationEvent:
    event_id: str
    account_username: str
    slot_id: str
    save_key: str
    storylet_id: str
    reason: str
    narrative: str
    effects: Dict[str, object]
    status: str
    created_at: str


def cancellation_event_id(save_key: str, storylet_id: str, anchor: str) -> str:
    return "cancel_" + hashlib.md5((save_key + ":" + storylet_id + ":" + anchor).encode("utf-8")).hexdigest()[:24]


def neglect_snapshot(storylet_manager, storylet_id: str):
    storylet = storylet_manager.storylets.get(storylet_id)
    if storylet and storylet.neglect:
        return storylet.neglect.narrative, dict(storylet.neglect.effects)
    return "The moment passes.", {}


def build_cancellation_event(
    save_key: str,
    account_username: str,
    slot_id: str,
    storylet_id: str,
    reason: str,
    narrative: str,
    effects: Dict[str, object],
    event_id: str,
) -> StoryletCancellationEvent:
    return StoryletCancellationEvent(
        event_id=event_id,
        account_username=account_username,
        slot_id=slot_id,
        save_key=save_key,
        storylet_id=storylet_id,
        reason=reason,
        narrative=narrative,
        effects=dict(effects),
        status="pending",
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )


def _event_payload(event: StoryletCancellationEvent) -> dict:
    return {
        "event_id": event.event_id,
        "storylet_id": event.storylet_id,
        "reason": event.reason,
        "narrative": event.narrative,
        "effects": event.effects,
        "created_at": event.created_at,
    }


def stage_cancellation_event(db, event: StoryletCancellationEvent, *, sequence: int = 0) -> bool:
    return db.insert_storylet_cancellation({
        "event_id": event.event_id,
        "account_username": event.account_username,
        "slot_id": event.slot_id,
        "save_key": event.save_key,
        "payload_json": json.dumps(_event_payload(event)),
        "status": "pending",
        "created_at": event.created_at,
        "sequence": int(sequence),
    })


def list_cancellations_for(db, account_username: str, slot_id: str) -> list:
    return db.list_storylet_cancellations(account_username, slot_id)


def _split_effects(effects: Dict[str, object]):
    player_effects = {
        key: value
        for key, value in effects.items()
        if key not in SHARED_EFFECT_KEYS and key not in UNSUPPORTED_EFFECT_KEYS
    }
    shared_effects = {key: value for key, value in effects.items() if key in SHARED_EFFECT_KEYS}
    return player_effects, shared_effects


def _has_unsupported_effects(effects) -> bool:
    return bool(effects and UNSUPPORTED_EFFECT_KEYS.intersection(effects))


def _has_shared_effects(effects: Dict[str, object]) -> bool:
    return bool(_split_effects(effects)[1])


async def _apply_shared_partition(ctx, shared_effects: Dict[str, object]) -> None:
    from .commands import _effects_as_list, apply_storylet_effects, log_event
    non_log = {key: value for key, value in shared_effects.items() if key != "log_event"}
    if non_log:
        await apply_storylet_effects(ctx, non_log, player_side=False)
    for text in _effects_as_list(shared_effects.get("log_event")):
        if text:
            log_event(ctx, str(text), player_side=False)


def _retain_cancellation_intent(player, storylet_id: str, anchor: str) -> None:
    intents = getattr(player, "pending_cancellation_storylets", None)
    if intents is None:
        intents = []
        player.pending_cancellation_storylets = intents
    record = {"storylet_id": storylet_id, "anchor": anchor}
    if record not in intents:
        intents.append(record)
    if len(intents) > MAX_PENDING_CANCELLATION_INTENTS:
        del intents[: len(intents) - MAX_PENDING_CANCELLATION_INTENTS]


def _clear_cancellation_intent(player, storylet_id: str, anchor: str) -> None:
    intents = getattr(player, "pending_cancellation_storylets", None)
    if not intents:
        return
    record = {"storylet_id": storylet_id, "anchor": anchor}
    if record in intents:
        intents.remove(record)


def _valid_payload(payload) -> bool:
    if not isinstance(payload, dict):
        return False
    effects = payload.get("effects")
    if effects is not None and not isinstance(effects, dict):
        return False
    narrative = payload.get("narrative")
    if narrative is not None and not isinstance(narrative, str):
        return False
    storylet_id = payload.get("storylet_id")
    if storylet_id is not None and not isinstance(storylet_id, str):
        return False
    return True


async def _await_resolution_completion(active) -> None:
    while getattr(active, "resolution_started", False) and not getattr(active, "resolved", False):
        await asyncio.sleep(0)


def _shared_projection_ids(shared) -> list:
    ids = getattr(shared, "applied_cancellation_event_ids", None)
    if ids is None:
        ids = []
        shared.applied_cancellation_event_ids = ids
    return ids


def _mark_applied(player, event_id: str) -> None:
    applied_ids = getattr(player, "cancelled_storylet_event_ids", None)
    if applied_ids is None:
        applied_ids = []
        player.cancelled_storylet_event_ids = applied_ids
    if event_id not in applied_ids:
        applied_ids.append(event_id)
    if len(applied_ids) > MAX_APPLIED_CANCELLATIONS:
        del applied_ids[: len(applied_ids) - MAX_APPLIED_CANCELLATIONS]


async def apply_neglect(ctx, active, *, announce: bool = True, claimed: bool = False) -> Optional[str]:
    from .commands import (
        _complete_room_storylet,
        _display_storylet,
        apply_storylet_effects,
        claim_storylet_resolution,
        post_display,
        storylet_resolution_owned,
    )
    if not claimed and not claim_storylet_resolution(active):
        return None
    try:
        storylet = ctx.storylet_manager.storylets.get(active.storylet_id)
        player = ctx.session.player
        has_neglect = storylet is not None and storylet.neglect is not None
        narrative, effects = neglect_snapshot(ctx.storylet_manager, active.storylet_id)
        if announce:
            await post_display(ctx, narrative, msg_type="storylet_frame")
            if not storylet_resolution_owned(active) or getattr(ctx.session, "clean_close_completed", False):
                return None
        if has_neglect and effects:
            if not storylet_resolution_owned(active):
                return None
            applied = await apply_storylet_effects(ctx, effects, active=active)
            if applied is False:
                return None
            active.resolution_committed = True
        active.resolved = True
        if active.storylet_id not in player.storylet_history:
            player.storylet_history.append(active.storylet_id)
        if active in player.active_storylets:
            player.active_storylets.remove(active)
        if announce:
            await ctx.session.send_storylet_resolved(active.storylet_id)
        await _complete_room_storylet(ctx, active, narrative)
        if announce and not has_neglect and active.storylet_id.startswith("shop_"):
            from .popup_payloads import close_popup_if_kind
            await close_popup_if_kind(ctx, "store", "invalid")
        if announce and player.active_storylets:
            await _display_storylet(ctx, player.active_storylets[0])
        return narrative
    except Exception:
        if not claimed:
            active.resolution_started = False
        raise


async def handoff_claimed_cancellation(ctx, active, *, sequence: int = 0) -> Optional[StoryletCancellationEvent]:
    from .auth import _get_db
    from .lifecycle import authorized_session_save_key, save_authorized_session
    save_key = authorized_session_save_key(ctx.session)
    if not save_key:
        return None
    player = ctx.session.player
    account_username = (player.account_username or ctx.session.username).strip().lower()
    narrative, effects = neglect_snapshot(ctx.storylet_manager, active.storylet_id)
    anchor = str(active.timer_started_at or 0.0)
    event_id = cancellation_event_id(save_key, active.storylet_id, anchor)
    event = build_cancellation_event(
        save_key,
        account_username,
        ctx.session.slot_id,
        active.storylet_id,
        "disconnect_handoff",
        narrative,
        effects,
        event_id,
    )
    try:
        staged = stage_cancellation_event(_get_db(), event, sequence=sequence)
    except Exception:
        staged = False
    if not staged:
        _retain_cancellation_intent(player, active.storylet_id, anchor)
        try:
            save_authorized_session(ctx.session)
        except Exception:
            pass
        return None
    active.resolution_started = False
    return event


async def cancel_active_storylet_on_disconnect(ctx, active, *, sequence: int = 0) -> Optional[StoryletCancellationEvent]:
    from .auth import _get_db
    from .commands import claim_storylet_resolution
    from .lifecycle import authorized_session_save_key, save_authorized_session
    from .save_manager import save_world_state
    save_key = authorized_session_save_key(ctx.session)
    if not save_key:
        return None
    if not claim_storylet_resolution(active):
        return None
    player = ctx.session.player
    account_username = (player.account_username or ctx.session.username).strip().lower()
    narrative, effects = neglect_snapshot(ctx.storylet_manager, active.storylet_id)
    anchor = str(active.timer_started_at or 0.0)
    event_id = cancellation_event_id(save_key, active.storylet_id, anchor)
    event = build_cancellation_event(
        save_key,
        account_username,
        ctx.session.slot_id,
        active.storylet_id,
        "disconnect",
        narrative,
        effects,
        event_id,
    )
    try:
        staged = stage_cancellation_event(_get_db(), event, sequence=sequence)
    except Exception:
        staged = False
    if not staged:
        active.resolution_started = False
        _retain_cancellation_intent(player, active.storylet_id, anchor)
        try:
            save_authorized_session(ctx.session)
        except Exception:
            pass
        return None
    _clear_cancellation_intent(player, active.storylet_id, anchor)
    if event_id in getattr(player, "cancelled_storylet_event_ids", []):
        return event
    if _has_unsupported_effects(effects):
        return event
    await apply_neglect(ctx, active, announce=False, claimed=True)
    _mark_applied(player, event_id)
    _shared_projection_ids(ctx.shared).append(event_id)
    if not save_authorized_session(ctx.session):
        return None
    if _has_shared_effects(effects):
        try:
            save_world_state(ctx.shared)
        except Exception:
            return None
    _get_db().set_storylet_cancellation_status(event_id, "applied")
    return event


async def recover_cancellations(ctx) -> None:
    from .auth import _get_db
    from .commands import apply_storylet_effects
    from .lifecycle import authorized_session_save_key, save_authorized_session
    from .save_manager import save_world_state
    save_key = authorized_session_save_key(ctx.session)
    if not save_key:
        return
    player = ctx.session.player
    db = _get_db()
    account_username = (player.account_username or ctx.session.username).strip().lower()
    legacy = getattr(player, "_pending_legacy_cancellations", None)
    if legacy:
        retained = []
        for index, record in enumerate(legacy):
            storylet_id = record.get("storylet_id", "")
            narrative, effects = neglect_snapshot(ctx.storylet_manager, storylet_id)
            event_id = cancellation_event_id(save_key, storylet_id, record.get("anchor", "0"))
            event = build_cancellation_event(
                save_key,
                account_username,
                ctx.session.slot_id,
                storylet_id,
                "legacy_migration",
                narrative,
                effects,
                event_id,
            )
            try:
                staged = stage_cancellation_event(db, event, sequence=index)
            except Exception:
                staged = False
            if not staged:
                retained.append(record)
        for record in retained:
            _retain_cancellation_intent(player, record.get("storylet_id", ""), record.get("anchor", "0"))
        player._pending_legacy_cancellations = None
    intents = getattr(player, "pending_cancellation_storylets", None)
    if intents:
        remaining = []
        for index, record in enumerate(intents):
            storylet_id = record.get("storylet_id", "")
            narrative, effects = neglect_snapshot(ctx.storylet_manager, storylet_id)
            event_id = cancellation_event_id(save_key, storylet_id, record.get("anchor", "0"))
            event = build_cancellation_event(
                save_key,
                account_username,
                ctx.session.slot_id,
                storylet_id,
                "disconnect",
                narrative,
                effects,
                event_id,
            )
            try:
                staged = stage_cancellation_event(db, event, sequence=index)
            except Exception:
                staged = False
            if not staged:
                remaining.append(record)
        player.pending_cancellation_storylets = remaining
    rows = [dict(row) for row in list_cancellations_for(db, account_username, ctx.session.slot_id)]
    for row in rows:
        status = row["status"]
        event_id = row["event_id"]
        if status == "feedback_delivered":
            continue
        try:
            payload = json.loads(row["payload_json"])
        except Exception:
            payload = None
        if not _valid_payload(payload):
            try:
                await ctx.session.send_display(UNRECOVERABLE_NOTICE, msg_type="system")
            except Exception:
                pass
            continue
        if _has_unsupported_effects(payload.get("effects") or {}):
            try:
                await ctx.session.send_display(UNRECOVERABLE_NOTICE, msg_type="system")
            except Exception:
                pass
            db.set_storylet_cancellation_status(event_id, "feedback_delivered")
            continue
        applied_ids = getattr(player, "cancelled_storylet_event_ids", None)
        if applied_ids is None:
            applied_ids = []
            player.cancelled_storylet_event_ids = applied_ids
        if status == "pending" and event_id not in applied_ids:
            effects = payload.get("effects") or {}
            player_effects, shared_effects = _split_effects(effects)
            if player_effects:
                await apply_storylet_effects(ctx, player_effects)
            projection = _shared_projection_ids(ctx.shared)
            if shared_effects and event_id not in projection:
                await apply_storylet_effects(ctx, shared_effects)
                projection.append(event_id)
            storylet_id = payload.get("storylet_id", "")
            if storylet_id and storylet_id not in player.storylet_history:
                player.storylet_history.append(storylet_id)
            _mark_applied(player, event_id)
            if not save_authorized_session(ctx.session):
                continue
            if shared_effects:
                try:
                    save_world_state(ctx.shared)
                except Exception:
                    continue
            db.set_storylet_cancellation_status(event_id, "applied")
        elif status == "pending":
            effects = payload.get("effects") or {}
            _, shared_effects = _split_effects(effects)
            if shared_effects:
                projection = _shared_projection_ids(ctx.shared)
                if event_id not in projection:
                    await _apply_shared_partition(ctx, shared_effects)
                    projection.append(event_id)
                try:
                    save_world_state(ctx.shared)
                except Exception:
                    continue
            db.set_storylet_cancellation_status(event_id, "applied")
        narrative = payload.get("narrative", "The moment passes.")
        try:
            await ctx.session.send_display(narrative, msg_type="storylet_frame")
        except Exception:
            continue
        db.set_storylet_cancellation_status(event_id, "feedback_delivered")
