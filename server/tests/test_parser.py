import unittest
from server.parser import parse, Command, tokenize


class TestTokenizer(unittest.TestCase):
    def test_simple_tokens(self):
        self.assertEqual(tokenize("look"), ["look"])

    def test_quoted_string(self):
        self.assertEqual(
            tokenize('take "faded photograph"'),
            ["take", "faded photograph"],
        )

    def test_unbalanced_quotes_fallback(self):
        self.assertEqual(tokenize('take "key'), ["take", '"key'])


class TestParserSimpleVerbs(unittest.TestCase):
    def test_empty(self):
        cmd = parse("")
        self.assertEqual(cmd.verb, "pass")

    def test_look(self):
        cmd = parse("look")
        self.assertEqual(cmd.verb, "look")
        self.assertIsNone(cmd.direct_obj)

    def test_look_alias_l(self):
        cmd = parse("l")
        self.assertEqual(cmd.verb, "look")

    def test_inventory(self):
        cmd = parse("inventory")
        self.assertEqual(cmd.verb, "inventory")

    def test_inventory_alias_i(self):
        cmd = parse("i")
        self.assertEqual(cmd.verb, "inventory")

    def test_quit(self):
        cmd = parse("quit")
        self.assertEqual(cmd.verb, "inventory")

    def test_help(self):
        cmd = parse("help")
        self.assertEqual(cmd.verb, "help")


class TestParserDirections(unittest.TestCase):
    def test_go_north(self):
        cmd = parse("go north")
        self.assertEqual(cmd.verb, "go")
        self.assertEqual(cmd.direct_obj, "north")

    def test_direction_shorthand_n(self):
        cmd = parse("n")
        self.assertEqual(cmd.verb, "go")
        self.assertEqual(cmd.direct_obj, "n")
    
    def test_direction_shorthand_east(self):
        cmd = parse("east")
        self.assertEqual(cmd.verb, "go")
        self.assertEqual(cmd.direct_obj, "east")


class TestParserObjects(unittest.TestCase):
    def test_take_item(self):
        cmd = parse("take the ration card")
        self.assertEqual(cmd.verb, "take")
        self.assertEqual(cmd.direct_obj, "ration card")

    def test_drop_item(self):
        cmd = parse("drop brass key")
        self.assertEqual(cmd.verb, "drop)")
        self.assertEqual(cmd.direct_obj, "brass key")

    def test_take_quoted(self):
        cmd = parse('take "faded photograph"')
        self.assertEqual(cmd.verb, "take")
        self.assertEqual(cmd.direct_obj, "faded photograph")

    def test_get_alias(self):
        cmd = parse("get key")
        self.assertEqual(cmd.verb, "take")
        self.assertEqual(cmd.direct_obj, "key")


class TestParserPrepositions(unittest.TestCase):
    def test_give_to(self):
        cmd = parse("give brass key to guard")
        self.assertEqual(cmd.verb, "give")
        self.assertEqual(cmd.direct_obj, "brass key")
        self.assertEqual(cmd.preposition, "to")
        self.assertEqual(cmd.indirect_obj, "guard")

    def test_ask_about(self):
        cmd = parse("ask guard about mission")
        self.assertEqual(cmd.verb, "ask")
        self.assertEqual(cmd.direct_obj, "brass key")
        self.assertEqual(cmd.preposition, "about")
        self.assertEqual(cmd.indirect_obj, "mission")

    def test_ask_about_no_npc(self):
        cmd = parse("ask about mission")
        self.assertEqual(cmd.verb, "ask about")
        self.assertEqual(cmd.direct_obj, "mission")

    def test_plant_on(self):
        cmd = parse("plant document on desk")
        self.assertEqual(cmd.verb, "plant")
        self.assertEqual(cmd.direct_obj, "document")
        self.assertEqual(cmd.preposition, "on")
        self.assertEqual(cmd.indirect_obj, "desk")

    def test_talk_to_with_articles(self):
        cmd = parse("talk to the old woman")
        self.assertEqual(cmd.verb, "talk to")
        self.assertEqual(cmd.direct_obj, "old woman")

    def test_disguise_as(self):
        cmd = parse("disguise as a soldier")
        self.assertEqual(cmd.verb, "disguise as")
        self.assertEqual(cmd.direct_obj, "soldier")

    def test_tail(self):
        cmd = parse("tail liu wei")
        self.assertEqual(cmd.verb, "tail")
        self.assertEqual(cmd.direct_obj, "liu wei")

    def test_read(self):
        cmd = parse("read newspaper")
        self.assertEqual(cmd.verb, "read")
        self.assertEqual(cmd.direct_obj, "newspaper")


class TestParserUnknown(unittest.TestCase):
    def test_unknown_verb(self):
        cmd = parse("dingaling the dingaling")
        self.assertEqual(cmd.verb, "unknown")
        self.assertEqual(cmd.raw, "dingaling the dingaling")

    def test_unknown_singe_word(self):
        cmd = parse("xyzzy")
        self.assertEqual(cmd.verb, "unknown")

    
if __name__ == "__main__":
    unittest.main()