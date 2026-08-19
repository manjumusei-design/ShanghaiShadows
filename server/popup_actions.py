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
