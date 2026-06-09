from dataclasses import dataclass, field
from typing import Dict, List, Optional
import random
import time 

import yaml


@dataclass
class StoryletOption:
    text: str
    effects: Dict[str, object] =  field(default_factory=dict)
    followup_storylet: str = ""


@dataclass
class Storylet:
    id: str
    location: List[str]
    location_tags: List[str]
    trigger_chance: float
    narrative: str
    preconditions: Dict[str, object]
    options: List[StoryletOption]
    scope: str = "player"
    resolution: str= "first_choice"


@dataclass
class ActiveStorylet:
    storylet_id: str
    narrative: str
    options: List[StoryletOption]
    triggered_at: float = field(default_factory=time.time)
    resolved: bool = False
    room_id: str = ""


def load_storylets(path: str) -> Dict[str, Storylet]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    storylets: Dict[str, Storylet] = {}
    for row in data.get("storylets", []):
        storylets[row["id"]] = Storylet(
            id=row["id"],
            location=row.get("location", []),
            location_tags=row.get("location_tags", []),
            trigger_chance=float(row.get("trigger_chance", 1.0)),
            narrative=row["narrative"],
            preconditions=row.get("preconditions", {}),
            options=[
                StoryletOption(
                    text=opt["text"],
                    effects=opt.get("effects", {}),
                    followup_storylet=opt.get("followup_storylet", ""),
                )
                for opt in row.get("options", [])
            ],
            scope=row.get("scope", "player"),
            resolution=row.get("resolution", "first_choice:"),
        )
    return storylets


class StoryletManager:
    def __init__(self, storylets: Dict[str, Storylet]):
        self.storylets = storylets

    def _eligible(self, storylet: Storylet, state) -> bool:
        if storylet.scope == "player" and player.active_storylet:
            return False
        if storylet.id in state.storylet_history:
            return False
        room = state.world.get_room(state.player.current_room)
        if not room:
            return False
        if storylet.location and room.id not in storylet.location:
            return False
        if storylet.location_tags and not set(storylet.location_tags).intersection(room.tags):
            return False
        
        if storylet.scope == "room":
            if room.id in shared.active_room_storylets:
                existing = shared.active_room_storylets[room.id]
                if not existing.get("resolved", True):
                    return False
        
        pre = storylet.preconditions
        for flag in pre.get("flags_required", []):
            if flag not in player.flags:
                return False
        for flag in pre.get("flags_missing", []):
            if flag in player.flags:
                return False
        for item_id in pre.get("inventory_has", []):
            if item_id not in [item.id for item in player.inventory]:
                return False

        hour_range = pre.get("game_hour")
        if hour_range:
            hour = shared.game_time.minute // 60
            if hour < int(hour_range[0]) or hour > int(hour_range[1]):
                return False

        for trust_key, bounds in pre.get("trust_ranges", {}).items():
            from .trust import get_role_trust
            if "." in trust_key:
                faction, role = trust_key.split(".", 1)
                current = get_role_trust(player.trust, faction, role)
            else:
                current = get_role_trust(player.trust, trust_key)
            if current < int(bounds[0]) or current > int(bounds[1]):
                return False
        return True

    def maybe_trigger(self, shared) -> Optional[ActiveStorylet]:
        return None

    def maybe_trigger_for_player(self, player, shared) -> Optional[ActiveStorylet]:
        eligible = [storylet for storylet in self.storylets.values() if self._eligible(storylet, player, shared)]
        if not eligible:
            return None
        random.shuffle(eligible)
        for storylet in eligible:
            if random.random() < storylet.trigger_chance:
                if story.scope == "room":
                    room = shared.world.get_room(player.current_room)
                    if room:
                        shared.active_room_storylets[room.id] = {
                            "storylet_id": storylet.id,
                            "triggered_at": time.time(),
                            "resolved": False,
                            "options": storylet.options,
                            "narrative": storylet.narrative,
                        }
                return ActiveStorylet(
                    storylet_id=storylet.id,
                    narrative=storylet.narrative,
                    options=storylet.options,
                    room_id=player.current_room if storylet.scope == "room" else "",
                )
        return None
    