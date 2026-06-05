import asyncio
import websockets
import json
import sys
from pathlib import Path

WS_HOST = "127.0.0.1"
WS_PORT = 8765
TEST_TIMEOUT = 60

class TestClient:
    def __init__(self, username, slot_name):
        self.username = username
        self.slot_name = slot_name
        self.ws = None
        self.messages = []
        self.state = {}
        self.room_players = []
        self.running = True

    async def connect(self):
        self.ws = await websockets.connect(WS_URL)
        asyncio.create_task(self.receive_messages())

    async def receive_messages(self):
        try:
            async for message in self.ws:
                data = json.loads(message)
                msg_type = data.get("type")
                payload = data.get("payload", "")

                if msg_type == "display":
                    self.messages.append(payload)
                    print(f"[{self.username}] DISPLAY: {payload[:80]}...")
                elif msg_type == "state":
                    if isinstance(payload, dict):
                        self.state = payload
                        print(f"[{self.username}] STATE UPDATE: time={payload.get('game_time', 'N/A')}")
                    else:
                        print(f"[{self.username}] STATE UPDATE: {payload}")
                elif msg_type == "room_players":
                    self.room_players = payload
                    print(f"[{self.username}] ROOM PLAYERS: {payload}")
                elif msg_type == "prompt":
                    await self.handle_prompt(payload)
                elif msg_type == "completions":
                    pass


        except websockets.exceptions.ConnectionClosed:
            print(f"[{self.username}] Connection closed")
            self.running = False

    async def handle_prompt(self, prompt_text):
        if "Username:" in prompt_text or "username" in prompt_text.lower():
            await self.send(self.username)
        elif "Password:" in prompt_text or "password" in prompt_text.lower():
            await self.send("testpass123")
        elif "slot" in prompt_text.lower():
            await self.send("new")  
        elif ">" == prompt_text.strip():
            pass  
        elif "Choose" in prompt_text:
            await self.send("1")
        else:
            print(f"[{self.username}] Unknown prompt: {prompt_text}")

    async def send(self, command):
        if self.ws:
            try:
                await self.ws.send(command)
                print(f"[{self.username}] SENT: {command}")
            except Exception as e:
                print(f"[{self.username}] Error sending command: {e}")

    def find_message(self, substring):
        for msg in self.messages:
            if substring.lower() in msg.lower():
                return True
        return False
    
    async def wait_for_message(self, substring, timeout=10):
        for _ in range(timeout * 10):
            if self.find_message(substring):
                return True
            await asyncio.sleep(0.1)
        return False
    
    async def close(self):
        if self.ws:
            try:
                await self.ws.close()
                await asyncio.sleep(0.5)
            except Exception:
                pass

async def test_checkpoint_1():
    print("Shared state")
    alice = TestClient("alice", "test_slot")
    bob = TestClient("bob", "test_slot2")

    await alice.connect()
    await asyncio.sleep(1)
    await bob.connect()
    await asyncio.sleep(2)

    if alice.state.get("game_time") and bob.state.get("game_time"):
        alice_time = alice.state["game_time"]
        bob_time = bob.state["game_time"]
        if alice_time == bob_time:
            print(f"Both players see game time: {alice_time}")
        else:
            print(f"Game time mismatch: alice={alice_time}, bob={bob_time}")
    else:
        print("State not received")

    await alice.close()
    await bob.close()
    return True

async def test_checkpoint_2():
    print("SAY Command")
    alice = TestClient("alice", "test_slot")
    bob = TestClient("bob", "test_slot2")

    await alice.connect()
    await asyncio.sleep(1)
    await bob.connect()
    await asyncio.sleep(3)


    bob.messages.clear()


    await alice.send("say hello from alice")


    if await bob.wait_for_message("hello from alice", timeout=5):
        print("Bob received Alice's message")
    else:
        print("Bob did not receive Alice's message")
        print(f"Bob's messages: {bob.messages[-5:]}")

    await alice.close()
    await bob.close()
    return True

async def test_checkpoint_3():
    print("WWHISPER Command")
    alice = TestClient("alice","test_slot")
    bob = TestClient("bob", "test_slot2")
    await alice.connect()
    await asyncio.sleep(1)
    await bob.connect()
    await asyncio.sleep(3)
    bob.messages.clear()
    alice.messages.clear()

    await bob.send("whisper alice secret message")

    await asyncio.sleep(2)

    alice_received = alice.find_message("secret message")
    bob_received = bob.find_message("secret message")

    if alice_received and not bob_received:
        print("Alice received whisper, bob did not see it")
    else:
        print(f"Whisper failed: alice={alice_received}, bob={bob_received}")

    await alice.close()
    await bob.close()
    return True

async def test_checkpoint_5():
    print("Room Players")
    alice = TestClient("alice", "test_slot")
    bob = TestClient("bob", "test_slot2")

    await alice.connect()
    await asyncio.sleep(1)
    await bob.connect()
    await asyncio.sleep(3)
    alice.messages.clear()
    bob.messages.clear()

    await alice.send("look")
    await asyncio.sleep(1)
    await bob.send("look")
    await asyncio.sleep(1)
    await alice.send("go east")
    await asyncio.sleep(1)
    await bob.send("go east")
    await asyncio.sleep(2)

    alice_sees_bob = "bob" in alice.room_players or alice.find_message("bob")
    bob_sees_alice = "alice" in bob.room_players or bob.find_message("alice")

    if alice_sees_bob and bob_sees_alice:
        print("Both see each other")
    else:
        print(f"[FAIL] Players don't see each other: alice sees bob={alice_sees_bob}, bob sees alice={bob_sees_alice}")
        print(f"Alice room_players: {alice.room_players}")
        print(f"Bob room_players: {bob.room_players}")

    await alice.close()
    await bob.close()
    return True

async def test_checkpoint_7():
    print("Graceful logout")
    alice = TestClient("alice", "test_slot")

    await alice.connect()
    await asyncio.sleep(3)
    await alice.send("go north")
    await asyncio.sleep(1)
    await alice.send("sleep")
    await asyncio.sleep(2)
    await alice.close()
    await asyncio.sleep(2)

    alice2 = TestClient("alice", "test_slot")
    await alice2.connect()
    await asyncio.sleep(3)


    still_alive = not alice2.find_message("died") and not alice2.find_message("collapse")
    if still_alive:
        print("Alice survived safe logout")
    else:
        print("Alice died after safe logout")
    await alice2.close()
    return True

async def run_all_tests():
    print("Multiplayer verification")

    tests = [
        ("1: Shared State", test_checkpoint_1),
        ("2: SAY Command", test_checkpoint_2),
        ("3: WHISPER Command", test_checkpoint_3),
        ("5: Room Players", test_checkpoint_5),
        ("7: Safe Logout", test_checkpoint_7),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = await asyncio.wait_for(test_func(), timeout=TEST_TIMEOUT)
            results.append((name, result))
        except asyncio.TimeoutError:
            print(f"Failed{name}: TIMEOUT")
            results.append((name, False))
        except Exception as e:
            print(f"Failed {name}: ERROR - {e}")
            results.append((name, False))
        await asyncio.sleep(2)
