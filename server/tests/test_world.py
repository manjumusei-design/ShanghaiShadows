import unittest
from server.world import load_items, load_rooms, World


class TestLoadItems(unittest.TestCase):
    def test_loads_all_items(self):
        items = load_items("server/data/items.yaml")
        self.assertGreaterEqual(len(items), 10)
        self.assertIn("ration_card", items)
        self.assertIn("brass_key", items)

    def test_item_fields(self):
        items = load_items("server/data/items.yaml")
        card = items["ration_card"]
        self.assertEqual(card.id, "ration_card")
        self.assertEqual(card.name, "a tattered ration card")
        self.assertTrue(card.takeable)
        

class TestLoadRooms(unittest.TestCase):
    def test_loads_rooms_with_items(self):
        items = load_items("server/data/items.yaml")
        rooms = load_rooms("server/data/rooms/yaml", items)
        self.assertGreaterEqual(len(rooms), 150)
        bund = rooms["bund_dawn"]
        self.assertEqual(bund.title, "The Bund, Dawn")
        self.assertTrue(bund.items)
        self.assertIn("bund", bund.tags)

    def test_room_exits(self):
        items = load_items("server/data/items.yaml")
        rooms = load_rooms("server//data/rooms/yaml", items)
        bund = rooms["bund_dawn"]
        self.assertEqual(bund.exits["west"], "nanking_road")
        self.assertIn("east", bund.exits)

