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

    async def _process_tailing_for_session(self, session: Session):
        tail = session.player.tailing_state
        current_total = (self.shared.game_time.day - 1) * 1440 + self.shared.game_time.minute
        if current_total - tail.last_checked_minute < 5:
            return
        tail.last_checked_minute = current_total
        tail.elapsed_minutes += 5
        target = self.shared.world.npcs.get(tail.target_npc_id)
        if not target:
            session.player.tailing_state = None
            from .locales import get as loc
            asyncio.create_task(session.send_display(loc("cmd_tail.target_vanished")))
            return
        success, _ = self.stealth.tail_check(
            tail,
            target,
            session.player.stealth_skill,
            self._disguise_bonus_for_session(session),
            session.player.hidden,
        )
        if not success and tail.distance <= 0:
            session.player.tailing_state = None
            session.player.world_events.append(f"{target.name} spotted you while you were tailing them.")
            session.player.world_events = session.player.world_events[-50:]
            asyncio.create_task(session.send_display(f"{target.name} glances over a shoulder, slows, and knows exactly what you are doing."))
            return
        target_room = self.shared.world.npc_locations.get(target.id)
        if success and target_room and session.player.current_room != target_room:
            session.player.current_room = target_room
            session.player.hidden = False
            asyncio.create_task(session.send_display(f"You shadow {target.name} and keep them in sight."))

    def _disguise_bonus_for_session(self, session: Session) -> int:
        disguise = self.disguises.get(session.player.disguise)
        return disguise.bonus if disguise else 0
    
    async def _check_curfew_all_sessions(self):
        if self.shared.game_time.minute < CURFEW_MINUTE:
            return
        for session in self.session_manager.sessions.values():
            if session.player.last_curfew_penalty_day != self.shared.game_time.day:
                room = self.shared.world.get_room(session.player.current_room)
                if room and not room.indoors:
                    from .commands import CommandContext
                    from .trust import apply_trust_delta
                    rule = self.shared.trust_rules.get("out_after_curfew")
                    if rule:
                        apply_trust_delta(session.player.trust, rule)
                        if getattr(rule, "visible", False):
                            for npc_id in room.npcs:
                                npc = self.shared.world.npcs.get(npc_id)
                                if npc:
                                    memory = f"Observed player action: out_after_curfew"
                                    if memory not in npc.memory:
                                        npc.memory.append(memory)
                    session.player.last_curfew_penalty_day = self.shared.game_time.day
                    session.player.world_events.append("You were seen outside after curfew.")
                    session.player.world_events = session.player.world_events[-WORLD_EVENTS_MAXLEN:]
                    self.shared.event_log.append({
                        "day": self.shared.game_time.day,
                        "minute": self.shared.game_time.minute,
                        "text": "You were seen outside after curfew.",
                    })
                    self.shared.event_log = self.shared.event_log[-EVENT_LOG_MAXLEN:]
                    from .locales import get as loc
                    asyncio.create_task(session.send_display(loc("curfew.warning")))

    async def _check_storylets(self):
        for session in self.session_manager.sessions.values():
            if not session.player.active_storylet:
                from .commands import CommandContext
                active = self.storylet_manager.maybe_trigger_for_player(session.player, self.shared)
                if active:
                    session.player.active_storylet = active
                    lines = [active.narrative]
                    for idx, option in enumerate(active.options, start=1):
                        lines.append(f"{idx}. {option.text}")
                    asyncio.create_task(session.send_display("\n".join(lines)))

    def _process_survival_all_sessions(self):
        HUNGER_DECAY_RATE = 0.5
        HUNGER_HEALTH_DAMAGE = 2
        LOW_HUNGER_THRESHOLD = 20

        for session in self.session_manager.sessions.values():
            session.player.hunger = max(0, session.player.hunger - HUNGER_DECAY_RATE)
            if session.player.hunger <= LOW_HUNGER_THRESHOLD:
                session.player.health = max(0, session.player.health - HUNGER_HEALTH_DAMAGE)
                if self.shared.game_time.minute % 30 == 0:
                    from .locales import get as loc
                    asyncio.create_task(session.send_display(loc("hunger.cramps")))
            if session.player.hunger > 80 and self.shared.game_time.minute % 60 == 0:
                session.player.health = min(100, session.player.health + 1)

    async def _check_death_and_victory(self):
        from .victory import check_victory_conditions
        from .trust import get_role_trust
        from .locales import get as loc

        for session in self.session_manager.sessions.values():
            is_dead = False
            death_message = ""

            if session.player.health <= 0:
                is_dead = True
                death_message = loc("death.health")
            elif session.player.arrested:
                kempeitai_trust = get_role_trust(session.player.trust, "kempeitai", None)
                if kempeitai_trust < 25:
                    is_dead = True
                    death_message = loc("death.arrest")

            if is_dead:
                from .commands import _generate_obituary, format_life_retrospective
                obituary = _generate_obituary(session.player, death_message)
                retrospective = format_life_retrospective(self.shared.event_log, session.player.name)
                self.shared.legacy_book.append({
                    "character_name": session.player.name,
                    "obituary": obituary,
                    "summary": retrospective,
                    "day_of_death": self.shared.game_time.day,
                })
                end_screen = f"""THE END

{death_message}

---
{obituary}
---

{retrospective}

{loc("death.legacy")}
"""
                asyncio.create_task(session.send_display(end_screen))
                session.player.flags.append("player_died")
                from .save_manager import save_player
                save_player(session.player)
                session.running = False
                try:
                    await session.websocket.close()
                except Exception:
                    pass

            if self.shared.game_time.minute == 0:
                ending = check_victory_conditions(
                    self.shared.game_time.day,
                    self.shared.ccp_influence,
                    self.shared.gmd_influence,
                )
                if ending:
                    from .commands import trigger_ending
                    from .save_manager import save_player, save_world_state
                    from .victory import generate_liberation_ending, compile_legacy_narrative
                    ending_text = generate_liberation_ending(ending, session.player.name, self.shared.legacy_book)
                    legacy = compile_legacy_narrative(self.shared.legacy_book)

                    end_screen = f"""
{ending_text}

{legacy}

{loc("victory.footer")}
"""
                    asyncio.create_task(session.send_display(end_screen))
                    session.player.flags.append("player_died")
                    save_player(session.player)
                    save_world_state(self.shared)
                    session.running = False
                    try:
                        await session.websocket.close()
                    except Exception:
                        pass

    async def _broadcast_display(self, text: str):
        for session in self.session_manager.sessions.values():
            try:
                await session.send_display(text)
            except Exception:
                pass
