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


class WorldClock:
    def __init__(self, shared: SharedWorldState, session_manager: "SessionManager", disguises, stealth, storylet_manager):
        self.shared = shared
        self.session_manager = session_manager
        self.disguises = disguises
        self.stealth = stealth
        self.storylet_manager = storylet_manager
        self.manually_advancing = False

    async def tick(self):
        if not self.session_manager.sessions:
            return
        
        if self.manually_advancing:
            return
        
        self._advance_time_one_minute()
        self._move_npcs_if_hour_changed()
        self._process_gossip()
        await self._process_planted_evidence_all_sessions()
        await self._process_tailing_all_sessions()
        await self._check_curfew_all_sessions()
        if self.shared.game_time.minute % 15 == 0:
            await self._check_storylets()
        self._process_survival_all_sessions()
        await self._check_death_and_victory()

    def _advance_time_one_minute(self):
        self.shared.game_time.minute += 1
        if self.shared.game_time.minute >= 1440:
            self.shared.game_time.minute = 0
            self.shared.game_time.day += 1
        self.shared.scheduler.process(
            self.shared.game_time,
            lambda msg: asyncio.create_task(self._broadcast_display(msg)),
        )

    def _move_npcs_if_hour_changed(self):
        if self.shared.game_time.minute % 60 != 0:
            return
        hour = self.shared.game_time.minute // 60
        for npc_id, npc in self.shared.world.npcs.items():
            room_id = npc.schedule.get(hour)
            if room_id and room_id in self.shared.world.rooms:
                old_room_id = self.shared.world.npc_locations.get(npc_id)
                if old_room_id:
                    old_room = self.shared.world.rooms.get(old_room_id)
                    if old_room and npc_id in old_room.npcs:
                        old_room.npcs.remove(npc_id)
                if npc_id not in self.shared.world.rooms.get(room_id, []).npcs:
                    self.shared.world.rooms[room_id].npcs.append(npc_id)
                self.shared.world.npc_locations[npc_id] = room_id

                if old_room_id and old_room_id != room_id:
                    self._broadcast_npc_movement(npc_id, old_room_id, room_id)
