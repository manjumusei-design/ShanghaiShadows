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

    def _broadcast_npc_movement(self, npc_id: str, old_room_id: str, new_room_id: str):
        npc = self.shared.world.npcs.get(npc_id)
        if not npc:
            return
        
        old_room = self.shared.world.rooms.get(old_room_id)
        new_room = self.shared.world.rooms.get(new_room_id)

        if old_room:
            for session in self.session_manager.get_players_in_room(old_room_id):
                direction = self._get_direction(old_room_id, new_room_id)
                if direction:
                    asyncio.create_task(session.send_display(f"{npc.name} walks {direction}."))
            
        if new_room:
            for session in self.session_manager.get_players_in_room(new_room_id):
                direction = self._get_direction(new_room_id, old_room_id)
                if direction:
                    asyncio.create_task(session.send_display(f"{npc.name} arrives from {direction}."))

    def _get_direction(self, from_room: str, to_room: str) -> str:
        from_room_obj = self.shared.world.rooms.get(from_room)
        if not from_room_obj:
            return ""
        for direction, dest in from_room_obj.exits.items():
            if dest == to_room:
                return direction
        return ""
    
    def _process_gossip(self):
        for room in self.shared.world.rooms.values():
            npc_ids = room.npcs
            if len(npc_ids) < 2:
                continue
            for i in range(len(npc_ids) -1):
                from .trust import exchange_gossip
                a = self.shared.world.npcs.get(npc_ids[i])
                b = self.shared.world.npcs.get(npc_ids[i+1])
                if not a or not b:
                    continue
                if exchange_gossip(a.memory, b.memory, chance=0.25):
                    rumor = b.memory[-1] if b.memory else ""
                    if rumor:
                        self.shared.rumour_mill.setdefault(b.faction, []).append(rumor)
                        self.shared.rumour_mill[b.faction] = self.shared.rumour_mill[b.faction][-12:]

    async def _process_planted_evidence_all_sessions(self):
        for session in self.session_manager.sessions.values(): 
            if session.player.planted_evidence:
                await self._check_planted_evidence_for_session(session)

    async def _check_planted_evidence_for_session(self, session: Session):
        from .commands import CommandContext
        remaining = []
        for planted in session.player.planted_evidence:
            room = self.shared.world.get_room(str(planted["room_id"]))
            target = str(planted.get("target", "")).lower()
            triggered = False
            if room:
                for npc_id in room.npcs:
                    npc = self.shared.world.npcs.get(npc_id)
                    if not npc:
                        continue
                    if not target or target in npc.faction.lower() or target in npc.role.lower() or target in npc.name.lower():
                        event_text = f"Your planted {planted['item_name']} in {room.title} has stirred suspicion."
                        session.player.world_events.append(event_text)
                        session.player.world_events = session.player.world_events[-50:]
                        self.shared.event_log.append({
                            "day": self.shared.game_time.day,
                            "minute": self.shared.game_time.minute,
                            "text": event_text,
                        })
                        self.shared.event_log = self.shared.event_log[-500:]
                        self.shared.rumour_mill.setdefault(npc.faction, []).append(event_text)
                        asyncio.create_task(session.send_display(event_text))
                        triggered = True
                        break
            if not triggered:
                remaining.append(planted)
        session.player.planted_evidence = remaining

    async def _process_tailing_all_sessions(self):
        for session in self.session_manager.sessions.values():
            if session.player.tailing_state:
                await self._process_tailing_for_session(session)

