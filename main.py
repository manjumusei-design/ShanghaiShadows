import asyncio
import logging
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import websockets

from server.config import get_setting
from server.game_server import GameServer

_sessions_lock = threading.Lock()

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('main')


import json as _json

class ClientHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.join(os.path.dirname(__file__), "client"), **kwargs)

    def log_message(self, format, *args):
        pass 

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')


    def do_GET(self):
        if self.path == "/health":
            try:
                from server.game_server import GameServer
                with _sessions_lock:
                    game = getattr(GameServer, '_last_instance', None)
                    player_count = len(game.session_manager.sessions) if game else 0
                status = {
                    "status": "ok",
                    "players": player_count,
                }
                body = _json.dumps(status).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                body = _json.dumps({"status": "error", "message": str(exc)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            return
        super().do_GET()


def start_http_server(host: str = "127.0.0.1", port: int = 8080):
    server= ThreadingHTTPServer((host, port), ClientHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"HTTP Client served at http://{host}:{port}/")
    return server


async def start_websocket_server(host: str = "127.0.0.1", port: int = 8765):
    game = GameServer()
    GameServer._last_instance = game  #graceful store
    asyncio.create_task(game.tick_loop())
    stop = asyncio.Future()

    async with websockets.serve(game.session_manager.handle_client, host, port):
        print(f"Game server listening on ws://{host}:{port}/")
        print("Open browser at http://{}:{}/".format(host, 8080))
        print("Press Ctrl+C to stop.\n")
        await stop


def main():
    http_host = get_setting("HTTP_HOST", "127.0.0.1") 
    http_port = int(get_setting("HTTP_PORT", "8080"))
    ws_host = get_setting("WS_HOST", "127.0.0.1")
    ws_port = int(get_setting("WS_PORT", "8765"))

    import signal
    import atexit

    def _perform_shutdown_save():
        try:
            from server.save_manager import save_world_state, save_player
            game = getattr(GameServer, '_last_instance', None)
            if game:
                for session in list(game.session_manager.sessions.values()):
                    save_player(session.player)
                save_world_state(game.shared)
                print("World and players saved.")
        except Exception as e:
            print(f"Shutdown save error: {e}")

    signal.signal(signal.SIGTERM, lambda s, f: (_perform_shutdown_save(), sys.exit(0)))
    atexit.register(_perform_shutdown_save)

    start_http_server(http_host, http_port)
    try:
        asyncio.run(start_websocket_server(ws_host, ws_port))
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as exc:
        print(f"\nFatal error: {exc}")
    finally:
        print("Saving world state before exit...")
        _perform_shutdown_save()
        sys.exit(0)


if __name__ == "__main__":
    main()