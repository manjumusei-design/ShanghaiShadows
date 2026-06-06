import random
from typing import TYPE_CHECKING, Callable, Dict, List

from .auth import add_character_to_account, create_account, verify_password, get_account
from .commands import (
    CommandContext,
    apply_storylet_effects,
    build_command_registry,
    build_completions,
    initialize_new_character,
    maybe_trigger_storylet,
    parse,
    resolve_storylet_choice,
)
from .parser import Command
from .save_manager import legacy_save_exists, load_player, load_world_state, migrate_legacy_save, save_player
from .session import Session
from .game_world import SharedWorldState

if TYPE_CHECKING:
    from .commands import CommandContext


class SessionManager:
    def __init__(self, shared: SharedWorldState, disguises, stealth, storylet_manager):
        self.shared = shared
        self.sessions: Dict[str, Session] = {}
        self.disguises = disguises
        self.stealth = stealth
        self.storylet_manager = storylet_manager
        self.command_registry: Dict[str, Callable] = build_command_registry()

    async def handle_client(self, websocket):
        session = await self._login_flow(websocket)
        if not session:
            try:
                await websocket.close()
            except Exception:
                pass
            return

        self.sessions[session.username] = session

        room = self.shared.world.get_room(session.player.current_room)
        if room and session.username not in room.npcs:
            if not hasattr(room, "players"):
                room.players = []
            if session.username not in room.players:
                room.players.append(session.username)

        await self._send_room_players(session)
        try:
            async for message in websocket:
                text = message.strip()
                if not text:
                    await session.send_prompt()
                    continue

                if session.player.active_storylet:
                    await resolve_storylet_choice(self._make_context(session), text)
                    if session.running:
                        await session.send_prompt()
                    continue

                cmd = parse(text)
                if cmd.verb == "pass":
                    await session.send_prompt()
                    continue

                handler = self.command_registry.get(cmd.verb, self.command_registry.get("unknown"))
                await handler(self._make_context(session), cmd)

                if session.running:
                    await session.send_prompt()

        except Exception as exc:
            print(f"Client {session.username} disconnected: {exc}")
        finally:
            await self.handle_disconnect(session)

    async def _login_flow(self, websocket) -> Session:
        from .locales import get as loc

        await websocket.send('{"type":"display","payload":"Multiplayer Mode"}')
        await websocket.send('{"type":"prompt","payload":"Username: "}')

        try:
            username_msg = await websocket.recv()
        except Exception:
            return None

        username = username_msg.strip().lower()
        if not username:
            await websocket.send('{"type":"display","payload":"Username cannot be empty."}')
            return None

        if get_account(username):
            await websocket.send('{"type":"prompt","payload":"Password: "}')
            try:
                password_msg = await websocket.recv()
            except Exception:
                return None

            password = password_msg.strip()
            account = verify_password(username, password)

            if not account:
                await websocket.send('{"type":"display","payload":"Invalid password."}')
                return None

            await websocket.send('{"type":"display","payload":"Character slot (or \\"new\\"): "}')
            await websocket.send('{"type":"prompt","payload":"character> "}')

            try:
                slot_msg = await websocket.recv()
            except Exception:
                return None

            slot_name = slot_msg.strip().lower()

            if slot_name == "new" or not load_player(slot_name, self.storylet_manager):
                player = self._create_new_player(username)
                slot_name = username
                add_character_to_account(username, slot_name)
            else:
                player = load_player(slot_name, self.storylet_manager)

        else:
            await websocket.send('{"type":"display","payload":"New account. Set a password."}')
            await websocket.send('{"type":"prompt","payload":"Password: "}')

            try:
                password_msg = await websocket.recv()
            except Exception:
                return None

            password = password_msg.strip()
            if len(password) < 4:
                await websocket.send('{"type":"display","payload":"Password must be at least 4 characters."}')
                return None

            try:
                create_account(username, password)
            except Exception as e:
                await websocket.send(f'{{"type":"display","payload":"Error creating account: {e}"}}')
                return None

            player = self._create_new_player(username)
            slot_name = username

        session = Session(
            websocket=websocket,
            username=username,
            player=player,
            running=True,
            seconds_since_autosave=0,
            seconds_since_state_broadcast=0,
        )

        await websocket.send(f'{{"type":"display","payload":"Connected as {username}. Welcome to occupied Shanghai."}}')
        await websocket.send(f'{{"type":"display","payload":"You are {player.name}. {player.flags}"}}')
        await websocket.send(f'{{"type":"display","payload":"Use \\"help\\" for commands, \\"look\\" to see your surroundings."}}')

        return session

    def _create_new_player(self, username: str):
        from .player_data import PlayerData
        from .trust import default_trust
        from .commands import _generate_background, _apply_inherited_trust

        background = _generate_background()

        player = PlayerData()
        player.username = username
        player.name = background.get("name", "Newcomer")
        player.current_room = "bund_dawn"
        player.inventory = []
        player.trust = _apply_inherited_trust(None, background.get("trust_adjustments", {}))
        player.disguise = ""
        player.stealth_skill = 55
        player.hidden = False
        player.flags = []
        player.world_events = []
        player.newspapers = []
        player.health = 100
        player.hunger = 100
        player.morale = 80
        player.arrested = False
        player.relationships = {}
        player.storylet_history = []
        player.active_storylet = None
        player.tailing_state = None
        player.planted_evidence = []
        player.last_curfew_penalty_day = 0
        player.last_newspaper_day = 0

        save_player(player)
        return player

    def _make_context(self, session: Session) -> CommandContext:
        from .commands import CommandContext
        room = self.shared.world.get_room(session.player.current_room)
        return CommandContext(
            session=session,
            shared=self.shared,
            session_manager=self,
            disguises=self.disguises,
            stealth=self.stealth,
            storylet_manager=self.storylet_manager,
            room=room,
        )

    async def _send_room_players(self, session: Session):
        room = self.shared.world.get_room(session.player.current_room)
        if not room:
            return

        players = [s.player.name for s in self.get_players_in_room(room.id) if s.username != session.username]
        await session.send_room_players(players)

    def get_players_in_room(self, room_id: str) -> List[Session]:
        return [s for s in self.sessions.values() if s.player.current_room == room_id]

    async def broadcast_to_room(self, room_id: str, message: str, exclude_username: str = ""):
        for session in self.get_players_in_room(room_id):
            if session.username != exclude_username:
                try:
                    await session.send_display(message)
                except Exception:
                    pass

    async def handle_disconnect(self, session: Session):
        if session.username in self.sessions:
            del self.sessions[session.username]

        room = self.shared.world.get_room(session.player.current_room)
        if room and hasattr(room, "players"):
            if session.username in room.players:
                room.players.remove(session.username)

        save_player(session.player)

        if session.running:
            room = self.shared.world.get_room(session.player.current_room)
            safe_logout = room and room.indoors and "safe_logout" in room.tags

            if not safe_logout:
                from .commands import check_death_conditions, handle_player_death
                is_dead, death_message = check_death_conditions(self._make_context(session))
                if is_dead:
                    await handle_player_death(self._make_context(session), death_message)

        session.running = False
        try:
            await session.websocket.close()
        except Exception:
            pass

    def get_session_by_username(self, username: str) -> Session:
        return self.sessions.get(username)
