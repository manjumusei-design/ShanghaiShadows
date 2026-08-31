import asyncio
import random
import time
from collections import deque
from typing import TYPE_CHECKING

from .constants import (
    CURFEW_MINUTE,
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
from .time_system import GameTime
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
    resolve_patrol_warning,
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
from .tutorial import(
    TUTORIAL_BUND_CHEN_RESPONDER_KEY,
    get_cloned_room_id,
    tutorial_blocks_world_events,
)

SOCIAL_CONSEQUENCE_PAIR_CATEGORY_COOLDOWN = 180
SOCIAL_CONSEQUENCE_ROOM_CAP = 3
SOCIAL_CONSEQUENCE_DISTRICT_CAP = 8


NPC_ACTION_SOUNDS = {
    "argue": (3, "npc_argument", "yell"),
    "extort_civilian": (3, "npc_extortion", "yell"),
    "intimidate_rival": (3, "npc_intimidation", "yell"),
}


WEATHER_TRANSITION_TEXT = {
    "clear": "The weather clears over the city.",
    "rain": "Rain begins to fall across the city.",
    "fog": "Fog gathers over the streets.",
    "storm": "A storm rolls over the city, and thunder follows.",
    "snow": "Snow begins to settle over the city.",
}


def record_social_consequence(interaction, actor, target, shared, room, witnesses: list[str] | None = None) -> dict | None:
    consequence_class = getattr(interaction, "consequence_class", "ambient")
    if consequence_class not in {"persistent", "actionable"}:
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


def cleanup_social_consequences(shared) -> list[str]:
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
    if npc_id not in clone_ids or not npc_id.endswith("tutorial_kempeitai_officer"):
        return False
    blackboard = getattr(npc, "_blackboard", None)
    if not blackboard:
        return False
    if not (
        npc_id.endswith("tutorial_kempeitai_officer")
        or blackboard.get(TUTORIAL_BUND_CHEN_RESPONDER_KEY)
    ):
        return False
    return bool(
        blackboard.get("last_heard_sound") or blackboard.get("sound_investigation")
    )


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
        self._sanctioned_curfew_demos: dict = {}
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

        if not hasattr(self, "_pending_tasks"):
            self._pending_tasks = set()
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

    def _delivery_time(self) -> float:
        game_time = self.shared.game_time
        day = int(getattr(game_time, "day", 1))
        minute = int(getattr(game_time, "minute", 0))
        return float((day - 1) * 1440 + minute)

    def _schedule_notice(
        self,
        session,
        *,
        tier,
        locality,
        source: str,
        semantic_key: str,
        msg_type,
        text: str | None,
        state_token: str | None = None,
        source_room_id: str | None = None,
        source_district: str | None = None,
        sound: str | None = None,
        sound_volume: float = 0.6,
    ):
        from .delivery import DeliveryPolicy, Notice
        delivery = getattr(session, "delivery", None)
        if delivery is None:
            delivery = DeliveryPolicy()
            session.delivery = delivery
        return self._track_task(delivery.deliver(
            session,
            Notice(
                tier=tier,
                locality=locality,
                source=source,
                semantic_key=semantic_key,
                msg_type=msg_type,
                text=text,
                state_token=state_token,
                source_room_id=source_room_id,
                source_district=source_district,
                sound=sound,
                sound_volume=sound_volume,
            ),
            current_time=self._delivery_time(),
        ))

    async def _broadcast_display(self, text: str, msg_type=None):
        from .delivery import DeliveryPolicy, Locality, Notice, Tier

        raw_type = getattr(msg_type, "value", msg_type)
        tier = Tier.AMBIENT if raw_type == MessageType.AMBIENT or raw_type == "ambient" else Tier.ACTIONABLE
        semantic_key = f"legacy_broadcast.{raw_type or 'default'}"
        notice = Notice(
            tier=tier,
            locality=Locality.CITYWIDE,
            source="legacy_broadcast",
            semantic_key=semantic_key,
            msg_type=msg_type,
            text=text,
        )
        current_time = self._delivery_time()
        for session in list(self.session_manager.sessions.values()):
            if tutorial_blocks_world_events(session.player):
                continue
            delivery = getattr(session, "delivery", None)
            if delivery is None:
                delivery = DeliveryPolicy()
                session.delivery = delivery
            await delivery.deliver(session, notice, current_time=current_time)

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
        await self._flush_npc_movement_batches()
        await self._process_planted_evidence_all_sessions()
        await self._process_tailing_all_sessions()
        await self._process_patrol_entities()
        await self._check_ambient_events_all_sessions()
        if self.shared.game_time.minute % 15 == 0:
            await self._check_storylets()
        await self._check_storylet_timers_all_sessions()
        if self.shared.game_time.minute % 60 == 0 and self.shared.game_time.minute > 0:
            await self._check_mission_expiry()
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
        effects = self.shared.scheduler.process(
            self.shared.game_time,
            lambda msg: self._track_task(self._deliver_scheduled_event(msg)),
            lambda msg, event: self._track_task(
                self._deliver_scheduled_event(
                    msg,
                    str(event.payload.get("scope", "district")),
                    event_id=event.event_id,
                    source_district=event.payload.get("district"),
                )
            ),
        )
        if any(effect.get("curfew_start") for effect in effects):
            asyncio.create_task(self._broadcast_audio("gong", volume=0.6))

    async def _deliver_scheduled_event(
        self,
        text: str,
        scope: str = "district",
        *,
        event_id: str = "scheduled",
        source_district: str | None = None,
    ) -> None:
        from .delivery import Locality, Notice, Tier
        tier = Tier.ACTIONABLE if scope == "citywide" else Tier.AMBIENT
        locality = Locality.CITYWIDE if scope == "citywide" else Locality.DISTRICT
        notice = Notice(
            tier=tier,
            locality=locality,
            source="scheduler",
            semantic_key=f"scheduled_event.{event_id}",
            msg_type=MessageType.AMBIENT,
            text=text + "\n",
            source_district=source_district,
        )
        for session in list(self.session_manager.sessions.values()):
            if tutorial_blocks_world_events(session.player):
                continue
            await session.delivery.deliver(session, notice, current_time=self._delivery_time())

    async def _broadcast_audio(self, sound: str, volume: float = 0.7) -> None:
        for session in list(self.session_manager.sessions.values()):
            if tutorial_blocks_world_events(session.player):
                continue
            if not getattr(session, "audio_enabled", False):
                continue
            try:
                await session.send_audio(sound, volume=volume)
            except Exception:
                pass

    def _release_custody_sessions(self) -> None:
        from .delivery import Locality, Tier
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
                previous_room = player.current_room
                player.current_room = detention_room
                room_change = getattr(self.session_manager, "_on_room_changed", None)
                if room_change is not None:
                    room_change(session, previous_room, detention_room)
            player.custody_until = -1
            player.custody_detention_room = ""
            self._schedule_notice(
                session, tier=Tier.ACTIONABLE, locality=Locality.ROOM, source="custody",
                semantic_key=f"custody.release.{session.username}", msg_type=MessageType.EVENT,
                text=loc("arrest.custody_release"), source_room_id=player.current_room,
            )

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
            if (
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

        for session in self.session_manager.sessions.values():
            if not session.running or tutorial_blocks_world_events(session.player):
                continue
            payload = resolve_patrol_warning(
                self.shared.world.rooms,
                patrol_room_id=patrol.room_id,
                patrol_last_room_id=patrol.last_room_id,
                zone=patrol.zone,
                zone_of=self._room_zone,
                player_room_id=session.player.current_room,
                game_time=self.shared.game_time,
                now=now,
                expires_at=patrol.expires_at,
            )
            if payload is None:
                await session.clear_patrol_warning()
                continue
            if payload["stage"] == 3:
                await session.send_patrol_warning(
                    patrol_id=patrol.npc_id,
                    stage=payload["stage"],
                    seconds_remaining=payload["seconds_remaining"],
                    expires_at=payload["expires_at"],
                )
            else:
                await session.send_patrol_warning(
                    patrol_id=patrol.npc_id,
                    stage=payload["stage"],
                )

    def _despawn_patrol(self, npc_id: str) -> None:
        room_id = self.shared.world.npc_locations.pop(npc_id, None)
        room = self.shared.world.get_room(room_id) if room_id else None
        if room and npc_id in room.npcs:
            room.npcs.remove(npc_id)
        self.shared.world.npcs.pop(npc_id, None)

    SANCTIONED_CURFEW_DEMO_STEP_SECONDS = 2.0

    def start_sanctioned_curfew_demo(self, instance_id, session, *, step_seconds=None):
        self.cancel_sanctioned_curfew_demo(instance_id)
        step = (
            self.SANCTIONED_CURFEW_DEMO_STEP_SECONDS
            if step_seconds is None
            else step_seconds
        )
        task = asyncio.create_task(self._run_sanctioned_curfew_demo(instance_id, session, step))
        self._sanctioned_curfew_demos[instance_id] = task
        return task

    def cancel_sanctioned_curfew_demo(self, instance_id):
        task = self._sanctioned_curfew_demos.pop(instance_id, None)
        if task is not None and not task.done():
            task.cancel()
        return task

    async def _run_sanctioned_curfew_demo(self, instance_id, session, step_seconds):
        from collections import deque

        from .npc import Npc

        npc_id = f"transient_patrol_demo_{instance_id}"
        try:
            shared = self.shared
            clone_map = shared.tutorial_room_clones.get(instance_id) or {}
            rooms = shared.world.rooms
            player_room_id = session.player.current_room
            outdoor_ids = [
                room_id for room_id in clone_map.values()
                if room_id in rooms and not rooms[room_id].indoors and rooms[room_id].exits
            ]
            if not outdoor_ids or player_room_id not in rooms:
                return

            zone = self._room_zone(rooms[player_room_id])
            eligible = lambda room: not room.indoors and self._room_zone(room) == zone

            distances = {}
            parents = {}
            queue = deque([(player_room_id, None, 0)])
            while queue:
                room_id, parent, depth = queue.popleft()
                if room_id in distances:
                    continue
                distances[room_id] = depth
                parents[room_id] = parent
                room = rooms.get(room_id)
                if room is None or depth >= 3:
                    continue
                for next_room_id in dict.fromkeys(room.exits.values()):
                    neighbor = rooms.get(next_room_id)
                    if neighbor is None or not eligible(neighbor):
                        continue
                    queue.append((next_room_id, room_id, depth + 1))

            ladder = sorted(
                {depth for room_id, depth in distances.items() if depth >= 1},
                reverse=True,
            )
            if not ladder:
                return

            scoped_time = GameTime(day=shared.game_time.day, minute=CURFEW_MINUTE + 30)
            spawn_depth = min(ladder[0], 3)
            current = next((rid for rid, d in distances.items() if d == spawn_depth), None)
            path = []
            while current is not None:
                path.append(current)
                current = parents[current]
            path.reverse()

            shared.world.npcs[npc_id] = Npc(
                id=npc_id,
                name="Kempeitai patrol",
                description="A disciplined Kempeitai patrol moving through the occupied streets.",
                faction="kempeitai",
                role="patrol",
                personality="disciplined",
                awareness=50,
                perception=50,
            )
            patrol = PatrolState(npc_id=npc_id, zone=zone, room_id="")
            now = time.time()

            for index, target_room in enumerate(path):
                steps_left = len(path) - index
                expires_at = now + step_seconds * (steps_left + 1)
                previous_room_id = patrol.room_id
                shared.world.place_npc(npc_id, target_room)
                patrol.room_id = target_room
                payload = resolve_patrol_warning(
                    rooms,
                    patrol_room_id=target_room,
                    patrol_last_room_id=previous_room_id,
                    zone=zone,
                    zone_of=self._room_zone,
                    player_room_id=session.player.current_room,
                    game_time=scoped_time,
                    now=now,
                    expires_at=expires_at,
                )
                if payload is None:
                    await session.clear_patrol_warning()
                elif payload["stage"] == 3:
                    await session.send_patrol_warning(
                        patrol_id=npc_id,
                        stage=3,
                        seconds_remaining=payload["seconds_remaining"],
                        expires_at=payload["expires_at"],
                    )
                else:
                    await session.send_patrol_warning(
                        patrol_id=npc_id,
                        stage=payload["stage"],
                    )
                await asyncio.sleep(step_seconds)

            await session.clear_patrol_warning()
        except asyncio.CancelledError:
            await session.clear_patrol_warning()
            raise
        finally:
            self._despawn_patrol(npc_id)
            self._sanctioned_curfew_demos.pop(instance_id, None)

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
        from .delivery import Locality, Tier
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
            if getattr(player, "custody_until", -1) >= 0:
                continue
            await session.clear_patrol_warning()
            if not player.hidden:
                self._schedule_notice(
                    session, tier=Tier.AMBIENT, locality=Locality.ROOM, source="patrol",
                    semantic_key=f"patrol.pass.{room_id}", msg_type=MessageType.AMBIENT,
                    text="Boots pass close by, then fade into the street.", source_room_id=room_id,
                )
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
                self._schedule_notice(
                    session, tier=Tier.ACTIONABLE, locality=Locality.ROOM, source="patrol",
                    semantic_key=f"patrol.exposed.{room_id}", msg_type=MessageType.EVENT,
                    text="Boots pass close by, then fade into the street.", source_room_id=room_id,
                )
                if active_curfew:
                    ctx = self.session_manager._make_context(session)
                    await resolve_curfew_encounter(ctx, CurfewTrigger.PATROL_CONTACT)
                continue
            self._schedule_notice(
                session, tier=Tier.AMBIENT, locality=Locality.ROOM, source="patrol",
                semantic_key=f"patrol.pass.{room_id}", msg_type=MessageType.AMBIENT,
                text="Boots pass close by, then fade into the street.", source_room_id=room_id,
            )

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
        from .delivery import Locality, Tier
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
                self._schedule_notice(
                    session, tier=Tier.ACTIONABLE, locality=Locality.ROOM, source="trust_decay",
                    semantic_key=f"trust_decay.{current_day}", msg_type=MessageType.PLAYER_STATUS,
                    text=f"Your standing has faded from neglect: {summary}.",
                    source_room_id=session.player.current_room,
                )

            self._apply_wanted_decay(session, current_day)

    def _apply_wanted_decay(self, session: Session, current_day: int) -> None:
        from .delivery import Locality, Tier
        from .trust import has_faction_perk
        from .locales import get as loc

        room = self.shared.world.get_room(session.player.current_room)
        safe_room = bool(room and room.safe_room)
        if apply_crime_free_decay(session.player, day=current_day, safe_room=safe_room):
            self._schedule_notice(
                session, tier=Tier.ACTIONABLE, locality=Locality.ROOM, source="wanted_decay",
                semantic_key=f"wanted_decay.{current_day}", msg_type=MessageType.PLAYER_STATUS,
                text=loc("wanted.decay"), source_room_id=session.player.current_room,
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

        if old_room and self._visible_sessions(old_room_id):
            direction = self._get_direction(old_room_id, new_room_id)
            if direction:
                self._queue_movement_line(old_room_id, f"{npc.name} walks {direction}.")

        if new_room and self._visible_sessions(new_room_id):
            direction = self._get_direction(new_room_id, old_room_id)
            if direction:
                self._queue_movement_line(new_room_id, f"{npc.name} arrives from {direction}.")

    def _queue_movement_line(self, room_id: str, clause: str) -> None:
        if not hasattr(self, "_movement_batches"):
            self._movement_batches = {}
        self._movement_batches.setdefault(room_id, []).append(clause)

    async def _flush_npc_movement_batches(self) -> None:
        from .delivery import Locality, Notice, Tier
        batches = getattr(self, "_movement_batches", None) or {}
        self._movement_batches = {}
        current_time = self._delivery_time()
        for room_id, clauses in batches.items():
            if not clauses:
                continue
            text = " ".join(clauses[:3])
            if len(clauses) > 3:
                text += " Several others move through as well."
            notice = Notice(
                tier=Tier.AMBIENT,
                locality=Locality.ROOM,
                source="npc_movement",
                semantic_key=f"npc_movement.{room_id}",
                msg_type=MessageType.NPC_AMBIENT,
                text=text + "\n",
                source_room_id=room_id,
            )
            for session in self._visible_sessions(room_id):
                await session.delivery.deliver(session, notice, current_time=current_time)

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

    def trigger_sanctioned_tutorial_meetings(self) -> None:
        for pool_key, pool in self._social_dialogue.dialogue_pools.items():
            if not isinstance(pool, dict) or not pool.get("exchanges"):
                continue
            for meeting in pool.get("meeting_windows", []):
                if isinstance(meeting, dict) and meeting.get("tutorial_demonstration"):
                    self._run_sanctioned_tutorial_meeting(str(pool_key), pool, meeting)

    def _run_authored_meetings(self) -> None:
        from .npc import get_npc_archetype

        minute_of_day = int(self.shared.game_time.minute)
        absolute_minute = game_clock_total_minutes(self.shared.game_time)
        for pool_key, pool in self._social_dialogue.dialogue_pools.items():
            if not isinstance(pool, dict) or not pool.get("exchanges"):
                continue
            for meeting in pool.get("meeting_windows", []):
                if not isinstance(meeting, dict):
                    continue
                if meeting.get("tutorial_demonstration"):
                    self._run_sanctioned_tutorial_meeting(str(pool_key), pool, meeting)
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

    _SANCTIONED_MEETING_BLOCKERS = ("last_heard_sound", "heard_hostile_sound", "danger_nearby", "player_suspicion_nearby")

    def _run_sanctioned_tutorial_meeting(self, pool_key: str, pool: dict, meeting: dict) -> None:
        from .npc import get_npc_archetype

        npc_ids = meeting.get("npc_ids", [])
        room_id = meeting.get("room_id", "")
        if not isinstance(npc_ids, list) or len(npc_ids) != 2 or not isinstance(room_id, str) or not room_id:
            return
        identity = f"{pool_key}:{room_id}"
        for instance_id in list(self.shared.tutorial_room_clones.keys()):
            owner_session = None
            for session in self.session_manager.sessions.values():
                player = getattr(session, "player", None)
                if (
                    getattr(player, "in_tutorial", False)
                    and getattr(player, "tutorial_instance_id", "") == instance_id
                ):
                    owner_session = session
                    break
            if owner_session is None or getattr(owner_session, "manually_advancing", False):
                continue
            player = owner_session.player
            records = getattr(player, "tutorial_social_exchanges", None)
            if records is None:
                records = {}
                player.tutorial_social_exchanges = records
            record = records.get(identity)
            if record and record.get("fired"):
                continue
            clone_room_id = get_cloned_room_id(instance_id, room_id, self.shared)
            actor = self.shared.world.npcs.get(f"tut_{instance_id}_{npc_ids[0]}")
            target = self.shared.world.npcs.get(f"tut_{instance_id}_{npc_ids[1]}")
            room = self.shared.world.rooms.get(clone_room_id)
            if not actor or not target or not room:
                continue
            if player.current_room != clone_room_id:
                continue
            if [get_npc_archetype(actor), get_npc_archetype(target)] != pool.get("archetypes"):
                continue
            blocked = False
            for npc in (actor, target):
                blackboard = getattr(npc, "_blackboard", None) or {}
                if (
                    getattr(npc, "wounded", False)
                    or int(getattr(npc, "hp", 100)) <= 0
                    or getattr(npc, "suspicion", 0) > SUSPICION_THRESHOLD_INVESTIGATE
                    or any(blackboard.get(key) for key in self._SANCTIONED_MEETING_BLOCKERS)
                ):
                    blocked = True
                    break
            if blocked or "crime_scene" in getattr(room, "tags", []):
                continue
            delivered: dict = {}

            def _on_produced(entry_data: dict, delivered: dict = delivered) -> None:
                delivered.update(entry_data)

            if not self._run_social_interaction(actor, room, "exchange_rumors", target, on_delivered=_on_produced):
                continue
            records[identity] = {
                "fired": True,
                "action": "exchange_rumors",
                "speaker": delivered.get("speaker", ""),
                "listener": delivered.get("listener", ""),
                "turns": delivered.get("turns", []),
            }

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
        if any(self._meeting_player_blocks(session, absolute_minute) for session in self.session_manager.get_players_in_room(room_id)):
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
    def _meeting_player_blocks(session, absolute_minute: int) -> bool:
        if getattr(session, "manually_advancing", False):
            return True
        player = getattr(session, "player", None)
        if not player or tutorial_blocks_world_events(player):
            return True
        custody_until = getattr(player, "custody_until", -1)
        if custody_until >= absolute_minute:
            return True
        active_storylets = getattr(player, "active_storylets", []) or []
        return any(getattr(storylet, "blocking", True) for storylet in active_storylets)

    async def _process_planted_evidence_all_sessions(self):
        for session in list(self.session_manager.sessions.values()):
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
                        from .rumors import publish_event_rumor
                        publish_event_rumor(
                            self.shared,
                            event_type="planted_evidence",
                            text=event_text,
                            location=room.id,
                            district=getattr(room, "district", ""),
                            witnesses=[],
                            faction_context=npc.faction,
                            created_day=self.shared.game_time.day,
                        )
                        from .delivery import Locality, Tier
                        self._schedule_notice(
                            session, tier=Tier.ACTIONABLE, locality=Locality.ROOM,
                            source="planted_evidence", semantic_key=f"planted_evidence.{room.id}",
                            msg_type=MessageType.WARNING, text=event_text, source_room_id=room.id,
                        )
                        if getattr(session, "audio_enabled", False):
                            asyncio.create_task(session.send_audio("alert", volume=0.6))
                        triggered = True
                        break
            if not triggered:
                remaining.append(planted)
        session.player.planted_evidence = remaining

    async def _process_tailing_all_sessions(self):
        for session in list(self.session_manager.sessions.values()):
            if session.player.tailing_state:
                await self._process_tailing_for_session(session)

    async def _process_tailing_for_session(self, session: Session):
        current_total = (self.shared.game_time.day - 1) * 1440 + self.shared.game_time.minute
        from .equipment import advance_tail_clock, resolve_tail_step
        tail = advance_tail_clock(session.player, current_total)
        if not tail:
            return
        target = self.shared.world.npcs.get(tail.target_npc_id)
        from .constants import get_season
        season = get_season(self.shared.game_time.day)
        result = resolve_tail_step(
            session.player,
            target,
            tail,
            self.stealth,
            self.disguises,
            wanted_bonus=wanted_consequences(session.player.wanted_level).disguise_perception_bonus,
            current_room=self.shared.world.get_room(session.player.current_room),
            target_room=self.shared.world.npc_locations.get(target.id) if target else "",
            season=season,
        )
        await self._present_tail_follow_result(session, target, result)

    async def _present_tail_follow_result(self, session: Session, target, result):
        from .locales import get as loc
        from .delivery import Locality, Notice, Tier

        async def deliver_tail_notice(text: str, semantic_key: str, msg_type) -> None:
            await session.delivery.deliver(
                session,
                Notice(
                    tier=Tier.ACTIONABLE,
                    locality=Locality.ROOM,
                    source="tailing",
                    semantic_key=semantic_key,
                    msg_type=msg_type,
                    text=text,
                    source_room_id=session.player.current_room,
                ),
                current_time=self._delivery_time(),
            )

        if result.outcome == "vanished":
            await deliver_tail_notice(
                loc("cmd_tail.target_vanished"),
                f"tailing.{target.id}.vanished",
                MessageType.EVENT,
            )
        elif result.outcome == "challenge":
            await deliver_tail_notice(
                f"{target.name} challenges you and the tail ends.",
                f"tailing.{target.id}.challenge",
                MessageType.WARNING,
            )
        elif result.outcome == "exposed":
            await deliver_tail_notice(
                f"{target.name} sees through your disguise. The disguise is confiscated.",
                f"tailing.{target.id}.exposed",
                MessageType.WARNING,
            )
        elif result.outcome == "spotted":
            await deliver_tail_notice(
                f"{target.name} glances over a shoulder, slows, and knows exactly what you are doing.",
                f"tailing.{target.id}.spotted",
                MessageType.WARNING,
            )
        elif result.outcome == "lost":
            await deliver_tail_notice(
                f"You lose {target.name} in the streets.",
                f"tailing.{target.id}.lost",
                MessageType.EVENT,
            )
        elif result.outcome == "moved":
            await deliver_tail_notice(
                f"You shadow {target.name} and keep them in sight.",
                f"tailing.{target.id}.moved",
                MessageType.PLAYER_ACTION,
            )
            if result.gained_stealth:
                await deliver_tail_notice(
                    "You learn from their movements. (+1 stealth)",
                    f"tailing.{target.id}.stealth",
                    MessageType.PLAYER_STATUS,
                )
            await self._present_tail_room_entry(session)
        if result.stage.name == "SUSPICION" and result.outcome in ("continued", "moved"):
            await deliver_tail_notice(
                f"{target.name} studies you but continues on.",
                f"tailing.{target.id}.suspicion",
                MessageType.WARNING,
            )

    async def _present_tail_room_entry(self, session: Session):
        from .commands import Command, cmd_look
        ctx = self.session_manager._make_context(session)
        await cmd_look(ctx, Command(verb="look", raw="look"))

    async def _check_storylets(self):
        for session in list(self.session_manager.sessions.values()):
            if tutorial_blocks_world_events(session.player):
                continue
            if not session.player.active_storylets:
                from .commands import CommandContext, _display_storylet
                active = self.storylet_manager.maybe_trigger_social_follow_up(session.player, self.shared)
                if not active:
                    active = self.storylet_manager.maybe_trigger_for_player(session.player, self.shared)
                if active:
                    ctx = self.session_manager._make_context(session)
                    asyncio.create_task(_display_storylet(ctx, active))


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
            change_trust(
                player.trust,
                faction,
                delta,
                last_trust_interaction=player.last_trust_interaction,
                current_day=self.shared.game_time.day,
            )

    def _apply_flag_effects(self, player, flag: str) -> None:
        player.flags.append(flag)

    def _apply_item_effects(self, player, item_id: str | list[str]) -> None:
        item_ids = item_id if isinstance(item_id, list) else [item_id]
        for catalog_item_id in item_ids:
            grant_catalog_item(self.shared.world, player.inventory, str(catalog_item_id))

    def _apply_health_effects(self, player, health_change: int) -> None:
        player.health = max(0, min(100, player.health + health_change))

    def _apply_morale_effects(self, player, morale_change: int) -> None:
        if morale_change < 0:
            season = _season_from_day(self.shared.game_time.day)
            seasonal_mod = SEASONAL_MORALE_MODIFIER.get(season, 0)
            morale_change = morale_change + int(seasonal_mod)
            morale_change = min(morale_change, 0)

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
            if is_transient_patrol_id(npc_id):
                continue
            if is_named_npc_dead(self.shared, npc_id):
                continue
            if npc.faction in ("ccp", "gmd"):
                own_inf, rival_inf = (ccp_inf, gmd_inf) if npc.faction == "ccp" else (gmd_inf, ccp_inf)
                disp = self.shared.npc_dispositions.setdefault(npc_id, {"disillusionment": 0})
                if own_inf < rival_inf:
                    disp["disillusionment"] = min(100, disp["disillusionment"] + DISILLUSIONMENT_PER_TICK)
                elif own_inf > rival_inf + 10:
                    disp["disillusionment"] = max(0, disp["disillusionment"] - 1)
            elif npc.faction == "green_gang":
                world_tension = (ccp_inf + gmd_inf) / 2
                disp = self.shared.npc_dispositions.setdefault(npc_id, {"disillusionment": 0})
                if world_tension > 60:
                    disp["disillusionment"] = min(100, disp["disillusionment"] + DISILLUSIONMENT_PER_TICK)
                elif world_tension < 30:
                    disp["disillusionment"] = max(0, disp["disillusionment"] - 1)

    EFFECT_HANDLERS = {
        "trust": lambda s, p, v: s._apply_trust_effects(p, v),
        "flag": lambda s, p, v: s._apply_flag_effects(p, v),
        "item": lambda s, p, v: s._apply_item_effects(p, v),
        "add_item": lambda s, p, v: s._apply_item_effects(p, v),
        "give_item": lambda s, p, v: s._apply_item_effects(p, v),
        "health": lambda s, p, v: s._apply_health_effects(p, v),
        "morale": lambda s, p, v: s._apply_morale_effects(p, v),
    }

    async def _resolve_room_storylet(self, room_id: str, option_index: int, option):
        if room_id not in self.shared.active_room_storylets:
            return

        storylet_data = self.shared.active_room_storylets[room_id]
        if storylet_data.get("resolved", False):
            return
        effects = option.get("effects", {})
        for effect_type in ("item", "add_item", "give_item"):
            item_ids = effects.get(effect_type)
            if item_ids is None:
                continue
            if not isinstance(item_ids, list):
                item_ids = [item_ids]
            for item_id in item_ids:
                validate_catalog_item(self.shared.world, str(item_id))
        storylet_data["resolved"] = True

        room_storylet_id = storylet_data.get("storylet_id", "")
        for session in self.session_manager.get_players_in_room(room_id):
            notified = set()
            for active in session.player.active_storylets[:]:
                if active.room_id == room_id:
                    session.player.active_storylets.remove(active)
                    notified.add(active.storylet_id)
            for card_id in notified:
                asyncio.create_task(session.send_storylet_resolved(card_id))
            if room_storylet_id and room_storylet_id not in notified:
                asyncio.create_task(session.send_storylet_resolved(room_storylet_id))

            for effect_type, effect_value in effects.items():
                handler = self.EFFECT_HANDLERS.get(effect_type)
                if handler:
                    handler(self, session.player, effect_value)

            if option_index == 0:
                asyncio.create_task(session.send_display("The moment passes.", msg_type=MessageType.PLAYER_ACTION))
            else:
                asyncio.create_task(session.send_display(f"You chose option {option_index + 1}. The moment passes.", msg_type=MessageType.PLAYER_ACTION))

    async def _check_mission_expiry(self):
        from .delivery import Locality, Notice, Tier
        from .locales import get as loc
        from .missions import get_mission_title
        mm = self.shared.mission_manager
        if not mm:
            return
        for session in list(self.session_manager.sessions.values()):
            if tutorial_blocks_world_events(session.player):
                continue
            expired = mm.check_expiry(session.player, self.shared.game_time.day)
            for mid in expired:
                await session.delivery.deliver(session, Notice(
                    tier=Tier.ACTIONABLE,
                    locality=Locality.CITYWIDE,
                    source="missions",
                    semantic_key=f"mission.{mid}.expiry",
                    msg_type=MessageType.WARNING,
                    text=loc("mission.expired").format(title=get_mission_title(mm, mid)),
                    state_token="fired",
                ))
            failed = mm.check_staleness(session.player, self.shared)
            for mid in failed:
                await session.delivery.deliver(session, Notice(
                    tier=Tier.ACTIONABLE,
                    locality=Locality.CITYWIDE,
                    source="missions",
                    semantic_key=f"mission.{mid}.stale",
                    msg_type=MessageType.WARNING,
                    text=(
                        f"Mission {get_mission_title(mm, mid)} has failed because its "
                        "required target is no longer available."
                    ),
                    state_token="fired",
                ))

    def _process_survival_all_sessions(self):
        from .survival import apply_survival_tick, init_hunger_notify_state
        from .delivery import Locality, Tier
        season = _season_from_day(self.shared.game_time.day)
        minute = self.shared.game_time.minute
        for session in list(self.session_manager.sessions.values()):
            if tutorial_blocks_world_events(session.player):
                continue
            if getattr(session.player, "custody_until", -1) >= 0:
                continue
            room = self.shared.world.get_room(session.player.current_room)
            weather = getattr(self.shared, "weather", "clear")
            init_hunger_notify_state(session.player, session._hunger_notify_state)
            apply_survival_tick(
                session.player,
                minute,
                self.shared.game_time.day,
                send_display=lambda msg, msg_type=None, s=session: self._schedule_notice(
                    s,
                    tier=Tier.ACTIONABLE,
                    locality=Locality.ROOM,
                    source="survival",
                    semantic_key="hunger.threshold",
                    msg_type=msg_type,
                    text=msg,
                    source_room_id=s.player.current_room,
                ),
                notify_state=session._hunger_notify_state,
            )

            if minute % 60 == 0:
                self._apply_morale_effects(session.player, -MORALE_DECAY_PER_HOUR)
                if room and not room.indoors:
                    self._apply_morale_effects(session.player, WEATHER_MORALE_HOURLY.get(weather, 0))

            if season == "winter" and minute % 60 == 0:
                if room and not room.indoors:
                    has_warm = any(i.id in ("winter_coat", "heavy_jacket") for i in session.player.inventory)
                    if not has_warm:
                        session.player.health = max(0, session.player.health - 1)
                        if session.player.health % 10 == 0:
                            from .delivery import Locality, Tier
                            self._schedule_notice(
                                session, tier=Tier.ACTIONABLE, locality=Locality.ROOM,
                                source="winter", semantic_key=f"winter.cold.{session.username}",
                                msg_type=MessageType.PLAYER_STATUS,
                                text="The winter cold seeps into your bones.\n",
                                source_room_id=session.player.current_room,
                            )

    async def _check_ambient_events_all_sessions(self) -> None:
        from .ambient_events import check_ambient_trigger

        events = self._get_ambient_events()
        if not events:
            return

        current_tick = game_clock_total_minutes(self.shared.game_time)
        current_time = float(current_tick)
        current_minute = self.shared.game_time.minute

        for session in list(self.session_manager.sessions.values()):
            if tutorial_blocks_world_events(session.player):
                continue

            room = self.shared.world.get_room(session.player.current_room)
            if not room:
                continue

            district = room.district if hasattr(room, 'district') else ""
            room_tags = room.tags if hasattr(room, 'tags') else []
            player_perception = getattr(session.player, 'perception', 50)
            player_hidden = getattr(session.player, 'hidden', False)

            triggered = check_ambient_trigger(
                events,
                room.id,
                room_tags,
                district,
                current_tick,
                player_perception,
                current_minute,
                player_hidden,
            )

            if triggered:
                text = triggered.get_text_for_perception(player_perception)
                if text:
                    active = session.player.active_storylets
                    blocking = bool(active and getattr(active[0], "blocking", True))
                    if not triggered.is_danger and (
                        session.open_popup is not None or blocking
                    ):
                        continue
                    from .delivery import Locality, Notice, Tier
                    if triggered.is_danger:
                        notice = Notice(
                            tier=Tier.ACTIONABLE,
                            locality=Locality.ROOM,
                            source="ambient_events",
                            semantic_key=f"danger_ambient.{getattr(triggered, 'id', 'unknown')}",
                            msg_type=MessageType.AMBIENT,
                            text=text + "\n",
                            state_token=str(current_tick // 30),
                            source_room_id=room.id,
                        )
                    else:
                        notice = Notice(
                            tier=Tier.AMBIENT,
                            locality=Locality.ROOM,
                            source="ambient_events",
                            semantic_key=f"ambient_event.{getattr(triggered, 'id', 'unknown')}",
                            msg_type=MessageType.AMBIENT,
                            text=text + "\n",
                            source_room_id=room.id,
                        )
                    await session.delivery.deliver(session, notice, current_time=current_time)

    def _process_npc_autonomy(self):
        if self.shared.game_time.minute % 30 == 0:
            self._accumulate_dispositions()
        current_minute = self.shared.game_time.day * 1440 + self.shared.game_time.minute
        schedules = self.shared.npc_social_schedules
        for npc_id in self.shared.world.npcs:
            schedules.setdefault(npc_id, SocialSchedule.initial_for(npc_id, current_minute).to_dict())
        rooms_with_players = self._rooms_with_players()
        bt_registry = self._get_bt_registry()
        due_ids = due_npc_ids(schedules, current_minute)
        clone_ids = self._tutorial_clone_npc_ids()
        for npc_id in clone_ids:
            npc = self.shared.world.npcs.get(npc_id)
            if not npc or not tutorial_sound_investigator_allowed(npc_id, clone_ids, npc):
                continue
            if npc_id not in due_ids:
                schedules.setdefault(npc_id, {"next_action_minute": current_minute})
                due_ids.insert(0, npc_id)
        for npc_id in due_ids:
            npc = self.shared.world.npcs.get(npc_id)
            if not npc:
                continue
            sound_investigator = tutorial_sound_investigator_allowed(npc_id, clone_ids, npc)
            if npc_id in clone_ids and not sound_investigator:
                continue
            interval_seed = int.from_bytes(npc_id.encode("utf-8"), "little", signed=False) % (SOCIAL_INTERVAL_MINUTES[1] - SOCIAL_INTERVAL_MINUTES[0] + 1)
            schedules[npc_id]["next_action_minute"] = current_minute + SOCIAL_INTERVAL_MINUTES[0] + interval_seed
            if is_transient_patrol_id(npc_id):
                continue
            if is_named_npc_dead(self.shared, npc_id):
                continue
            current_room_id = self.shared.world.npc_locations.get(npc_id)
            if not current_room_id:
                continue
            current_room = self.shared.world.rooms.get(current_room_id)
            if not current_room:
                continue
            npc.suspicion = max(0, npc.suspicion - SUSPICION_DECAY_PER_TICK)

            needs = getattr(npc, 'needs', None)
            if needs is not None:
                needs["hunger"] = min(100, needs.get("hunger", 0) + random.randint(1, 3))
                needs["fatigue"] = min(100, needs.get("fatigue", 0) + random.randint(1, 2))
                if current_room_id and any(
                    n.faction in ("kempeitai",) and n.faction != npc.faction
                    for n in self._get_nearby_npcs(npc_id, current_room)
                ):
                    needs["fear"] = min(100, needs.get("fear", 0) + random.randint(2, 5))
                else:
                    needs["fear"] = max(0, needs.get("fear", 0) - random.randint(1, 3))

            skip_npc = False
            for session in self.session_manager.get_players_in_room(current_room_id):
                if session.manually_advancing:
                    skip_npc = True
                    break
                if tutorial_blocks_world_events(session.player) and not sound_investigator:
                    skip_npc = True
                    break
                active = session.player.active_storylets
                if active and getattr(active[0], "blocking", True):
                    if npc_id in active[0].participant_npc_ids():
                        skip_npc = True
                        break
            if skip_npc:
                continue

            if getattr(npc, 'wounded', False):
                self._npc_flee_action(npc, current_room_id, current_room, rooms_with_players, reason="wounded")
                npc.hp = min(100, npc.hp + random.randint(1, 5))
                if npc.hp >= 80:
                    npc.wounded = False
                    npc.wound_type = ""
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
        retire_recorded_npcs(self.shared)

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

    async def _deliver_defection_district_knowledge(self, npc, old_faction: str, new_faction: str) -> None:
        from .delivery import Locality, Notice, Tier
        room = self.shared.world.get_room(self.shared.world.npc_locations.get(npc.id, ""))
        zone = self._room_zone(room) if room else None
        if zone is None:
            return
        notice = Notice(
            tier=Tier.AMBIENT,
            locality=Locality.DISTRICT,
            source="defection",
            semantic_key=f"defection.{npc.id}",
            msg_type=MessageType.AMBIENT,
            text=(
                f"Word travels through the district: {npc.name} has abandoned the "
                f"{old_faction.upper()} for the {new_faction.upper()}.\n"
            ),
            source_room_id=room.id,
            source_district=zone,
        )
        current_time = self._delivery_time()
        for session in list(self.session_manager.sessions.values()):
            if tutorial_blocks_world_events(session.player):
                continue
            player_room = self.shared.world.get_room(session.player.current_room)
            if not player_room or self._room_zone(player_room) != zone:
                continue
            await session.delivery.deliver(session, notice, current_time=current_time)

    def _get_nearby_npcs(self, npc_id: str, current_room) -> list:
        return [self.shared.world.npcs.get(nid) for nid in current_room.npcs if nid != npc_id and self.shared.world.npcs.get(nid)]

    def _run_social_interaction(self, actor, room, action: str, target=None, on_delivered=None) -> bool:
        candidates = [target] if target else self._get_nearby_npcs(actor.id, room)
        if not candidates:
            return False
        random.shuffle(candidates)
        world_state = type("SocialWorldState", (), {
            "world_tension": (self.shared.ccp_influence + self.shared.gmd_influence) / 2,
            "district": getattr(room, "district", ""),
        })()
        for candidate in candidates:
            interaction = npc_interaction_manager.select_interaction(action, actor, candidate, world_state)
            if not interaction:
                continue
            district = getattr(room, "district", "") or "default"
            self._social_resolver.apply(interaction, actor, candidate, self.shared, district)
            sound = NPC_ACTION_SOUNDS.get(action)
            if sound:
                intensity, sound_type, audio_name = sound
                self._track_task(self._dispatch_world_sound(room.id, intensity, sound_type, audio_name))
            sessions = list(self.session_manager.get_players_in_room(room.id))
            record_social_consequence(
                interaction, actor, candidate, self.shared, room,
                witnesses=[session.username for session in sessions],
            )
            if interaction.effects.rumor_propagation:
                exchange_gossip(
                    actor.memory, candidate.memory, chance=1.0,
                    game_day=self.shared.game_time.day, npc_a=actor, npc_b=candidate,
                    shared=self.shared,
                )
            if action in {"gossip", "trade_gossip", "exchange_rumors", "share_news"}:
                turns = self._social_dialogue.compose_turns(
                    actor,
                    candidate,
                    action,
                    {
                        "weather": self.shared.weather,
                        "absolute_minute": game_clock_total_minutes(self.shared.game_time),
                    },
                )
            else:
                turns = [
                    {"speaker": actor.name, "text": npc_interaction_manager.render_narrative(interaction, actor, candidate), "delay_ms": 900},
                    {"speaker": candidate.name, "text": "The exchange ends without drawing further attention.", "delay_ms": 900},
                ]
            from .rumors import push_panel_entry
            client_room_id = room.id
            for instance_id, clone_map in getattr(self.shared, "tutorial_room_clones", {}).items():
                if room.id in clone_map.values():
                    from .tutorial import get_original_tutorial_room_id
                    client_room_id = get_original_tutorial_room_id(instance_id, room.id, self.shared)
                    break
            entry_data = {
                "room_id": room.id,
                "client_room_id": client_room_id,
                "speaker": actor.name,
                "listener": candidate.name,
                "turns": turns,
            }
            if on_delivered:
                on_delivered(entry_data)
            for session in sessions:
                push_panel_entry(session, action, entry_data)
            return True
        return False

    def _npc_move_action(self, npc, current_room_id: str, current_room, rooms_with_players: set):
        import random
        from .delivery import Locality, Tier
        if not current_room.exits:
            return

        direction = random.choice(list(current_room.exits.keys()))
        dest_room_id = current_room.exits[direction]

        if self._move_npc_between_rooms(npc.id, current_room_id, dest_room_id):
            if current_room_id in rooms_with_players or dest_room_id in rooms_with_players:
                if self._visible_sessions(current_room_id):
                    self._queue_movement_line(current_room_id, f"{npc.name} walks {direction}.")
                if self._visible_sessions(dest_room_id):
                    self._queue_movement_line(
                        dest_room_id,
                        f"{npc.name} arrives from the {self._get_direction(dest_room_id, current_room_id)}.",
                    )

    def _npc_gossip_action(self, npc, current_room, rooms_with_players: set):
        self._run_social_interaction(npc, current_room, "exchange_rumors")

    def _npc_argue_action(self, npc, current_room, rooms_with_players: set):
        import random

        nearby_npcs = self._get_nearby_npcs(npc.id, current_room)
        if not nearby_npcs:
            return

        opponents = [n for n in nearby_npcs if self._are_opposite_factions(npc.faction, n.faction)]
        if not opponents:
            return

        opponent = random.choice(opponents)
        self._run_social_interaction(npc, current_room, "argue", opponent)
    async def _dispatch_world_sound(
        self,
        source_room_id: str,
        intensity: int,
        sound_type: str,
        audio_name: str | None = None,
        max_distance: int = 3,
    ) -> None:
        from .commands import _update_npc_sound_memory
        from .pathfinding import emit_sound, propagate_sound
        sound_event = emit_sound(
            source_room_id,
            "npc_confrontation",
            intensity=intensity,
            weather=getattr(self.shared, "weather", "clear"),
            game_time=self.shared.game_time,
            source_actor_id=sound_type,
            base_range=max_distance,
        )
        heard_rooms = propagate_sound(
            self.shared.world.rooms,
            sound_event,
        )
        for room_id, perceived_intensity in heard_rooms:
            room = self.shared.world.get_room(room_id)
            if not room:
                continue
            for npc_id in room.npcs:
                npc = self.shared.world.npcs.get(npc_id)
                if npc:
                    _update_npc_sound_memory(
                        npc,
                        source_room_id,
                        perceived_intensity,
                        sound_type,
                        self.shared.game_time,
                        sound_event=sound_event,
                    )
            from .delivery import player_sound_label
            sound_description = player_sound_label(sound_type)
            if perceived_intensity >= 3:
                message = f"You hear loud {sound_description} nearby!"
            elif perceived_intensity >= 2:
                message = f"You hear {sound_description} in the distance."
            else:
                message = f"You hear a muffled {sound_description} from somewhere nearby."
            from .delivery import Locality, Notice, Tier
            notice = Notice(
                tier=Tier.ACTIONABLE if perceived_intensity >= 3 else Tier.AMBIENT,
                locality=Locality.LOCAL,
                source="world_sound",
                semantic_key=f"world_sound.{sound_type}.{room_id}",
                msg_type=MessageType.EVENT if perceived_intensity >= 3 else MessageType.AMBIENT,
                text=message + "\n",
                sound=audio_name,
                sound_volume=min(1.0, perceived_intensity / max(1, sound_event.intensity)),
                source_room_id=source_room_id,
            )
            for session in self.session_manager.get_players_in_room(room_id):
                if tutorial_blocks_world_events(session.player):
                    continue
                await session.delivery.deliver(
                    session,
                    notice,
                    current_time=self._delivery_time(),
                )

    def _dispatch_authority_sound(self, source_room_id: str, intensity: int, sound_type: str) -> None:
        self._track_task(self._dispatch_world_sound(source_room_id, intensity, sound_type))

    def _npc_flee_action(self, npc, current_room_id: str, current_room, rooms_with_players: set, reason: str = ""):
        import random
        from .delivery import Locality, Tier

        is_wounded = getattr(npc, 'wounded', False)

        nearby_npcs = self._get_nearby_npcs(npc.id, current_room)
        kempeitai_nearby = any(n.faction == "kempeitai" for n in nearby_npcs)
        is_resistance = npc.faction in ["ccp", "gmd"]

        if not (is_wounded or (kempeitai_nearby and is_resistance)):
            return

        if not current_room.exits:
            return

        direction = None
        dest_room_id = None

        if is_wounded:
            nurse_rooms = ['grey_brick_longtang', 'hongkou_field_hospital', 'church_refugee_clinic']
            game_hour = self.shared.game_time.hour
            for nurse_room_id in nurse_rooms:
                for dir_opt, dest_opt in current_room.exits.items():
                    if dest_opt == nurse_room_id:
                        nurse_room = self.shared.world.rooms.get(nurse_room_id)
                        if nurse_room and getattr(nurse_room, 'nurse_available', False):
                            nurse_hours = getattr(nurse_room, 'nurse_hours', [8, 18])
                            if nurse_hours and len(nurse_hours) >= 2:
                                if nurse_hours[0] <= game_hour < nurse_hours[1]:
                                    direction = dir_opt
                                    dest_room_id = dest_opt
                                    break
                if direction:
                    break
                for dir1, mid_room_id in current_room.exits.items():
                    mid_room = self.shared.world.rooms.get(mid_room_id)
                    if mid_room and mid_room.exits:
                        for dir2, dest_opt in mid_room.exits.items():
                            if dest_opt == nurse_room_id:
                                nurse_room = self.shared.world.rooms.get(nurse_room_id)
                                if nurse_room and getattr(nurse_room, 'nurse_available', False):
                                    nurse_hours = getattr(nurse_room, 'nurse_hours', [8, 18])
                                    if nurse_hours and len(nurse_hours) >= 2:
                                        if nurse_hours[0] <= game_hour < nurse_hours[1]:
                                            direction = dir1
                                            dest_room_id = mid_room_id
                                            break
                    if direction:
                        break
                if direction:
                    break

        if not direction:
            direction = random.choice(list(current_room.exits.keys()))
            dest_room_id = current_room.exits[direction]

        if self._move_npc_between_rooms(npc.id, current_room_id, dest_room_id):
            if current_room_id in rooms_with_players or dest_room_id in rooms_with_players:
                dest_room = self.shared.world.rooms.get(dest_room_id)
                reached_nurse = is_wounded and dest_room and getattr(dest_room, 'nurse_available', False)
                nurse_hours = getattr(dest_room, 'nurse_hours', [8, 18]) if reached_nurse else []
                game_hour = self.shared.game_time.hour

                if reached_nurse and nurse_hours and len(nurse_hours) >= 2 and nurse_hours[0] <= game_hour < nurse_hours[1]:
                    heal_amount = random.randint(15, 25)
                    npc.hp = min(100, npc.hp + heal_amount)
                    flee_msg = f"{npc.name} stumbles into the clinic, seeking help for their wound."
                    if npc.hp >= 70:
                        npc.wounded = False
                        npc.wound_type = ""
                        flee_msg = f"{npc.name} stumbles into the clinic, and a nurse rushes to treat their wound. After a few minutes, they seem stable."
                else:
                    flee_msg = f"{npc.name} staggers away {direction}, clutching a wound!" if is_wounded else f"{npc.name} flees {direction}!"
                for session in self.session_manager.get_players_in_room(current_room_id):
                    self._schedule_notice(
                        session, tier=Tier.AMBIENT, locality=Locality.ROOM, source="npc_flee",
                        semantic_key=f"npc_flee.{npc.id}.{current_room_id}",
                        msg_type=MessageType.NPC_AMBIENT, text=flee_msg,
                        source_room_id=current_room_id,
                    )

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
        from .delivery import Locality, Tier

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

        def _action_social(action: str):
            def execute(bb):
                npc, room, _ = _npc_ctx(bb)
                if not npc or not room:
                    return Status.FAILURE
                return Status.SUCCESS if self._run_social_interaction(npc, room, action) else Status.FAILURE
            return execute

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
            from .pathfinding import a_star_find_path
            npc, _, _ = _npc_ctx(bb, require_room=False)
            if not npc:
                return Status.FAILURE
            hour = bb.get("game_hour", -1)
            target_room = npc.schedule.get(hour)
            current_room_id = self.shared.world.npc_locations.get(bb.get("npc_id"))
            if not target_room or current_room_id == target_room:
                return Status.FAILURE
            current_room_obj = self.shared.world.rooms.get(current_room_id)
            if not current_room_obj or not current_room_obj.exits:
                return Status.FAILURE

            path = a_star_find_path(
                self.shared.world.rooms,
                current_room_id,
                target_room,
                cost_fn=lambda a, b: 1.0,
            )
            if path:
                direction = path[0]
                dest_room_id = current_room_obj.exits.get(direction)
                if dest_room_id and self._move_npc_between_rooms(npc.id, current_room_id, dest_room_id, direction):
                    rooms_with_players = self._rooms_with_players()
                    if current_room_id in rooms_with_players or dest_room_id in rooms_with_players:
                        if self._visible_sessions(current_room_id):
                            self._queue_movement_line(current_room_id, f"{npc.name} walks {direction}.")
                        if self._visible_sessions(dest_room_id):
                            self._queue_movement_line(
                                dest_room_id,
                                f"{npc.name} arrives from the {self._get_direction(dest_room_id, current_room_id)}.",
                            )
                    return Status.SUCCESS
            self._npc_move_action(npc, current_room_id, current_room_obj, self._rooms_with_players())
            return Status.SUCCESS

        def _action_share_intel(bb):
            npc, room, _ = _npc_ctx(bb)
            if not npc or not room:
                return Status.FAILURE
            return Status.SUCCESS if self._run_social_interaction(npc, room, "share_intel") else Status.FAILURE

        def _action_hide_in_shadows(bb):
            npc, room, room_id = _npc_ctx(bb)
            if not npc or not room or not room.hiding_spots:
                return Status.FAILURE
            for session in self.session_manager.get_players_in_room(room_id):
                self._schedule_notice(
                    session, tier=Tier.AMBIENT, locality=Locality.ROOM, source="npc_hide",
                    semantic_key=f"npc_hide.{npc.id}.{room_id}", msg_type=MessageType.NPC_AMBIENT,
                    text=f"{npc.name} slips into the shadows and vanishes from sight.",
                    source_room_id=room_id,
                )
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
            if not self._run_social_interaction(npc, room, "extort_civilian", target):
                return Status.FAILURE
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
            return Status.SUCCESS if self._run_social_interaction(npc, room, "intimidate_rival", target) else Status.FAILURE

        def _action_hold_secret_meeting(bb):
            npc, room, _ = _npc_ctx(bb)
            if not npc or not room:
                return Status.FAILURE
            return Status.SUCCESS if self._run_social_interaction(npc, room, "hold_secret_meeting") else Status.FAILURE

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
            self._schedule_notice(
                target, tier=Tier.CRITICAL, locality=Locality.ROOM, source="npc_investigation",
                semantic_key=f"npc_investigation.{npc.id}.{room_id}", msg_type=MessageType.WARNING,
                text=f"{npc.name} scans the shadows and spots you. 'What are you doing?'",
                source_room_id=room_id,
            )
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
                self._schedule_notice(
                    session, tier=Tier.ACTIONABLE, locality=Locality.ROOM, source="vendor_shutter",
                    semantic_key=f"vendor_shutter.{room_id}", msg_type=MessageType.EVENT,
                    text=f"{npc.name} boards up the shop and slips away into the crowd.",
                    source_room_id=room_id,
                )
            return Status.SUCCESS

        def _action_defect(bb):
            npc, room, room_id = _npc_ctx(bb, require_room=False)
            if not npc:
                return Status.FAILURE

            old_faction = npc.faction

            if old_faction == "ccp":
                new_faction = "gmd"
            elif old_faction == "gmd":
                new_faction = "ccp"
            elif old_faction == "green_gang":
                disp = self.shared.npc_dispositions.get(npc.id, {"disillusionment": 0})
                if disp.get("disillusionment", 0) > 80:
                    new_faction = "civilian"
                else:
                    new_faction = "kempeitai"
            else:
                return Status.FAILURE

            npc.faction = new_faction
            self.shared.npc_dispositions.pop(npc.id, None)
            self._resolve_decision("defection", npc.id, room_id or "",
                                   {"old_faction": old_faction, "new_faction": new_faction})
            for nid, other in self.shared.world.npcs.items():
                if nid != npc.id and other.faction == old_faction:
                    disp = self.shared.npc_dispositions.setdefault(nid, {"disillusionment": 0})
                    disp["disillusionment"] = min(100, disp["disillusionment"] + 5)
            from .rumors import publish_event_rumor
            publish_event_rumor(
                self.shared,
                event_type="defection",
                text=f"{npc.name} has abandoned the {old_faction.upper()} for the {new_faction.upper()}.",
                location=room_id or "",
                district=getattr(self.shared.world.rooms.get(room_id or ""), "district", "") if room_id else "",
                witnesses=list(room.npcs) if room else [],
                faction_context=new_faction,
                created_day=self.shared.game_time.day,
                occurrence=npc.id,
            )
            asyncio.create_task(self._deliver_defection_district_knowledge(npc, old_faction, new_faction))
            return Status.SUCCESS

        def _action_seek_food(bb):
            npc, room, room_id = _npc_ctx(bb, require_exits=True)
            if not npc:
                return Status.FAILURE
            needs = getattr(npc, 'needs', None)
            if needs is not None:
                needs["hunger"] = max(0, needs.get("hunger", 0) - random.randint(15, 30))
            for session in self.session_manager.get_players_in_room(room_id):
                self._schedule_notice(
                    session, tier=Tier.AMBIENT, locality=Locality.ROOM, source="npc_needs",
                    semantic_key=f"npc_seek_food.{npc.id}.{room_id}", msg_type=MessageType.NPC_AMBIENT,
                    text=f"{npc.name} rummages around, looking for something to eat.",
                    source_room_id=room_id,
                )
            self._npc_move_action(npc, room_id, room, self._rooms_with_players())
            return Status.SUCCESS

        def _action_go_home(bb):
            npc, room, room_id = _npc_ctx(bb, require_exits=True)
            if not npc:
                return Status.FAILURE
            needs = getattr(npc, 'needs', None)
            if needs is not None:
                needs["fatigue"] = max(0, needs.get("fatigue", 0) - random.randint(20, 40))
            home_room = npc.schedule.get(22, None)
            if home_room and home_room in self.shared.world.rooms:
                from .pathfinding import a_star_find_path
                current_room_obj = self.shared.world.rooms.get(room_id)
                if current_room_obj and current_room_obj.exits:
                    path = a_star_find_path(
                        self.shared.world.rooms, room_id, home_room,
                        cost_fn=lambda a, b: 1.0,
                    )
                    if path:
                        direction = path[0]
                        dest_id = current_room_obj.exits.get(direction)
                        if dest_id:
                            self._move_npc_between_rooms(npc.id, room_id, dest_id, direction)
                            rooms_with_players = self._rooms_with_players()
                            if room_id in rooms_with_players or dest_id in rooms_with_players:
                                if self._visible_sessions(room_id):
                                    self._queue_movement_line(room_id, f"{npc.name} yawns and heads off to rest.")
                                if self._visible_sessions(dest_id):
                                    self._queue_movement_line(dest_id, f"{npc.name} arrives, looking tired.")
                            return Status.SUCCESS
            if self._visible_sessions(room_id):
                self._queue_movement_line(
                    room_id,
                    f"{npc.name} stifles a yawn and wanders off to find a place to rest.",
                )
            self._npc_move_action(npc, room_id, room, self._rooms_with_players())
            return Status.SUCCESS

        def _action_seek_safety(bb):
            npc, room, room_id = _npc_ctx(bb)
            if not npc:
                return Status.FAILURE
            needs = getattr(npc, 'needs', None)
            if needs is not None:
                needs["fear"] = max(0, needs.get("fear", 0) - random.randint(10, 25))
            for session in self.session_manager.get_players_in_room(room_id):
                self._schedule_notice(
                    session, tier=Tier.AMBIENT, locality=Locality.ROOM, source="npc_needs",
                    semantic_key=f"npc_seek_safety.{npc.id}.{room_id}", msg_type=MessageType.NPC_AMBIENT,
                    text=f"{npc.name} looks around nervously and hurries away.",
                    source_room_id=room_id,
                )
            self._npc_flee_action(npc, room_id, room, self._rooms_with_players())
            return Status.SUCCESS

        return {
            "patrol_random_exit": _action_move,
            "investigate_sound": _action_investigate_sound,
            "follow_schedule": _action_follow_schedule,
            "trade_gossip": _action_social("trade_gossip"),
            "exchange_rumors": _action_social("exchange_rumors"),
            "share_intel": _action_share_intel,
            "gather_rumors": _action_social("exchange_rumors"),
            "hide_in_shadows": _action_hide_in_shadows,
            "patrol_quietly": _action_move,
            "patrol_territory": _action_move,
            "extort_civilian": _action_extort_civilian,
            "intimidate_rival": _action_intimidate_rival,
            "hold_secret_meeting": _action_hold_secret_meeting,
            "delegate_task": _action_social("delegate_task"),
            "stay_put": _action_idle,
            "flee_to_safe_room": _action_flee,
            "flee_from_authority": _action_flee,
            "investigate_player": _action_investigate_player,
            "shutter_shop": _action_shutter_shop,
            "defect": _action_defect,
            "idle": _action_idle,
            "seek_food": _action_seek_food,
            "go_home": _action_go_home,
            "seek_safety": _action_seek_safety,
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

        def _cond_bravery_high(bb):
            return bb.get("bravery", 50) >= 70

        def _cond_bravery_low(bb):
            return bb.get("bravery", 50) < 30

        def _cond_sociability_high(bb):
            return bb.get("sociability", 50) >= 70

        def _cond_sociability_low(bb):
            return bb.get("sociability", 50) < 30

        def _cond_integrity_high(bb):
            return bb.get("integrity", 50) >= 70

        def _cond_integrity_low(bb):
            return bb.get("integrity", 50) < 30

        def _cond_curiosity_high(bb):
            return bb.get("curiosity", 50) >= 70

        def _cond_curiosity_low(bb):
            return bb.get("curiosity", 50) < 30

        def _cond_loyalty_high(bb):
            return bb.get("loyalty", 50) >= 70

        def _cond_loyalty_low(bb):
            return bb.get("loyalty", 50) < 30

        def _cond_needs_hunger_high(bb):
            return bb.get("needs_hunger", 0) > 70

        def _cond_needs_fatigue_high(bb):
            return bb.get("needs_fatigue", 0) > 70

        def _cond_needs_fear_high(bb):
            return bb.get("needs_fear", 0) > 70

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
            "bravery_high": _cond_bravery_high,
            "bravery_low": _cond_bravery_low,
            "sociability_high": _cond_sociability_high,
            "sociability_low": _cond_sociability_low,
            "integrity_high": _cond_integrity_high,
            "integrity_low": _cond_integrity_low,
            "curiosity_high": _cond_curiosity_high,
            "curiosity_low": _cond_curiosity_low,
            "loyalty_high": _cond_loyalty_high,
            "loyalty_low": _cond_loyalty_low,
            "needs_hunger_high": _cond_needs_hunger_high,
            "needs_fatigue_high": _cond_needs_fatigue_high,
            "needs_fear_high": _cond_needs_fear_high,
        }

    def _rooms_with_players(self) -> set:
        return {s.player.current_room for s in self.session_manager.sessions.values()}

    def _visible_sessions(self, room_id: str) -> list:
        return [
            s for s in self.session_manager.get_players_in_room(room_id)
            if not tutorial_blocks_world_events(s.player)
        ]

    def _tutorial_clone_npc_ids(self) -> set:
        return {nid for ids in self.shared.tutorial_npc_clones.values() for nid in ids}

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

        traits = npc.personality_traits or {}
        bb.set("bravery", traits.get("bravery", 50))
        bb.set("sociability", traits.get("sociability", 50))
        bb.set("integrity", traits.get("integrity", 50))
        bb.set("curiosity", traits.get("curiosity", 50))
        bb.set("loyalty", traits.get("loyalty", 50))

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

        needs = getattr(npc, 'needs', {})
        bb.set("needs_hunger", needs.get("hunger", 0))
        bb.set("needs_fatigue", needs.get("fatigue", 0))
        bb.set("needs_fear", needs.get("fear", 0))

        world_tension = (self.shared.ccp_influence + self.shared.gmd_influence) / 2
        bb.set("world_tension", world_tension)
        disp = self.shared.npc_dispositions.get(npc.id, {})
        bb.set("disillusionment", disp.get("disillusionment", 0))

        npc_bb = getattr(npc, "_blackboard", None)
        if npc_bb:
            sound = npc_bb.get("last_heard_sound")
            if sound:
                bb.set("last_heard_sound", sound)
            bb.set("heard_hostile_sound", npc_bb.get("heard_hostile_sound", False) if npc_bb else False)
        investigation = npc_bb.get("sound_investigation") if npc_bb else None
        if investigation:
            bb.set("sound_investigation", investigation)
            investigation = npc_bb.get("sound_investigation")
            if investigation:
                bb.set("sound_investigation", investigation)
        direct_move_minute = npc_bb.get("tutorial_direct_move_minute") if npc_bb else None
        if direct_move_minute is not None:
            bb.set("tutorial_direct_move_minute", direct_move_minute)

    OPPOSITE_DIRECTION = {
        "north": "south", "south": "north",
        "east": "west", "west": "east",
        "up": "down", "down": "up",
    }

    def _move_sound_investigator_toward_target(self, npc, bb):
        from .pathfinding import a_star_find_path

        sound = bb.get("last_heard_sound")
        target_room_id = sound.get("room_id") if isinstance(sound, dict) else None
        npc_id = getattr(npc, "id", "") or bb.get("npc_id")
        current_room_id = self.shared.world.npc_locations.get(npc_id)
        current_room = self.shared.world.rooms.get(current_room_id) if current_room_id else None
        if not target_room_id or current_room_id == target_room_id or not current_room or not current_room.exits:
            return None
        path = a_star_find_path(
            self.shared.world.rooms, current_room_id, target_room_id,
            cost_fn=lambda a, b: 1.0,
        )
        if not path:
            return None
        direction = path[0]
        dest_id = current_room.exits.get(direction)
        if not dest_id or not self._move_npc_between_rooms(npc_id, current_room_id, dest_id, direction):
            return None
        investigation = bb.get("sound_investigation")
        if isinstance(investigation, dict) and investigation.get("phase") == "travel":
            investigation["approach_direction"] = direction
        return current_room_id, dest_id, direction, f"{npc.name} moves purposefully {direction}."

    def move_tutorial_sound_investigator(self, npc_id: str, target_room_id: str):
        if not npc_id.endswith("tutorial_kempeitai_officer"):
            return None
        npc = self.shared.world.npcs.get(npc_id)
        bb = getattr(npc, "_blackboard", None) if npc else None
        if not npc or not bb:
            return None
        sound = bb.get("last_heard_sound")
        investigation = bb.get("sound_investigation")
        if not isinstance(sound, dict) or sound.get("room_id") != target_room_id:
            return None
        if not isinstance(investigation, dict) or investigation.get("phase") != "travel":
            return None
        step = self._move_sound_investigator_toward_target(npc, bb)
        if step:
            bb.set("tutorial_direct_move_minute", game_clock_total_minutes(self.shared.game_time))
            npc_bb = getattr(npc, "_blackboard", None)
            if npc_bb:
                npc_bb.set("tutorial_direct_move_minute", game_clock_total_minutes(self.shared.game_time))
        return step[3] if step else None

    def _npc_investigate_action(self, npc, bb):
        from .behavior_tree import Status
        from .delivery import Locality, Tier
        sound = bb.get("last_heard_sound")
        if not sound:
            return Status.FAILURE
        target_room_id = sound.get("room_id") if isinstance(sound, dict) else None
        if not target_room_id:
            return Status.FAILURE
        npc_id = bb.get("npc_id")
        if isinstance(sound, dict) and sound.get("actionable") and not bb.get("sound_investigation"):
            return Status.FAILURE
        if bb.get("tutorial_direct_move_minute") == game_clock_total_minutes(self.shared.game_time):
            bb.clear("tutorial_direct_move_minute")
            npc_bb = getattr(npc, "_blackboard", None)
            if npc_bb:
                npc_bb.clear("tutorial_direct_move_minute")
            return Status.RUNNING
        current_room_id = self.shared.world.npc_locations.get(npc_id)
        if current_room_id == target_room_id:
            investigation = bb.get("sound_investigation")
            if (
                isinstance(investigation, dict)
                and investigation.get("source_room") == current_room_id
                and investigation.get("phase") == "travel"
            ):
                search_room = self._select_search_room(current_room_id, investigation)
                self._finish_sound_search(bb, npc)
                if search_room:
                    self._move_npc_between_rooms(npc_id, current_room_id, search_room)
                return Status.SUCCESS
            self._clear_npc_sound_memory(npc, bb)
            return Status.SUCCESS
        step = self._move_sound_investigator_toward_target(npc, bb)
        if step:
            current_room_id, dest_id, direction, movement_message = step
            rooms_with_players = self._rooms_with_players()
            if current_room_id in rooms_with_players or dest_id in rooms_with_players:
                for session in self.session_manager.get_players_in_room(current_room_id):
                    if tutorial_blocks_world_events(session.player):
                        continue
                    self._schedule_notice(
                        session, tier=Tier.AMBIENT, locality=Locality.ROOM, source="npc_sound_search",
                        semantic_key=f"npc_search.{npc_id}.{current_room_id}",
                        msg_type=MessageType.NPC_AMBIENT, text=movement_message,
                        source_room_id=current_room_id,
                    )
                for session in self.session_manager.get_players_in_room(dest_id):
                    if tutorial_blocks_world_events(session.player):
                        if not tutorial_sound_investigator_allowed(npc_id, self._tutorial_clone_npc_ids(), npc):
                            continue
                    self._schedule_notice(
                        session, tier=Tier.AMBIENT, locality=Locality.ROOM, source="npc_sound_search",
                        semantic_key=f"npc_search.{npc_id}.{dest_id}",
                        msg_type=MessageType.NPC_AMBIENT, text=movement_message,
                        source_room_id=dest_id,
                    )
            return Status.RUNNING
        self._clear_npc_sound_memory(npc, bb)
        return Status.FAILURE

    def _select_search_room(self, room_id: str, investigation: dict):
        room = self.shared.world.rooms.get(room_id)
        if not room or not room.exits:
            return None
        approach = investigation.get("approach_direction") or ""
        forward = room.exits.get(approach)
        if forward and self.shared.world.rooms.get(forward):
            return forward
        opposite = self.OPPOSITE_DIRECTION.get(approach)
        fallbacks = [
            dest for direction, dest in room.exits.items()
            if direction != opposite and self.shared.world.rooms.get(dest)
        ]
        if fallbacks:
            return fallbacks[0]
        return None

    def _finish_sound_search(self, bb, npc) -> None:
        bb.clear("sound_investigation")
        npc_bb = getattr(npc, "_blackboard", None)
        if npc_bb:
            npc_bb.clear("sound_investigation")
        self._clear_npc_sound_memory(npc, bb)

    @staticmethod
    def _clear_npc_sound_memory(npc, bb) -> None:
        bb.clear("last_heard_sound")
        bb.set("heard_hostile_sound", False)
        npc_bb = getattr(npc, "_blackboard", None)
        if npc_bb:
            npc_bb.clear("last_heard_sound")
            npc_bb.set("heard_hostile_sound", False)

    def _update_weather(self):
        season = _season_from_day(self.shared.game_time.day)
        weather_weights = {
            "spring": (("clear", 50), ("rain", 25), ("fog", 15), ("storm", 10)),
            "summer": (("clear", 50), ("rain", 25), ("fog", 10), ("storm", 15)),
            "autumn": (("clear", 35), ("rain", 30), ("fog", 20), ("storm", 15)),
            "winter": (("clear", 40), ("snow", 30), ("fog", 15), ("rain", 10), ("storm", 5)),
        }
        states, weights = zip(*weather_weights[season])
        previous = getattr(self.shared, "weather", "clear")
        self.shared.weather = random.choices(states, weights=weights, k=1)[0]
        if self.shared.weather == "rain":
            self._apply_weather_degradation()
        elif self.shared.weather == "storm":
            self._apply_weather_degradation(multiplier=2)
            if previous != "storm":
                asyncio.create_task(self._broadcast_audio("thunder", volume=0.6))
        if self.shared.weather != previous:
            self._announce_weather_transition(previous, self.shared.weather)

    def _announce_weather_transition(self, previous: str, current: str) -> None:
        from .delivery import Locality, Tier

        text = WEATHER_TRANSITION_TEXT.get(current)
        if not text:
            return
        msg_type = getattr(MessageType, f"WEATHER_{current.upper()}", MessageType.EVENT)
        for session in list(self.session_manager.sessions.values()):
            if tutorial_blocks_world_events(session.player):
                continue
            self._schedule_notice(
                session,
                tier=Tier.AMBIENT,
                locality=Locality.CITYWIDE,
                source="weather",
                semantic_key="weather.state",
                msg_type=msg_type,
                text=text,
                state_token=current,
            )

    def _apply_weather_degradation(self, multiplier: int = 1):
        from .constants import DEGRADE_RAIN_RATE
        for session in list(self.session_manager.sessions.values()):
            room = self.shared.world.get_room(session.player.current_room)
            if room and room.indoors:
                continue
            broken = []
            for item in session.player.inventory:
                if not (item.is_weapon or item.is_armour) or item.durability <= 0:
                    continue
                item.durability = max(0, item.durability - DEGRADE_RAIN_RATE * multiplier)
                if item.durability <= 0:
                    verb = "rusts apart" if item.is_weapon else "is ruined by the rain"
                    from .delivery import Locality, Tier
                    self._schedule_notice(
                        session, tier=Tier.ACTIONABLE, locality=Locality.ROOM, source="weather_damage",
                        semantic_key=f"weather_damage.{item.instance_id}", msg_type=MessageType.WARNING,
                        text=f"Your {item.name} {verb}.", source_room_id=session.player.current_room,
                    )
                    if getattr(session, "audio_enabled", False):
                        asyncio.create_task(session.send_audio("item_break", volume=0.6))
                    broken.append(item)
            for item in broken:
                session.player.inventory.remove(item)
                from .equipment import invalidate_disguise_if_support_lost
                invalidate_disguise_if_support_lost(session.player, item)

    async def _check_death_and_victory(self):
        from .locales import get as loc

        for session in list(self.session_manager.sessions.values()):
            is_dead = False
            death_message = ""

            if session.player.health <= 0:
                is_dead = True
                death_message = loc("death.health")

            if is_dead:
                from .commands import _trigger_death
                ctx = self.session_manager._make_context(session)
                await _trigger_death(ctx, death_message)

        if self.shared.game_time.minute == 0:
            await self._check_milestone_day()
            await resolve_shared_liberation(self.shared, self.session_manager)

    async def _handle_server_reset(self, ending_type: str = ""):
        return await resolve_shared_liberation(self.shared, self.session_manager)

    def _reset_shared_world(self):
        from .victory import _reset_shared_world

        _reset_shared_world(self.shared, self.session_manager)

    async def _check_milestone_day(self):
        mm = self.shared.milestone_manager
        if not mm:
            return
        triggered = mm.check_day(self.shared.game_time.day)
        if not triggered:
            return
        from .milestones import apply_milestone_effects
        for m in triggered:
            for session in list(self.session_manager.sessions.values()):
                if tutorial_blocks_world_events(session.player):
                    continue
                if m.narrative and apply_milestone_effects(session.player, m, self.shared):
                    from .delivery import Locality, Tier
                    self._schedule_notice(
                        session, tier=Tier.ACTIONABLE, locality=Locality.ROOM,
                        source="milestone", semantic_key=f"milestone.{m.id}",
                        msg_type=MessageType.ROOM_DESCRIPTION,
                        text=f"\n[MILESTONE] {m.narrative}\n",
                        source_room_id=session.player.current_room,
                    )

    async def _check_storylet_timers_all_sessions(self):
        from .storylets import is_storylet_expired
        from .commands import _resolve_neglect

        for session in list(self.session_manager.sessions.values()):
            if not session.player.active_storylets:
                continue
            if tutorial_blocks_world_events(session.player):
                continue
            expired = [a for a in session.player.active_storylets if is_storylet_expired(a)]
            for active in expired:
                try:
                    ctx = self.session_manager._make_context(session)
                    await _resolve_neglect(ctx, active)
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Error resolving neglect for {active.storylet_id}: {e}")
