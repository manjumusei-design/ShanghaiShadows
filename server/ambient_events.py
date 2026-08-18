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
    min_perception: int = 0
    probability: float = 0.1
    sound_range: Optional[int] = None
    cooldown_ticks: int = 0
    last_triggered: dict[str, int] = field(default_factory=dict)
    hidden_player: bool = False

    @property
    def is_danger(self) -> bool:
        return "danger" in self.tags

    def is_eligible(self, room_id: str, room_tags: list[str], district: str,
                    current_tick: int, player_perception: int = 0, player_hidden: bool = False) -> bool:
        if self.hidden_player and not player_hidden:
            return False

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
        truncated_threshold = min(50, self.min_perception - 10)
        if perception >= max(truncated_threshold, 10):
            fragments = self.text.split('.')
            if len(fragments) > 1:
                return fragments[0].strip() + '.'
        return ""


def load_ambient_events(path: str) -> list[AmbientEvent]:
    try:
        data = load_strict_yaml(path) or []
        return [_parse_event(e) for e in data]
    except FileNotFoundError:
        return []


def _parse_event(data: dict) -> AmbientEvent:
    time_range = None
    if 'time_range' in data:
        tr = data['time_range']
        if isinstance(tr, list) and len(tr) == 2:
            time_range = (int(tr[0]), int(tr[1]))

    return AmbientEvent(
        id=data.get('id', ''),
        text=data.get('text', ''),
        tags=data.get('tags', []),
        time_range=time_range,
        districts=data.get('districts', []),
        room_types=data.get('room_types', []),
        min_perception=data.get('min_perception', 0),
        probability=data.get('probability', 0.1),
        sound_range=data.get('sound_range'),
        cooldown_ticks=data.get('cooldown_ticks', 0),
        hidden_player=data.get('hidden_player', False),
    )


def check_ambient_trigger(events: list[AmbientEvent], room_id: str,
                          room_tags: list[str], district: str,
                          current_tick: int, player_perception: int = 0,
                          current_minute: Optional[int] = None,
                          player_hidden: bool = False) -> Optional[AmbientEvent]: 
    eligible = []
    for event in events:
        if event.is_eligible(room_id, room_tags, district, current_tick, player_perception, player_hidden):
            if event.time_range:
                if current_minute is None:
                    continue
                start, end = event.time_range
                if start <= end:
                    if not (start <= current_minute < end):
                        continue
                else:
                    if not (current_minute >= start or current_minute < end):
                        continue
            eligible.append(event)

    if not eligible:
        return None

    chosen = random.choice(eligible)
    chosen.last_triggered[room_id] = current_tick
    return chosen
