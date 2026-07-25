import heapq
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class GameTime:
    minute: int = 0
    day: int = 1

    @property
    def hour(self) -> int:
        return (self.minute // 60) % 24
    
    
def time_str(gt: GameTime) -> str:
    h = (gt.minute // 60)  % 24
    m = gt.minute % 60
    return f"Day {gt.day}, {h:02d}:{m:02d}"



EVENTS = [
    {"minute": 0,    "text": "Silence falls over the city as midnight passes.",
     "effect": {"patrol_density_mult": 0.5, "duration": 120}},
    {"minute": 360,  "text": "The dawn broadcast crackles to life from a hidden radio loud enough to wake the dead.",
     "effect": {"reveal_rumour": True}},
    {"minute": 540,  "text": "Resistance leaflets flutter through the morning streets, telling civilians to fight for their home.",
     "effect": {"ccp_influence": 1, "patrol_density_mult": 1.1, "duration": 180}},
    {"minute": 600,  "text": "The morning market bustles with activity.",
     "effect": {"vendor_restock": 25}},
    {"minute": 720,  "text": "Patrols units are now changing shifts across the city.",
     "effect": {"reset_patrol_density": True}},
    {"minute": 900,  "text": "Afternoon rumours spread through the teahouses through the noises of .",
     "effect": {"spread_rumour": True}},
    {"minute": 1080, "text": "Dusk falls. Shadows lengthen in the alleyways.",
     "effect": {"stealth_modifier": 5, "duration": 120}},
    {"minute": 1200, "text": "Curfew is in effect. All civilians must be indoors.",
     "effect": {"curfew_start": True}},
    {"minute": 1380, "text": "Night raids intensify in high tension districts.",
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

    def add_event(self,   event: ScheduledEvent):
        heapq.heappush(self.events, event)

    def load_from_yaml(self, path: str):
        import yaml
        with open(path, "r", encoding = "utf-8") as f:
            data = yaml.safe_load(f)
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
        self.event = []
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
        if random.random() < 0.3:
            broadcast(f"A witness has reported the murder of {victim_name} to the Kempeitai.")