import asyncio
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import websockets

from server.config import get_setting
from server.game_server import GameServer


class ClientHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.join(os.path.dirname(__file__), "client"), **kwargs)

    def log_message(self, format, *args):
        pass # Supress noise for now so i can troubleshoot it easie     r later, need to remove soon after i get a MVP done


def start_http_server(host: str = "127.0.0.1", port: int = 8080):
    server= ThreadingHTTPServer((host, port), ClientHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"HTTP Client served at http://{host}:{port}/")
    return server


async def start_websocket_server(host: str = "127.0.0.1", port: int = 8765):
    game = GameServer()
    asyncio.create_task(game.tick_loop())
    stop = asyncio.Future()

    async with websockets.serve(game.session_manager.handle_client, host, port):
        print(f"Game server listening on ws://{host}:{port}/")
        print("Open browser at http://{}:{}/".format(host, 8080))
        print("Press Ctrl+C to stop.\n")
        await stop


def main():
    http_host = get_setting("HTTP_HOST", "127.0.0.1") #TODO: FALLBACK!!!!!!!!!!!!!!!!!!!!
    http_port = int(get_setting("HTTP_PORT", "8080"))
    ws_host = get_setting("WS_HOST", "127.0.0.1")
    ws_port = int(get_setting("WS_PORT", "8765"))

    start_http_server(http_host, http_port)
    try: 
        asyncio.run(start_websocket_server(ws_host, ws_port))
    except KeyboardInterrupt:
        print("Shutting down server")
        sys.exit(0)


if __name__ == "__main__":
    main()
    