# -*- coding: utf-8 -*-
"""C7: kassasumman utelämnade tyst de osäkra radernas kostnad.

"Total kassakostnad" summerade rader med `totalCost != null`; en osäker rad
(känt pris, gissat paketantal) bidrog med noll kronor. Bredvid stod "N med
uppskattat antal", men rubriksiffran var ändå lägre än kassan. Tre
msk-rader - honung, olivolja, tomatpuré - gjorde ~60 kr osynliga:
användaren budgeterade 640 och betalade 700.

Det saknade begreppet var inte "den här RADEN vet vi inte" - det fanns redan
- utan "den här SUMMAN är minst X".
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.grocery import GroceryStore, RawProduct  # noqa: E402
from services.grocery import api as grocery_api  # noqa: E402
from services.grocery.pricing import RecipePricingEngine  # noqa: E402

APP_JS = Path(__file__).resolve().parents[2] / "frontend" / "app" / "app.js"


def raw(name, *, quantity=None, unit=None, size=None):
    return RawProduct(chain="Willys", external_product_id=name, name=name,
                      store_id="2132", store_name="Willys", gtin=None, brand=None,
                      quantity=quantity, unit=unit, size=size)


class _Priced(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "grocery.db"
        self._real = grocery_api.DB_PATH
        grocery_api.DB_PATH = self.db_path
        self.addCleanup(lambda: setattr(grocery_api, "DB_PATH", self._real))
        grocery_api.clear_cache()
        self.addCleanup(grocery_api.clear_cache)

        self.db = GroceryStore(self.db_path)
        self.addCleanup(self.db.close)
        self.store = self.db.upsert_store(chain="Willys", external_store_id="2132",
                                          name="Willys test")
        self.engine = RecipePricingEngine(self.db)

    def _add(self, name, price, quantity, unit):
        product = self.db.find_or_create_product(
            raw(name, quantity=quantity, unit=unit, size=f"{quantity}{unit}"))
        self.db.upsert_current_price(product_id=product.id, store_id=self.store.id,
                                     regular_price=price)
        return product


class TheTotalSaysWhenItIsAFloor(_Priced):
    def test_an_uncertain_row_makes_the_total_a_floor(self):
        """Honung i msk mot en 350 g-burk: priset är känt, antalet gissat.
        Radens kostnad räknas inte in - då är summan en undre gräns."""
        self._add("Kycklingfilé Naturell", 79.90, 700, "g")
        self._add("Honung Flytande", 32.0, 350, "g")

        result = self.engine.price_list([
            {"name": "Kycklingfilé", "amount": 600, "unit": "g"},
            {"name": "Honung", "amount": 2, "unit": "msk"},
        ], "Willys", self.store.id)

        self.assertEqual(result["totalCheckoutCost"], 79.90)
        self.assertTrue(result["totalIsFloor"],
                        "en rad utan radtotal gör summan till ett golv")
        self.assertEqual(result["uncertainRows"], 1)

    def test_a_fully_certain_list_is_not_a_floor(self):
        """Motpolen: varje rad räknad, ingenting utelämnat. Då ÄR talet
        kassans belopp och ska visas som ett tal."""
        self._add("Kycklingfilé Naturell", 79.90, 700, "g")
        self._add("Ris Jasmin", 25.0, 1, "kg")

        result = self.engine.price_list([
            {"name": "Kycklingfilé", "amount": 600, "unit": "g"},
            {"name": "Ris", "amount": 900, "unit": "g"},
        ], "Willys", self.store.id)

        self.assertEqual(result["totalCheckoutCost"], 104.90)
        self.assertFalse(result["totalIsFloor"])
        self.assertEqual(result["uncertainRows"], 0)

    def test_a_missing_item_also_makes_the_total_a_floor(self):
        """En vara utan produktmatchning kostar inte noll i kassan heller."""
        self._add("Kycklingfilé Naturell", 79.90, 700, "g")

        result = self.engine.price_list([
            {"name": "Kycklingfilé", "amount": 600, "unit": "g"},
            {"name": "Saffran", "amount": 1, "unit": "g"},
        ], "Willys", self.store.id)

        self.assertTrue(result["totalIsFloor"])
        self.assertEqual(result["uncertainRows"], 0, "saknad vara är inte en osäker RAD")

    def test_an_empty_list_is_honestly_zero(self):
        result = self.engine.price_list([], "Willys", self.store.id)
        self.assertEqual(result["totalCheckoutCost"], 0)
        self.assertFalse(result["totalIsFloor"])

    def test_the_floor_travels_all_the_way_out_in_the_payload(self):
        self._add("Kycklingfilé Naturell", 79.90, 700, "g")
        self._add("Honung Flytande", 32.0, 350, "g")

        payload = grocery_api.price_week([
            {"name": "Kycklingfilé", "amount": 600, "unit": "g"},
            {"name": "Honung", "amount": 2, "unit": "msk"},
        ], chains=["Willys"])
        willys = next(r for r in payload["results"] if r["chain"] == "Willys")
        self.assertTrue(willys["totalIsFloor"])
        self.assertEqual(willys["uncertainRows"], 1)


class TheAppNeverPresentsAFloorAsExact(unittest.TestCase):
    """Acceptanskriteriet: rubriksiffran får aldrig presenteras som exakt när
    en osäker rad finns. Samma speglingsprincip som test_frontend_contract:
    app.js måste läsa serverns flagga, inte härleda en andra sanning."""

    def setUp(self):
        self.app = APP_JS.read_text(encoding="utf-8")

    def test_the_headline_label_is_chosen_by_the_servers_floor_flag(self):
        match = re.search(r"const floor = ([^;]+);", self.app)
        self.assertIsNotNone(match, "app.js läser ingen golvflagga")
        self.assertIn("data.totalIsFloor", match.group(1))

    def test_a_floor_total_is_labelled_minst_and_an_exact_one_is_not(self):
        match = re.search(r"const totalLabel = floor \? \"([^\"]+)\" : \"([^\"]+)\";", self.app)
        self.assertIsNotNone(match, "rubriken väljs inte av golvflaggan")
        floor_label, exact_label = match.groups()
        self.assertIn("minst", floor_label.lower())
        self.assertNotIn("minst", exact_label.lower())

    def test_the_sticky_header_says_minst_too(self):
        """Rubriken högst upp försvinner när man skrollar; den klistrade
        raden är det man faktiskt läser i butiken."""
        match = re.search(r"const stickyTotal = floor \? ([^;]+) :", self.app)
        self.assertIsNotNone(match)
        self.assertIn("minst", match.group(1))

    def test_the_uncertain_rows_are_counted_next_to_the_total(self):
        """"minst 640 kr + 3 varor utan säkert antal" - talet ensamt säger
        inte vad som saknas."""
        match = re.search(r"const uncertainNote = ([^;]+;)", self.app, re.S)
        self.assertIsNotNone(match, "app.js räknar inte de osäkra raderna")
        note = match.group(1)
        self.assertIn("data.uncertainRows", note)
        self.assertIn("utan säkert antal", note)


if __name__ == "__main__":
    unittest.main()
