import asyncio
import json
from typing import Dict, List

from .world import World, load_items, load_rooms, Item, Room
from .parser import parse, Command


def _find_item_by_name(name: str, items: List[Item]) -> Item | None:
    name = name.lower().strip()
    for item in items:
        if item.name.lower() == name:
            return item
    for item in items:
        if name in item.name.lower():
            return item
    return None


class PlayerSession:
    def __init__(self, websocket):
        self.websocket = websocket
        self.location = "bund_dawn"
        self.inventory: List[Item] = []
        self.running = True

    async def send(self, text: str):
        await self.websocket.send(json.dumps({"type": "display", "payload": text}))

    async def send_prompt(self):
        await self.websocket.send(json.dumps({"type": "prompt", "payload": "> "}))


class GameServer:
    def __init__(self):
        self.world = World()
        self.sessions: Dict[str, PlayerSession] = {}

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
            "  HELP           - Show this message\n"
            "  QUIT           - Leave the game\n"
            "\n"
            "You can also type a direction alone, e.g. 'north' or 'n'.\n"
        )
        await session.send(help_text)

    async def _cmd_talk_to(self, session: PlayerSession, cmd: Command):
        await session.send("Talking has not been implemented.\n")

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

    async def _cmd_wait(self, session: PlayerSession, cmd: Command):
        await session.send("Using items has not been implemented yet.\n")

    async def _cmd_sleep(self, session: PlayerSession, cmd: Command):
        await session.send("Sleeping has not been implemented yet.\n")
    
    async def _cmd_journal(self, session: PlayerSession, cmd: Command):
        await session.send("Your Journal is empty.\n")

    async def _cmd_unknown(self, session: PlayerSession, cmd: Command):
        await session.send(f"I don't understand '{cmd.raw}'. Try HELP.\n")