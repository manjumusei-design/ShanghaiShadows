import asyncio
import json
from typing import TYPE_CHECKING, Callable, Dict, List

from .action_result import CommandOutcome, failure

_TUTORIAL_FAMILY_TEMPLATES = {
    "talk_to": "To begin a conversation, use TALK TO (name).",
    "ask_about": "To ask a question, use ASK (name) ABOUT (topic).",
    "buy_from": "To buy, use BUY FROM (name).",
    "eat": "To eat, use EAT (food).",
    "go": "To move, use GO (direction).",
    "hide": "To hide, use HIDE.",
    "inventory": "To see what you carry, use INVENTORY.",
    "status": "To see your condition, use STATUS.",
    "search": "To look closely, use SEARCH (detail).",
    "take_item": "To pick something up, use TAKE (item).",
    "take_from": "To take from a container, use TAKE FROM (container).",
    "examine": "To inspect something, use EXAMINE (item).",
    "wear": "To wear armour, use WEAR (item).",
    "equip": "To ready a weapon, use EQUIP (item).",
    "attack": "To fight, use ATTACK (name).",
    "assess": "To size someone up, use ASSESS (name).",
    "disguise_as": "To change appearance, use DISGUISE AS (disguise).",
    "remove_disguise": "To drop the disguise, use REMOVE DISGUISE.",
    "tail": "To follow someone, use TAIL (name).",
    "give": "To hand something over, use GIVE <item> TO <person>.",
    "claim": "To claim shelter, use CLAIM.",
    "journal": "To read your journal, use JOURNAL.",
    "rumors": "To hear what the streets carry, use RUMORS.",
    "wanted": "To see how much notice you have drawn, use WANTED.",
    "trust": "To see who remembers you, use TRUST.",
    "look": "To view the room again, use LOOK.",
}

_ZONE_SILHOUETTE_SLOTS = {
    "bund": (0, 0),
    "old_city": (1, 0),
    "hongkou": (2, 0),
    "french": (0, 1),
    "nanjing_rd": (1, 1),
    "zhabei": (2, 1),
    "yangpu": (0, 2),
    "xujiahui": (1, 2),
    "refugee_entry": (2, 2),
    "orientation": (3, 2),
}

_DISTRICT_ZONE_FALLBACK = {
    "commercial": "bund",
    "docks": "yangpu",
    "residential": "hongkou",
    "warehouse": "zhabei",
    "church": "french",
    "school": "french",
    "ccp_base": "old_city",
    "gmd_office": "french",
    "hidden_shanghai": "old_city",
}

_ZONE_SILHOUETTE_FALLBACK_ZONE = "bund"

