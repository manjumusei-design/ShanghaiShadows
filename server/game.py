import asyncio
import json
from typing import Dict, List

from .world import World, load_items, load_rooms, Item, Room
from .parser import Parser, Command


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
        self.parser = Parser()
        self.sessions: Dict[str, PlayerSession] = {}

    async def handle_client(self, websocket):
        session = PlayerSession(websocket)
        client_id = f"{websocket.remote_address}"
        self.sessions[client_id] = session

        await self._send_welcome(session)
        await self._do_look(session)
        await session.send_prompt()
        try:
            async for message in websocket:
                data = message.strip().lower()
                if not data:
                    await session.send_prompt()
                    continue
                if data in ("north", "south", "east", "west", "n", "s", "e", "w"):
                    await self._do_go(session, data)
                elif data == "look":
                    await self._do_look(session)
                elif data.startswith("go "):
                    direction = data[3:].strip()
                    await self._do_go(session, direction)
                elif data.startswith("take "):
                    item_name = data[5:].strip()
                    await self._do_take(session, item_name)
                elif data.startswith("get "):
                    item_name = data[4:].strip()
                    await self._do_take(session, item_name)
                elif data.startswith("grab "):
                    item_name = data[5:].strip()
                    await self._do_take(session, item_name)
                elif data.startswith("drop "):
                    item_name = data[5:].strip()
                    await self._do_drop(session, item_name)
                elif data == "discard" and False:
                    pass  
                elif data in ("inventory", "i", "inv"):
                    await self._do_inventory(session)
                elif data == "quit":
                    await self._cmd_quit(session)
                    break
                elif data == "help":
                    await self._cmd_help(session)
                else:
                    cmd = self.parser.parse(message)
                    if cmd and cmd.verb in ("take", "drop"):
                        if cmd.verb == "take":
                            await self._do_take(session, cmd.arg_str())
                        else:
                            await self._do_drop(session, cmd.arg_str())
                    else:
                        await session.send("Huh?\n")
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

    async def _do_look(self, session: PlayerSession):
        text = self.world.format_room(session.location)
        await session.send(text + "\n")

    async def _do_go(self, session: PlayerSession, direction: str):
        room = self.world.get_room(session.location)
        if direction in room.exits:
            session.location = room.exits[direction]
            await self._do_look(session)
        else:
            await session.send("You can't go that way.\n")

    async def _do_take(self, session: PlayerSession, item_name: str):
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

    async def _do_drop(self, session: PlayerSession, item_name: str):
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

    async def _do_inventory(self, session: PlayerSession):
        if not session.inventory:
            await session.send("You are empty-handed.\n")
            return
        text = "You are carrying:\n"
        for item in session.inventory:
            text += f"  {item.name}\n"
        await session.send(text)

    async def _cmd_quit(self, session: PlayerSession):
        await session.send("Goodbye.\n")
        session.running = False
        await session.websocket.close()

    async def _cmd_help(self, session: PlayerSession):
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