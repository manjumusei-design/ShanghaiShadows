import unittest
from server.npc import Npc, load_npcs, get_dialogue


class TestLoadNpcs(unittest.TestCase):
    def test_loads_npcs(self):
        npcs = load_npcs("server/data/npcs.yaml")
        self.assertIn("liu_wei", npcs)
        npc = npcs["liu_wei"]
        self.assertEqual(npc.name, "Liu Wei, the rickshaw puller")
        self.assertEqual(npc.faction, "civilian")
        self.assertEqual(npc.role, "worker")
         

class TestGetDialogue(unittest.TestCase):
    def setUp(self):
        self.npc = Npc(
            id="test",
            name="Test",
            description="A test npc.",
            faction="civilian",
            role="resident",
            personality="test",
            awareness=50,
            faction_leader=False,
            schedule={},
            dialogue={
                "greeting": ["Hello."],
                "friendly": ["Good friend."],
                "hostile": ["Go away."],
            },
        )
    
    def test_friendly_trust(self):
        trust = {"civilian": {"resident": 80}}
        line = get_dialogue(self.npc, trust)
        self.assertEqual(line, "Good friend.")

    def hostile_trust(self):
        trust = {"civilian": {"resident": 20}}
        line = get_dialogue(self.npc, trust)
        self.assertEqual(line, "Go away.")

        