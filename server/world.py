from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .npc import Npc, load_npcs
from .dataclass_utils import filter_to_dataclass
from .npc_memory import npc_relationship_system
from .formatting import format_bold, format_bold_underline, format_npc_presence, format_item_list, format_exit
from .testimonies import validate_testimony_items
from .content_validation import ContentValidationError, load_strict_yaml

CUSTOM_DIR = Path("server/data/custom")

DISTRICT_LABELS = {
    "bund": "Bund",
    "commercial": "Commercial District",
    "old_city": "Old City",
    "hongkou": "Hongkou",
    "french": "French Concession",
    "docks": "Huangpu Docks",
    "hidden_shanghai": "Hidden Shanghai",
    "residential": "Residential Lane",
    "warehouse": "Warehouse District",
    "church": "Church District",
    "school": "School District",
    "ccp_base": "Underground Base",
    "gmd_office": "Intelligence Office",
}


def is_public_map_room(room) -> bool:
    return bool(room) and room.district != "hidden_shanghai" and "hidden_shanghai" not in room.tags


def _select_time_desc(room: "Room", game_hour: int, weather: str = "clear", season: str = "spring") -> str:
    if weather == "rain":
        if room.indoors and room.rain_desc:
            return room.rain_desc
        elif room.indoors:
            base_desc = room.description
            return f"{base_desc} Rain pounds outside."
        elif room.rain_desc:
            return room.rain_desc

    season_desc_attr = f"{season}_desc"
    season_desc = getattr(room, season_desc_attr, None)
    if season_desc:
        return season_desc

    if game_hour < 6:
        desc = room.night_desc or room.description
    elif game_hour < 8:
        desc = room.dawn_desc or room.description
    elif game_hour < 18:
        desc = room.day_desc or room.description
    elif game_hour < 20:
        desc = room.dusk_desc or room.description
    else:
        desc = room.night_desc or room.description
    return desc


@dataclass
class Item:
    id: str
    name: str
    description: str
    examine_text: str = ""
    instance_id: str = ""
    takeable: bool = True
    readable_text: str = ""
    planted_on: str = ""
    food_value: int = 0
    morale_restore: int = 0
    courage_bonus: int = 0
    disguise_id: str = ""
    defense_value: int = 0
    durability: int = -1
    max_durability: int = -1
    mods: List[str] = field(default_factory=list)
    concealed: bool = False
    is_weapon: bool = False
    weapon_type: str = ""
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
    category: str = ""
    base_cost: int = 0
    rarity: str = "common"
    mod_slots: int = 0
    shop_inventory: bool = False
    is_quest_item: bool = False
    is_corpse: bool = False
    corpse_npc_id: str = ""
    decay_day: int = 0
    culture: str = ""
    contraband_risk: bool = False
    evidence: bool = False
    on_read_effects: Dict[str, Any] = field(default_factory=dict)
    is_open: bool = True
    testimony_id: str = ""
    testimony_title: str = ""
    testimony_date: str = ""
    testimony_place: str = ""
    testimony_writer: str = ""
    testimony_source: str = ""
    testimony_source_type: str = ""
    testimony_source_badge: str = ""
    testimony_reprint: bool = False
    testimony_perspective: str = ""
    testimony_provenance: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.examine_text, str):
            raise ValueError(f"item examine_text must be a string: {self.id}")


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
    nurse_available: bool = False
    nurse_hours: List[int] = field(default_factory=list)
    dead_drops: List[dict] = field(default_factory=list)
    district: str = ""
    dawn_desc: str = ""
    day_desc: str = ""
    dusk_desc: str = ""
    night_desc: str = ""
    rain_desc: str = ""
    crime_scene_until_day: int = 0
    hints: List[str] = field(default_factory=list)
    search_signal: str = ""
    search_item: str = ""
    detailed_desc: str = ""
    spring_desc: str = ""
    summer_desc: str = ""
    autumn_desc: str = ""
    winter_desc: str = ""


def _runtime_item_data(item_data):
    return {key: value for key, value in item_data.items() if key != "examine_provenance"}


