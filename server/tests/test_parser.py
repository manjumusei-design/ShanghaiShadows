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

        