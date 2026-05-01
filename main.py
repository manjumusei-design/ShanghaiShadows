import asyncio
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import websockets

from server.game import GameServer
class ClientHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.join(os.path.dirname(__file__), "client"), **kwargs)

    def log_message(self, format, *args):
        pass # Supress noise for now so i can troubleshoot it easier later


def start_http_server(host: str = "127.0.0.1", port: int = 8080):
    server= ThreadingHTTPServer((host, port), ClientHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[HTTP] Client served at http://{host}:{port}/")
    return server