def load_items(path: str) -> Dict[str, Item]:
    data = load_strict_yaml(Path(path))

    items: Dict[str, Item] = {}
    for item_data in data.get("items", []):
        item = Item(**filter_to_dataclass(_runtime_item_data(item_data), Item, warn_unknown=True))
        items[item.id] = item
    for item_data in data.get("items", []):
        container = items.get(item_data.get("id", ""))
        if not container or not container.is_container:
            continue
        contents = []
        for child in item_data.get("container_items", []) or []:
            child_item = items.get(child) if isinstance(child, str) else None
            if child_item:
                contents.append(replace(child_item))
            elif isinstance(child, dict):
                contents.append(Item(**filter_to_dataclass(_runtime_item_data(child), Item, warn_unknown=True)))
        container.container_items = contents
    validation_items = list(items.values())
    for item_data in data.get("items", []):
        validation_items.extend(_iter_inline_container_items(item_data))
    validate_testimony_items(validation_items)
    return items


def _iter_inline_container_items(item_data):
    if not isinstance(item_data, dict):
        return
    for child in item_data.get("container_items", []) or []:
        if not isinstance(child, dict):
            continue
        yield child
        yield from _iter_inline_container_items(child)


def load_rooms(path: str, items: Dict[str, Item]) -> Dict[str, Room]:
    data = load_strict_yaml(Path(path))

    if "districts" in data:
        return _load_generated_rooms(data, items)

    rooms: Dict[str, Room] = {}
    for room_id, fields in data.items():
        room_items = []
        for item_id in fields.get("items", []):
            if item_id in items:
                room_items.append(replace(items[item_id]))

        filtered_data = filter_to_dataclass(fields, Room, overrides={"items": room_items, "npcs": []}, warn_unknown=True)
        rooms[room_id] = Room(**filtered_data)
    return rooms


def _load_generated_rooms(data: Dict[str, object], items: Dict[str, Item]) -> Dict[str, Room]:
    rooms: Dict[str, Room] = {}
    outdoor_street_districts = {
        "bund",
        "commercial",
        "old_city",
        "hongkou",
        "french",
        "docks",
        "residential",
        "warehouse",
        "church",
        "school",
    }
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
        special_descriptions = district.get("special_descriptions", {})
        special_detailed_descriptions = district.get("special_detailed_descriptions", {})
        special_items = district.get("special_items", {})
        for idx in range(count):
            room_index = idx + 1
            room_id = special_ids.get(str(room_index), f"{room_prefix}_{room_index:02d}")
            title = special_names.get(str(room_index), f"{title_prefix} {room_index}")
            description = special_descriptions.get(str(room_index)) or (
                description_templates[idx % len(description_templates)] if description_templates else "The city waits here."
            ).format(index=room_index, title=title)
            detailed_desc = special_detailed_descriptions.get(str(room_index), "")
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
            for item_id in special_items.get(str(room_index), []):
                if item_id in items:
                    room_items.append(replace(items[item_id]))

            is_indoors = bool(indoors_pattern and room_index % int(indoors_pattern) == 0)
            room_tags = tags + [prefix]
            if not is_indoors and prefix in outdoor_street_districts:
                room_tags.append("street")
            rooms[room_id] = Room(
                id=room_id,
                title=title,
                description=description,
                exits=exits,
                items=room_items,
                npcs=[],
                indoors=is_indoors,
                tags=room_tags,
                district=prefix,
                detailed_desc=detailed_desc,
            )
    for authored in data.get("authored_rooms", []):
        room_id = authored.get("id")
        if not room_id or room_id in rooms:
            continue
        room_items = []
        for item_id in authored.get("items", []) or []:
            if item_id in items:
                room_items.append(replace(items[item_id]))
        rooms[room_id] = Room(
            id=room_id,
            title=authored.get("title", room_id.replace("_", " ").title()),
            description=authored.get("description", "The room bears the marks of the work done here."),
            exits=dict(authored.get("exits", {})),
            items=room_items,
            npcs=[],
            indoors=bool(authored.get("indoors", True)),
            tags=list(authored.get("tags", [])),
            district=authored.get("district", ""),
            detailed_desc=authored.get("detailed_desc", ""),
        )
    return rooms


