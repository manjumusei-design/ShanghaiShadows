import heapq
from dataclasses import dataclass, field


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


@dataclass(order=True)
class ScheduledEvent:
    trigger_minute: int
    event_id: str = field(compare=False)
    payload: dict = field(compare=False)


class EventScheduler:
    def __init__(self):
        self.events = []

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

    def process(self, game_time: GameTime, broadcast):
        total = (game_time.day - 1) * 1440 + game_time.minute
        while self.events and self.events[0].trigger_minute <= total:
            event = heapq.heappop(self.events)
            for action in event.payload.get("actions", []):
                if action["type"] == "message_to_player":
                    broadcast(action["text"])
            if event.payload.get("recurring"):
                heapq.heappush(self.events,ScheduledEvent(
                        trigger_minute=event.trigger_minute + 1440,
                        event_id=event.event_id,
                        payload=event.payload,
                    ),
                )
                
    def to_payload(self):
        return [
            {
                "trigger_minute": event.trigger_minute,
                "event_id": event.event_id,
                "payload": event.payload,
            }
            for event in self.events
        ]
    
    def load_from_payload(self, rows):
        self.event = []
        for row in rows or []:
            self.add_event(ScheduledEvent(trigger_minute=int(row["trigger_minute"]),
                    event_id=row["event_id"],
                    payload=row.get("payload", {}),
                )
            )
