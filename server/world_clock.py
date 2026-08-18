import asyncio
import random
import time
from collections import deque, defaultdict
from typing import TYPE_CHECKING, Optional

from .constants import (
    MessageType,
    MORALE_DECAY_PER_HOUR,
    STAT_GAIN_STEALTH_TAIL,
    WANTED_LEVEL_MAX,
    WANTED_DECAY_INTERVAL_DAYS,
    SUSPICION_DECAY_PER_TICK,
    SUSPICION_THRESHOLD_INVESTIGATE,
    SUSPICION_INVESTIGATE_RELIEF,
    VENDOR_SHUTTER_TENSION,
    DEFECTION_DISILLUSIONMENT_THRESHOLD,
    DEFECTION_DAILY_CHANCE,
    DISILLUSIONMENT_PER_TICK,
    SEASONAL_FOOD_SHORTAGE,
    FOOD_RESTOCK_INTERVAL,
    SEASONAL_MORALE_MODIFIER,
    AMBIENT_EVENTS_PATH,
    CRIME_SCENE_DURATION_DAYS,
    CORPSE_DECAY_DAYS,
    SEASONAL_PATROL_DENSITY,
    WEATHER_MORALE_HOURLY,
    get_season,
)
from .content_validation import load_strict_yaml
from .player_data import grow_stat
from .law import (
    apply_crime_free_decay,
    wanted_consequences,
)
from .curfew import CurfewTrigger, curfew_night_key, game_clock_total_minutes, resolve_curfew_encounter
from .trust import exchange_gossip
from .victory import _season_from_day, resolve_shared_liberation
from .rewards import grant_catalog_item, validate_catalog_item
from .commands import (
    apply_action_trust,
    check_planted_evidence,
    disguise_bonus,
    log_event,
    maybe_trigger_storylet,
    move_npcs_if_hour_changed,
    post_display,
    process_gossip,
    process_survival_tick,
)
from .session import Session
from .game_world import SharedWorldState, is_named_npc_dead, retire_recorded_npcs
from .patrols import (
    PatrolState,
    is_transient_patrol_id,
    patrol_next_rooms,
    patrol_pause_seconds,
    patrol_reachable_rooms,
)
from .npc_interactions import npc_interaction_manager
from .social_interactions import (
    SOCIAL_INTERVAL_MINUTES,
    SocialDialogueComposer,
    SocialInteractionResolver,
    SocialSchedule,
    due_npc_ids,
)
from .social_consequences import publish_consequence_rumour
from .tutorial import tutorial_blocks_world_events

SOCIAL_CONSEQUENCE_PAIR_CATEGORY_COOLDOWN = 130
SOCIAL_CONSEQUENCE_ROOM_CAP = 3
SOCIAL_CONSEQUENCE_DISTRICT_CAP = 8


NPC_ACTION_SOUNDS = {
    "argue": (3, "npc_argument", "yell"),
    "extort_civilian": (3, "npc_extortion", "yell"),
    "intimidate_rival": (3, "npc_intimidation", "yell"),
}


