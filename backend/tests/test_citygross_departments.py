# -*- coding: utf-8 -*-
"""D6: City Gross tappar hela avdelningar tyst.

Axfood-providern har spårat `failed_categories` sedan den skrevs, och
`importer._run` läser fältet på varje provider: en icke-tom lista gör
körningen PARTIELL i stället för "success med errors=0". City Gross loggade
och gick vidare, så en förlorad avdelning såg ut som en lyckad natt.

Tre vägar en avdelning kan försvinna, och alla tre var tysta:

  * avdelningssidan slutar svara (kategorifelet loggades och `break`:ades),
  * City Gross döper om avdelningen, så allow-listan på NAMN inte matchar
    och avdelningen aldrig ens hämtas,
  * avdelningen svarar men returnerar noll produkter.

30 %-regeln i publiceringen fångar bara om över 70 % av katalogen försvinner.
Skafferiet är ~12 % av ~8 700 produkter, alltså aldrig.
"""

import io
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.grocery import RawProduct  # noqa: E402
from services.grocery.providers import citygross as cg_module  # noqa: E402
from services.grocery.providers.citygross import (  # noqa: E402
    FOOD_DEPARTMENTS, CityGrossProvider,
)

# Sid-id:n behöver bara vara unika i fixturen - det är NAMNEN allow-listan
# matchar på, och det är namnen som försvinner när City Gross döper om något.
DEPARTMENT_IDS = {name: 1500 + index for index, name in enumerate(sorted(FOOD_DEPARTMENTS))}

PRODUKT = {
    "id": "101233933_ST", "gtin": "7340083443893", "name": "Mellanmjölk",
    "brand": "GARANT", "superCategory": "Mejeri, ost & ägg", "descriptiveSize": "1,5L",
    "productStoreDetails": {
        "p_has_price": True,
        "prices": {"currentPrice": {"price": 16.5, "unit": "PCE"},
                   "ordinaryPrice": {"price": 16.5, "unit": "PCE"},
                   "memberPrice": None, "promotions": [], "activePromotion": None},
    },
}


