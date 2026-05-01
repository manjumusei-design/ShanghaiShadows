from dataclasses import dataclass, field
from typing import Dict, List

import yaml


@dataclass
class Room:
    id: str
    title: str
    description: str
    exits: Dict[str, str] = field(default_factory=dict)
    items: List[str] = field(default_factory=list)
    npcs: List[str] = field(default_factory=list)


def load_rooms(path: str) -> Dict[str, Room]:
    with open(path, "r", encoding = "utf-8") as f:
        data = yaml.safe_load(f)

    rooms: Dict[str, Room] = {}
    for room_id, fields in data.items():
        rooms[room_id] = Room(
            id=fields["id"],
            title=fields["title"],
            description=fields["description"],
            exits=fields.get("exits", {}),
            items=fields.get("items", []),
            npcs=fields.get("npcs",[]),  
        )
    return rooms

