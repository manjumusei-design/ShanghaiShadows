from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .npc import Npc, load_npcs
from .data_utils import filter_to_dataclass

CUSTOM_DIR = Path("server/data/custom")


@dataclass
class Item:
    id: str
    name: str
    description: str
    takeable: bool = True
    readable_text: str = ""
    planted_on: str = ""
    food_value: int = 0
    morale_restore: int = 0
    courage_bonus: int = 0
    defense_value: int = 0
    durability: int = -1 
    max_durability: int = -1
    mods: List[str] = field(default_factory=list)
    concealed: bool = False
    is_weapon: bool = False
    is_armour: bool = False
    is_container: bool = False
    container_items: List = field(default_factory=list)
    locked: bool = False
    key_id: str = ""
    is_note: bool = False
    note_text: str = ""
    is_map: bool = False
    map_districts: List[str] = field(default_factory=list)
    is_money: bool = False
    money_amount: int = 0
    money_currency: str = ""
    is_key: bool = False
    opens_container: str = ""
    is_mod: bool = False
    mod_type: str = ""
    mod_bonus: int = 0


@dataclass
class Room:
    id: str
    title: str
    description: str
    exits: Dict[str, str] = field(default_factory=dict)
    items: List[Item] = field(default_factory=list)
    npcs: List[str] = field(default_factory=list)
    indoors: bool = False
    tags: List[str] = field(default_factory=list)
    players: List[str] = field(default_factory=list)
    hiding_spots: bool = False
    hidden_exits: Dict[str, str] = field(default_factory=dict)
    safe_room: bool = False
    trishaw_stand: bool = False
    nurse_available: bool = False
    nurse_hours: List[int] = field(default_factory=list)


def load_items(path: str) -> Dict[str, Item]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    items: Dict[str, Item] = {}
    for item_data in data.get("items", []):
        item = Item(**filter_to_dataclass(item_data, Item))
        items[item.id] = item
    return items


def load_rooms(path: str, items: Dict[str, Item]) -> Dict[str, Room]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if "districts" in data:
        return _load_generated_rooms(data, items)

    rooms: Dict[str, Room] = {}
    for room_id, fields in data.items():
        room_items = []
        for item_id in fields.get("items", []):
            if item_id in items:
                room_items.append(replace(items[item_id]))

        filtered_data = filter_to_dataclass(fields, Room, overrides={"items": room_items, "npcs": []})
        rooms[room_id] = Room(**filtered_data)
    return rooms


def _load_generated_rooms(data: Dict[str, object], items: Dict[str, Item]) -> Dict[str, Room]:
    rooms: Dict[str, Room] = {}
    for district in data.get("districts", []):
        prefix = district["prefix"]
        count = int(district["count"])
        tags = list(district.get("tags", []))
        indoors_pattern = district.get("indoors_every", 0)
        room_prefix = district.get("room_prefix", prefix)
        title_prefix = district.get("title_prefix", prefix.title())
        description_templates = district.get("description_templates", [])
        item_cycle = district.get("item_cycle", [])
        special_names = district.get("special_names", {})
        special_ids = district.get("special_ids", {})
        for idx in range(count):
            room_index = idx + 1
            room_id = special_ids.get(str(room_index), f"{room_prefix}_{room_index:02d}")
            title = special_names.get(str(room_index), f"{title_prefix} {room_index}")
            template = description_templates[idx % len(description_templates)] if description_templates else "The city waits here."
            description = template.format(index=room_index, title=title)
            exits: Dict[str, str] = {}
            if idx > 0:
                prev_id = special_ids.get(str(room_index - 1), f"{room_prefix}_{room_index - 1:02d}")
                exits["west"] = prev_id
            if idx < count - 1:
                next_id = special_ids.get(str(room_index + 1), f"{room_prefix}_{room_index + 1:02d}")
                exits["east"] = next_id
            for connector in district.get("connectors", []):
                if int(connector["at"]) == room_index:
                    exits[str(connector["direction"])] = str(connector["to"])

            room_items: List[Item] = []
            if item_cycle and idx % max(1, len(item_cycle)) == 0:
                item_id = item_cycle[idx % len(item_cycle)]
                if item_id in items:
                    room_items.append(replace(items[item_id]))

            rooms[room_id] = Room(
                id=room_id,
                title=title,
                description=description,
                exits=exits,
                items=room_items,
                npcs=[],
                indoors=bool(indoors_pattern and room_index % int(indoors_pattern) == 0),
                tags=tags + [prefix],
            )
    return rooms