def record_social_consequence(interaction, actor, target, shared, room, witnesses: list[str] | None = None) -> dict | None:
    consequence_class = getattr(interaction, "consequence_class", "ambient")
    if consequence_class not in {"persistent",  "actionable"}:
        return None

    actor_ids = sorted((actor.id, target.id))
    category = getattr(interaction, "consequence_category", "") or interaction.id
    room_id = getattr(room, "id", "")
    district_id = getattr(room, "district", "") or "default"
    consequence_id = f"{':'.join(actor_ids)}:{room_id}:{category}"
    records = shared.social_consequences
    cooldowns = shared.social_consequence_cooldowns
    existing = records.get(consequence_id)
    if existing and existing.get("state") == "active":
        return existing

    created_at = (shared.game_time.day - 1) * 1440 + shared.game_time.minute
    cooldown_id = f"{':'.join(actor_ids)}:{category}"
    cooldown = getattr(interaction, "consequence_cooldown", None)
    if cooldown is None:
        cooldown = SOCIAL_CONSEQUENCE_PAIR_CATEGORY_COOLDOWN
    last_created_at = cooldowns.get(cooldown_id)
    if last_created_at is not None and created_at - last_created_at < cooldown:
        return None

    room_cap = getattr(interaction, "consequence_room_cap", None)
    if room_cap is None:
        room_cap = SOCIAL_CONSEQUENCE_ROOM_CAP
    district_cap = getattr(interaction, "consequence_district_cap", None)
    if district_cap is None:
        district_cap = SOCIAL_CONSEQUENCE_DISTRICT_CAP
    active_records = [record for record in records.values() if record.get("state") == "active"]
    if sum(record.get("room_id") == room_id for record in active_records) >= room_cap:
        return None
    if sum(record.get("district_id") == district_id for record in active_records) >= district_cap:
        return None

    duration = int(getattr(interaction, "consequence_duration", 0) or 0)
    record = {
        "id": consequence_id,
        "source_interaction_id": interaction.id,
        "npc_ids": actor_ids,
        "room_id": room_id,
        "district_id": district_id,
        "consequence_class": consequence_class,
        "category": category,
        "created_at": created_at,
        "expires_at": created_at + duration if duration else None,
        "follow_up_key": getattr(interaction, "follow_up_key", None) if consequence_class == "actionable" else None,
        "rumour": getattr(interaction, "consequence_rumour", None),
        "room_manifestation": getattr(interaction, "consequence_room_manifestation", None),
        "ask_topic": getattr(interaction, "consequence_ask_topic", None),
        "ask_response": getattr(interaction, "consequence_ask_response", None),
        "follow_up_due_at": created_at + int(getattr(interaction, "follow_up_delay", 30) or 0)
        if consequence_class == "actionable" and getattr(interaction, "follow_up_key", None) else None,
        "follow_up_state": "pending" if consequence_class == "actionable" and getattr(interaction, "follow_up_key", None) else None,
        "follow_up_trust_ranges": getattr(interaction, "follow_up_trust_ranges", {}),
        "visibility": getattr(interaction, "consequence_visibility", "local"),
        "witnesses": sorted(witnesses or []),
        "state": "active",
    }
    records[consequence_id] = record
    cooldowns[cooldown_id] = created_at
    publish_consequence_rumour(shared, record, actor, target)
    return record


def cleanup_social_consequenes(shared) -> list[str]:
    now = (shared.game_time.day - 1) * 1440 + shared.game_time.minute
    resolved_ids = []
    world = shared.world

    for consequence_id in sorted(shared.social_consequences):
        record = shared.social_consequences[consequence_id]
        if record.get("state") != "active":
            continue

        involved_npcs = record.get("npc_ids", [])
        unavailable = any(
            npc_id not in world.npcs
            or is_named_npc_dead(shared, npc_id)
            or npc_id not in world.npc_locations
            for npc_id in involved_npcs
        )
        if unavailable:
            if record.get("follow_up_state") == "pending":
                record["resolved_at"] = now
                record["resolution_reason"] = "actor_unavailable"
                resolved_ids.append(consequence_id)
            continue

        if record.get("follow_up_state") == "pending" and any(
            world.npc_locations.get(npc_id) != record.get("room_id")
            for npc_id in involved_npcs
        ):
            record["follow_up_invalidated_at"] = now
            record["follow_up_invalidation_reason"] = "actor_departed_room"

        expires_at = record.get("expires_at")
        if expires_at is not None and now >= int(expires_at):
            if record.get("follow_up_state") == "pending":
                record["resolved_at"] = now
                record["resolution_reason"] = "expired"
                resolved_ids.append(consequence_id)

    return resolved_ids

if TYPE_CHECKING:
    from .session_manager import SessionManager


def tutorial_sound_investigator_allowed(npc_id: str, clone_ids: set, npc) -> bool:
    if npc_id not in clone_ids or not npc_id. endswith("tutorial_kempeitai_officer"):
        return False
    blackboard = getattr(npc, "_blackboard", None)
    return bool(blackboard and blackboard.get("last_heard_sound"))


