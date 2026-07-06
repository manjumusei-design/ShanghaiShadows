import asyncio
import random
import time
from collections import deque, defaultdict
from typing import TYPE_CHECKING, Optional

from .constants import (
    CURFEW_MINUTE,
    EVENT_LOG_MAXLEN,
    WORLD_EVENTS_MAXLEN,
    HUNGER_DECAY_RATE,
    HUNGER_HEALTH_DAMAGE,
    HUNGER_WARNING_THRESHOLD,
    LOW_HUNGER_THRESHOLD,
    MORALE_DECAY_PER_HOUR,
    MORALE_WARNING_THRESHOLD,
    MORALE_LOW_THRESHOLD,
    STAT_GAIN_STEALTH_TAIL,
    WANTED_LEVEL_MAX,
    HIDDEN_DECAY_CHANCE,
    SUSPICION_DECAY_PER_TICK,
    SUSPICION_THRESHOLD_INVESTIGATE,
    SUSPICION_INVESTIGATE_RELIEF,
    VENDOR_SHUTTER_TENSION,
    VENDOR_REOPEN_TENSION,
    DEFECTION_DISILLUSIONMENT_THRESHOLD,
    DEFECTION_DAILY_CHANCE,
    DISILLUSIONMENT_PER_TICK,
    SEASONAL_FOOD_SHORTAGE,
    FOOD_RESTOCK_INTERVAL,
    RUMORS_PATH,
    AMBIENT_EVENTS_PATH,
    MessageType,
    AUTO_SAVE_WORLD_INTERVAL,
    AUTO_SAVE_PLAYER_INTERVAL,
)
from .ambient_events import load_ambient_events, check_ambient_trigger
from .pathfinding import propagate_sound
from .player_data import grow_stat
from .trust import exchange_gossip
from .victory import _season_from_day
from .combat import strip_article
from .constants import (
    SEASONAL_MORALE_MODIFIER, SEASONAL_STEALTH_MODIFIER,
    SEASONAL_PERCEPTION_MODIFIER, SEASONAL_CURFEW_MODIFIER,
    SEASONAL_PATROL_DENSITY,
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
from .locales import get as loc

if TYPE_CHECKING:
    from .session_manager import SessionManager
    from .ai_client import AIClient

def _describe_relationship(rel_type: str, strength: int) -> str:
    if rel_type == "friend":
        if strength >= 70:
            return "warmly"
        elif strength >= 40:
            return "with concern"
        return "in a friendly way"
    elif rel_type in ("close_friend", "family"):
        return "intimately"
    elif rel_type == "enemy":
        if strength >= 60:
            return "mockingly"
        elif strength >= 30:
            return "coldly"
        return "with disdain"
    elif rel_type == "rival":
        return "skeptically"
    return "casually"

#this functions prompt was ai generated 
async def _ai_enhance_gossip(ai_client: Optional["AIClient"], npc_a_name: str, npc_b_name: str, rumor: str, relationship_context: str = "") -> str:
    if not ai_client:
        return None
    
    context = f" Their relationship is {relationship_context}." if relationship_context else ""
    prompt = f"""You are writing NPC dialogue for a 1930s Shanghai RPG. Two NPCs, {npc_a_name} and {npc_b_name}, are gossiping.{context}
Create a brief (1-2 sentences max) piece of dialogue where {npc_a_name} tells {npc_b_name} about: "{rumor}"

Write only the spoken words in quotes. Use period-appropriate slang sparingly if at all. Stay under 50 words."""

    try:
        enhanced = await ai_client.chat_text([{"role": "user", "content": prompt}], timeout_seconds=3.0)
        if ehnahced and len(enhanced) < 300:
            return enhanced.strip()
    except Exception:
        pass
    return None
 
class WorldClock:
    def __init__(self, shared: SharedWorldState, session_manager: "SessionManager", disguises, stealth, storylet_manager):
        self.shared = shared
        self.session_manager = session_manager
        self.disguises = disguises
        self.stealth = stealth
        self.storylet_manager = storylet_manager
        self._bt_registry = None

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
        if self.shared.game_time.minute % 60 == 0:
            self._update_weather()
        self._process_survival_all_sessions()
        if self.shared.game_time.minute % 360 == 0:
            self._respawn_dead_npcs()
        if self.shared.game_time.minute % FOOD_RESTOCK_INTERVAL == 0:
            self._restock_market_food()
        if self.shared.game_time.minute % 30 == 0:
            self._process_ambient_sounds()
        await self._check_death_and_victory()

    def _advance_time_one_minute(self):
        self.shared.game_time.minute += 1
        if self.shared.game_time.minute >= 1440:
            self.shared.game_time.minute = 0
            self.shared.game_time.day += 1
            self._rotate_rumors()
            from .economy import economy_system
            economy_system.update_market_conditions(self.shared.game_time.day, self.shared)
        self.shared.scheduler.process(
            self.shared.game_time,
            lambda msg: asyncio.create_task(self._broadcast_display(msg)),
            self.shared,
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
                    asyncio.create_task(session.send_display(loc("ambient.npc_walks").format(name=npc.name, direction=direction), msg_type=MessageType.NPC_AMBIENT))

        if new_room:
            for session in self.session_manager.get_players_in_room(new_room_id):
                direction = self._get_direction(new_room_id, old_room_id)
                if direction:
                    asyncio.create_task(session.send_display(loc("ambient.npc_arrives").format(name=npc.name, direction=direction), msg_type=MessageType.NPC_AMBIENT))

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
            if not self.session_manager.get_players_in_room(room.id):
                continue
            for i in range(len(npc_ids) - 1):
                a = self.shared.world.npcs.get(npc_ids[i])
                b = self.shared.world.npcs.get(npc_ids[i + 1])
                if not a or not b:
                    continue
                if exchange_gossip(a.memory, b.memory, chance=0.25):
                    rumor = b.memory[-1] if b.memory else ""
                    if rumor:
                        self.shared.rumour_mill.setdefault(b.faction, []).append(rumor)
                        self.shared.rumour_mill[b.faction] = self.shared.rumour_mill[b.faction][-12:]
                        if "Observed player action:" in rumor:
                            for nid in room.npcs:
                                other = self.shared.world.npcs.get(nid)
                                if other:
                                    other.suspicion = min(100, other.suspicion + 5)

    def _rotate_rumors(self):
        from .rumors import seed_active_rumors
        self.shared.active_rumors = seed_active_rumors(self.shared.game_time.day)

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
                        if not isinstance(session.player.world_events, deque):
                            session.player.world_events = deque(session.player.world_events, maxlen=WORLD_EVENTS_MAXLEN)
                        session.player.world_events.append(event_text)
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
            if not tail.stealth_awarded:
                tail.stealth_awarded = True
                grow_stat(session.player, "stealth_skill", STAT_GAIN_STEALTH_TAIL)
                asyncio.create_task(session.send_display("You learn from their movements. (+1 stealth)"))

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
                    arrest_chance = 15 + session.player.wanted_level * 20
                    if random.randint(1, 100) <= arrest_chance:
                        from .commands import _trigger_death
                        ctx = self.session_manager._make_context(session)
                        asyncio.create_task(_trigger_death(ctx, loc("death.arrest")))
                    else:
                        session.player.wanted_level = min(WANTED_LEVEL_MAX, session.player.wanted_level + 1)
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
                    await self._resolve_room_storylet(room_id, 0, first_option)
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
        player.flags.append(flag)

    def _apply_item_effects(self, player, item_id: str) -> None:
        item = self.shared.world.clone_item(item_id)
        if item:
            player.inventory.append(item)

    def _apply_health_effects(self, player, health_change: int) -> None:
        player.health = max(0, min(100, player.health + health_change))

    def _apply_morale_effects(self, player, morale_change: int) -> None:
        player.morale = max(0, min(100, player.morale + morale_change))

    def _resolve_decision(self, decision_type: str, npc_id: str, room_id: str, effects: dict, storylet_id: str = "") -> None:
        npc = self.shared.world.npcs.get(npc_id)
        entry = {
            "id": f"{decision_type}_{self.shared.game_time.day}_{self.shared.game_time.minute}_{npc_id}",
            "day": self.shared.game_time.day,
            "minute": self.shared.game_time.minute,
            "actor_npc_id": npc_id,
            "actor_faction": npc.faction if npc else "",
            "decision_type": decision_type,
            "effects": effects,
            "storylet_id": storylet_id,
            "resolved": False,
        }
        self.shared.world_decisions.append(entry)
        if storylet_id and room_id:
            self.shared.active_room_storylets[room_id] = {
                "storylet_id": storylet_id,
                "triggered_at": time.time(),
                "options": [
                    {"text": "Let events unfold.", "effects": {}},
                ],
                "resolved": False,
                "decision_entry": entry,
            }

    def _accumulate_dispositions(self) -> None:
        ccp_inf = self.shared.ccp_influence
        gmd_inf = self.shared.gmd_influence
        for npc_id, npc in self.shared.world.npcs.items():
            if npc_id in self.shared.dead_npcs:
                continue
            if npc.faction not in ("ccp", "gmd"):
                continue
            own_inf, rival_inf = (ccp_inf, gmd_inf) if npc.faction == "ccp" else (gmd_inf, ccp_inf)
            disp = self.shared.npc_dispositions.setdefault(npc_id, {"disillusionment": 0})
            if own_inf < rival_inf:
                disp["disillusionment"] = min(100, disp["disillusionment"] + DISILLUSIONMENT_PER_TICK)
            elif own_inf > rival_inf + 10:
                disp["disillusionment"] = max(0, disp["disillusionment"] - 1)

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

            for effect_type, effect_value in effects.items():
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
        for session in self.session_manager.sessions.values():
            expired = mm.check_expiry(session.player, self.shared.game_time.day)
            for mid in expired:
                asyncio.create_task(session.send_display(f"Mission {mid} has expired."))

    def _process_survival_all_sessions(self):
        season = _season_from_day(self.shared.game_time.day)
        minute = self.shared.game_time.minute
        hunger_multiplier = 1.5 if season == "winter" else 1.0
        is_summer = season == "summer"

        for session in self.session_manager.sessions.values():
            session.player.hunger = max(0, session.player.hunger - HUNGER_DECAY_RATE * hunger_multiplier)
            if session.player.hunger <= LOW_HUNGER_THRESHOLD:
                session.player.health = max(0, session.player.health - HUNGER_HEALTH_DAMAGE)
                if minute % 30 == 0:
                    from .locales import get as loc
                    asyncio.create_task(session.send_display(loc("hunger.cramps")))
            if session.player.hunger > 80 and minute % 60 == 0:
                session.player.health = min(100, session.player.health + 1)

            if minute % 60 == 0:
                self._apply_morale_effects(session.player, -MORALE_DECAY_PER_HOUR)

            if season == "winter" and minute % 60 == 0:
                room = self.shared.world.get_room(session.player.current_room)
                if room and not room.indoors:
                    has_warm = any(i.id in ("winter_coat", "heavy_jacket") for i in session.player.inventory)
                    if not has_warm:
                        session.player.health = max(0, session.player.health - 1)
                        if session.player.health % 10 == 0:
                            asyncio.create_task(session.send_display(
                                "The winter cold seeps into your bones.\n"
                            ))

            if minute % 15 == 0 and session.player.hidden and random.random() <= HIDDEN_DECAY_CHANCE:
                session.player.hidden = False
                asyncio.create_task(session.send_display(
                    "A passerby glances your way. You are no longer hidden."
                ))

            if is_summer and minute % 60 == 0:
                room = self.shared.world.get_room(session.player.current_room)
                if room and len(room.npcs) >= 3 and not room.indoors:
                    import random
                    if random.randint(1, 100) <= 5:
                        session.player.health = max(0, session.player.health - 1)
                        asyncio.create_task(session.send_display(
                            "The oppressive heat and close quarters make you feel ill.\n"
                        ))

    def _process_npc_autonomy(self):
        import random

        if self.shared.game_time.minute % 30 != 0:
            return

        self._accumulate_dispositions()

        world_tension = (self.shared.ccp_influence + self.shared.gmd_influence) / 2
        base_act_chance = 0.2
        if world_tension > 50:
            base_act_chance = 0.3

        rooms_with_players = self._rooms_with_players()
        bt_registry = self._get_bt_registry()

        for npc_id, npc in self.shared.world.npcs.items():
            if npc_id in self.shared.dead_npcs:
                continue
            current_room_id = self.shared.world.npc_locations.get(npc_id)
            if not current_room_id:
                continue
            current_room = self.shared.world.rooms.get(current_room_id)
            if not current_room:
                continue
            npc.suspicion = max(0, npc.suspicion - SUSPICION_DECAY_PER_TICK)
            skip_npc = False
            for session in self.session_manager.get_players_in_room(current_room_id):
                if session.player.active_storylet or session.player.manually_advancing:
                    skip_npc = True
                    break
            if skip_npc:
                continue
            if random.random() >= base_act_chance:
                continue

            archetype = getattr(npc, "bt_archetype", "")
            if archetype:
                tree = bt_registry.tree_for(npc_id, archetype)
                self._refresh_blackboard(tree.blackboard, npc, current_room_id, current_room)
                tree.tick()
            else:
                roll = random.random()
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

    def _respawn_dead_npcs(self):
        if not self.shared.dead_npcs:
            return
        npc_id = next(iter(self.shared.dead_npcs))
        npc = self.shared.world.npcs.get(npc_id)
        if not npc:
            self.shared.dead_npcs.discard(npc_id)
            return
        rooms = list(self.shared.world.rooms)
        if not rooms:
            return
        room_id = random.choice(rooms)
        self.shared.world.place_npc(npc_id, room_id)
        self.shared.dead_npcs.discard(npc_id)

    def _restock_market_food(self):
        season = _season_from_day(self.shared.game_time.day)
        restock_chance = SEASONAL_FOOD_SHORTAGE.get(season, 1.0)
        for room_id, item_ids in self.shared.market_rooms.items():
            room = self.shared.world.rooms.get(room_id)
            if not room:
                continue
            override = self.shared.room_state_overrides.get(room_id)
            if override and override.get("shop_closed"):
                continue
            existing_ids = {i.id for i in room.items}
            for item_id in item_ids:
                if item_id in existing_ids:
                    continue
                if random.random() <= restock_chance:
                    item = self.shared.world.clone_item(item_id)
                    if item:
                        room.items.append(item)

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
                    asyncio.create_task(session.send_display(f"{npc.name} arrives from the {self._get_direction(dest_room_id, current_room_id)}."))

    def _npc_gossip_action(self, npc, current_room, rooms_with_players: set):
        from .trust import exchange_gossip
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
        frozenset(("kempeitai", "ccp")),
        frozenset(("kempeitai", "gmd")),
        frozenset(("kempeitai", "green_gang")),
        frozenset(("green_gang", "ccp")),
        frozenset(("green_gang", "gmd")),
    }

    def _are_opposite_factions(self, faction_a: str, faction_b: str) -> bool:
        return frozenset((faction_a, faction_b)) in self.OPPOSITE_FACTION_PAIRS

    def _get_bt_registry(self):
        if self._bt_registry is not None:
            return self._bt_registry
        from .behavior_tree import TreeRegistry, Status
        actions = self._build_bt_actions()
        conditions = self._build_bt_conditions()
        self._bt_registry = TreeRegistry.from_yaml(
            action_bindings=actions,
            condition_bindings=conditions,
        )
        return self._bt_registry

    def _build_bt_actions(self):
        from .behavior_tree import Status

        def _npc_ctx(bb, require_room=True, require_exits=False):
            npc_id = bb.get("npc_id")
            npc = self.shared.world.npcs.get(npc_id)
            room_id = self.shared.world.npc_locations.get(npc_id) if npc else None
            room = self.shared.world.rooms.get(room_id) if room_id else None
            if not npc or (require_room and not room) or (require_exits and (not room or not room.exits)):
                return None, None, None
            return npc, room, room_id

        def _action_move(bb):
            npc, room, room_id = _npc_ctx(bb, require_exits=True)
            if not npc:
                return Status.FAILURE
            self._npc_move_action(npc, room_id, room, self._rooms_with_players())
            return Status.SUCCESS

        def _action_gossip(bb):
            npc, room, _ = _npc_ctx(bb)
            if not npc:
                return Status.FAILURE
            self._npc_gossip_action(npc, room, self._rooms_with_players())
            return Status.SUCCESS

        def _action_flee(bb):
            npc, room, room_id = _npc_ctx(bb)
            if not npc:
                return Status.FAILURE
            self._npc_flee_action(npc, room_id, room, self._rooms_with_players())
            return Status.SUCCESS

        def _action_idle(bb):
            return Status.SUCCESS

        def _action_investigate_sound(bb):
            npc, _, _ = _npc_ctx(bb, require_room=False)
            return self._npc_investigate_action(npc, bb)

        def _action_follow_schedule(bb):
            npc, _, _ = _npc_ctx(bb, require_room=False)
            if not npc:
                return Status.FAILURE
            hour = bb.get("game_hour", -1)
            target_room = npc.schedule.get(hour)
            current_room_id = self.shared.world.npc_locations.get(bb.get("npc_id"))
            if not target_room or current_room_id == target_room:
                return Status.FAILURE
            current_room_obj = self.shared.world.rooms.get(current_room_id)
            if current_room_obj:
                self._npc_move_action(npc, current_room_id, current_room_obj, self._rooms_with_players())
                return Status.SUCCESS
            return Status.FAILURE

        def _action_share_intel(bb):
            npc, _, room_id = _npc_ctx(bb, require_room=False)
            if not npc or not room_id:
                return Status.FAILURE
            for session in self.session_manager.get_players_in_room(room_id):
                asyncio.create_task(session.send_display(
                    f"{npc.name} glances around cautiously, then leans in close to share a whispered detail."
                ))
            return Status.SUCCESS

        def _action_hide_in_shadows(bb):
            npc, room, room_id = _npc_ctx(bb)
            if not npc or not room or not room.hiding_spots:
                return Status.FAILURE
            for session in self.session_manager.get_players_in_room(room_id):
                asyncio.create_task(session.send_display(
                    f"{npc.name} slips into the shadows and vanishes from sight."
                ))
            return Status.SUCCESS

        def _action_extort_civilian(bb):
            npc, room, room_id = _npc_ctx(bb)
            if not npc:
                return Status.FAILURE
            civilians = [nid for nid in room.npcs
                         if nid != npc.id and self.shared.world.npcs.get(nid)
                         and self.shared.world.npcs.get(nid).faction == "civilian"]
            if not civilians:
                return Status.FAILURE
            target = self.shared.world.npcs.get(civilians[0])
            for session in self.session_manager.get_players_in_room(room_id):
                asyncio.create_task(session.send_display(
                    f"{npc.name} corners {target.name} and demands something in a low voice."
                ))
            self._resolve_decision("extortion", npc.id, room_id,
                                   {"victim_npc_id": target.id if target else ""},
                                   "extortion_underway")
            return Status.SUCCESS

        def _action_intimidate_rival(bb):
            npc, room, room_id = _npc_ctx(bb)
            if not npc:
                return Status.FAILURE
            rivals = [nid for nid in room.npcs
                      if nid != npc.id and self.shared.world.npcs.get(nid)
                      and self._are_opposite_factions(npc.faction, self.shared.world.npcs.get(nid).faction)]
            if not rivals:
                return Status.FAILURE
            target = self.shared.world.npcs.get(rivals[0])
            for session in self.session_manager.get_players_in_room(room_id):
                asyncio.create_task(session.send_display(
                    f"{npc.name} glares at {target.name} threateningly."
                ))
            return Status.SUCCESS

        def _action_hold_secret_meeting(bb):
            npc, _, room_id = _npc_ctx(bb, require_room=False)
            if not npc or not room_id:
                return Status.FAILURE
            for session in self.session_manager.get_players_in_room(room_id):
                asyncio.create_task(session.send_display(
                    f"{npc.name} beckons you closer. 'We need to talk. Quickly.'"
                ))
            return Status.SUCCESS

        def _action_investigate_player(bb):
            npc, room, room_id = _npc_ctx(bb)
            if not npc or not room_id:
                return Status.FAILURE
            players = self.session_manager.get_players_in_room(room_id)
            target = next((s for s in players if s.player.hidden), None)
            if not target:
                for nid in room.npcs:
                    other = self.shared.world.npcs.get(nid)
                    if other:
                        other.suspicion = 0
                return Status.FAILURE
            target.player.hidden = False
            asyncio.create_task(target.send_display(
                f"{npc.name} scans the shadows and spots you. 'What are you doing?'"
            ))
            for nid in room.npcs:
                other = self.shared.world.npcs.get(nid)
                if other:
                    other.suspicion = max(0, other.suspicion - SUSPICION_INVESTIGATE_RELIEF)
            return Status.SUCCESS

        def _action_shutter_shop(bb):
            npc, room, room_id = _npc_ctx(bb)
            if not npc or not room_id:
                return Status.FAILURE
            world_tension = (self.shared.ccp_influence + self.shared.gmd_influence) / 2
            if world_tension < VENDOR_SHUTTER_TENSION:
                return Status.FAILURE
            if bb.get("courage", 50) >= 40:
                return Status.FAILURE
            self.shared.room_state_overrides[room_id] = {
                "shop_closed": True,
                "closed_reason": f"{npc.name} has fled Shanghai, fearing the rising tension.",
            }
            self._resolve_decision("vendor_shutter", npc.id, room_id,
                                   {"room_id": room_id}, "vendor_fled")
            schedule_rooms = [r for h, r in npc.schedule.items() if r in self.shared.world.rooms]
            if schedule_rooms:
                self._move_npc_between_rooms(npc.id, room_id, schedule_rooms[0])
            for session in self.session_manager.get_players_in_room(room_id):
                asyncio.create_task(session.send_display(
                    f"{npc.name} boards up the shop and slips away into the crowd."
                ))
            return Status.SUCCESS

        def _action_defect(bb):
            npc, room, room_id = _npc_ctx(bb, require_room=False)
            if not npc:
                return Status.FAILURE
            old_faction = npc.faction
            new_faction = "gmd" if old_faction == "ccp" else "ccp"
            npc.faction = new_faction
            self.shared.npc_dispositions.pop(npc.id, None)
            self._resolve_decision("defection", npc.id, room_id or "",
                                   {"old_faction": old_faction, "new_faction": new_faction})
            for nid, other in self.shared.world.npcs.items():
                if nid != npc.id and other.faction == old_faction:
                    disp = self.shared.npc_dispositions.setdefault(nid, {"disillusionment": 0})
                    disp["disillusionment"] = min(100, disp["disillusionment"] + 5)
            asyncio.create_task(self._broadcast_display(
                f"Rumour spreads: {npc.name} has abandoned the {old_faction.upper()} for the {new_faction.upper()}."
            ))
            return Status.SUCCESS

        return {
            "patrol_random_exit": _action_move,
            "investigate_sound": _action_investigate_sound,
            "follow_schedule": _action_follow_schedule,
            "trade_gossip": _action_gossip,
            "exchange_rumors": _action_gossip,
            "share_intel": _action_share_intel,
            "gather_rumors": _action_gossip,
            "hide_in_shadows": _action_hide_in_shadows,
            "patrol_quietly": _action_move,
            "patrol_territory": _action_move,
            "extort_civilian": _action_extort_civilian,
            "intimidate_rival": _action_intimidate_rival,
            "hold_secret_meeting": _action_hold_secret_meeting,
            "delegate_task": _action_gossip,
            "stay_put": _action_idle,
            "flee_to_safe_room": _action_flee,
            "flee_from_authority": _action_flee,
            "investigate_player": _action_investigate_player,
            "shutter_shop": _action_shutter_shop,
            "defect": _action_defect,
            "idle": _action_idle,
        }

    def _build_bt_conditions(self):
        def _cond_heard_hostile_sound(bb):
            return bb.get("heard_hostile_sound", False)

        def _cond_on_schedule_time(bb):
            npc_id = bb.get("npc_id")
            npc = self.shared.world.npcs.get(npc_id)
            return npc is not None and bb.get("game_hour", -1) in npc.schedule

        _cond_danger_nearby = _cond_high_alert = lambda bb: bb.get("danger_nearby", False)
        _cond_kempeitai_in_room = _cond_authority_nearby = lambda bb: bb.get("kempeitai_in_room", False)

        def _cond_courage_low(bb):
            return bb.get("courage", 50) < 40

        _cond_customer_nearby = _cond_trusted_player_nearby = lambda bb: bb.get("nearby_player_count", 0) > 0

        def _cond_nearby_same_faction(bb):
            npc_id = bb.get("npc_id")
            npc = self.shared.world.npcs.get(npc_id)
            return npc is not None and bb.get("nearby_same_faction", 0) > 0

        _cond_subordinate_nearby = _cond_nearby_same_faction

        def _cond_not_disguised(bb):
            return True

        def _cond_hiding_spots_available(bb):
            return bb.get("hiding_spots", False)

        def _cond_civilian_nearby(bb):
            return bb.get("nearby_civilian_count", 0) > 0

        def _cond_not_watched(bb):
            return not bb.get("kempeitai_in_room", False)

        def _cond_gang_rival_nearby(bb):
            return bb.get("nearby_rival_count", 0) > 0

        def _cond_player_suspicious(bb):
            return bb.get("player_suspicion_nearby", False)

        def _cond_tension_high(bb):
            return bb.get("world_tension", 0) > VENDOR_SHUTTER_TENSION

        def _cond_should_defect(bb):
            disillusionment = bb.get("disillusionment", 0)
            if disillusionment < DEFECTION_DISILLUSIONMENT_THRESHOLD:
                return False
            return random.random() < DEFECTION_DAILY_CHANCE

        return {
            "heard_hostile_sound": _cond_heard_hostile_sound,
            "on_schedule_time": _cond_on_schedule_time,
            "danger_nearby": _cond_danger_nearby,
            "courage_low": _cond_courage_low,
            "customer_nearby": _cond_customer_nearby,
            "nearby_same_faction": _cond_nearby_same_faction,
            "kempeitai_in_room": _cond_kempeitai_in_room,
            "not_disguised": _cond_not_disguised,
            "trusted_player_nearby": _cond_trusted_player_nearby,
            "hiding_spots_available": _cond_hiding_spots_available,
            "high_alert": _cond_high_alert,
            "authority_nearby": _cond_authority_nearby,
            "civilian_nearby": _cond_civilian_nearby,
            "not_watched": _cond_not_watched,
            "gang_rival_nearby": _cond_gang_rival_nearby,
            "subordinate_nearby": _cond_subordinate_nearby,
            "player_suspicious": _cond_player_suspicious,
            "tension_high": _cond_tension_high,
            "should_defect": _cond_should_defect,
        }

    def _rooms_with_players(self) -> set:
        return {s.player.current_room for s in self.session_manager.sessions.values()}

    def _refresh_blackboard(self, bb, npc, room_id, room):
        game_time = self.shared.game_time
        bb.set("current_room_id", room_id)
        bb.set("game_minute", game_time.minute + game_time.day * 1440)
        bb.set("game_hour", game_time.hour)
        bb.set("weather", getattr(self.shared, "weather", "clear"))
        bb.set("courage", npc.courage)
        bb.set("awareness", npc.awareness)
        bb.set("perception", npc.perception)
        bb.set("faction", npc.faction)

        bb.set("hiding_spots", room.hiding_spots if room else False)
        bb.set("safe_room", room.safe_room if room else False)

        nearby_npcs = self._get_nearby_npcs(npc.id, room) if room else []
        bb.set("nearby_npc_count", len(nearby_npcs))
        bb.set("nearby_same_faction", sum(1 for n in nearby_npcs if n.faction == npc.faction))
        bb.set("nearby_rival_count", sum(1 for n in nearby_npcs if self._are_opposite_factions(npc.faction, n.faction)))
        bb.set("kempeitai_in_room", any(n.faction == "kempeitai" for n in nearby_npcs))
        bb.set("nearby_civilian_count", sum(1 for n in nearby_npcs if n.faction == "civilian"))
        player_count = len(self.session_manager.get_players_in_room(room_id)) if room else 0
        bb.set("nearby_player_count", player_count)

        bb.set("danger_nearby", bb.get("kempeitai_in_room", False) and npc.faction in ("ccp", "gmd"))
        bb.set("player_suspicion_nearby",
               npc.suspicion > SUSPICION_THRESHOLD_INVESTIGATE
               or any(n.suspicion > SUSPICION_THRESHOLD_INVESTIGATE for n in nearby_npcs))

        world_tension = (self.shared.ccp_influence + self.shared.gmd_influence) / 2
        bb.set("world_tension", world_tension)
        disp = self.shared.npc_dispositions.get(npc.id, {})
        bb.set("disillusionment", disp.get("disillusionment", 0))

        npc_bb = getattr(npc, "_blackboard", None)
        if npc_bb:
            sound = npc_bb.get("last_heard_sound")
            if sound:
                bb.set("last_heard_sound", sound)
            bb.set("heard_hostile_sound", npc_bb.get("heard_hostile_sound", False))

    def _npc_investigate_action(self, npc, bb):
        from .behavior_tree import Status
        from .pathfinding import a_star_find_path
        sound = bb.get("last_heard_sound")
        if not sound:
            return Status.FAILURE
        target_room_id = sound.get("room_id") if isinstance(sound, dict) else None
        if not target_room_id:
            return Status.FAILURE
        npc_id = bb.get("npc_id")
        current_room_id = self.shared.world.npc_locations.get(npc_id)
        if current_room_id == target_room_id:
            bb.clear("last_heard_sound")
            return Status.SUCCESS
        current_room = self.shared.world.rooms.get(current_room_id) if current_room_id else None
        if not current_room or not current_room.exits:
            bb.clear("last_heard_sound")
            return Status.FAILURE
        path = a_star_find_path(
            self.shared.world.rooms, current_room_id, target_room_id,
            cost_fn=lambda a, b: 1.0,
        )
        if not path:
            bb.clear("last_heard_sound")
            return Status.FAILURE
        direction = path[0]
        dest_id = current_room.exits.get(direction)
        if dest_id:
            rooms_with_players = self._rooms_with_players()
            self._move_npc_between_rooms(npc_id, current_room_id, dest_id, direction)
            if current_room_id in rooms_with_players or dest_id in rooms_with_players:
                for session in self.session_manager.get_players_in_room(current_room_id):
                    asyncio.create_task(session.send_display(f"{npc.name} moves purposefully {direction}."))
            return Status.RUNNING
        bb.clear("last_heard_sound")
        return Status.FAILURE

    def _update_weather(self):
        season = _season_from_day(self.shared.game_time.day)
        rain_chance = 30 if season in ("summer", "autumn") else 10
        if random.randint(1, 100) <= rain_chance:
            self.shared.weather = "rain"
        else:
            self.shared.weather = "clear"
        if self.shared.weather == "rain":
            self._apply_weather_degradation()

    def _apply_weather_degradation(self):
        from .constants import DEGRADE_RAIN_RATE
        for session in self.session_manager.sessions.values():
            room = self.shared.world.get_room(session.player.current_room)
            if room and room.indoors:
                continue
            broken = []
            for item in session.player.inventory:
                if not (item.is_weapon or item.is_armour) or item.durability <= 0:
                    continue
                item.durability = max(0, item.durability - DEGRADE_RAIN_RATE)
                if item.durability <= 0:
                    verb = "rusts apart" if item.is_weapon else "is ruined by the rain"
                    asyncio.create_task(session.send_display(f"Your {item.name} {verb}."))
                    broken.append(item)
            for item in broken:
                session.player.inventory.remove(item)

    async def _check_death_and_victory(self):
        from .victory import check_victory_conditions, archive_legacy_cycle
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
                from .commands import _trigger_death
                ctx = self.session_manager._make_context(session)
                await _trigger_death(ctx, death_message)

        if self.shared.game_time.minute == 0:
            await self._check_milestone_day()
            ending = check_victory_conditions(
                self.shared.game_time.day,
                self.shared.ccp_influence,
                self.shared.gmd_influence,
            )
            if ending:
                await self._handle_server_reset(ending)

    async def _handle_server_reset(self, ending_type: str):
        from .victory import generate_liberation_ending, compile_legacy_narrative, archive_legacy_cycle
        from .save_manager import save_player, save_world_state
        from .locales import get as loc
        import json

        archive_legacy_cycle(self.shared.legacy_book, self.shared.server_cycle)
        legacy = compile_legacy_narrative(self.shared.legacy_book)

        for session in self.session_manager.sessions.values():
            ending_text = generate_liberation_ending(
                ending_type, session.player.name, self.shared.legacy_book,
                self.shared.ccp_influence, self.shared.gmd_influence,
            )

            end_screen = f"""
{ending_text}

{legacy}

{loc("victory.footer")}
"""
            try:
                await session.websocket.send(json.dumps({"type": "ending", "payload": end_screen}))
            except Exception:
                pass
            session.player.flags.append("player_died")
            save_player(session.player)

        save_world_state(self.shared)

        self.shared.server_cycle += 1

        await asyncio.sleep(60)

        reset_msg = "A new timeline begins. Shanghai, November 1937."
        for session in list(self.session_manager.sessions.values()):
            try:
                await session.websocket.send(json.dumps({"type": "server_reset", "payload": reset_msg}))
                await session.websocket.close()
            except Exception:
                pass

        self._reset_shared_world()

    def _reset_shared_world(self):
        from .game_world import SharedWorldState
        from .world import World
        from .time_system import EventScheduler, GameTime
        from .constants import EVENTS_PATH, TRUST_RULES_PATH
        from .trust import load_trust_rules

        cycle = self.shared.server_cycle
        self.shared.world = World()
        self.shared.game_time = GameTime()
        self.shared.scheduler = EventScheduler()
        self.shared.scheduler.load_from_yaml(EVENTS_PATH)
        self.shared.trust_rules = load_trust_rules(TRUST_RULES_PATH)
        self.shared.ccp_influence = 10
        self.shared.gmd_influence = 15
        self.shared.event_log = []
        self.shared.legacy_book = []
        self.shared.rumour_mill = {}
        self.shared.archived_journals = {}
        self.shared.mission_manager = None
        self.shared.milestone_manager = None
        self.shared.server_cycle = cycle
        self.shared.weather = "clear"
        self.shared.active_room_storylets = {}
        self.shared.dead_npcs = set()
        from .game_world import build_market_tracker
        self.shared.world_decisions.clear()
        self.shared.room_state_overrides.clear()
        self.shared.npc_dispositions.clear()
        self.shared.market_rooms = build_market_tracker(self.shared.world)
        self.session_manager.sessions.clear()

    async def _check_milestone_day(self):
        mm = self.shared.milestone_manager
        if not mm:
            return
        triggered = mm.check_day(self.shared.game_time.day)
        if not triggered:
            return
        from .milestones import apply_milestone_effects
        for m in triggered:
            for session in self.session_manager.sessions.values():
                if apply_milestone_effects(session.player, m, self.shared):
                    asyncio.create_task(session.send_display(f"\n{m.narrative}\n"))
            await self._broadcast_display(f"\n[MILESTONE] {m.narrative}\n")

    async def _broadcast_display(self, text: str):
        for session in self.session_manager.sessions.values():
            try:
                await session.send_display(text)
            except Exception:
                pass
