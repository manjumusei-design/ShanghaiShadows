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
         
