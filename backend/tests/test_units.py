# -*- coding: utf-8 -*-
"""Enhetskonverteringens regressionslås (§51).

Volym konverteras aldrig till vikt utan ingrediensspecifik densitet, och
msk/tsk KONVERTERAR inom volymfamiljen (1 msk = 15 ml är en definition,
ingen gissning) men vägrar mot vikt: en gissad densitet ger
fel paketantal, och fel antal är ett fel pris. None är rätt svar."""

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.grocery.pricing import convert_amount, effective_package  # noqa: E402


class UnitConversion(unittest.TestCase):
    def test_mass_and_volume_convert_within_their_families(self):
        self.assertEqual(convert_amount(1, "kg", "g"), 1000.0)
        self.assertEqual(convert_amount(500, "g", "kg"), 0.5)
        self.assertEqual(convert_amount(1, "l", "ml"), 1000.0)
        self.assertEqual(convert_amount(2, "dl", "ml"), 200.0)
        self.assertEqual(convert_amount(30, "cl", "dl"), 3.0)
        self.assertEqual(convert_amount(3, "hg", "g"), 300.0)

    def test_spoons_convert_within_volume(self):
        self.assertEqual(convert_amount(1, "msk", "ml"), 15.0)
        self.assertEqual(convert_amount(2, "tsk", "ml"), 10.0)
        self.assertEqual(convert_amount(1, "krm", "ml"), 1.0)
        self.assertEqual(convert_amount(1, "msk", "dl"), 0.15)

    def test_spoons_pieces_and_cross_family_refuse(self):
        for amount, source, target in [(1, "tsk", "g"),
                                       (2, "st", "g"), (400, "g", "l"),
                                       (1, "dl", "kg")]:
            self.assertIsNone(convert_amount(amount, source, target),
                              f"{amount} {source}->{target} ska vägra, inte gissa")

    def test_same_unit_is_identity(self):
        self.assertEqual(convert_amount(7, "st", "st"), 7.0)
        self.assertEqual(convert_amount(2.5, "dl", "dl"), 2.5)


def _product(size=None, name="Vara", quantity=None, unit=None):
    """Så mycket av en produkt som effective_package faktiskt läser."""
    return types.SimpleNamespace(size=size, name=name, quantity=quantity,
                                 unit=unit, package_conflict=None)


class MultipackSize(unittest.TestCase):
    """C2: ett multipack är N förpackningar, inte en.

    Mass/volymuttrycket lästes förr rakt av och returnerade direkt, så
    "Krossade Tomater 390 g 4-pack" blev 390 g. En vecka som behövde
    1 500 g fick då fyra FYRPACK - sexton burkar - på en rad som ändå var
    märkt exactPackaging=True och gick in i den säkra totalen."""

    def test_the_four_strings_from_the_report(self):
        for size, expected in [("450 g 2-pack", (900.0, "g")),
                               ("33 cl 24-pack", (792.0, "cl")),
                               ("390 g 4-pack", (1560.0, "g")),
                               ("2x120g", (240.0, "g"))]:
            with self.subTest(size=size):
                self.assertEqual(effective_package(_product(size=size)), expected)

    def test_the_soda_case_in_litres(self):
        """33 cl × 24 = 7,92 l, inte 0,33 l."""
        amount, unit = effective_package(_product(size="33 cl 24-pack"))
        self.assertAlmostEqual(convert_amount(amount, unit, "l"), 7.92, places=4)

    def test_a_count_before_the_weight_is_pieces_inside_one_package(self):
        """Ordningen bär betydelsen: "18-pack 750 g" är arton kakor som
        TILLSAMMANS väger 750 g. Att multiplicera där vore 13,5 kg kaka."""
        self.assertEqual(effective_package(_product(size="18-pack 750 g")), (750.0, "g"))

    def test_st_is_not_a_multipack(self):
        """"Köttbullar 500 g 25 st" är 25 bullar i ETT paket."""
        self.assertEqual(effective_package(_product(size="500 g 25 st")), (500.0, "g"))

    def test_pk_and_p_forms_count_too(self):
        self.assertEqual(effective_package(_product(size="330 ml 6 pk")), (1980.0, "ml"))
        self.assertEqual(effective_package(_product(size="1,5 l 4-p")), (6.0, "l"))

    def test_a_lone_count_is_still_pieces(self):
        """Utan massa i strängen är "Ägg 6p" fortfarande 6 st."""
        self.assertEqual(effective_package(_product(size="6p", name="Ägg")), (6.0, "st"))

    def test_an_explicit_import_quantity_still_wins(self):
        """Kedjans egen mängd är starkare än vilken texttolkning som helst."""
        self.assertEqual(
            effective_package(_product(size="450 g 2-pack", quantity=900.0, unit="g")),
            (900.0, "g"))