def _merge_custom(base: Dict, custom_path: Path, load_func) -> Dict:
    if not custom_path.exists():
        return base
    base.update(load_func(str(custom_path)))
    return base

def _apply_room_properties(rooms: Dict[str, Room], props_path: Path) -> None:
    if not props_path.exists():
        return
    with open(props_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    BOOL_FIELDS = ("safe_room", "hiding_spots", "trishaw_stand", "nurse_available", "indoors")
    for entry in data.get("rooms", []):
        room_id = entry.get("id")
        if not room_id or room_id not in rooms:
            continue
        room = rooms[room_id]
        for key in BOOL_FIELDS:
            if key in entry:
                setattr(room, key, entry[key])
        if "hidden_exits" in entry:
            room.hidden_exits.update(entry["hidden_exits"])
        if "nurse_hours" in entry:
            room.nurse_hours = entry["nurse_hours"]
        if "tags" in entry:
            for tag in entry["tags"]:
                if tag not in room.tags:
                    room.tags.append(tag)

                    
class World:
    def __init__(self):
        items = load_items("server/data/items.yaml")
        if CUSTOM_DIR.exists():
            items = _merge_custom(items, CUSTOM_DIR / "items.yaml", load_items)
        self.item_catalog: Dict[str, Item] = items
        self.rooms: Dict[str, Room] = load_rooms("server/data/rooms.yaml", items)
        if CUSTOM_DIR.exists():
            self.rooms = _merge_custom(self.rooms, CUSTOM_DIR / "rooms.yaml", lambda p: load_rooms(p, items))
        self.npcs: Dict[str, Npc] = load_npcs("server/data/npcs.yaml")
        if CUSTOM_DIR.exists():
            self.npcs = _merge_custom(self.npcs, CUSTOM_DIR / "npcs.yaml", load_npcs)
        self.npc_locations: Dict[str, str] = {}
        self._place_npcs()

    def _place_npcs(self):
        for npc_id, npc in self.npcs.items():
            if not npc.schedule:
                continue
            hour = min(npc.schedule.keys())
            room_id = npc.schedule[hour]
            if room_id in self.rooms:
                self.rooms[room_id].npcs.append(npc_id)
                self.npc_locations[npc_id] = room_id

    def clone_item(self, item_id: str) -> Optional[Item]:
        item = self.item_catalog.get(item_id)
        return replace(item) if item else None
    
    def get_room(self, room_id: str) -> Optional[Room]:
        return self.rooms.get(room_id)

    def place_npc(self, npc_id: str, room_id: str) -> None:
        old_room_id = self.npc_locations.get(npc_id)
        if old_room_id and old_room_id in self.rooms and npc_id in self.rooms[old_room_id].npcs:
            self.rooms[old_room_id].npcs.remove(npc_id)
        if room_id in self.rooms and npc_id not in self.rooms[room_id].npcs:
            self.rooms[room_id].npcs.append(npc_id)
            self.npc_locations[npc_id] = room_id

    def format_room(self, room_id: str) -> str:
        room = self.get_room(room_id)
        if not room:
            return "You are nowhere."
        lines = [room.title, room.description]
        if room.items:
            lines.append("You see here: " + ", ".join(item.name for item in room.items))
        if room.npcs:
            for npc_id in room.npcs:
                npc = self.npcs.get(npc_id)
                if npc:
                    lines.append(npc.name + " is here.")
        if room.exits:
            lines.append("Exits: " + ", ".join(room.exits.keys()))
        return "\n".join(lines) + "\n"


def load_world() -> World:
    return World()