def _apply_room_properties(rooms: Dict[str, Room], props_path: Path) -> None:
    if not props_path.exists():
        return
    data = load_strict_yaml(props_path) or {}
    BOOL_FIELDS = ("safe_room", "hiding_spots", "nurse_available", "indoors")
    TIME_DESC_FIELDS = ("dawn_desc", "day_desc", "dusk_desc", "night_desc", "rain_desc")
    DETAIL_FIELDS = ("detailed_desc",)
    for index, entry in enumerate(data.get("rooms", [])):
        room_id = entry.get("id")
        if not room_id or room_id not in rooms:
            raise ContentValidationError(props_path, f"rooms[{index}].id", f"unknown room {room_id!r}")
        for exit_index, exit_entry in enumerate(entry.get("exits", []) or []):
            destination = exit_entry.get("to") if isinstance(exit_entry, dict) else ""
            if destination and destination not in rooms:
                raise ContentValidationError(
                    props_path,
                    f"rooms[{index}].exits[{exit_index}].to",
                    f"unknown room {destination!r}",
                )
        for exit_index, exit_entry in enumerate(entry.get("hidden_exits", []) or []):
            destination = exit_entry.get("to") if isinstance(exit_entry, dict) else ""
            if destination and destination not in rooms:
                raise ContentValidationError(
                    props_path,
                    f"rooms[{index}].hidden_exits[{exit_index}].to",
                    f"unknown room {destination!r}",
                )
        room = rooms[room_id]
        for key in BOOL_FIELDS:
            if key in entry:
                setattr(room, key, entry[key])
        for key in TIME_DESC_FIELDS:
            if key in entry:
                setattr(room, key, entry[key])
        for key in DETAIL_FIELDS:
            if key in entry:
                setattr(room, key, entry[key])
        if "hidden_exits" in entry:
            for he in entry["hidden_exits"]:
                if isinstance(he, dict) and "direction" in he and "to" in he:
                    room.hidden_exits[he["direction"]] = he["to"]
                elif isinstance(he, dict):
                    room.hidden_exits.update(he)
        if "nurse_hours" in entry:
            room.nurse_hours = entry["nurse_hours"]
        if "tags" in entry:
            for tag in entry["tags"]:
                if tag not in room.tags:
                    room.tags.append(tag)
        if "exits" in entry:
            for exit_entry in entry["exits"]:
                if isinstance(exit_entry, dict) and "direction" in exit_entry and "to" in exit_entry:
                    room.exits[exit_entry["direction"]] = exit_entry["to"]
        if "hints" in entry:
            room.hints = entry["hints"]
        if "search_signal" in entry:
            room.search_signal = entry["search_signal"]
        if "search_item" in entry:
            room.search_item = entry["search_item"]