from .auth import (
    create_account,
    create_living_slot,
    get_account,
    get_character_slot,
    get_living_character_slot,
    list_character_slots,
    load_authenticated_slot,
    verify_password,
)
from .commands import (
    CommandContext,
    apply_storylet_effects,
    build_command_registry,
    build_completions,
    _display_storylet,
    parse,
    resolve_storylet_choice,
)
from .parser import Command
from .save_manager import load_world_state, save_player
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
        self._shared_liberation_in_progress = False
        self._shared_liberation_pending_reset = False

    async def handle_client(self, websocket):
        session = await self._login_flow(websocket)
        if not session:
            try:
                await websocket.close()
            except Exception:
                pass
            return

        self.sessions[session.username] = session
        await session.clear_patrol_warning(force=True)

        room = self.shared.world.get_room(session.player.current_room)
        if room and session.username not in room.npcs:
            if not hasattr(room, "players"):
                room.players = []
            if session.username not in room.players:
                room.players.append(session.username)

        tutorial_card_shown = await self._begin_tutorial_if_new(session)
        if not getattr(session.player, "tutorial_choice_pending", False):
            await self._send_room_players(session)
            await self._send_map_data(session)
            if getattr(session.player, "in_tutorial", False):
                from .tutorial import _emit_stage_entry
                ctx = self._make_context(session)
                await _emit_stage_entry(ctx, replay_only=True, force_immediate=True)
            await session.send_prompt()
        elif not tutorial_card_shown:
            await session.send_prompt()
        try:
            async for message in websocket:
                text = message.strip()
                if not text:
                    await session.send_prompt()
                    continue

                cmd = parse(text)
                room_storylet = self.shared.active_room_storylets.get(session.player.current_room)
                if (
                    not session.player.active_storylets
                    and
                    room_storylet
                    and not room_storylet.get("resolved", False)
                    and room_storylet.get("owner_username") != session.username
                    and text.strip().isdigit()
                ):
                    await session.send_display(
                        f"{room_storylet['owner_username']} is deciding how to respond.",
                        msg_type="event",
                    )
                    await session.send_prompt()
                    continue
                if not session.player.active_storylets and cmd.verb == "unknown" and text.strip().isdigit():
                    await session.send_display("\nThere is no active choice to select.\n")
                    await session.send_prompt()
                    continue
                if cmd.verb == "pass":
                    await session.send_prompt()
                    continue

                if (getattr(session.player, 'in_tutorial', False) and cmd.verb == "unknown"
                        and not session.player.active_storylets
                        and not text.strip().startswith("{")):
                    from .tutorial import (STAGE_ACTIONS, hint_family_for,
                                           normalize_to_actionable_stage)
                    stage = normalize_to_actionable_stage(session.player)
                    action = STAGE_ACTIONS.get(stage, {})
                    hint = action.get("cmd_hint", "")
                    family = hint_family_for(action)
                    template = _TUTORIAL_FAMILY_TEMPLATES.get(family, "")
                    if template:
                        await session.send_display(template)
                    if hint:
                        await session.send_display(f"Try: {hint}")
                        from .tutorial import _send_tutorial_hint
                        ctx = self._make_context(session)
                        await _send_tutorial_hint(ctx, stage, action, force_immediate=True)
                    await session.send_prompt()
                    continue

                await self.dispatch_command(session, text)

                if session.running:
                    ctx = self._make_context(session)
                    await session.send_completions(build_completions(ctx))
                    await session.send_prompt()

        except Exception as exc:
            print(f"Client {session.username} disconnected: {exc}")
        finally:
            await self.handle_disconnect(session)

    async def dispatch_command(self, session: Session, raw_input: str) -> CommandOutcome:
        from .commands import is_storylet_choice_input, resolve_storylet_choice
        from .popup_actions import handle_popup_action, parse_popup_action

        text = (raw_input or "").strip()
        if not text:
            return failure("empty_command")

        cmd = parse(text)
        if getattr(session.player, "custody_until", -1) >= 0 and cmd.verb not in ("status", "journal", "quit"):
            from .locales import get as loc
            await session.send_display(loc("custody.command_blocked"))
            return failure("custody_blocked")

        ctx = self._make_context(session)
        popup_action = parse_popup_action(text)
        active_storylets = getattr(session.player, "active_storylets", [])
        blocking_storylet = active_storylets and getattr(active_storylets[0], "blocking", True)
        if popup_action is not None and not blocking_storylet:
            return await handle_popup_action(self, session, popup_action)

        if active_storylets:
            first = active_storylets[0]
            if getattr(first, "blocking", True) or is_storylet_choice_input(first, text):
                if getattr(first, "blocking", True) and text.casefold() in ("help", "?", "h"):
                    result = await self.command_registry["help"](ctx, parse("help"))
                else:
                    result = await resolve_storylet_choice(ctx, text)
                if not isinstance(result, CommandOutcome):
                    return failure("handler_no_outcome")
                return await self._record_tutorial_outcome(session, text, result, ctx)

        handler = self.command_registry.get(cmd.verb, self.command_registry.get("unknown"))
        tutorial_room = session.player.current_room
        result = await handler(ctx, cmd)
        if not isinstance(result, CommandOutcome):
            return failure("handler_no_outcome")
        result = await self._record_tutorial_outcome(session, text, result, ctx, cmd, tutorial_room)
        from .commands import _record_terminal_recovery
        await _record_terminal_recovery(ctx, cmd, result)
        return result

    async def _record_tutorial_outcome(
        self,
        session: Session,
        raw_input: str,
        result: CommandOutcome,
        ctx,
        cmd=None,
        tutorial_room: str = "",
    ) -> CommandOutcome:
        if not result.succeeded or not getattr(session.player, "in_tutorial", False):
            return result
        from .tutorial import TutorialEvent, get_original_tutorial_room_id, record_tutorial_event

        event_data = result.data.get("tutorial_event") or {}
        verb = event_data.get("verb") or getattr(cmd, "verb", "choose")
        target = event_data.get("target", getattr(cmd, "direct_obj", "") or raw_input)
        indirect = event_data.get("indirect", getattr(cmd, "indirect_obj", "") or "")
        source_room = tutorial_room or session.player.current_room
        event_room = get_original_tutorial_room_id(
            getattr(session.player, "tutorial_instance_id", ""), source_room, self.shared
        )
        event = TutorialEvent(verb, target, indirect, event_room, succeeded=True)
        await record_tutorial_event(ctx, event)
        if event_data.get("verb") == "go" and getattr(session.player, "in_tutorial", False):
            await self._send_map_data(session)
        return result

    async def _login_flow(self, websocket) -> Session:
        await websocket.send(json.dumps({"type": "prompt", "payload": "Username: "}))
        try:
            username_msg = await websocket.recv()
        except Exception:
            return None
        username = username_msg.strip().lower()
        if username in ("1", "debug"):
            if username in self.sessions:
                await websocket.send('{"type":"display","payload":"That debug session is already connected."}')
                return None
            from .lifecycle import ephemeral_debug_slot
            slot = ephemeral_debug_slot()
            player = self._create_new_player("debug_player", save=False)
            player.ephemeral = True
            player.account_username = "debug"
            player.character_slot_id = slot.slot_id
            player.save_key = slot.save_key
            return Session(
                websocket=websocket,
                username=username,
                player=player,
                running=True,
                seconds_since_autosave=0,
                seconds_since_state_broadcast=0,
                audio_enabled=True,
                slot_id=slot.slot_id,
                save_key=slot.save_key,
                ephemeral=True,
            )
        if not username:
            await websocket.send('{"type":"display","payload":"Username cannot be empty."}')
            return None
        if get_account(username):
            await websocket.send('{"type":"prompt","payload":"Password: "}')
            try:
                password_msg = await websocket.recv()
            except Exception:
                return None
            account = verify_password(username, password_msg.strip())
            if not account:
                await websocket.send('{"type":"display","payload":"Invalid password."}')
                return None
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
            except Exception as exc:
                await websocket.send(json.dumps({"type": "display", "payload": f"Error creating account: {exc}"}))
                return None
        if username in self.sessions:
            await websocket.send('{"type":"display","payload":"That account is already connected."}')
            return None
        slots = list_character_slots(username, self.storylet_manager)
        living = get_living_character_slot(username, self.storylet_manager)
        listing = "\n".join(f"{slot.slot_number}. {slot.display_name} [{slot.status.upper()}]" for slot in slots)
        await websocket.send(json.dumps({"type": "display", "payload": listing or "No character slots."}))
        await websocket.send(json.dumps({"type": "prompt", "payload": "Character number or NEW: "}))
        while True:
            try:
                selection = (await websocket.recv()).strip()
            except Exception:
                return None
            if not selection:
                return None
            if selection.casefold() == "new":
                if living is not None:
                    await websocket.send('{"type":"display","payload":"NEW is unavailable while a living character exists."}')
                    continue
                player = self._create_new_player(username, save=False)
                try:
                    slot = create_living_slot(username, player, player.name)
                except Exception as exc:
                    await websocket.send(json.dumps({"type": "display", "payload": f"Unable to create character: {exc}"}))
                    return None
                break
            if selection.isdecimal() and selection:
                slot = get_character_slot(username, int(selection), self.storylet_manager)
                if slot is None:
                    await websocket.send('{"type":"display","payload":"That character number is not available."}')
                    continue
                if slot.status != "living":
                    await websocket.send('{"type":"display","payload":"That character slot cannot enter gameplay."}')
                    continue
                player, slot = load_authenticated_slot(username, slot.slot_number, self.storylet_manager)
                if player is None:
                    await websocket.send('{"type":"display","payload":"That character save is unavailable."}')
                    continue
                from .rumors import materialize_player_rumor_records
                materialize_player_rumor_records(self.shared, player)
                break
            await websocket.send('{"type":"display","payload":"Enter a character number or NEW."}')
        session = Session(
            websocket=websocket,
            username=username,
            player=player,
            running=True,
            seconds_since_autosave=0,
            seconds_since_state_broadcast=0,
            audio_enabled=getattr(player, 'audio_enabled', True),
            slot_id=slot.slot_id,
            save_key=slot.save_key,
        )
        from .storylet_cancellation import recover_cancellations
        try:
            await recover_cancellations(self._make_context(session))
        except Exception:
            pass
        await websocket.send(json.dumps({"type": "display", "payload": f"Connected as {username}. Welcome to occupied Shanghai."}))
        await websocket.send(json.dumps({"type": "display", "payload": f"You are {player.name}."}))
        return session

    def _create_new_player(self, username: str, save: bool = True):
        from .player_data import PlayerData
        from .trust import default_trust
        from .commands import _generate_character_name, _reset_player_defaults
        from .auth import resolve_spawn_room

        spawn_room = resolve_spawn_room(username) or "bund_dawn"
        if not self.shared.world.get_room(spawn_room):
            spawn_room = "bund_dawn"

        player = PlayerData()
        player.username = username
        _reset_player_defaults(player, _generate_character_name(), spawn_room)
        player.trust = default_trust()
        player.tutorial_choice_pending = True

        if save:
            save_player(player, save_key=getattr(player, "save_key", "") or None)
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

    async def _send_map_data(self, session: Session):
        import logging
        logger = logging.getLogger(__name__)

        visited = set(session.player.map_revealed)
        layout_coords = self.shared.room_layout_coords

        in_tutorial = session.player.in_tutorial
        tutorial_complete = "tutorial_complete" in session.player.flags

        current_room = session.player.current_room
        original_current_room = current_room

        if in_tutorial and getattr(session.player, "tutorial_instance_id", ""):
            from .tutorial import get_original_tutorial_room_id
            instance_id = session.player.tutorial_instance_id
            original_current_room = get_original_tutorial_room_id(instance_id, current_room, self.shared)
            visited = {
                get_original_tutorial_room_id(instance_id, room_id, self.shared)
                for room_id in visited
            }

        tutorial_stub_direction = None
        if in_tutorial:
            from .tutorial import STAGE_ACTIONS
            stage = getattr(session.player, "tutorial_stage", 0)
            for idx in range(stage, len(STAGE_ACTIONS)):
                action = STAGE_ACTIONS.get(idx)
                if action is None or action.get("verb") == "none":
                    continue
                if action.get("verb") == "go":
                    if action.get("room_id") == original_current_room:
                        tutorial_stub_direction = action.get("target", "")
                        break

        rooms_data = {}
        filtered_out = 0
        zone_silhouettes = {}
        for room_id, (x, y) in layout_coords.items():
            if room_id.startswith("p_") and len(room_id.split("_", 2)) >= 3:
                continue

            if in_tutorial:
                if not (room_id.startswith("refugee_entry_") or room_id.startswith("orientation_")):
                    filtered_out += 1
                    continue
            elif tutorial_complete:
                if room_id.startswith("refugee_entry_") or room_id.startswith("orientation_"):
                    filtered_out += 1
                    continue
            else:
                if room_id.startswith("refugee_entry_") or room_id.startswith("orientation_"):
                    filtered_out += 1
                    continue

            room = self.shared.world.get_room(room_id)
            if not room:
                logger.warning(f"Room not found while building map data: {room_id}")
                continue

            is_visited = room_id in visited

            zone = room.district
            for tag in room.tags:
                if tag in ("bund", "old_city", "hongkou", "french", "nanjing_rd",
                           "zhabei", "yangpu", "xujiahui",
                           "refugee_entry", "orientation"):
                    zone = tag
                    break

            if not is_visited:
                if zone not in _ZONE_SILHOUETTE_SLOTS:
                    zone = _DISTRICT_ZONE_FALLBACK.get(zone, _ZONE_SILHOUETTE_FALLBACK_ZONE)
                zone_silhouettes.setdefault(zone, zone)
                continue

            exits = {}
            for direction, dest_id in room.exits.items():
                if dest_id in visited:
                    dest_room = self.shared.world.get_room(dest_id)
                    exits[direction] = {
                        "key": dest_id,
                        "name": dest_room.title if dest_room else dest_id,
                    }
                elif (
                    tutorial_stub_direction is not None
                    and room_id == original_current_room
                    and direction == tutorial_stub_direction
                ):
                    exits[direction] = {"tutorial_route_stub": True}
                else:
                    exits[direction] = {"hidden": True}

            rooms_data[room_id] = {
                "key": room_id,
                "name": room.title,
                "x": x,
                "y": y,
                "z": 0,
                "exits": exits,
                "type": "indoor" if room.indoors else "road",
                "district": room.district,
                "zone": zone,
                "tags": list(room.tags),
                "visited": is_visited,
                "npc_count": len(room.npcs) if hasattr(room, 'npcs') else 0,
                "item_count": len(room.items) if hasattr(room, 'items') else 0,
                "safe": room.safe_room if hasattr(room, 'safe_room') else False,
            }

        for zone, district in zone_silhouettes.items():
            slot_x, slot_y = _ZONE_SILHOUETTE_SLOTS.get(zone, (0, 0))
            rooms_data[f"silhouette_{zone}"] = {
                "x": slot_x,
                "y": slot_y,
                "district": district,
                "zone": zone,
                "silhouette": True,
            }

        payload = {
            "rooms": rooms_data,
            "current_room": original_current_room
        }
        await session.send_map_data(payload)

    async def _begin_tutorial_if_new(self, session: Session) -> bool:
        player = session.player

        if not getattr(player, "tutorial_choice_pending", False):
            return False
        if player.in_tutorial:
            return False
        existing = next(
            (s for s in player.active_storylets if s.storylet_id == "tutorial_choice"),
            None,
        )
        if existing is not None:
            await _display_storylet(self._make_context(session), existing)
            return True
        if player.active_storylets:
            return False
            
        from .storylets import ActiveStorylet, StoryletOption
        from .commands import _display_storylet
        import time
        
        tutorial_choice = ActiveStorylet(
            storylet_id="tutorial_choice",
            narrative="Welcome to occupied Shanghai. Would you like to play through the tutorial to learn the basics?",
            options=[
                StoryletOption(
                    text="Yes, teach me the basics",
                    effects={"flag": "start_tutorial"},
                    followup_storylet="",
                    disabled=False,
                ),
                StoryletOption(
                    text="No, I know how to play",
                    effects={"flag": "skip_tutorial"},
                    followup_storylet="",
                    disabled=False,
                ),
            ],
            triggered_at=time.time(),
            timer_duration=0,
            timer_started_at=time.time(),
            blocking=True,
            owner_username=player.username,
            room_id=player.current_room,
        )
        player.active_storylets.append(tutorial_choice)
        ctx = self._make_context(session)
        await _display_storylet(ctx, tutorial_choice)
        return True

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
        from .commands import cleanup_storylet_speakers, finalize_committed_resolution
        from .lifecycle import close_session_cleanly
        from .storylet_cancellation import (
            RESOLUTION_HANDOFF_TIMEOUT,
            _await_resolution_completion,
            cancel_active_storylet_on_disconnect,
            handoff_claimed_cancellation,
        )
        from .tutorial import tutorial_blocks_world_events
        try:
            cleanup_storylet_speakers(self._make_context(session))
        except Exception:
            pass
        player = getattr(session, "player", None)
        if player is not None:
            ctx = self._make_context(session)
            to_cancel = []
            for active in list(getattr(player, "active_storylets", []) or []):
                if active.storylet_id == "tutorial_choice" or tutorial_blocks_world_events(player):
                    continue
                to_cancel.append(active)
            for sequence, active in enumerate(to_cancel):
                try:
                    await asyncio.wait_for(
                        _await_resolution_completion(active),
                        timeout=RESOLUTION_HANDOFF_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    if not getattr(active, "resolution_committed", False):
                        try:
                            await handoff_claimed_cancellation(ctx, active, sequence=sequence)
                        except Exception:
                            pass
                    continue
                try:
                    await cancel_active_storylet_on_disconnect(ctx, active, sequence=sequence)
                except Exception:
                    pass
            for active in list(getattr(player, "active_storylets", []) or []):
                if getattr(active, "resolution_committed", False) and not getattr(active, "resolved", False):
                    try:
                        await finalize_committed_resolution(ctx, active)
                    except Exception:
                        pass
            player.active_storylets = [
                active
                for active in getattr(player, "active_storylets", []) or []
                if not getattr(active, "resolved", False)
                and not (active.storylet_id == "tutorial_choice" or tutorial_blocks_world_events(player))
            ]
        if session.username in self.sessions:
            del self.sessions[session.username]

        room = self.shared.world.get_room(session.player.current_room)
        if room and hasattr(room, "players"):
            if session.username in room.players:
                room.players.remove(session.username)
        await close_session_cleanly(self, session)

    def _strip_to_rice(self, player) -> None:
        from .serialization import deserialize_item

        player.inventory = [deserialize_item({
            "id": "rice_bowl",
            "name": "a bowl of rice",
            "description": "Plain short grained rice from the Northeastern part of China, now overrun by the Imperial Japanese troops, highly prized for its fresh taste and nutrition which everyone needs more of nowadays.",
            "takeable": True,
            "food_value": 20,
            "morale_restore": 3,
        })]

        from .economy import set_wallet_fabi_value
        set_wallet_fabi_value(player, 50)
        player.money_military_yen = 0

        player.disguise = ""
        player.worn_armour_id = ""
        player.equipped_weapon_id = ""
        player.wanted_level = 0
        player.health = 100
        player.hunger = 60
        player.morale = 80

    def get_session_by_username(self, username: str) -> Session:
        return self.sessions.get(username)
