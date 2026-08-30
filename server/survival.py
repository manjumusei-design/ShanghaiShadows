from .constants import (
    HUNGER_DECAY_PER_HOUR,
    HUNGER_DECAY_PER_HOUR_WINTER,
    HUNGER_TIER_FULL,
    HUNGER_TIER_SATISFIED,
    HUNGER_TIER_HUNGRY,
    HUNGER_TIER_STARVING,
    MessageType,
    get_season,
)
from .locales import get as loc


HUNGER_SEVERE_TIERS = ("STARVING", "FAMISHED")


HUNGER_TIER_LABELS = {
    "FULL": "hunger.tier.full",
    "SATISFIED": "hunger.tier.satisfied",
    "HUNGRY": "hunger.tier.hungry",
    "STARVING": "hunger.tier.starving",
    "FAMISHED": "hunger.tier.famished",
}


def get_hunger_tier(hunger: float) -> str:
    if hunger > HUNGER_TIER_FULL:
        return "FULL"
    elif hunger >= HUNGER_TIER_SATISFIED:
        return "SATISFIED"
    elif hunger >= HUNGER_TIER_HUNGRY:
        return "HUNGRY"
    elif hunger >= HUNGER_TIER_STARVING:
        return "STARVING"
    return "FAMISHED"


def get_hunger_tier_label(hunger: float) -> str:
    return loc(HUNGER_TIER_LABELS[get_hunger_tier(hunger)])

def get_hunger_notify_state(player, notify_state: dict) -> None:
    notify_state.setdefault("last_notified_tier", get_hunger_tier(player.hunger))

def apply_survival_tick(
    player,
    minute: int,
    day: int,
    send_display=None,
    notify_state: dict | None = None,
) -> None:
    decay_per_minute = (
        HUNGER_DECAY_PER_HOUR_WINTER / 60
        if get_season(day) == "winter"
        else HUNGER_DECAY_PER_HOUR / 60
    )
    player.hunger = max(0, player.hunger - decay_per_minute)
    tier = get_hunger_tier(player.hunger)
    if notify_state is None:
        notify_state = getattr(player, "_hunger_notify_state", None)
        if notify_state is None:
            notify_state = {}
            setattr(player, "_hunger_notify_state", notify_state)
    prev_notified = notify_state.get("last_notified_tier")
    if tier == "FULL":
        if minute % 60 == 0:
            player.health = min(100, player.health + 1)
    elif tier in HUNGER_SEVERE_TIERS:
        player.health = max(0, player.health - (2 if tier == "FAMISHED" else 1))
    if (
        send_display is not None
        and prev_notified != tier
        and tier in ("HUNGRY",) + HUNGER_SEVERE_TIERS
        and not (prev_notified in HUNGER_SEVERE_TIERS and tier not in HUNGER_SEVERE_TIERS)
    ):
        send_display(loc(f"hunger.{tier.lower()}"), msg_type=MessageType.WARNING)
    if (
        send_display is not None
        and prev_notified in HUNGER_SEVERE_TIERS
        and tier not in HUNGER_SEVERE_TIERS
    ):
        send_display(loc("hunger.recovered"), msg_type=MessageType.PLAYER_STATUS)
    notify_state["last_notified_tier"] = tier
