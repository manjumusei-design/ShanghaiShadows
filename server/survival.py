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


def apply_survival_tick(player, minute: int, day: int, send_display=None) -> None:
    decay_per_minute = (
        HUNGER_DECAY_PER_HOUR_WINTER / 60
        if get_season(day) == "winter"
        else HUNGER_DECAY_PER_HOUR / 60
    )
    player.hunger = max(0, player.hunger - decay_per_minute)
    tier = get_hunger_tier(player.hunger)
    if tier == "FULL":
        if minute % 60 == 0:
            player.health = min(100, player.health + 1)
    elif tier == "HUNGRY":
        if minute % 60 == 0 and send_display is not None:
            send_display(loc("hunger.hungry"), msg_type=MessageType.WARNING)
    elif tier == "STARVING":
        player.health = max(0, player.health - 1)
        if send_display is not None:
            send_display(loc("hunger.starving"), msg_type=MessageType.WARNING)
    elif tier == "FAMISHED":
        player.health = max(0, player.health - 2)
        if send_display is not None:
            send_display(loc("hunger.famished"), msg_type=MessageType.WARNING)