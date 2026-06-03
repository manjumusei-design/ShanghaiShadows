import asyncio
import random
from typing import TYPE_CHECKING

from .constants import CURFEW_MINUTE, EVENT_LOG_MAXLEN, WORLD_EVENTS_MAXLEN
from .commands import (
    apply_action_trust,
    advance_time_one_minute,
    check_death_conditions,
    check_planted_evidence,
    check_curfew_penalty,
    disguise_bonus,
    handle_player_death,
    log_event,
    maybe_trigger_storylet,
    move_npcs_if_hour_changed,
    post_display,
    process_gossip,
    process_survival_tick,
    process_tailing,
    trigger_ending,
)
from .session import Session
from .game_world import SharedWorldState

if TYPE_CHECKING:
    from .session_manager import SessionManager