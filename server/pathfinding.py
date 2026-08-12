from collections import deque
from dataclasses import dataclass
from heapq import heappush, heappop
from typing import Callable, Dict, List, Optional, Tuple

from .law import is_curfew

SOUND_YELL = 3
SOUND_GUNSHOT = 5
SOUND_WHISPER = 1
SOUND_NPC_ALERT = 2
SOUND_FOOTSTEP = 1
SOUND_MELEE = 2


@dataclass(frozen=True)
class SoundEvent:
    kind: str
    source_room_id: str
    base_range: int
    emit_audio: bool
    locally_visible: bool
    surpress_witnesses: bool
    effective_range: int
    intensity: int
    source_actor_id: str = ""
    investigator_target_room_id: str = ""


def _sound_range(base_range: int, weather: str, game_time, range_multiplier: float) -> int:
    effective = max(0, int(base_range * range_multiplier))
    from .constants import WEATHER_SOUND_RANGE_MODIFIER
    effective = max(0, int(effective * WEATHER_SOUND_RANGE_MODIFIER.get(weather, 1.0)))
    if game_time and (game_time.hour >= 22 or game_time.hour < 6) and effective:
        effective += 1
    return effective


def emit_sound(
    source_room_id: str,
    kind: str,
    *,
    intensity: int = 3,
    weapon=None,
    hidden: bool = False,
    weather: str = "clear",
    game_time=None,
    range_multiplier: float = 1.0,
    source_actor_id: str = "",
    base_range: int | None = None,
) -> SoundEvent:
    weapon_type = getattr(weapon, "weapon_type", "") if weapon else ""
    silenced = bool(weapon and "silencer" in getattr(weapon, "mods", []))
    if kind == "melee" or weapon_type == "melee":
        range_base = 0
        effective = 0
        audio = False
    elif kind == "gunshot" or weapon_type == "firearm":
        range_base = 4 if base_range is None else base_range
        effective = 0 if silenced else _sound_range(range_base, weather, game_time, range_multiplier)
        audio = not silenced
    else:
        range_base = 3 if base_range is None else base_range
        effective = _sound_range(range_base, weather, game_time, range_multiplier)
        audio = True
    return SoundEvent(
        kind=kind,
        source_room_id=source_room_id,
        base_range=range_base,
        emit_audio=audio,
        locally_visible=not (hidden and weapon_type == "firearm" and silenced),
        suppress_witnesses=bool(hidden and silenced and weapon_type == "firearm"),
        effective_range=effective,
        intensity=intensity,
        source_actor_id=source_actor_id,
        investigator_target_room_id=source_room_id,
    )


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
        if is_curfew(game_time):
            cost += 3.0

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


def propagate_sound(rooms: dict, event: SoundEvent) -> List[Tuple[str, int]]:
    if event.effective_range <= 0:
        return []
    origin_room_id = event.source_room_id
    intensity = event.intensity
    effective_max = event.effective_range

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