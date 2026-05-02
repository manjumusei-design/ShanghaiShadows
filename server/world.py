from dataclasses import dataclass, field
from typing import Dict, List

import yaml


@dataclass
class Item:
    id: str
    name: str
    description: str
    takeable: bool = True

    
@dataclass
class Room:
    id: str
    title: str
    description: str
    exits: Dict[str, str] = field(default_factory=dict)
    items: List[str] = field(default_factory=list)
    npcs: List[str] = field(default_factory=list)


def load_rooms(path: str) -> Dict[str, Room]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    rooms: Dict[str, Room] = {}
    for room_id, fields in data.items():
        rooms[room_id] = Room(
            id=fields["id"],
            title=fields["title"],
            description=fields["description"],
            exits=fields.get("exits", {}),
            items=fields.get("items", []),
            npcs=fields.get("npcs", []),
        )
    return rooms


class World:
    """This is to hold the room graph and to provide navigation function"""
    def __init__(self):
        self.rooms: Dict[str, Room] = load_rooms("server/data/rooms.yaml")

    def get_room(self, room_id: str) -> Room | None:
        return self.rooms.get(room_id)

    def format_room(self, room_id: str) -> str:
        room = self.get_room(room_id)
        if not room:
            return "You are nowhere."
        lines = [
            f"  {room.title}",
            "",
            room.description,
            "",
            "Exits:",
        ]
        if room.exits:
            for direction, dest_id in room.exits.items():
                dest = self.get_room(dest_id)
                name = dest.title if dest else "unknown"
                lines.append(f"  {direction:10} => {name}")
        else:
            lines.append("None")
        return "\n".join(lines)


    
