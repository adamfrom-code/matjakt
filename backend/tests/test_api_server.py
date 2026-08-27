import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api_server import clean_text, parse_price, parse_willys_price  # noqa: E402


class ApiHelpersTest(unittest.TestCase):
    def test_clean_text(self):
        self.assertEqual(clean_text("  ekologisk\n mjölk "), "ekologisk mjölk")

    def test_parse_price(self):
        self.assertEqual(parse_price("Pris 18,90 kr"), 18.9)
        self.assertIsNone(parse_price("pris saknas"))

    def test_parse_willys_price(self):
        self.assertEqual(parse_willys_price("24 95"), 24.95)
