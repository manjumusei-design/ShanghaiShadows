import heapq
from dataclasses import dataclass, field


@dataclass
class GameTime:
    minute: int = 0
    day: int = 1


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
