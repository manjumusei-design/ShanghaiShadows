import asyncio
import json
from typing import Dict, List

from .world import World, load_items, load_rooms, Item, Room
from .parser import parse, Command
from .time_system import GameTime, EventScheduler, time_str
from .npc import get_dialogue


FACTIONS = ["resistance", "kampeitai", "green_gang", "french_concession", "british_concession", "civilian"]

def _find_item_by_name(name: str, items: List[Item]) -> Item | None:
    name = name.lower().strip()
    for item in items:
        if item.name.lower() == name:
            return item
    for item in items:
        if name in item.name.lower():
            return item
    return None



def _find_npc_by_name(name: str, npc_ids: List[str], npcs: Dict[str, any]) -> str | None:
    name = name.lower().strip()
    for npc_id in npc_ids:
        npc = npcs.get(npc_id)
        if npc and name in npc.name.lower():
            return npc_id
    return None


class PlayerSession:
    def __init__(self, websocket):
        self.websocket = websocket
        self.location = "bund_dawn"
        self.inventory: List[Item] = []
        self.running = True
        self. trust = {f: 50 for f in FACTIONS}

    async def send(self, text: str):
        await self.websocket.send(json.dumps({"type": "display", "payload": text}))

    async def send_prompt(self):
        await self.websocket.send(json.dumps({"type": "prompt", "payload": "> "}))


