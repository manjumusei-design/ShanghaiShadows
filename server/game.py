import asyncio
import json
from typing import Dict
from .world import World, load_rooms
from .parser import Parser, Command  # now actually used

class PlayerSession:
    def __init__(self, websocket):
        self.websocket = websocket
        self.location = "bund_dawn"
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
        self.handlers = {
            "look": self.handle_look,
            "go": self.handle_go,
            "inventory": self.handle_inventory,
            "help": self.handle_help,
            "quit": self.handle_quit,
        }

    async def handle_client(self, websocket):
        session = PlayerSession(websocket)
        client_id = f"{websocket.remote_address}"
        self.sessions[client_id] = session
        await self._send_welcome(session)
        await self.handle_look(session, None)  # initial look
        await session.send_prompt()
        try: 
            async for message in websocket: 
                raw = message.strip()
                if not raw:
                    continue
                command = self.parser.parse(raw)
                handler = self.handlers.get(command.verb, self.handle_unknown)
                await handler(session, command)
                if session.running:
                    await session.send_prompt()
        except Exception as exc:
            print(f"Client {client_id} disconnected: {exc}")
        finally:
            self.sessions.pop(client_id, None)

        # C.Helper
    async def handle_look(self, session: PlayerSession, _):
        room = self.world.get_room(session.location)
        text = f"{room.title}\n{room.description}\n"
        if room.exits:
            text += f"Exits: {', '.join(room.exits.keys())}\n"
        await session.send(text)

    async def handle_go(self, session: PlayerSession, command: Command):
        direction = command.object
        if not direction:
            await session.send("Go where?\n")
            return
        
        room = self.world.get_room(session.location)
        if direction in room.exits:
            session.location = room.exits[direction]
            await self.handle_look(session, None)
        else:
            await session.send("You can't go that way.\n")

    async def handle_inventory(self, session: PlayerSession, _):
            await session.send("You are carrying nothing. The streets are dangerous enough empty-handed.\n")

    async def handle_help(self, session: PlayerSession, _):
        help_text = (
            "\nAvailable commands:\n"
            "  LOOK           - Examine your surroundings\n"
            "  GO <direction> - Move (north, south, east, west)\n"
            "  INVENTORY (I)  - Check your belongings\n"
            "  HELP           - Show this message\n"
            "  QUIT           - Leave the game\n"
            "\nYou can also type a direction alone, e.g. 'north' or 'n'.\n"
        )
        await session.send(help_text)

    async def handle_quit(self, session: PlayerSession, _):
        await session.send("Farewell until we meet again.\n")
        session.running = False
        await session.websocket.close()

    async def handle_unknown(self, session: PlayerSession,_):
        await session.send("Huh? (Type HELP for a list of commands!.)\n")

        #Helper func

    async def _send_welcome(self, session: PlayerSession):
        welcome = (
            "Shanghai Shadows\n\n"
            "Shanghai, 1938. The city bleeds under the brutal Japanese occupation.\n"
            "Type HELP for available commands.\n"
        )
        await session.send(welcome)