class WorldClock:
    def __init__(self, shared: SharedWorldState, session_manager: "SessionManager", disguises, stealth, storylet_manager):
        self.shared = shared
        self.session_manager = session_manager
        self.disguises = disguises
        self.stealth = stealth
        self.storylet_manager = storylet_manager
        self._bt_registry = None
        self._ambient_events = None  
        self._pending_tasks: set = set() 
        self._patrol_entities: list[PatrolState] = []
        self._patrol_counter = 0
        self._patrol_warnings_pending_clear = True
        self._clear_transient_patrols()
        self._social_resolver = SocialInteractionResolver()
        self._social_dialogue = SocialDialogueComposer(self._load_voice_sheets())

    @staticmethod
    def _load_voice_sheets() -> dict:
        import yaml
        from pathlib import Path

        path = Path("server/data/custom/npc_voice_sheets.yaml")
        if not path.exists():
            return {}
        return {row["npc_id"]: row for row in (load_strict_yaml(path) or []) if row.get("npc_id")}

    def _track_task(self, coro):
        import logging
        logger = logging.getLogger(__name__)

        task = asyncio.create_task(coro)
        self._pending_tasks.add(task)
        task.add_done_callback(lambda t: self._pending_tasks.discard(t))
        task.add_done_callback(lambda t: t.exception() and logger.error(f"Task failed: {t.exception()}"))
        return task

    def _get_ambient_events(self):
        if self._ambient_events is None:
            from .ambient_events import load_ambient_events
            self._ambient_events = load_ambient_events(AMBIENT_EVENTS_PATH)
        return self._ambient_events

    async def tick(self):
        if not self.session_manager.sessions:
            await self._process_patrol_entities()
            return

        if any(s.manually_advancing for s in list(self.session_manager.sessions.values())):
            return

        self._advance_time_one_minute()
        self._release_custody_sessions()
        cleanup_social_consequences(self.shared)
        self._expire_crime_scenes()
        self._move_npcs_if_hour_changed()
        self._process_gossip()
        self._run_authored_meetings()
        self._process_npc_autonomy()
        await self._process_planted_evidence_all_sessions()
        await self._process_tailing_all_sessions()
        await self._process_patrol_entities()
        self._check_ambient_events_all_sessions()  
        if self.shared.game_time.minute % 15 == 0:
            await self._check_storylets()
        await self._check_storylet_timers_all_sessions()
        if self.shared.game_time.minute % 60 == 0 and self.shared.game_time.minute > 0:
            self._check_mission_expiry()
        if self.shared.game_time.minute % 60 == 0:
            self._update_weather()
        self._process_survival_all_sessions()
        if self.shared.game_time.minute % 360 == 0:
            self._respawn_dead_npcs()
        if self.shared.game_time.minute % FOOD_RESTOCK_INTERVAL == 0:
            self._restock_market_food()
        await self._check_death_and_victory()

    def _advance_time_one_minute(self):
        self.shared.game_time.minute += 1
        if self.shared.game_time.minute >= 1440:
            self.shared.game_time.minute = 0
            self.shared.game_time.day += 1
            self._apply_trust_decay_all_sessions()
            from .economy import economy_system
            economy_system.update_market_conditions(self.shared.game_time.day)
            from .rumors import reseed_active_rumors
            reseed_active_rumors(self.shared, self.shared.game_time.day)
        self.shared.scheduler.process(
            self.shared.game_time,
            lambda msg: asyncio.create_task(self._broadcast_display(msg)),
        )

    def _release_custody_sessions(self) -> None:
        from .locales import get as loc
        now = game_clock_total_minutes(self.shared.game_time)
        for session in list(self.session_manager.sessions.values()):
            player = session.player
            if getattr(player, "custody_until", -1) < 0:
                continue
            if now < player.custody_until:
                continue
            detention_room = getattr(player, "custody_detention_room", "") or ""
            if self._valid_custody_release_room(detention_room):
                player.current_room = detention_room
            player.custody_until = -1
            player.custody_detention_room = ""
            asyncio.create_task(session.send_display(loc("arrest.custody_release")))

    def _valid_custody_release_room(self, room_id: str) -> bool:
        if not room_id or room_id.startswith(("tut_", "p_")):
            return False
        room = self.shared.world.get_room(room_id)
        return room is not None and "tutorial" not in getattr(room, "tags", [])

    async def _process_patrol_entities(self) -> None:
        now = time.time()
        if self._patrol_warnings_pending_clear:
            for session in self.session_manager.sessions.values():
                await session.clear_patrol_warning()
            self._patrol_warnings_pending_clear = False
        active_zones = {
            self._room_zone(self.shared.world.get_room(session.player.current_room))
            for session in self.session_manager.sessions.values()
            if(
                session.running
                and self.shared.world.get_room(session.player.current_room)
                and not tutorial_blocks_world_events(session.player)
            )
        }
        active_zones.discard("")
        previous_patrol_ids = {patrol.npc_id for patrol in self._patrol_entities}
        self._sync_patrol_zones(active_zones, now)
        removed_patrol_ids = previous_patrol_ids - {
            patrol.npc_id for patrol in self._patrol_entities
        }

        for patrol in list(self._patrol_entities):
            if patrol.npc_id not in self.shared.world.npcs:
                self._despawn_patrol(patrol.npc_id)
                self._patrol_entities.remove(patrol)
                removed_patrol_ids.add(patrol.npc_id)

        if removed_patrol_ids:
            for session in self.session_manager.sessions.values():
                await session.clear_patrol_warning()

        for patrol in list(self._patrol_entities):
            if patrol.expires_at <= now:
                await self._advance_patrol(patrol, now)
            await self._broadcast_patrol_warning(patrol, now)

    def _room_zone(self, room) -> str:
        if not room:
            return ""
        zone_tags = {
            "bund", "old_city", "hongkou", "french", "nanjing_rd",
            "zhabei", "yangpu", "xujiahui",
        }
        return next((tag for tag in getattr(room, "tags", []) if tag in zone_tags), room.district)

    def _sync_patrol_zones(self, active_zones: set[str], now: float) -> None:
        for patrol in list(self._patrol_entities):
            if patrol.zone not in active_zones:
                self._despawn_patrol(patrol.npc_id)
                self._patrol_entities.remove(patrol)

        covered_zones = {patrol.zone for patrol in self._patrol_entities}
        for zone in active_zones - covered_zones:
            room_ids = [
                room_id for room_id, room in self.shared.world.rooms.items()
                if not room.indoors and self._room_zone(room) == zone and room.exits
            ]
            if not room_ids:
                continue
            self._patrol_counter += 1
            npc_id = f"transient_patrol_{self._patrol_counter}"
            from .npc import Npc
            self.shared.world.npcs[npc_id] = Npc(
                id=npc_id,
                name="Kempeitai patrol",
                description="A disciplined Kempeitai patrol moving through the occupied streets.",
                faction="kempeitai",
                role="patrol",
                personality="disciplined",
                awareness=50,
                perception=50,
            )
            room_id = random.choice(room_ids)
            self.shared.world.place_npc(npc_id, room_id)
            patrol = PatrolState(
                npc_id=npc_id,
                zone=zone,
                room_id=room_id,
            )
            patrol.expires_at = now + self._patrol_pause_seconds(patrol)
            self._patrol_entities.append(patrol)

    def _patrol_candidates(self, patrol: PatrolState) -> list[str]:
        candidates = patrol_next_rooms(self.shared.world.rooms, patrol.room_id, patrol.last_room_id)
        return [
            room_id for room_id in candidates
            if (room := self.shared.world.get_room(room_id))
            and not room.indoors
            and self._room_zone(room) == patrol.zone
        ]

    async def _advance_patrol(self, patrol: PatrolState, now: float) -> None:
        candidates = self._patrol_candidates(patrol)
        if not candidates:
            patrol.expires_at = now + self._patrol_pause_seconds(patrol)
            return
        next_room_id = random.choice(candidates)
        patrol.last_room_id, patrol.room_id = patrol.room_id, next_room_id
        self.shared.world.place_npc(patrol.npc_id, next_room_id)
        patrol.expires_at = now + self._patrol_pause_seconds(patrol)
        await self._resolve_patrol_entry(patrol)

    def _patrol_pause_seconds(self, patrol: PatrolState) -> int:
        active = any(
            session.running
            and wanted_consequences(session.player.wanted_level).patrol_multiplier > 1
            and self._room_zone(self.shared.world.get_room(session.player.current_room)) == patrol.zone
            and not tutorial_blocks_world_events(session.player)
            for session in self.session_manager.sessions.values()
        )
        seasonal_density = SEASONAL_PATROL_DENSITY.get(
            get_season(self.shared.game_time.day), 1.0
        )
        return patrol_pause_seconds(
            self.shared.game_time,
            seasonal_density=seasonal_density,
            wanted_multiplier=2 if active else 1,
        )

    async def _broadcast_patrol_warning(self, patrol: PatrolState, now: float) -> None:
        if curfew_night_key(self.shared.game_time) is None:
            for session in self.session_manager.sessions.values():
                if session.running:
                    await session.clear_patrol_warning()
            return

        eligible = lambda room: (
            not room.indoors and self._room_zone(room) == patrol.zone
        )
        reachable = patrol_reachable_rooms(
            self.shared.world.rooms,
            patrol.room_id,
            patrol.last_room_id,
            eligible=eligible,
        )
        seconds_remaining = max(0, int(patrol.expires_at - now))
        for session in self.session_manager.sessions.values():
            if not session.running or tutorial_blocks_world_events(session.player):
                continue
            distance = reachable.get(session.player.current_room)
            if distance not in {1, 2, 3}:
                await session.clear_patrol_warning()
                continue
            stage = 4 - distance
            if stage == 3:
                await session.send_patrol_warning(
                    patrol_id=patrol.npc_id,
                    stage=stage,
                    seconds_remaining=seconds_remaining,
                    expires_at=patrol.expires_at,
                )
            else:
                await session.send_patrol_warning(
                    patrol_id=patrol.npc_id,
                    stage=stage,
                )

    def _despawn_patrol(self, npc_id: str) -> None:
        room_id = self.shared.world.npc_locations.pop(npc_id, None)
        room = self.shared.world.get_room(room_id) if room_id else None
        if room and npc_id in room.npcs:
            room.npcs.remove(npc_id)
        self.shared.world.npcs.pop(npc_id, None)

    def _clear_transient_patrols(self) -> None:
        for npc_id in list(self.shared.world.npcs):
             if is_transient_patrol_id(npc_id):
                 self._despawn_patrol(npc_id)
        for room in self.shared.world.rooms.values():
            room.npcs = [npc_id for npc_id in room.npcs if not is_transient_patrol_id(npc_id)]
        for npc_id in list(self.shared.world.npc_locations):
            if is_transient_patrol_id(npc_id):
                self.shared.world.npc_locations.pop(npc_id, None)

    async def _resolve_patrol_entry(self, patrol: PatrolState) -> None:
        from .stealth import PierceStage
        room_id = patrol.room_id
        patrol_npc = self.shared.world.npcs.get(patrol.npc_id)
        if not patrol_npc:
            return
        room = self.shared.world.get_room(room_id)
        if not room or room.indoors:
            return
        active_curfew = curfew_night_key(self.shared.game_time) is not None
        for session in self.session_manager.get_players_in_room(room_id):
            player = session.player
            if not session.running or tutorial_blocks_world_events(player):
                continue
            if getattr(player, "custody_until", -1) >=0:
                continue
            await session.clear_patrol_warning()
            if not player.hidden:
                await session.send_display("Boots pass close by, then fade into the street.", msg_type="ambient")
                if active_curfew:
                    ctx = self.session_manager._make_context(session)
                    await resolve_curfew_encounter(ctx, CurfewTrigger.PATROL_CONTACT)
                continue
            stage = self.stealth.passive_detection_check(
                patrol_npc,
                player.stealth_skill,
                season=get_season(self.shared.game_time.day),
                room_indoors=False,
                game_hour=self.shared.game_time.hour,
                weather=getattr(self.shared, "weather", "clear"),
            )
            if stage == PierceStage.EXPOSED:
                player.hidden = False
                await session.send_display("Boots pass close by, then fade into the street.", msg_type="ambient")
                if active_curfew:
                    ctx = self.session_manager._make_context(session)
                    await resolve_curfew_encounter(ctx, CurfewTrigger.PATROL_CONTACT)
                continue
            await session.send_display("Boots pass close by, then fade into the street.", msg_type="ambient")

    def _expire_crime_scenes(self) -> None:
        current_day = self.shared.game_time.day

        for room in self.shared.world.rooms.values():
            if room.crime_scene_until_day > 0 and current_day >= room.crime_scene_until_day:
                if "crime_scene" in room.tags:
                    room.tags.remove("crime_scene")
                room.crime_scene_until_day = 0
            room.items = [
                item for item in room.items
                if not (item.is_corpse and item.decay_day > 0 and current_day >= item.decay_day)
            ]

    def _apply_trust_decay_all_sessions(self) -> None:
        from .trust import apply_trust_decay
        current_day = self.shared.game_time.day
        for session in list(self.session_manager.sessions.values()):
            if tutorial_blocks_world_events(session.player):
                continue
            decayed = apply_trust_decay(
                session.player.trust,
                session.player.last_trust_interaction,
                current_day,
            )
            if decayed:
                summary = ", ".join(
                    f"{faction.upper()} ({total_delta})" for faction, total_delta in decayed
                )
                asyncio.create_task(
                    session.send_display(
                        f"Your standing has faded from neglect: {summary}."
                    )
                )

            self._apply_wanted_decay(session, current_day)

    def _apply_wanted_decay(self, session: Session, current_day: int) -> None:
        from .trust import has_faction_perk
        from .locales import get as loc

        room = self.shared.world.get_room(session.player.current_room)
        safe_room = bool(room and room.safe_room)
        if apply_crime_free_decay(session.player, day=current_day, safe_room=safe_room):
            asyncio.create_task(session.send_display(loc("wanted.decay")))

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
            for session in self._visible_sessions(old_room_id):
                direction = self._get_direction(old_room_id, new_room_id)
                if direction:
                    asyncio.create_task(session.send_display(
                        f"{npc.name} walks {direction}.", msg_type=MessageType.NPC_AMBIENT,
                    ))

        if new_room:
            for session in self._visible_sessions(new_room_id):
                direction = self._get_direction(new_room_id, old_room_id)
                if direction:
                    asyncio.create_task(session.send_display(
                        f"{npc.name} arrives from {direction}.", msg_type=MessageType.NPC_AMBIENT,
                    ))

    def _get_direction(self, from_room: str, to_room: str) -> str:
        from_room_obj = self.shared.world.rooms.get(from_room)
        if not from_room_obj:
            return ""
        for direction, dest in from_room_obj.exits.items():
            if dest == to_room:
                return direction
        return ""

    def _process_gossip(self):
        from .rumors import process_gossip_room
        for room in self.shared.world.rooms.values():
            if room.id in self.shared.cloned_tutorial_rooms:
                continue
            process_gossip_room(self.shared, room)

    def _run_authored_meetings(self) -> None:
        from .npc import get_npc_archetype

        minute_of_day = int(self.shared.game_time.minute)
        absoulute_minute = game_clock_total_minutes(self.shared.game_time)
        for pool in self._social_dialogue.dialoue_pools.values():
            if not isinstance(pool, dict) or not pool.get("exchanges"):
                continue
            for meeting in pool.get("meeting_windows", []):
                if not isinstance(meeting, dict):
                    continue
                if not any(
                    isinstance(window, dict)
                    and self._meeting_window_is_due(window, minute_of_day)
                    for window in meeting.get("windows", [])
                ):
                    continue
                npc_ids = meeting.get("npc_ids", [])
                room_id = meeting.get("room_id", "")
                if not isinstance(npc_ids, list) or len(npc_ids) != 2:
                    continue
                if not isinstance(room_id, str) or not room_id:
                    continue
                actor = self.shared.world.npcs.get(npc_ids[0])
                target = self.shared.world.npcs.get(npc_ids[1])
                if not actor or not target:
                    continue
                if [get_npc_archetype(actor), get_npc_archetype(target)] != pool.get("archetypes"):
                    continue
                if self._authored_meeting_blocked(npc_ids, room_id, absolute_minute):
                    continue
                room = self.shared.world.get_room(room_id)
                if not room:
                    continue
                self._run_social_interaction(actor, room, "exchange_rumors", target)

    @staticmethod
    def _meeting_window_is_due(window: dict, minute_of_day: int) -> bool:
        try:
            start_minute = int(window["start_minute"])
            end_minute = int(window["end_minute"])
        except (KeyError, TypeError, ValueError):
            return False
        return 0 <= start_minute <= end_minute < 1440 and minute_of_day == start_minute

    def _authored_meeting_blocked(self, npc_ids: list[str], room_id: str, absolute_minute: int) -> bool:
        room = self.shared.world.get_room(room_id)
        if not room or room_id in self.shared.cloned_tutorial_rooms:
            return True
        if any(is_transient_patrol_id(npc_id) for npc_id in room.npcs):
            return True
        if any(self._meeting_player_blocks(session, absoulute_minute) for session in self.session_manager.get_players_in_room(room_id)):
            return True
        schedules = self.shared.npc_social_schedules
        for npc_id in npc_ids:
            npc = self.shared.world.npcs.get(npc_id)
            if not npc or is_named_npc_dead(self.shared, npc_id):
                return True
            if self.shared.world.npc_locations.get(npc_id) != room_id or npc_id not in room.npcs:
                return True
            if is_transient_patrol_id(npc_id) or getattr(npc, "wounded", False) or int(getattr(npc, "hp", 100)) <= 0:
                return True
            if getattr(npc, "suspicion", 0) > SUSPICION_THRESHOLD_INVESTIGATE:
                return True
            needs = getattr(npc, "needs", {}) or {}
            if any(int(needs.get(key, 0)) >= 80 for key in ("hunger", "fatigue", "fear")):
                return True
            blackboard = getattr(npc, "_blackboard", None) or {}
            if any(blackboard.get(key) for key in ("last_heard_sound", "heard_hostile_sound", "danger_nearby", "player_suspicion_nearby")):
                return True
            schedule = schedules.get(npc_id)
            if schedule and int(schedule.get("next_action_minute", absolute_minute + 1)) <= absolute_minute:
                return True
        if "crime_scene" in getattr(room, "tags", []):
            return True
        nearby = [self.shared.world.npcs.get(npc_id) for npc_id in room.npcs if npc_id not in npc_ids]
        nearby = [npc for npc in nearby if npc]
        return any(getattr(npc, "suspicion", 0) > SUSPICION_THRESHOLD_INVESTIGATE for npc in nearby)

    @staticmethod
    def _meeting_player_blocks(session, absoulute_minute: int) -> bool:
        if getattr(session, "manually_advancing", False):
            return True
        player = getattr(session, "player", None)
        if not player or tutorial_blocks_world_events(player):
            return True
        custody_until = getattr(player, "custody_until", -1)
        if custody_until >= absoulute_minute:
            return True
        active_storylets = getattr(player, "active_storylets", []) or []
        return any(getattr(storylet, "blocking", True) for storylet in active_storylets)

    