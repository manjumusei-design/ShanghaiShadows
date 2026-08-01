from dataclasses import dataclass
from typing import Dict, List


@dataclass
class PatrolState:
    npc_id: str
    zone: str
    room_id: str
    last_room_id: str = ""
    expires_at: float = 0.0


def patrol_pause_seconds(game_time) -> int:
    hour = game_time.hour
    if 6 <= hour < 12:
        return 240
    if 12 <= hour < 20:
        return 120
    return 60


def patrol_next_rooms(rooms: Dict, room_id: str, last_room_id: str = "") -> List[str]:
    room = rooms.get(room_id)
    if not room:
        return []
    candidates = list(dict.fromkeys(room.exits.values()))
    forward = [candidate for candidate in candidates if candidate != last_room_id]
    return forward or candidates