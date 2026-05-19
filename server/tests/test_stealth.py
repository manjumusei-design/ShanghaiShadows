import unittest

from server.npc import Npc
from server.stealth import Disguise, StealthSystem


class TestStealthSystem(unittest.TestCase):
    def setUp(self):
        disguises = {
            "coolie": Disguise(
                id="coolie",
                name="a dock coolie",
                apparent_faction="civilian",
                bonus = 10,
                description="test",
            )
        }
        self.system = StealthSystem(disguises)
        self.target = Npc(
            id="target",
            name="Target",
            description="test",
            faction="kempeitai",
            role="patrol",
            personality="watchful",
            awareness=60,
            faction_leader=False,
            schedule={},
            dialogue={},
        )











if __name__ == "__main__":
    unittest.main()