class GameServer:
    def __init__(self):
        self.world = World()
        self.game_time = GameTime()
        self.scheduler = EventScheduler()
        self.scheduler.load_from_yaml("server/data/events.yaml")
        self.sessions: Dict[str, PlayerSession] = {}
        
    def _broadcast(self, text: str):
        for session in list(self.sessions.values()):
            asyncio.create_task(session.send(text + "\n")
                                
    def _move_npcs_if_hour_changed(self):
        current_hour = self.game_time.minute // 60
        if self.game_time.minute % 60 != 0:
            return
        for npc_id, npc in self.world.npcs.items():
            if current_hour in npc.schedule:
                new_room_id = npc.schedule[current_hour]
                old_room_id = self.world.npc_locations.get(npc_id)
                if old_room_id != new_room_id:
                    if old_room_id and old_room_id in self.world.rooms:
                        if npc_id in self.world.rooms[old_room_id].npcs:
                            self.world.rooms[old_room_id].npcs.remove(npc_id)
                    self.world.rooms[new_room_id].npcs.append(npc_id)
                    self.world.npc_locations[npc_id] = new_room_id

    async def tick_loop(self):
        while True:
            await asyncio.sleep(1)
            self.game_time.minute += 1
            if self.game_time.minute >= 1440:
                self.game_time.minute = 0
                self.game_time.day += 1
            self.scheduler.process(self.game_time, self._broadcast)
            self._move_npcs_if_hour_changed()

    async def handle_client(self, websocket):
        session = PlayerSession(websocket)
        client_id = f"{websocket.remote_address}"
        self.sessions[client_id] = session

        await self._send_welcome(session)
        await self._cmd_look(session, Command(verb="look", raw="look"))
        await session.send_prompt()
        
        try:
            async for message in websocket:
                text = message.strip()
                if not text:
                    await session.send_prompt()
                    continue

                cmd = parse(text)
                if cmd.verb == "pass":
                    await session.send_prompt()
                    continue

                handler_name = f"_cmd_{cmd.verb.replace(' ', '_')}"
                handler = getattr(self, handler_name, self._cmd_unknown)
                await handler(session, cmd)

                if session.running:
                    await session.send_prompt()
        except Exception as exc:
            print(f"Client {client_id} disconnected: {exc}")
        finally:
            self.sessions.pop(client_id, None)

    async def _send_welcome(self, session: PlayerSession):
        welcome = (
            "Shanghai, 1938. The city bleeds under occupation.\n"
            "Type HELP for available commands.\n"
        )
        await session.send(welcome)

    async def _cmd_look(self, session: PlayerSession, cmd: Command):
        text = self.world.format_room(session.location)
        await session.send(text + "\n")

    async def _cmd_go(self, session: PlayerSession, cmd: Command):
        direction = cmd.direct_obj
        if not direction:
            await session.send("Go where?\n")
            return

        room = self.world.get_room(session.location)
        if direction in room.exits:
            session.location = room.exits[direction]
            await self._cmd_look(session, cmd)
        else:
            await session.send("You can't go that way.\n")

    async def _cmd_take(self, session: PlayerSession, cmd: Command):
        item_name = cmd.direct_obj
        if not item_name:
            await session.send("Take what?\n")
            return

        room = self.world.get_room(session.location)
        item = _find_item_by_name(item_name, room.items)
        if not item:
            await session.send("You don't see that here.\n")
            return
        if not item.takeable:
            await session.send("You can't take that.\n")
            return
        room.items.remove(item)
        session.inventory.append(item)
        await session.send(f"You take {item.name}.\n")

    async def _cmd_drop(self, session: PlayerSession, cmd: Command):
        item_name = cmd.direct_obj
        if not item_name:
            await session.send("Drop what?\n")
            return
        item = _find_item_by_name(item_name, session.inventory)
        if not item:
            await session.send("You don't have that.\n")
            return
        session.inventory.remove(item)
        room = self.world.get_room(session.location)
        room.items.append(item)
        await session.send(f"You drop {item.name}.\n")

    async def _cmd_inventory(self, session: PlayerSession, cmd: Command):
        if not session.inventory:
            await session.send("You are empty-handed.\n")
            return
        text = "You are carrying:\n"
        for item in session.inventory:
            text += f"  {item.name}\n"
        await session.send(text)

    asyn def _cmd_wait(self, session: PlayerSession, cmd: Command):
        minutes_str = cmd.direct_obj
        if not minutes_str: 
            await session.send("Wait for how long?\n")
            return

        try:
            minutes = int(minutes_str)
        except ValueError:
            await session.send("You must wait a number of minutes.\n")
            return
        
        for _ in range(minutes):
            self.game_time.minute += 1
            if self.game_time.minute >= 1440:
                self.game_time.minute = 0
                self.game_time.day += 1
            self.scheduler.process(self.game_time, self._broadcast)
            self._move_npcs_if_hour_changed()

        await session.send(f"You wait {minutes} minutes. It is now {time_str(self.game_time)}.\n")

    async def _cmd_talk_to(self, session: PlayerSession, cmd: Command):
        npc_name = cmd.direct_obj
        if not npc_name:
            await session.send("Talk to whom?\n")
            return
        room = self.world.get_room(session.location)
        npc_id = _find_npc_by_name(npc_name, room.npcs, self.world.npcs)
        if not npc_id:
            await session.send(" They aren't here.\n")
            return
        npc = self.world.npcs[npc_id]
        line = get_dialogue(npc, session.trust)
        await session.send(f'{npc.name} says, "{line}"\n')

    async def _cmd_quit(self, session: PlayerSession, cmd: Command):
        await session.send("Goodbye.\n")
        session.running = False
        await session.websocket.close()

    async def _cmd_help(self, session: PlayerSession, cmd: Command):
        help_text = (
            "\nAvailable commands:\n"
            "  LOOK           - Examine your surroundings\n"
            "  GO <direction> - Move (north, south, east, west)\n"
            "  TAKE <item>    - Pick up an item\n"
            "  DROP <item>    - Drop an item\n"
            "  INVENTORY (I)  - Check your belongings\n"
            "  WAIT <minutes> - Pass time\n"
            "  TALK TO <npc>  - Speak with someone\n"
            "  HELP           - Show this message\n"
            "  QUIT           - Leave the game\n"
            "\n"
            "You can also type a direction alone, e.g. 'north' or 'n'.\n"
        )
        await session.send(help_text)

    async def _cmd_give(self, session: PlayerSession, cmd: Command):
        await session.send("Giving has not been implemented.\n")

    async def _cmd_ask(self, session: PlayerSession, cmd: Command):
        await session.send("Asking has not been implemented.\n")
    
    async def _cmd_ask_about(self, session: PlayerSession, cmd: Command):
        await session.send("Asking has not been implemented.\n")
    
    async def _cmd_whisper(self,session: PlayerSession, cmd: Command):
        await session.send("Whispering has not been implemented.\n")

    async def _cmd_plant(self, session: PlayerSession, cmd: Command):
        await session.send("Planting has not been implemented.\n")
    
    async def _cmd_disguise_as(self, session: PlayerSession, cmd: Command):
        await session.send("Disguising has not been implemented.\n")
    
    async def _cmd_hide(self, session: PlayerSession, cmd: Command):
        await session.send("Disguises have not been implemented yet.\n")

    async def _cmd_read(self, session: PlayerSession, cmd: Command):
        await session.send("Reading has not been implemented yet.\n")

    async def _cmd_use(self, session: PlayerSession, cmd: Command):
        await session.send("Using items has not been implemented yet.\n")

    async def _cmd_sleep(self, session: PlayerSession, cmd: Command):
        await session.send("Sleeping has not been implemented yet.\n")
    
    async def _cmd_journal(self, session: PlayerSession, cmd: Command):
        await session.send("Your Journal is empty.\n")

    async def _cmd_unknown(self, session: PlayerSession, cmd: Command):
        await session.send(f"I don't understand '{cmd.raw}'. Try HELP.\n")