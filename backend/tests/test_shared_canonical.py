# -*- coding: utf-8 -*-
"""Tester för den kanoniska ingrediensmodellen.

De viktigaste testerna här är de NEGATIVA. En matchningsmodell som säger ja
för ofta är värdelös på ett sätt som är svårt att upptäcka: den ser ut att
fungera, den hittar massor av recept, och först i köket märker någon att
kycklingbuljong inte var kyckling. Varje rad i FALSKA_VÄNNER är ett par som
en substrängsmatchning hade klarat fel.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.recipes import normalize_ingredient_id  # noqa: E402
from services.shared.canonical import (  # noqa: E402
    DEFAULT_PANTRY_STAPLES,
    best_match,
    canonical_id,
    canonical_ingredient,
    general_id,
    satisfies,
)
from services.shared.matching import resolve_staples  # noqa: E402


# Par som ser besläktade ut för en substrängsmatchning men är olika varor.
# Tre av dem står i uppgiften; resten är samma misstag i andra kläder.
FALSKA_VÄNNER = [
    ("kycklingbuljong", "Kyckling"),
    ("Kycklingbuljongtärning", "Kyckling"),
    ("tomatsås", "Tomat"),
    ("Tomatpuré", "Tomater"),
    ("kanelknäcke", "Kanel"),
    ("Kokosmjölk", "Mjölk"),
    ("Jordnötssmör", "Smör"),
    ("Vitlökssalt", "Vitlök"),
    ("Soltorkade tomater", "Tomater"),
    ("Krossade tomater", "Tomater"),
    ("Purjolök", "Gul lök"),
    ("Grekisk yoghurt", "Yoghurt"),
    ("Gravad lax", "Lax"),
    ("Äppelmos", "Äpple"),
    ("Lingonsylt", "Lingon"),
]


class CanonicalIdTest(unittest.TestCase):
    def test_id_matches_the_recipe_banks_own_key(self):
        """Kanoniseringen får inte driva iväg från receptbankens
        normalized_id - det är hela poängen med att den delas."""
        for name in ("Kycklingfilé", "Crème fraiche", "Gul lök", "Ägg"):
            self.assertEqual(canonical_id(name), normalize_ingredient_id(name), name)

    def test_case_and_accents_fold_away(self):
        self.assertEqual(canonical_id("KYCKLINGFILÉ"), canonical_id("kycklingfile"))
        self.assertEqual(canonical_id("  Crème  Fraiche "), canonical_id("creme fraiche"))

    def test_synonyms_and_plurals_collapse_to_one_id(self):
        self.assertEqual(canonical_id("tomat"), canonical_id("Tomater"))
        self.assertEqual(canonical_id("morot"), canonical_id("Morötter"))
        self.assertEqual(canonical_id("sojasås"), canonical_id("Soja"))
        self.assertEqual(canonical_id("fetaost"), canonical_id("Feta"))

    def test_empty_input_has_no_id(self):
        for empty in ("", "   ", None):
            self.assertEqual(canonical_id(empty), "")


class SatisfiesTest(unittest.TestCase):
    def test_identical_ingredients_match_exactly(self):
        self.assertEqual(satisfies("Ris", "ris"), "exact")

    def test_a_specific_kind_covers_the_general_ingredient(self):
        """Har jag gul lök har jag lök."""
        self.assertEqual(satisfies("Gul lök", "Lök"), "specific")
        self.assertEqual(satisfies("Basmatiris", "Ris"), "specific")
        self.assertEqual(satisfies("Vispgrädde", "Grädde"), "specific")

    def test_the_general_ingredient_covers_a_specific_kind(self):
        """Den som skriver "kyckling" i sitt skafferi menar den kyckling som
        ligger i kylen, och receptet som säger "Kycklingfilé" ska hittas.
        Utan den här riktningen fungerar inte appens första milstolpe."""
        self.assertEqual(satisfies("kyckling", "Kycklingfilé"), "generic")
        self.assertEqual(satisfies("lök", "Gul lök"), "generic")
        self.assertEqual(satisfies("pasta", "Spaghetti"), "generic")

    def test_two_kinds_of_the_same_thing_are_substitutes(self):
        self.assertEqual(satisfies("Kycklinglårfilé", "Kycklingfilé"), "substitute")
        self.assertEqual(satisfies("Rödlök", "Gul lök"), "substitute")
        self.assertEqual(satisfies("Nötfärs", "Blandfärs"), "substitute")

    def test_false_friends_never_match(self):
        for have, need in FALSKA_VÄNNER:
            self.assertIsNone(satisfies(have, need), f"{have!r} borde inte duga för {need!r}")

    def test_unrelated_ingredients_never_match(self):
        for have, need in [("Ris", "Pasta"), ("Lax", "Torsk"), ("Mjölk", "Ägg"),
                           ("Basilika", "Persilja"), ("Röda linser", "Vita bönor")]:
            self.assertIsNone(satisfies(have, need), f"{have!r} / {need!r}")

    def test_nothing_matches_an_empty_name(self):
        self.assertIsNone(satisfies("", "Lök"))
        self.assertIsNone(satisfies("Lök", ""))


class GeneralIdTest(unittest.TestCase):
    def test_a_qualifier_plus_one_ingredient_generalises(self):
        self.assertEqual(general_id("Gul lök"), canonical_id("Lök"))
        self.assertEqual(general_id("Fryst spenat"), canonical_id("Spenat"))
        self.assertEqual(general_id("Riven ost"), canonical_id("Ost"))

    def test_two_real_ingredients_do_not_generalise(self):
        """"Lök & vitlök" är två varor, inte en bestämd form av någon av
        dem - och "krossade tomater" är en konservburk."""
        self.assertIsNone(general_id("Lök & vitlök"))
        self.assertIsNone(general_id("Krossade tomater"))
        self.assertIsNone(general_id("Garam masala"))

    def test_a_single_compound_word_is_never_split_automatically(self):
        """Det steget är exakt det som hade gjort kokosmjölk till mjölk."""
        self.assertIsNone(general_id("Kokosmjölk"))
        self.assertIsNone(general_id("Jordnötssmör"))
        self.assertIsNone(general_id("Kanelknäcke"))


class BestMatchTest(unittest.TestCase):
    def test_the_surest_relation_wins(self):
        """Har man både kyckling och kycklingfilé hemma är det filén som
        matchar receptets filé - inte det allmänna ordet."""
        name, relation = best_match(["kyckling", "Kycklingfilé"], "Kycklingfilé")
        self.assertEqual((name, relation), ("Kycklingfilé", "exact"))

    def test_order_of_the_pantry_never_changes_the_answer(self):
        forward = best_match(["kyckling", "Kycklinglårfilé"], "Kycklingfilé")
        backward = best_match(["Kycklinglårfilé", "kyckling"], "Kycklingfilé")
        self.assertEqual(forward, backward)

    def test_no_match_returns_nothing(self):
        self.assertEqual(best_match(["Ris", "Pasta"], "Kycklingfilé"), (None, None))


class PantryStapleTest(unittest.TestCase):
    def test_the_cupboard_basics_are_staples(self):
        for name in ("Salt", "Peppar", "Olja", "Vetemjöl", "Socker"):
            self.assertIn(canonical_id(name), DEFAULT_PANTRY_STAPLES, name)

    def test_real_shopping_items_are_not_staples(self):
        """Banken flaggar ris, lök och vitlök som pantryStaple i en del
        recept. Standarduppsättningen gör det inte: ett "kan lagas nu" som
        förutsätter ris man inte har är ett löfte appen inte kan hålla."""
        for name in ("Ris", "Lök", "Vitlök", "Honung", "Parmesan", "Kycklingfilé"):
            self.assertNotIn(canonical_id(name), DEFAULT_PANTRY_STAPLES, name)

    def test_the_caller_can_add_and_remove_staples(self):
        staples = resolve_staples(extra=["Vitlök"], exclude=["Smör"])
        self.assertIn(canonical_id("Vitlök"), staples)
        self.assertNotIn(canonical_id("Smör"), staples)
        self.assertIn(canonical_id("Salt"), staples)

    def test_resolving_staples_never_mutates_the_default(self):
        before = set(DEFAULT_PANTRY_STAPLES)
        resolve_staples(extra=["Kycklingfilé"], exclude=["Salt"])
        self.assertEqual(set(DEFAULT_PANTRY_STAPLES), before)


class CanonicalIngredientTest(unittest.TestCase):
    def test_it_describes_an_ingredient_as_data(self):
        described = canonical_ingredient("Gul lök")
        self.assertEqual(described["id"], canonical_id("Gul lök"))
        self.assertEqual(described["name"], "Gul lök")
        self.assertEqual(described["generalId"], canonical_id("Lök"))
        self.assertFalse(described["isPantryStaple"])

    def test_a_staple_is_marked_as_one(self):
        self.assertTrue(canonical_ingredient("Salt")["isPantryStaple"])


if __name__ == "__main__":
    unittest.main()
