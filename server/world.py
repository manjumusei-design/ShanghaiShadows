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
    items: List[Item] = field(default_factory=list)
    npcs: List[str] = field(default_factory=list)


def load_items(path: str) -> Dict[str, Item]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    items: Dict[str, Item] = {}
    for item_data in data.get("items", []):
        item = Item(
            id=item_data["id"],
            name=item_data["name"],
            description=item_data["description"],
            takeable=item_data.get("takeable", True),
        )
        items[item.id] = item
    return items


def load_rooms(path: str, items: Dict[str, Item]) -> Dict[str, Room]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    rooms: Dict[str, Room] = {}
    for room_id, fields in data.items():
        room_items = []
        for item_id in fields.get("items", []):
            if item_id in items:
                room_items.append(replace(items[item_id]))

        rooms[room_id] = Room(
            id=fields["id"],
            title=fields["title"],
            description=fields["description"],
            exits=fields.get("exits", {}),
            items=room_items,
            npcs=fields.get("npcs", []),
        )
    return rooms


class World:
    def __init__(self):
        items = load_items("server/data/items.yaml")
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


    
