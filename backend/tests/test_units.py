# -*- coding: utf-8 -*-
"""Enhetskonverteringens regressionslås (§51).

Volym konverteras aldrig till vikt utan ingrediensspecifik densitet, och
msk/tsk är MEDVETET okonverterbara i prissättningen: en gissad densitet ger
fel paketantal, och fel antal är ett fel pris. None är rätt svar."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.grocery.pricing import convert_amount  # noqa: E402


class UnitConversion(unittest.TestCase):
    def test_mass_and_volume_convert_within_their_families(self):
        self.assertEqual(convert_amount(1, "kg", "g"), 1000.0)
        self.assertEqual(convert_amount(500, "g", "kg"), 0.5)
        self.assertEqual(convert_amount(1, "l", "ml"), 1000.0)
        self.assertEqual(convert_amount(2, "dl", "ml"), 200.0)
        self.assertEqual(convert_amount(30, "cl", "dl"), 3.0)
        self.assertEqual(convert_amount(3, "hg", "g"), 300.0)

    def test_spoons_pieces_and_cross_family_refuse(self):
        for amount, source, target in [(1, "msk", "ml"), (1, "tsk", "g"),
                                       (2, "st", "g"), (400, "g", "l"),
                                       (1, "dl", "kg")]:
            self.assertIsNone(convert_amount(amount, source, target),
                              f"{amount} {source}->{target} ska vägra, inte gissa")

    def test_same_unit_is_identity(self):
        self.assertEqual(convert_amount(7, "st", "st"), 7.0)
        self.assertEqual(convert_amount(2.5, "dl", "dl"), 2.5)
