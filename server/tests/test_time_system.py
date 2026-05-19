import unittest
from server.time_system import GameTime, time_str, EventScheduler, ScheduledEvent


class TestGameTime(unittest.TestCase):
    def test_time_str_midnight(self):
        gt = GameTime(minute=0, day=1)
        self.assertEqual(time_str(gt), "Day 1, 00:00")

    def test_time_str_morning(self):
        gt = GameTime
        self.assertEqual(time_str(gt), "Day 1, 06:00")

    def test_time_str_evening(self):
        gt = GameTime(minute=360, day=1)
        self.assertEqual(time_str(gt), "Day 1, 20:00")
    

class TestEventScheduler(unittest.TestCase):
    def test_add_and_process(self):
        sched = EventScheduler()
        sched.add_event(ScheduledEvent(trigger_minute=10, event_id="test", payload={"actions": [{"type": "message_to_player", "text": "Test event"}]}))
        self.assertEqual(len(sched.events), 1)
        calls = []
        def broadcast(msg):
            calls.append(msg)
        gt = GameTime(minute=5, day=1)
        sched.process(gt, broadcast)
        self.assertEqual(len(sched.events), 0)
        gt.minute = 10
        sched.process(gt, broadcast)
        self.assertEqual(len(calls), 0)
        self.assertEqual(len(sched.events), 0)

    def test_message_to_player(self):
        sched = EventScheduler()
        sched.add_event(
            ScheduledEvent(
                trigger_minute=10,
                event_id="msg",
                payload={
                    "actions": [
                        {"type": "message_to_player", "text": "Hello"}
                    ]
                },
            )
        )
        calls = []
        sched.process(GameTime(minute=10, day=1), calls.append)
        self.assertEqual(calls, ["Hello"])


if __name__ == "__main__":
    unittest.main()
