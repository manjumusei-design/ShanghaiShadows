import asyncio
from pathlib import Path

from .config import get_setting, load_dotenv
from .constants import DISGUISES_PATH, STORYLETS_PATH, STATE_BROADCAST_INTERVAL
from .game_world import (
    SharedWorldState,
    load_disguises,
    SAVES_DIR,
    populate_vendor_shop_inventories,
)
from .save_manager import load_world_state, save_world_state
from .world_clock import WorldClock
from .save_manager import save_player
from .locales import load_locale, get as loc
from .stealth import StealthSystem
from .storylets import load_storylets, StoryletManager
from .missions import load_missions, MissionManger
from .world import World
from .ai_client import AIClient


class GameServer:
    def __init__(self, fresh_world: bool = False):
        load_dotenv()
        load_locale(get_setting("LOCALE", "en"))
        SAVES_DIR.mkdir(parents=True, exist_ok=True)

        self.ai_client = AIClient()
        self.shared = (
            self._create_shared_world()
            if fresh_world
            else (load_world_state() or self._create_shared_world())
        )
        self.disguises = load_disguises(DISGUISES_PATH)
        self.stealth = StealthSystem(self.disguises)

        storylets = load_storylets(STORYLETS_PATH)
        self.storylet_manager = StoryletManager(storylets)

        missions = load_missions()
        self.shared.mission_manager = MissionManager(missions)

        from .session_manager import SessionManager
        self.session_manager = SessionManager(self.shared, self.disguises, self.stealth, self.storylet_manager, self.ai_client)

        self.clock = WorldClock(self.shared, self.session_manager, self.disguises, self.stealth, self.storylet_manager)

    def _create_shared_world(self) -> SharedWorldState:
        world = World()
        from .time_system import EventScheduler, GameTime
        from .constants import EVENTS_PATH, TRUST_RULES_PATH, MILESTONES_PATH
        from .trust import load_trust_rules
        from .game_world import SharedWorldState
        from .milestones import load_milestones, MilestoneManager
        from .game_world import build_market_tracker
        from .rumors import seed_active_rumors
        from .tutorial import STAGF_BLOCKED_EXITS

        scheduler = EventScheduler()
        scheduler.load_from_yaml(EVENTS_PATH)
        trust_rules = load_trust_rules(TRUST_RULES_PATH)
        milestones = load_milestones(MILESTONES_PATH)

        _active = seed_active_rumors(1)

        state = SharedWorldState(
            world=world,
            game_time=GameTime(minute=480),
            scheduler=scheduler,
            trust_rules=trust_rules,
            ccp_influence=10,
            gmd_influence=15,
            kempeitai_influence = 20,
            gang_influence = 15,
            event_log=[],
            legacy_book=[],
            rumour_mill=[],
            milestone_manager=MilestoneManager(milestones),
            market_rooms=build_market_tracker(world),
            death_journals={},
            active_rumors=_active,
        )

        from .room_codes import generate_room_codes, layout_rooms, layout_tutorial_rooms, get_manual_coordinates
        map_rooms = {rid: r for rid, r in world.rooms.items() if not rid.startswith("refugee_entry_")}
        tutorial_rooms = {rid: r for rid, r in world.rooms.items() if rid.startswith("refugee_entry_")}
        all_rooms = {**map_rooms, **tutorial_rooms}
        state.room_codes = generate_room_codes(all_rooms)
        state.code_to_room = {v: k for k, v in state.room_codes.items()}
        state.room_layout_coords = layout_rooms(map_rooms)
        state.tutorial_layout_coords = layout_tutorial_rooms(tutorial_rooms)
        for rid, code in state.room_codes.items():
            if rid in world.rooms:
                world.rooms[rid].code = code

        populate_vendor_shop_inventories(world)

        self.load_npc_relationships(state.world.npcs)

        for stage, blocked_dict in STAGE_BLOCKED_EXITS.items():
            for room_id, exits in blocked_dict.items():
                if room_id in world.rooms:
                    world_rooms[room_id].blocked_exits.update(exits)
            
        return state
    
    def _load_npc_relationships(self, npcs: dict) -> None:
        from pathlib import Path
        from .npc_memory import npc_relationship_system
        import yaml

        rel_path = Path("server/data/npc_relationships.yaml")
        if rel_path.exists():
            try:
                with open(rel_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                relationships = data.get("relationships", [])
                npc_relationship_system.load_relationships(relationships, npcs)
            except Exception as e:
                print(f"Fail loading NPC relationships: {e}")

    async def tick_loop(self):
        while True:
            await asyncio.sleep(1)
            await self.clock.tick()

            for session in list(self.session_manager.sessions.values()):
                session.seconds_since_autosave += 1
                if session.seconds_since_autosave >= 300:
                    save_player(session.player)
                    session.seconds_since_autosave = 0

                session.seconds_since_state_broadcast += 1
                if session.seconds_since_state_broadcast >= STATE_BROADCAST_INTERVAL:
                    from.commands import CommandContext
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