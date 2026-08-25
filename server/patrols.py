from dataclasses import dataclass
from collections import deque
from typing import Callable, Dict, List, Mapping

from .curfew import curfew_night_key
from .time_system import GameTime
from .world import Room


@dataclass
class PatrolState:
    npc_id: str
    zone: str
    room_id: str
    last_room_id: str = ""
    expires_at: float = 0.0


def patrol_pause_seconds(
    game_time: GameTime,
    *,
    seasonal_density: float,
    wanted_multiplier: int,
) -> int:
    hour = game_time.hour
    if 6 <= hour < 12:
        base = 240
    elif 12 <= hour < 20:
        base = 120
    else:
        base = 60
    return max(1, int(base / seasonal_density / wanted_multiplier))


def patrol_next_rooms(rooms: Dict, room_id: str, last_room_id: str = "") -> List[str]:
    room = rooms.get(room_id)
    if not room:
        return []
    candidates = list(dict.fromkeys(room.exits.values()))
    forward = [candidate for candidate in candidates if candidate != last_room_id]
    return forward or candidates


def patrol_reachable_rooms(
    rooms: Mapping[str, Room],
    current_room_id: str,
    last_room_id: str,
    *,
    eligible: Callable[[Room], bool],
    max_steps: int = 3,
) -> dict[str, int]:
    current_room = rooms.get(current_room_id)
    if current_room is None or max_steps <= 0 or not eligible(current_room):
        return {}

    reachable: dict[str, int] = {}
    queue = deque([(current_room_id, last_room_id, 0)])
    visited = {(current_room_id, last_room_id)}

    while queue:
        room_id, previous_room_id, distance = queue.popleft()
        if distance >= max_steps:
            continue
        room = rooms.get(room_id)
        if room is None:
            continue
        candidates = list(dict.fromkeys(room.exits.values()))
        valid_candidates = [
            candidate
            for candidate in candidates
            if candidate in rooms and eligible(rooms[candidate])
        ]
        forward = [
            candidate
            for candidate in valid_candidates
            if candidate != previous_room_id
        ]
        next_rooms = forward or valid_candidates
        for next_room_id in next_rooms:
            next_distance = distance + 1
            if next_room_id != current_room_id:
                prior_distance = reachable.get(next_room_id)
                if prior_distance is None or next_distance < prior_distance:
                    reachable[next_room_id] = next_distance
            state = (next_room_id, room_id)
            if state in visited:
                continue
            visited.add(state)
            queue.append((next_room_id, room_id, next_distance))

    return reachable


def is_transient_patrol_id(npc_id: str) -> bool:
    prefix = "transient_patrol_"
    return isinstance(npc_id, str) and npc_id.startswith(prefix) and len(npc_id) > len(prefix)


def resolve_patrol_warning(
    rooms: Mapping[str, Room],
    *,
    patrol_room_id: str,
    patrol_last_room_id: str,
    zone: str,
    zone_of: Callable[[Room], str],
    player_room_id: str,
    game_time: GameTime,
    now: float,
    expires_at: float,
):
    if curfew_night_key(game_time) is None:
        return None
    eligible = lambda room: not room.indoors and zone_of(room) == zone
    reachable = patrol_reachable_rooms(
        rooms,
        patrol_room_id,
        patrol_last_room_id,
        eligible=eligible,
    )
    distance = reachable.get(player_room_id)
    if distance not in {1, 2, 3}:
        return None
    return {
        "stage": 4 - distance,
        "seconds_remaining": max(0, int(expires_at - now)),
        "expires_at": expires_at,
    }