import random
from collections import Counter, defaultdict
from server.game import GameServer, GameState, PlayerState, SessionContext, PlayerSession
from server.npc import load_npcs
from server.parser import Command, parse
from server.time_system import EventScheduler, GameTime
from server.trust import default_trust
from server.world import World


class MockSession:
    def __init__(self):
        self.running = True
        self.messages = []

    async def send_display(self, text):
        self.messages.append(text)

    async def send_prompt(self, text="> "):
        pass


def make_context(player=None):
    ws = MockSession()
    session = PlayerSession.__new__(PlayerSession)
    session.websocket = ws
    session.running = True

    world = World()
    if player is None:
        player = PlayerState()
    state = GameState(
        world=world,
        player=player,
        game_time=GameTime(day=1, minute=420),
        scheduler=EventScheduler(),
        trust_rules={},
    )

    context = SessionContext.__new__(SessionContext)
    context.session = session
    context.slot_name = ""
    context.state = state
    context.seconds_since_autosave = 0
    return context


ACTIONS = [
    "look",
    "go east",
    "go west",
    "go north",
    "go south",
    "wait",
    "status",
    "rest",
    "eat cold noodles",
]


def run_simulation(days=100, seed=42):
    random.seed(seed)
    context = make_context(player=PlayerState(name="SimRunner"))
    server = GameServer.__new__(GameServer)
    server.ai_client = None
    server.disguises = {}
    server.stealth = None
    server.storylet_manager = None
    server.sessions = {}
    server.command_registry = {}
    server._post_display = None
    original_survival_tick = server._process_survival_tick
    def safe_survival_tick(ctx):
        ctx.state.player.hunger = max(0, ctx.state.player.hunger - 0.5)
        if ctx.state.player.hunger <= 20:
            ctx.state.player.health = max(0, ctx.state.player.health - 2)
        if ctx.state.player.hunger > 80 and ctx.state.game_time.minute % 60 == 0:
            ctx.state.player.health = min(100, ctx.state.player.health + 1)
    server._process_survival_tick = safe_survival_tick

    metrics = {
        "health_history": [],
        "hunger_history": [],
        "morale_history": [],
        "death_day": None,
        "death_cause": None,
        "trust_snapshots": [],
        "rooms_visited": Counter(),
        "storylet_triggers": 0,
        "commands_executed": 0,
    }

    for day in range(1, days + 1):
        context.state.game_time.day = day
        for minute in range(420, 1380):  # 7am to 11pm
            context.state.game_time.minute = minute
            server._process_survival_tick(context)
            if minute % 30 == 0:
                action = random.choice(ACTIONS)
                metrics["commands_executed"] += 1
                if action.startswith("go "):
                    metrics["rooms_visited"][context.state.player.current_room] += 1
                room = context.state.world.get_room(context.state.player.current_room)
                if room and action.startswith("go "):
                    direction = action.split()[-1]
                    if direction in room.exits:
                        context.state.player.current_room = room.exits[direction]
                        metrics["rooms_visited"][context.state.player.current_room] += 1
                if action == "eat cold noodles" and context.state.player.hunger < 60:
                    context.state.player.hunger = min(100, context.state.player.hunger + 15)
                    context.state.player.morale = min(100, context.state.player.morale + 5)
            if minute % 60 == 0:
                context.state.player.hunger = min(100, context.state.player.hunger + 35)
                context.state.player.morale = min(100, context.state.player.morale + 3)
                if action == "rest":
                    context.state.player.morale = min(100, context.state.player.morale + 5)
            is_dead, msg = server._check_death_conditions(context)
            if is_dead:
                metrics["death_day"] = day
                metrics["death_cause"] = msg
                break
        metrics["health_history"].append(context.state.player.health)
        metrics["hunger_history"].append(context.state.player.hunger)
        metrics["morale_history"].append(context.state.player.morale)
        metrics["trust_snapshots"].append(
            {f: {r: v for r, v in roles.items()} for f, roles in context.state.player.trust.items()}
        )
        if metrics["death_day"]:
            break
    return metrics


def print_report(metrics):
    print("=" * 60)
    print("  SHANGHAI SHADOWS - Simulation Report")
    print("=" * 60)

    days_survived = len(metrics["health_history"])
    print(f"\nDays survived: {days_survived}")
    if metrics["death_day"]:
        print(f"Death on day: {metrics['death_day']}")
        print(f"Death cause: {metrics['death_cause']}")
    else:
        print("Character survived the full simulation.")
    if metrics["health_history"]:
        avg_health = sum(metrics["health_history"]) / len(metrics["health_history"])
        min_health = min(metrics["health_history"])
        max_health = max(metrics["health_history"])
        print(f"\nHealth: avg={avg_health:.1f}, min={min_health}, max={max_health}")

    # Hunger
    if metrics["hunger_history"]:
        avg_hunger = sum(metrics["hunger_history"]) / len(metrics["hunger_history"])
        min_hunger = min(metrics["hunger_history"])
        print(f"Hunger: avg={avg_hunger:.1f}, min={min_hunger:.1f}")

    # Morale
    if metrics["morale_history"]:
        avg_morale = sum(metrics["morale_history"]) / len(metrics["morale_history"])
        print(f"Morale: avg={avg_morale:.1f}")

    # Rooms
    print(f"\nRooms visited: {len(metrics['rooms_visited'])} unique")
    top_rooms = metrics["rooms_visited"].most_common(5)
    for room_id, count in top_rooms:
        print(f"  {room_id}: {count} visits")

    # Commands
    print(f"\nTotal commands executed: {metrics['commands_executed']}")

    # Difficulty assessment
    print("\n--- Difficulty Assessment ---")
    if metrics["death_day"] and metrics["death_day"] < 10:
        print("WARNING: Character dies too quickly (< 10 days). Consider reducing hunger decay.")
    elif metrics["death_day"] and metrics["death_day"] < 30:
        print("MODERATE: Character survives 10-30 days. Survival is challenging but fair.")
    elif metrics["death_day"]:
        print("EASY: Character survives 30+ days before death. Consider increasing difficulty.")
    else:
        print("SURVIVOR: Character survives full 100 days. May need more pressure.")
    if metrics["hunger_history"] and min(metrics["hunger_history"]) < 10:
        print("WARNING: Hunger drops very low. Food items may be too scarce.")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    metrics = run_simulation(days=100)
    print_report(metrics)
