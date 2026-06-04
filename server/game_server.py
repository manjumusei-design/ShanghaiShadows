import asyncio
from pathlib import Path

from .config import get_setting, load_dotenv
from .game_world import (
    SharedWorldState,
    load_world_state,
    save_world_state,
    load_disguises,
    DISGUISES_PATH,
    STORYLETS_PATH,
    SAVES_DIR,
    STATE_BROADCAST_INTERVAL,
)
from .world_clock import WorldClock
from .commands import build_command_registry, broadcast_state, build_completions
from .save_manager import save_player
from .locales import load_locale, get as loc
from .stealth import StealthSystem
from .storylets import load_storylets, StoryletManager
from .world import World


class GameServer:
    def __init__(self):
        load_dotenv()
        load_locale(get_setting("LOCALE", "en"))
        SAVES_DIR.mkdir(parents=True, exist_ok=True)

        self.shared = load_world_state() or self._create_shared_world()
        self.disguises = load_disguises(DISGUISES_PATH)
        self.stealtg = StealthSystem(self.disguises)

        storylets = load_storylets(STORYLETS_PATH)
        self.storylet_manager = StoryletManager(storylets)

        from .session_manager import SessionManager
        self.session_manager = SessionManager(self.shared, self.disguises, self.stealth, self.storylet_manager)

        self.clock = WorldClock(self.shared, self.session_manager, self.disguises, self.stealth, self.storylet_manager)

    def _create_shared_world(self) -> SharedWorldState:
        world = World()
        from .time_system import EventScheduler, GameTime
        from .game import EVENTS_PATH, TRUST_RULES_PATH
        from .trust import load_trust_rules
        from .game_world import SharedWorldState

        scheduler = EventScheduler()
        scheduler.load_from_yaml(EVENTS_PATH)
        trust_rules = load_trust_rules(TRUST_RULES_PATH)

        return SharedWorldState(
            world=world,
            game_time=GameTime(),
            scheduler=scheduler,
            trust_rules=trust_rules,
            ccp_influence=10,
            gmd_influence=15,
            event_log=[],
            legacy_book=[],
            rumour_mill=[],
        )
    
    