# -*- coding: utf-8 -*-
"""E2E-fixturens prisdata - en fixtur som ljuger gör resan värdelös.

Konsumentresan föll återkommande på att INGA butikskort var prissatta, och
det såg ut som flakighet. Det var det inte: fixturen valde förpackningsenhet
med MIN(unit), alltså i bokstavsordning, och sålde därför vetemjöl per liter
fast 18 recept mäter det i gram. De raderna gick inte att räkna om, blev
estimat, och estimat räknas inte in i coveragePercent. Under 85 % slutar en
kedja vara jämförbar - så en fixtur där varenda vara HADE ett pris kunde ge
noll prissatta kort, beroende på vilka recept veckan råkade välja.

Testet kör utan webbläsare och fångar alltså marginalen långt innan
Playwright-jobbet gör det."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e import fixture  # noqa: E402
from services.grocery.api import MIN_COVERAGE_FOR_COMPARISON  # noqa: E402
from services.grocery.pricing import RecipePricingEngine  # noqa: E402
from services.grocery.store import GroceryStore  # noqa: E402
from services.recipes import api as recipes_api  # noqa: E402
from services.recipes.store import RecipeStore  # noqa: E402


class PackageUnitChoice(unittest.TestCase):
    """Vilken enhet varan säljs i, givet hur recepten mäter den."""

    def test_mass_beats_volume_even_when_volume_is_alphabetically_first(self):
        # Vetemjöl: 18 recept i g, 5 i dl, 4 i msk. MIN(unit) gav 'dl'.
        self.assertEqual(fixture._forpackningsenhet([("dl", 5), ("g", 18), ("msk", 4)]), "g")

    def test_mass_beats_volume_even_when_volume_is_more_common(self):
        # En gramvara duger åt BÅDA sorternas recept - motorn väger om ett
        # styck till gram, men inte 300 g till ett antal morötter.
        self.assertEqual(fixture._forpackningsenhet([("dl", 40), ("g", 1)]), "g")

    def test_pieces_lose_to_everything_measurable(self):
        self.assertEqual(fixture._forpackningsenhet([("st", 30), ("g", 2)]), "g")
        self.assertEqual(fixture._forpackningsenhet([("st", 30), ("ml", 2)]), "ml")

    def test_the_choice_is_the_same_every_run(self):
        # Lika vanliga enheter i samma familj avgörs på namnet, inte på
        # ordningen raderna råkar komma i från databasen.
        self.assertEqual(fixture._forpackningsenhet([("dl", 3), ("ml", 3)]), "dl")
        self.assertEqual(fixture._forpackningsenhet([("ml", 3), ("dl", 3)]), "dl")

    def test_no_rows_is_no_unit_rather_than_a_crash(self):
        self.assertIsNone(fixture._forpackningsenhet([]))


class FixtureCoverage(unittest.TestCase):
    """Fixturen får inte TILLVERKA estimat.

    Ett estimat betyder att motorn inte kunde räkna om receptets mått till
    förpackningens enhet. I verkligheten händer det - 2 msk tomatpuré mot en
    gramtub är en äkta lucka - men en fixtur som säljer mjöl per liter
    tillverkar luckor som inte finns, och då mäter resan fel sak.

    Gränsen är satt strax över de sex äkta raderna, inte över de 33 som
    MIN(unit) gav. En lös gräns hade inte fångat något: totaltäckningen var
    98,4 % även med mjölet i literförpackning."""

    def test_the_fixture_manufactures_almost_no_estimates(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipes_api.DB_PATH = Path(tmp) / "recipes.db"
            recipes_api.clear_cache()
            recipes_api.bootstrap_if_empty()
            info = fixture.seed_grocery(Path(tmp) / "grocery.db", recipes_api.DB_PATH)
            db = GroceryStore(Path(tmp) / "grocery.db")
            rs = RecipeStore(recipes_api.DB_PATH)
            try:
                engine = RecipePricingEngine(db)
                store_id = info["stores"]["Willys"]
                rader = exakta = 0
                osäkra: dict[str, int] = {}
                for (recipe_id,) in rs.connection.execute("SELECT id FROM recipes"):
                    for ing in rs.get(recipe_id).get("ingredients", []):
                        if ing.get("pantryStaple") or ing.get("optional"):
                            continue
                        rader += 1
                        row = engine.price_item(ing["name"], ing.get("amount") or 1,
                                                ing.get("unit") or "st", "Willys", store_id)
                        if row is not None and row.get("exactPackaging", True):
                            exakta += 1
                        else:
                            osäkra.setdefault(f"{ing['name']} ({ing.get('unit')})", 0)
                            osäkra[f"{ing['name']} ({ing.get('unit')})"] += 1
            finally:
                db.close()
                rs.close()
                recipes_api.clear_cache()
        self.assertGreater(rader, 500, "receptbanken verkar inte ha laddats")
        self.assertLessEqual(sum(osäkra.values()), 10,
                             f"fixturen tillverkar estimat: {osäkra}")
        täckning = 100.0 * exakta / rader
        self.assertGreater(täckning, MIN_COVERAGE_FOR_COMPARISON + 10,
                           f"fixturen ger bara {täckning:.1f} % exakta rader av {rader}")


if __name__ == "__main__":
    unittest.main()
