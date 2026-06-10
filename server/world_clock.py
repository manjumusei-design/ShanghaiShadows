import asyncio
import random
from typing import TYPE_CHECKING

from .constants import (
    CURFEW_MINUTE,
    EVENT_LOG_MAXLEN,
    WORLD_EVENTS_MAXLEN,
    HUNGER_DECAY_RATE,
    HUNGER_HEALTH_DAMAGE,
    LOW_HUNGER_THRESHOLD,
)
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

    async def tick(self):
        if not self.session_manager.sessions:
            return
        
        if any(s.manually_advancing for s in self.session_manager.sessions.values()):
            return
        
        self._advance_time_one_minute()
        self._move_npcs_if_hour_changed()
        self._process_gossip()
        self._process_npc_autonomy()
        await self._process_planted_evidence_all_sessions()
        await self._process_tailing_all_sessions()
        await self._check_curfew_all_sessions()
        if self.shared.game_time.minute % 15 == 0:
            await self._check_storylets()
        if self.shared.game_time.minute % 60 == 0 and self.shared.game_time.minute > 0:
            self._check_mission_expiry()
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

        await self._check_room_storylet_timeouts()

    async def _check_room_storylet_timeouts(self):
        import time
        expired_rooms = []
        for room_id, storylet_data in self.shared.active_room_storylets.items():
            if storylet_data.get("resolved", False):
                expired_rooms.append(room_id)
                continue
            triggered_at = storylet_data.get("triggered_at", 0)
            if time.time() - triggered_at > 30:
                options = storylet_data.get("options", [])
                if options:
                    first_option = options[0]
                    await self._resolve_room_storylet(room_id, first_option)
                else:
                    expired_rooms.append(room_id)

        for room_id in expired_rooms:
            if room_id in self.shared.active_room_storylets:
                del self.shared.active_room_storylets[room_id]

    def _apply_trust_effects(self, player, trust_changes: dict) -> None:
        from .trust import change_trust
        for faction, delta in trust_changes.items():
            change_trust(player.trust, faction, delta)

    def _apply_flag_effects(self, player, flag: str) -> None:
        player.flags.appemd(flag)

    def _apply_item_effects(self, player, item_id: str) -> None:
        item = self.shared.world.clone_item(item_id)
        if item:
            player.inventory.append(item)

    def _apply_health_effects(self, player, health_change: int) -> None:
        player.health = max(0, min(100, player.health + health_change))

    def _apply_morale_effects(self, player, morale_change: int) -> None:
        player.morale = max(0, min(100, player.morale + morale_change))

    EFFECT_HANDLERS = {
        "trust": lambda s, v: s._apply_trust_effects(s.player, v),
        "flag": lambda s, v: s._apply_flag_effects(s.player, v),
        "item": lambda s, v: s._apply_item_effects(s.player, v),
        "health": lambda s, v: s._apply_health_effects(s.player, v),
        "morale": lambda s, v: s._apply_morale_effects(s.player, v),
    }

    async def _resolve_room_storylet(self, room_id: str, option_index: int, option):
        if room_id not in self.shared.active_room_storylets:
            return
        
        storylet_data = self.shared.active_room_storylets[room_id]
        storylet_data["resolved"] = True

        effects = option.get("effects", {})
        for session in self.session_manager.get_players_in_room(room_id):
            if session.player.active_storylet and session.player.active_storylet.room_id == room_id:
                session.player.active_storylet = None

                for effect_type, effect_value in effects.item():
                    handler = self.EFFECT_HANDLERS.get(effect_type)
                    if handler:
                        handler(self, effect_value)

                if option_index == 0:
                    asyncio.create_task(session.send_display("The moment passes."))
                else:
                asyncio.create_task(session.send_display(f"You chose option {option_index + 1}. The moment passes."))

    def _check_mission_expiry(self):
        mm = self.shared.mission_manager
        if not mm:
            return
        for session in self.session_amanger.sessions.values():
            expired = mm.check_expiry(session.player, self.shared.game_time.day)
            for mid in expired:
                asyncio.create_task(session.send_display(f"Mission {mid} has expired."))

    def _process_survival_all_sessions(self):
        for session in self.session_manager.sessions.values():
            session.player.hunger = max(0, session.player.hunger - HUNGER_DECAY_RATE)
            if session.player.hunger <= LOW_HUNGER_THRESHOLD:
                session.player.health = max(0, session.player.health - HUNGER_HEALTH_DAMAGE)
                if self.shared.game_time.minute % 30 == 0:
                    from .locales import get as loc
                    asyncio.create_task(session.send_display(loc("hunger.cramps")))
            if session.player.hunger > 80 and self.shared.game_time.minute % 60 == 0:
                session.player.health = min(100, session.player.health + 1)

    def _process_npc_autonomy(self):
        import random
        from .trust import exchange_gossip

        if self.shared.game_time.minute % 30 != 0:
            return
        
        world_tension = (self.shared.ccp_influence + self.shared.gmd_influence) / 2
        base_act_chance = 0.2
        if world_tension > 50:
            base_act_chance = 0.3

        rooms_with_players = set()
        for session in self.session_manager.sessions.values():
            rooms_with_players.add(session.player.current_room)

        for npc_id, npc in self.shared.world.npcs.items():
            current_room_id = self.shared.world.npc_locations.get(npc_id)
            if not current_room_id:
                continue
            current_room = self.shared.world.rooms.get(current_room_id)
            if not current_room:
                continue
            skip_npc = False
            for session in self.session_manager.get_players_in_room(current_room_id):
                if session.player.active_storylet or session.player.manually_advancing:
                    skip_npc = True
                    break
            if skip_npc:
                continue
            if random.random() >= base_act_chance:
                continue

            roll = random.random()
            action_roll = random.random()
            if roll < 0.40:
                self._npc_move_action(npc, current_room_id, current_room, rooms_with_players)
            elif roll < 0.60:
                self._npc_gossip_action(npc, current_room, rooms_with_players)
            elif roll < 0.70:
                self._npc_argue_action(npc, current_room, rooms_with_players)
            elif roll < 0.80:
                self._npc_flee_action(npc, current_room_id, current_room, rooms_with_players)

    def _move_npc_between_rooms(self, npc_id: str, from_room_id: str, to_room_id: str, direction: str = "", silent: bool = False):
        old_room = self.shared.world.rooms.get(from_room_id)
        if old_room and npc_id in old_room.npcs:
            old_room.npcs.remove(npc_id)

        dest_room = self.shared.world.rooms.get(to_room_id)
        if dest_room:
            dest_room.npcs.append(npc_id)
            self.shared.world.npc_locations[npc_id] = to_room_id
            return True
        return False
    
    def _get_nearby_npcs(self, npc_id: str, current_room) -> list:
        return [self.shared.world.npcs.get(nid) for nid in current_room.npcs if nid != npc_id and self.shared.world.npcs.get(nid)]

    def _npc_move_action(self, npc, current_room_id: str, current_room, rooms_with_players: set):
        import random
        if not current_room.exits:
            return

        direction = random.choice(list(current_room.exits.keys()))
        dest_room_id = current_room.exits[direction]

        if self._move_npc_between_rooms(npc.id, current_room_id, dest_room_id):
            if current_room_id in rooms_with_players or dest_room_id in rooms_with_players:
                for session in self.session_manager.get_players_in_room(current_room_id):
                    asyncio.create_task(session.send_display(f"{npc.name} walks {direction}."))

                for session in self.session_manager.get_players_in_room(dest_room_id):
                    asyncio.create_task(session.send_display(f"{npc.name} walks {direction}."))

    def _npc_gossip_action(self, npc, current_room, rooms_with_players: set):
        from.trust import exchange_gossip
        import random

        nearby_npcs = self._get_nearby_npcs(npc.id, current_room)
        if not nearby_npcs:
            return
        
        other = random.choice(nearby_npcs)
        if exchange_gossip(npc.memory, other.memory, chance=0.5):
            if current_room.id in rooms_with_players:
                for session in self.session_manager.get_players_in_room(current_room.id):
                    asyncio.create_task(session.send_display(f"{npc.name} whispers something to {other.name}."))

    def _npc_argue_action(self, npc, current_room, rooms_with_players: set):
        import random

        nearby_npcs = self._get_nearby_npcs(npc.id, current_room)
        if not nearby_npcs:
            return
        
        opponents = [n for n in nearby_npcs if self._are_opposite_factions(npc.faction, n.faction)]
        if not opponents:
            return

        opponent = random.choice(opponents)
        if current_room.id in rooms_with_players:
            for session in self.session_manager.get_players_in_room(current_room.id):
                messages = [
                    f"{npc.name} argues heatedly with {opponent.name}.",
                    f"{npc.name} and {opponent.name} exchange angry words.",
                    f"Tension rises as {npc.name} confronts {opponent.name}."
                ]
                asyncio.create_task(session.send_display(random.choice(messages)))

    def _npc_flee_action(self, npc, current_room_id: str, current_room, rooms_with_players: set):
        import random

        nearby_npcs = self._get_nearby_npcs(npc.id, current_room)
        kempeitai_nearby = any(n.faction == "kempeitai" for n in nearby_npcs)
        is_resistance = npc.faction in ["ccp", "gmd"]

        if not (kempeitai_nearby and is_resistance):
            return

        if not current_room.exits:
            return

        direction = random.choice(list(current_room.exits.keys()))
        dest_room_id = current_room.exits[direction]

        if self._move_npc_between_rooms(npc.id, current_room_id, dest_room_id):
            if current_room_id in rooms_with_players or dest_room_id in rooms_with_players:
                for session in self.session_manager.get_players_in_room(current_room_id):
                    asyncio.create_task(session.send_display(f"{npc.name} flees {direction}!"))

OPPOSITE_FACTION_PAIRS = {
    ("ccp", "kempeitai"),
    ("gmd", "kempeitai"),
    ("ccp", "green_gang"),
    ("gmd", "green_gang"),
    ("green_gang", "civilian"),
}

def _are_opposite_factions(self, faction1: str, faction2: str) -> bool:
    pair = tuple(sorted([faction1, faction2]))
    return pair in OPPOSITE_FACTION_PAIRS

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
                    ending_text = generate_liberation_ending(ending, session.player.name, self.shared.legacy_book, self.shared.ccp_influence, self.shared.gmd_influence)
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