class FakeResponse(io.BytesIO):
    def __init__(self, body=b"", *, status=200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _json(payload):
    return FakeResponse(json.dumps(payload).encode("utf-8"))


def navigation(names):
    """Navigationsträdet som det ser ut när `names` är de matavdelningar
    sajten erbjuder. Säsongsidan ligger alltid med och ska aldrig hämtas."""
    barn = [{"id": DEPARTMENT_IDS[name], "name": name, "type": "ProductCategoryPage",
             "link": {"url": "/matvaror/x", "categoryPageId": str(DEPARTMENT_IDS[name])},
             "children": []}
            for name in names]
    barn.append({"id": 4492, "name": "Jul", "type": "ProductCategoryPage",
                 "link": {"url": "/matvaror/jul", "categoryPageId": "4492"}, "children": []})
    return {"data": {"tree": {"id": 66, "name": "root", "children": [
        {"id": 69, "name": "Matvaror", "type": "ProductFolderPage",
         "link": {"url": "/matvaror", "categoryPageId": None}, "children": barn}]}}}


def category_page(*produkter):
    return {"items": list(produkter), "totalCount": len(produkter),
            "pageSize": 100, "currentPage": 0, "totalPages": 1}


def _http_error(code):
    return urllib.error.HTTPError("https://example.test", code, "fel", {}, io.BytesIO(b""))


class Avdelningsbokslutet(unittest.TestCase):
    """Vad providern själv rapporterar efter en körning."""

    def setUp(self):
        self._orig = cg_module.urllib.request.urlopen
        self._sleep = cg_module.time.sleep
        cg_module.time.sleep = lambda s: None
        self.addCleanup(lambda: setattr(cg_module.time, "sleep", self._sleep))
        self.addCleanup(lambda: setattr(cg_module.urllib.request, "urlopen", self._orig))

    def _kör(self, erbjudna, tomma=(), trasiga=()):
        """Kör en insamling där `erbjudna` avdelningar finns i navigationen,
        `tomma` svarar utan produkter och `trasiga` inte svarar alls."""
        tomma_id = {DEPARTMENT_IDS[n] for n in tomma}
        trasiga_id = {DEPARTMENT_IDS[n] for n in trasiga}

        def _open(request, timeout=None):
            url = request.full_url
            if "api/v1/navigation" in url:
                return _json(navigation(erbjudna))
            if "Loop54/category/" in url:
                kid = int(url.split("Loop54/category/")[1].split("/")[0])
                if kid in trasiga_id:
                    raise _http_error(500)
                if kid in tomma_id:
                    return _json(category_page())
                return _json(category_page(PRODUKT))
            return _json({"searchResults": {"products": [], "totalCount": 0}})

        cg_module.urllib.request.urlopen = _open
        provider = CityGrossProvider(search_terms=[])
        provider.get_products("3209")
        return provider

    def test_en_hel_insamling_ar_inte_partiell(self):
        """Motprovet först: elva av elva avdelningar, inga fel. Utan det här
        vore spårningen bara ett sätt att göra varje natt partiell."""
        provider = self._kör(sorted(FOOD_DEPARTMENTS))
        self.assertEqual(provider.failed_categories, [])
        self.assertEqual(sorted(provider.collected_categories), sorted(FOOD_DEPARTMENTS))

    def test_ett_kategorifel_gor_korningen_partiell(self):
        """D6:s acceptanskriterium, på providernivå. Förut loggades felet och
        `break`:ades - körningen rapporterades success."""
        provider = self._kör(sorted(FOOD_DEPARTMENTS), trasiga=["Skafferiet"])
        self.assertIn("Skafferiet", provider.failed_categories)
        self.assertNotIn("Skafferiet", provider.collected_categories)

    def test_en_omdopt_avdelning_namnges(self):
        """Allow-listan matchar på NAMN. Döper City Gross om "Skafferiet"
        matchar inget namn längre och avdelningen hämtas aldrig - förut utan
        ett enda felmeddelande."""
        kvar = [namn for namn in sorted(FOOD_DEPARTMENTS) if namn != "Skafferiet"]
        provider = self._kör(kvar)
        self.assertEqual(provider.failed_categories, ["Skafferiet (saknas i navigationen)"])
        self.assertEqual(len(provider.collected_categories), len(FOOD_DEPARTMENTS) - 1)

    def test_en_avdelning_som_ger_noll_produkter_flaggas(self):
        """Sidan finns, id:t stämmer, ingenting kastar - och hyllan är tom.
        Lika tyst som ett kategorifel var."""
        provider = self._kör(sorted(FOOD_DEPARTMENTS), tomma=["Fryst"])
        self.assertEqual(provider.failed_categories, ["Fryst (noll produkter)"])

    def test_bokslutet_nollstalls_mellan_korningar(self):
        """En provider som återanvänds får inte bära med sig förra körningens
        fel in i den här - då blir varje natt partiell efter den första."""
        provider = self._kör(sorted(FOOD_DEPARTMENTS), trasiga=["Skafferiet"])
        self.assertTrue(provider.failed_categories)

        def _open(request, timeout=None):
            url = request.full_url
            if "api/v1/navigation" in url:
                return _json(navigation(sorted(FOOD_DEPARTMENTS)))
            if "Loop54/category/" in url:
                return _json(category_page(PRODUKT))
            return _json({"searchResults": {"products": [], "totalCount": 0}})

        cg_module.urllib.request.urlopen = _open
        provider.get_products("3209")
        self.assertEqual(provider.failed_categories, [])


class KorningenBlirPartiell(unittest.TestCase):
    """Samma kriterium en nivå upp: att providern spårar felet ska göra den
    LAGRADE körningen partiell. Vägen fanns för Axfood men var aldrig testad
    - och City Gross gick aldrig in i den."""

    def setUp(self):
        from services.grocery import api as grocery_api
        self.grocery_api = grocery_api
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "grocery.db"
        self._real_path = grocery_api.DB_PATH
        grocery_api.DB_PATH = self.db_path
        self.addCleanup(lambda: setattr(grocery_api, "DB_PATH", self._real_path))
        grocery_api.clear_cache()
        self.addCleanup(grocery_api.clear_cache)

    def _kör_import(self, failed_categories):
        from services.grocery import importer
        from services.grocery.models import Store

        class FakeProvider:
            name = "citygross"

            def __init__(self):
                self.failed_categories = list(failed_categories)

            def get_stores(self):
                return [Store(id=0, chain="City Gross", external_store_id="3209",
                              name="City Gross Gävle", city="Gävle", postal_code="80646",
                              address=None, latitude=None, longitude=None, active=True)]

            def get_products(self, store_id):
                return [RawProduct(chain="City Gross", external_product_id=f"p{i}",
                                   name=f"Vara {i}", store_id=store_id, store_name="City Gross Gävle",
                                   gtin=None, size="1 kg", quantity=1000.0, unit="g",
                                   category="Skafferiet", regular_price=10.0 + i)
                        for i in range(5)]

        original = importer._provider_for
        importer._provider_for = lambda chain: FakeProvider()
        try:
            importer.start("City Gross")
            for _ in range(400):
                if not importer.status().get("running"):
                    break
                time.sleep(0.05)
            for thread in threading.enumerate():
                if thread.name == "grocery-import-City Gross":
                    thread.join(timeout=10)
        finally:
            importer._provider_for = original

        store = self.grocery_api.open_store()
        try:
            return store.connection.execute(
                "SELECT status, error_message, prices_updated FROM grocery_collector_runs "
                "ORDER BY id DESC LIMIT 1").fetchone()
        finally:
            store.close()

    def test_ett_kategorifel_gor_den_lagrade_korningen_partiell(self):
        rad = self._kör_import(["Skafferiet"])
        self.assertEqual(rad["status"], "blocked")
        self.assertIn("Skafferiet", rad["error_message"])
        # Det som hämtades publiceras ändå - en tappad avdelning får inte
        # kosta de tio som kom hem.
        self.assertEqual(rad["prices_updated"], 5)

    def test_utan_kategorifel_ar_korningen_lyckad(self):
        rad = self._kör_import([])
        self.assertEqual(rad["status"], "success")
        self.assertIsNone(rad["error_message"])


if __name__ == "__main__":
    unittest.main()
