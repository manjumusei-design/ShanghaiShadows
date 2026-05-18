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