class World:
    def __init__(self):
        items = load_items("server/data/items.yaml")
        self.item_catalog: Dict[str, Item] = items
        self.rooms: Dict[str, Room] = load_rooms("server/data/rooms.yaml", items)
        if CUSTOM_DIR.exists():
            _apply_room_properties(self.rooms, CUSTOM_DIR / "room_properties.yaml")
        self.npcs: Dict[str, Npc] = load_npcs("server/data/custom/npcs.yaml")
        self._load_npc_relationships()
        self.npc_locations: Dict[str, str] = {}
        self._death_records = None
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
        return replace(item, instance_id=item.id) if item else None

    def clone_room(self, room_id: str, new_id: str) -> Optional[Room]:
        room = self.rooms.get(room_id)
        if not room:
            return None
        
        cloned_items = [replace(item) for item in room.items]
        
        return replace(
            room,
            id=new_id,
            exits=dict(room.exits),
            items=cloned_items,
            npcs=list(room.npcs),
            tags=list(room.tags),
             players=[],
            hidden_exits=dict(room.hidden_exits),
            nurse_hours=list(room.nurse_hours),
            dead_drops=[dict(d) for d in room.dead_drops],
            hints=list(room.hints),
        )

    def get_room(self, room_id: str) -> Optional[Room]:
        return self.rooms.get(room_id)

    def place_npc(self, npc_id: str, room_id: str) -> None:
        records = getattr(self, "_death_records", None)
        if records is not None and npc_id in records:
            return
        old_room_id = self.npc_locations.get(npc_id)
        if old_room_id and old_room_id in self.rooms and npc_id in self.rooms[old_room_id].npcs:
            self.rooms[old_room_id].npcs.remove(npc_id)
        if room_id in self.rooms and npc_id not in self.rooms[room_id].npcs:
            self.rooms[room_id].npcs.append(npc_id)
            self.npc_locations[npc_id] = room_id

    def format_room(self, room_id: str, room_state_overrides: dict = None, death_journals: dict = None, game_hour: int = 12, weather: str = "clear", game_day: int = 0, detailed: bool = False, district_control: dict = None, season: str = "spring", blocked_exits: dict = None, arrival_text: str = "", reveal_faction: bool = True) -> str:
        room = self.get_room(room_id)
        if not room:
            return "You are nowhere."
        if detailed and room.detailed_desc:
            description = room.detailed_desc
        elif detailed:
            description = _select_time_desc(room, game_hour, weather, season)
            if game_hour < 6:
                prefix = "The darkness presses in more than before. "
            elif game_hour < 8:
                prefix = "Dawn's light shifts, revealing new details. "
            elif game_hour < 18:
                prefix = "The midday bustle fills the streets. "
            elif game_hour < 20:
                prefix = "Shadows lengthen as dusk deepens. "
            else:
                prefix = "The night grows heavier around you. "
            if weather == "rain":
                prefix = "Rain continues to fall in sheets. "
            description = prefix + description
        else:
            description = _select_time_desc(room, game_hour, weather, season)
        lines = [format_bold_underline(room.title), description]
        if arrival_text:
            lines.append(arrival_text)
        if district_control:
            district = getattr(room, 'district', '')
            control = district_control.get(district, '')
            if control == 'ccp':
                lines.append("CCP pamphlets cover the walls — the resistance holds this district.")
            elif control == 'gmd':
                lines.append("GMD posters dominate — Nationalist influence runs deep here.")
            elif control == 'kempeitai':
                lines.append("Kempeitai patrols are visibly denser — the occupation tightens its grip.")
        if room.items:
            item_names = [item.name for item in room.items]
            lines.append("You see here: " + format_item_list(item_names))
        if room.npcs:
            for npc_id in room.npcs:
                npc = self.npcs.get(npc_id)
                if npc:
                    lines.append(format_npc_presence(
                        npc.name,
                        getattr(npc, 'faction', 'civilian'),
                        wounded=getattr(npc, 'wounded', False),
                        reveal_faction=reveal_faction,
                    ))
        if room.exits:
            blocked = blocked_exits or {}
            exit_parts = []
            for direction, dest_id in room.exits.items():
                dest = self.get_room(dest_id)
                dest_name = dest.title if dest else dest_id
                part = format_exit(direction, dest_name)
                if direction in blocked:
                    part += " (blocked)"
                exit_parts.append(part)
            lines.append("Exits: " + ", ".join(exit_parts))
        if room.crime_scene_until_day > 0 and (game_day == 0 or game_day < room.crime_scene_until_day):
            lines.append("⚠ Police tape and chalk marks indicate a recent crime scene here.")
        if room_state_overrides:
            override = room_state_overrides.get(room_id)
            if override and override.get("shop_closed"):
                lines.append(override.get("closed_reason", "This shop has closed."))
        if death_journals:
            journals = death_journals.get(room_id, [])
            if journals:
                if len(journals) == 1:
                    j = journals[0]
                    lines.append(f"A tattered journal lies here ({j['character_name']}, Day {j['day_of_death']}).")
                else:
                    names = ", ".join(f"{j['character_name']} (Day {j['day_of_death']})" for j in journals)
                    lines.append(f"{len(journals)} tattered journals lie here: {names}.")
        return "\n".join(lines) + "\n"

    def _load_npc_relationships(self) -> None:
        rel_path = Path("server/data/npc_relationships.yaml")
        if not rel_path.exists():
            return
        
        data = load_strict_yaml(rel_path) or {}
        
        relationships = data.get("relationships", [])
        npc_relationship_system.load_relationships(relationships, self.npcs)


def load_world() -> World:
    return World()
