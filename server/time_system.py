import heapq
from dataclasses import dataclass, field
from typing import List, Optional

from .content_validation import load_strict_yaml


@dataclass
class GameTime:
    minute: int = 0
    day: int = 1

    @property
    def hour(self) -> int:
        return (self.minute // 60) % 24


def time_str(gt: GameTime) -> str:
    h = (gt.minute // 60) % 24
    m = gt.minute % 60
    return f"Day {gt.day}, {h:02d}:{m:02d}"


EVENTS = [
    {"minute": 0,    "text": "Midnight settles over the city, leaving patrol lamps, shuttered windows, and the careful sounds people make while pretending to sleep.",
     "effect": {"patrol_density_mult": 0.5, "duration": 120}},
    {"minute": 360,  "text": "The dawn broadcast crackles through thin walls, praising order while families count rice and decide which errands can wait.",
     "effect": {"reveal_rumour": True}},
    {"minute": 540,  "text": "Fresh leaflets appear on damp walls before the patrols scrape them away, their wet ink passing from hand to hand.",
     "effect": {"ccp_influence": 1, "patrol_density_mult": 1.1, "duration": 180}},
    {"minute": 600,  "text": "The morning market opens in layers: shutters, baskets, bargaining voices, and ration queues already bending around the corner.",
     "effect": {"vendor_restock": 25}},
    {"minute": 720,  "text": "Patrol shifts change across the city, leaving corners briefly crowded with boots, cigarette smoke, and papers checked twice.",
     "effect": {"reset_patrol_density": True}},
    {"minute": 900,  "text": "Afternoon rumours pass through teahouses and market stalls, gathering prices, names, denials, and half-truths with every cup.",
     "effect": {"spread_rumour": True}},
    {"minute": 1080, "text": "Dusk lengthens the alleyways, and every errand begins to measure itself against the curfew lamps being lit.",
     "effect": {"stealth_modifier": 5, "duration": 120}},
    {"minute": 1200, "text": "Curfew takes hold across Shanghai, turning open streets into official ground and doorways into whispered negotiations.",
     "effect": {"curfew_start": True}},
    {"minute": 1380, "text": "Night raids gather in tense districts, where one mistaken address can empty a staircase and silence a whole lane.",
     "effect": {"kempeitai_raid_chance": 0.2, "duration": 60}},
]


@dataclass(order=True)
class ScheduledEvent:
    trigger_minute: int
    event_id: str = field(compare=False)
    payload: dict = field(compare=False)
    effect: Optional[dict] = field(compare=False, default=None)


class EventScheduler:
    def __init__(self):
        self.events = []
        self._daily_loaded = False
        self.load_daily_events()

    def load_daily_events(self):
        if self._daily_loaded:
            return
        existing_ids = {e.event_id for e in self.events}
        for ev in EVENTS:
            event_id = f"daily_{ev['minute']}"
            if event_id not in existing_ids:
                self.add_event(ScheduledEvent(
                    trigger_minute=ev["minute"],
                    event_id=event_id,
                    payload={
                        "actions": [{"type": "message_to_player", "text": ev["text"]}],
                        "effect": ev.get("effect"),
                        "recurring": True,
                    },
                    effect=ev.get("effect"),
                ))
        self._daily_loaded = True

    def add_event(self, event: ScheduledEvent):
        heapq.heappush(self.events, event)

    def load_from_yaml(self, path: str):
        data = load_strict_yaml(path)
        for ev in data.get("events", []):
            self.add_event(ScheduledEvent(
                    trigger_minute=ev["trigger_time"],
                    event_id=ev["event_id"],
                    payload=ev,
                )
            )

    def process(self, game_time: GameTime, broadcast) -> List[dict]:
        total = (game_time.day - 1) * 1440 + game_time.minute
        effects = []
        while self.events and self.events[0].trigger_minute <= total:
            event = heapq.heappop(self.events)
            for action in event.payload.get("actions", []):
                if action["type"] == "message_to_player":
                    broadcast(action["text"])
            eff = event.effect or event.payload.get("effect")
            if eff:
                effects.append(eff)
            if event.payload.get("type") == "witness_report":
                self._handle_witness_report(event.payload, broadcast, game_time)
            if event.payload.get("recurring"):
                heapq.heappush(self.events,ScheduledEvent(
                        trigger_minute=event.trigger_minute + 1440,
                        event_id=event.event_id,
                        payload=event.payload,
                        effect=event.effect,
                    ),
                )
        return effects

    def to_payload(self):
        return [
            {
                "trigger_minute": event.trigger_minute,
                "event_id": event.event_id,
                "payload": event.payload,
                "effect": event.effect,
            }
            for event in self.events
        ]

    def load_from_payload(self, rows):
        self.events = []
        self._daily_loaded = False
        for row in rows or []:
            self.add_event(ScheduledEvent(
                    trigger_minute=int(row["trigger_minute"]),
                    event_id=row["event_id"],
                    payload=row.get("payload", {}),
                    effect=row.get("effect") or row.get("payload", {}).get("effect"),
                )
            )
        self.load_daily_events()

    def schedule(self, event_id: str, trigger_minute: int, payload: dict):
        self.add_event(ScheduledEvent(
            trigger_minute=trigger_minute,
            event_id=event_id,
            payload=payload,
        ))

    def _handle_witness_report(self, payload: dict, broadcast, game_time: GameTime) -> None:
        import random
        victim_name = payload.get("victim_name", "someone")
        if random.random() < 0.30:
            broadcast(f"A witness has reported the murder of {victim_name} to the Kempeitai.")
