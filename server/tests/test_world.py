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


class TestWorld(unittest.TestCase):
    def test_get_room(self):
        world = World()
        room = world.get_room("bund_dawn")
        self.assertIsNotNone(room)
        self.assertEqual(room.id, "bund_dawn")

    def test_get_room_missing(self):
        world = World()
        self.assertIsNone(world.get_room("nonexistent"))

    def test_format_room_contains_title(self):
        world = World()
        text = world.format_room("bund_dawn")
        self.assertIn("The Bund, Dawn", text)

    def test_format_room_contains_items(self):
        world = World()
        text = world.format_room("bund_dawn")
        self.assertIn("You see here:", text)
        self.assertIn("The Bund, Dawn", text)


    def test_format_room_contains_exits(self):
        world = World()
        text = world.format_room("bund_dawn")
        self.assertIn("Exits:", text)
        self.assertIn("west", text)

if __name__ == "__main__":
    unittest.main()