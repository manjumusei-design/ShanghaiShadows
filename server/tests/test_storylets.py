import unittest

from server.game import GameServer


class TestStorylets(unittest.TestCase):
    def test_storylets_load(self):
        server = GameServer()
        self.assertGreaterEqual(len(server.storylet_manager.storylets), 30)
        self.assertIn("wounded_courier", server.storylet_manager.storylets)

        
    def test_new_state_has_nested_trust(self):
        server = GameServer()
        state = server._new_state()
        self.assertIn("resistance", state.player.trust)
        self.assertIn("courier", state.player.trust["resistance"])

if __name__ == "__main__":
    unittest.main