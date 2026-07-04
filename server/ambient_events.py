import random
from dataclasses import dataclass, field
from typing import Optional
import yaml


@dataclass
class AmbientEvent:
    id: str
    text: str
    tags: list[str] = field(default_factory=list)
    time_range: Optional[tuple[int, int]] = None
    districts: list[str] = field(default_factory=list)
    room_types: list[str] = field(default_factory=list)
    min_perception: int = 0 # Need to change 
    probability: float = 0.1
    sound_range: Optional[int] = None
    cooldown_tiks: int = 0
    last_triggered: dict[str, int] = field(default_factory=dict)

    def is_eligible(self, room_id: str, room_tags: list[str], district: str,
                    current_tick: int, player_perception: int = 0) -> bool:
        if player_perception < self.min_perception:
            return False

        if self.districts and district not in self.districts:
            return False

        if self.room_types:
            if not any(tag in room_tags for tag in self.room_types):
                return False

        if self.cooldown_ticks > 0:
            last = self.last_triggered.get(room_id, -self.cooldown_ticks)
            if current_tick - last < self.cooldown_ticks:
                return False

        if random.random() > self.probability:
            return False

        return True
    
    def get_text_for_perception(self, perception: int) -> str:
        if perception >= self.min_perception:
            return self.text
        elif perception >= self.min_perception - 10:
            fragments = self.text.split(". ")
            if len(fragments) > 1:
                return fragments[0].strip() + '.'
        return ""
    

def load_ambient_events(path: str) -> list[AmbientEvent]:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or []
        return [_parse_event(e) for e in data]
    except FileNotFoundError:
        return []