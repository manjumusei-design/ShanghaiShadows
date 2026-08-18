import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from .config import get_setting, load_dotenv
from .game_world import (
    SharedWorldState,
    bootstrap_cycle_state,
    load_world_state,
    load_disguises,
    DISGUISES_PATH,
    STORYLETS_PATH,
    SAVES_DIR,
    STATE_BROADCAST_INTERVAL,
)
from .constants import AUTOSAVE_INTERVAL_SECONDS
from .world_clock import WorldClock
from .commands import build_command_registry, broadcast_state, build_completions
from .save_manager import save_world_state
from .locales import load_locale, get as loc
from .stealth import StealthSystem
from .storylets import load_storylets, load_narrative_chains, StoryletManager
from .missions import load_missions, MissionManager
from .milestones import load_milestones, MilestoneManager


class GameServer:
    def __init__(self, shared: Optional[SharedWorldState] = None, fresh_world: bool = False):
        load_dotenv()
        load_locale(get_setting("LOCALE", "en"))
        SAVES_DIR.mkdir(parents=True, exist_ok=True)

        if shared is None:
            shared = (
                self._create_shared_world()
                if fresh_world
                else (load_world_state() or self._create_shared_world())
            )
        self.shared = shared
        from .content_references import assert_valid_authored_references
        assert_valid_authored_references(self.shared.world)
        from .lifecycle import replay_lifecycle_outbox
        replay_lifecycle_outbox(self.shared)
        from .npc_memory import npc_relationship_system
        self.shared.relationship_system = npc_relationship_system

        self.disguises = load_disguises(DISGUISES_PATH)
        self.stealth = StealthSystem(self.disguises)

        storylets = load_storylets(STORYLETS_PATH)
        from .constants import NARRATIVE_CHAINS_PATH
        narrative_chains = load_narrative_chains(NARRATIVE_CHAINS_PATH)
        self.storylet_manager = StoryletManager(storylets, narrative_chains)

        if self.shared.mission_manager is None:
            self.shared.mission_manager = MissionManager(load_missions())
        if self.shared.milestone_manager is None:
            from .constants import MILESTONES_PATH
            self.shared.milestone_manager = MilestoneManager(load_milestones(MILESTONES_PATH))

        from .session_manager import SessionManager
        self.session_manager = SessionManager(self.shared, self.disguises, self.stealth, self.storylet_manager)

        self.clock = WorldClock(self.shared, self.session_manager, self.disguises, self.stealth, self.storylet_manager)
        self._world_seconds_since_save = 0

    def _create_shared_world(self) -> SharedWorldState:
        return bootstrap_cycle_state()

    async def tick_loop(self):
        import traceback as _tb
        while True:
            try:
                await asyncio.sleep(1)
                await self.clock.tick()

                self._process_autosaves()

                for session in list(self.session_manager.sessions.values()):
                    session.seconds_since_state_broadcast += 1
                    if session.seconds_since_state_broadcast >= STATE_BROADCAST_INTERVAL:
                        from .commands import CommandContext
                        ctx = CommandContext(
                            session=session,
                            shared=self.shared,
                            session_manager=self.session_manager,
                            disguises=self.disguises,
                            stealth=self.stealth,
                            storylet_manager=self.storylet_manager,
                            room=self.shared.world.get_room(session.player.current_room),
                        )
                        await broadcast_state(ctx)
                        session.seconds_since_state_broadcast = 0

            except Exception:
                logger.critical(f"tick_loop crashed: {_tb.format_exc()}")
                from .lifecycle import save_authorized_session
                for session in list(self.session_manager.sessions.values()):
                    if getattr(session, "clean_close_completed", False) or getattr(session, "final_save_attempted", False) or getattr(session, "ephemeral", False):
                        continue
                    try:
                        save_authorized_session(session)
                    except Exception:
                        pass
                save_world_state(self.shared)
                raise

    def _process_autosaves(self):
        from .lifecycle import save_authorized_session
        for session in list(self.session_manager.sessions.values()):
            if getattr(session, "clean_close_completed", False) or getattr(session, "final_save_attempted", False) or getattr(session, "ephemeral", False):
                continue
            session.seconds_since_autosave += 1
            if session.seconds_since_autosave >= AUTOSAVE_INTERVAL_SECONDS:
                if save_authorized_session(session):
                    session.seconds_since_autosave = 0

        self._world_seconds_since_save += 1
        if self._world_seconds_since_save >= AUTOSAVE_INTERVAL_SECONDS:
            save_world_state(self.shared)
            self._world_seconds_since_save = 0
