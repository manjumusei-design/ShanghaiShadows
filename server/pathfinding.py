from collections import deque
from heapq import heappush, heappop
from typing import Callable, Dict, List, Optional, Tuple

SOUND_YELL = 3
SOUND_GUNSHOT = 5
SOUND_WHISPER = 1
SOUND_NPC_ALERT = 2
SOUND_FOOTSTEP = 1


def a_star_find_path(
    rooms: dict,
    start_id: str,
    goal_id: str,
    cost_fn: Callable[[str, str], float],
    heuristic_fn: Optional[Callable[[str, str], float]] = None,
) -> List[str]:
    if start_id == goal_id:
        return []

    if heuristic_fn is None:
        heuristic_fn = _default_heuristic

    counter = 0
    open_set: List[Tuple[float, int, str, List[str]]] = []
    heappush(open_set, (heuristic_fn(start_id, goal_id), counter, start_id, []))

    g_scores: Dict[str, float] = {start_id: 0.0}
    closed: set = set()

    while open_set:
        _f, _c, current_id, path = heappop(open_set)

        if current_id in closed:
            continue
        closed.add(current_id)

        if current_id == goal_id:
            return path

        room = rooms.get(current_id)
        if not room:
            continue

        for direction, dest_id in room.exits.items():
            if dest_id in closed:
                continue
            tentative_g = g_scores[current_id] + cost_fn(current_id, dest_id)
            if tentative_g < g_scores.get(dest_id, float("inf")):
                g_scores[dest_id] = tentative_g
                f = tentative_g + heuristic_fn(dest_id, goal_id)
                counter += 1
                heappush(open_set, (f, counter, dest_id, path + [direction]))

    return []


def _default_heuristic(_a: str, _b: str) -> float:
    return 1.0


def default_edge_cost(
    room_a_id: str,
    room_b_id: str,
    rooms: dict,
    player=None,
    game_time=None,
    weather: str = "clear",
) -> float:
    cost = 1.0
    room_b = rooms.get(room_b_id)
    if not room_b:
        return cost

    if game_time and not getattr(room_b, "indoors", False):
        hour = game_time.hour
        if hour >= 20 or hour < 6:
            cost += 3.0

    if weather == "rain" and not getattr(room_b, "indoors", False):
        cost += 1.0

    if getattr(room_b, "safe_room", False):
        cost *= 0.7

    tags = [t.lower() for t in room_b.tags] if room_b.tags else []
    if "checkpoint" in tags:
        cost += 2.0
    if "hidden" in tags:
        cost += 1.5

    if player and player.health < 30:
        cost *= 1.5

    return cost


def make_cost_fn(rooms: dict, player=None, game_time=None, weather: str = "clear"):
    return lambda a, b: default_edge_cost(a, b, rooms, player, game_time, weather)


def propagate_sound(
    rooms: dict,
    origin_room_id: str,
    intensity: int,
    max_distance: int = 3,
    weather: str = "clear",
    game_time=None,
) -> List[Tuple[str, int]]:
    effective_max = max_distance
    if weather == "rain":
        effective_max = max(1, int(max_distance * 0.6))
    if game_time:
        hour = game_time.hour
        if hour >= 22 or hour < 6:
            effective_max += 1

    result: List[Tuple[str, int]] = []
    visited = {origin_room_id}
    queue: deque = deque([(origin_room_id, 0)])

    while queue:
        room_id, distance = queue.popleft()

        if distance > 0:
            perceived = max(1, intensity // (2 ** (distance - 1)))
            result.append((room_id, perceived))

        if distance >= effective_max:
            continue

        room = rooms.get(room_id)
        if not room:
            continue

        for _direction, dest_id in room.exits.items():
            if dest_id in visited:
                continue
            dest_room = rooms.get(dest_id)
            if not dest_room:
                continue
            visited.add(dest_id)
            queue.append((dest_id, distance + 1))

    return result
