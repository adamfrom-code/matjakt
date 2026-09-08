# -*- coding: utf-8 -*-
"""Diagnosen måste läsa prissättningens VERKLIGA svar.

En felutskrift som tyst läser fel nyckel är värre än ingen: den ser ut att
svara och gör det inte, och det upptäcks först den gång man behöver den -
då är körningen redan förbi. Därför byggs svaret här av den riktiga
prismotorn, med en avsiktligt saknad och en avsiktligt osäker rad, i
stället för av en handskriven dict som bara speglar mina antaganden."""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e.diagnos import (rader_som_saenker_taeckningen, sammanfatta_begaran,  # noqa: E402
                         sammanfatta_svar)
from services.grocery.models import RawProduct  # noqa: E402
from services.grocery.pricing import RecipePricingEngine  # noqa: E402
from services.grocery.store import GroceryStore  # noqa: E402


class DiagnosenLaserRiktigaSvaret(unittest.TestCase):

    def _prissatt(self):
        """En riktig price_list med tre rader: en exakt, en osäker, en saknad."""
        with tempfile.TemporaryDirectory() as tmp:
            db = GroceryStore(Path(tmp) / "g.db")
            try:
                store = db.upsert_store(chain="Willys", external_store_id="w1",
                                        name="Willys Test", active=True)
                for namn, storlek, pris in (("Pasta", "1 kg", 24.9), ("Tomatpuré", "140 g", 12.5)):
                    product = db.find_or_create_product(RawProduct(
                        chain="Willys", external_product_id=namn.lower(), name=namn,
                        store_id="w1", store_name="Willys", gtin=None, brand=None,
                        size=storlek, quantity=None, unit=None, category=None))
                    db.upsert_current_price(product_id=product.id, store_id=store.id,
                                            regular_price=pris, campaign_price=None,
                                            member_price=None, multibuy_price=None,
                                            unit_price=None, currency="SEK",
                                            source_url=None, fetched_at=time.time())
                return RecipePricingEngine(db).price_list([
                    {"name": "Pasta", "amount": 250, "unit": "g"},          # exakt
                    {"name": "Tomatpuré", "amount": 2, "unit": "msk"},      # osäker: msk mot gram
                    {"name": "Enhörningskött", "amount": 1, "unit": "st"},  # saknas
                ], "Willys", store.id)
            finally:
                db.close()

    def test_svarets_nycklar_ser_ut_som_diagnosen_tror(self):
        result = self._prissatt()
        self.assertIn("matchedItems", result)
        self.assertIn("missingItems", result)
        # Täckningen räknar exakta rader - det är hela skälet till att en
        # osäker rad måste kunna namnges.
        self.assertEqual(result["totalItems"], 3, result)
        self.assertEqual(result["realPriceItems"], 1, result)
        osäker = [r for r in result["matchedItems"] if r.get("rowUncertain")]
        self.assertEqual([r["name"] for r in osäker], ["Tomatpuré"], result["matchedItems"])
        # En osäker rad har ingen radtotal - den får inte tyst bli 0 kr.
        self.assertIsNone(osäker[0]["totalCost"])

    def test_bade_saknad_och_osaker_rad_namnges_var_for_sig(self):
        rader = rader_som_saenker_taeckningen(self._prissatt())
        self.assertEqual(rader, {"osäkra": ["Tomatpuré"], "saknade": ["Enhörningskött"]})

    def test_ett_svar_utan_problem_ger_tomma_listor(self):
        self.assertEqual(rader_som_saenker_taeckningen(
            {"matchedItems": [{"name": "Pasta", "exactPackaging": True}], "missingItems": []}),
            {"osäkra": [], "saknade": []})

    def test_ett_trasigt_eller_maskerat_svar_kraschar_inte(self):
        # Free-svaret maskeras (mask_pricing_for_free) och kan sakna raderna
        # helt. Diagnosen ska då säga "inget att visa", inte kasta.
        for svar in ({}, {"matchedItems": None, "missingItems": None},
                     {"matchedItems": [{}], "missingItems": [{}]}):
            self.assertEqual(rader_som_saenker_taeckningen(svar), {"osäkra": [], "saknade": []})


class BegaranSammanfattas(unittest.TestCase):
    """Begäran är beviset - men den får inte bära med sig hemligheter."""

    def test_faelten_som_paverkar_berakningen_foljer_med(self):
        kropp = json.dumps({
            "chain": "Willys", "people": 4, "recipeIds": ["a", "b"],
            "excludeItems": ["Lök"], "stores": {"Willys": "w1"},
            "pantry": {"Ris": 500, "Basilika": 1},
            "items": [{"name": "Pasta", "amount": 250, "unit": "g"}],
        })
        self.assertEqual(sammanfatta_begaran(kropp), {
            "chain": "Willys", "people": 4, "recipeIds": ["a", "b"],
            "excludeItems": ["Lök"], "stores": {"Willys": "w1"},
            "items": [{"name": "Pasta", "amount": 250, "unit": "g"}],
            "pantry": {"Basilika": 1, "Ris": 500},
        })

    def test_allt_annat_slas_bort_aven_om_det_ar_nytt(self):
        # WHITELISTA, inte svartlista. Ett fält som läggs till i API:t i
        # morgon ska inte hamna i en CI-logg bara för att ingen tänkte på
        # det - utskriften går till en logg som andra läser.
        kropp = json.dumps({
            "chain": "Willys", "token": "hemligt", "authorization": "Bearer x",
            "email": "adam@example.com", "postnummer": "80252",
            "nyttFaltNagonLaggerTillSen": {"lösenord": "abc"},
        })
        self.assertEqual(sammanfatta_begaran(kropp), {"chain": "Willys"})

    def test_en_kropp_som_inte_gar_att_tolka_saeger_det(self):
        for kropp in (None, "", "inte json", json.dumps([1, 2])):
            ut = sammanfatta_begaran(kropp)
            self.assertIn("kropp", ut, ut)
            self.assertNotIn("items", ut)


class SvaretSammanfattas(unittest.TestCase):

    def test_veckosvaret_namnger_raderna_for_den_kedja_som_foll(self):
        ut = sammanfatta_svar(200, {"results": [
            {"chain": "Willys", "comparable": True, "realPriceItems": 19, "totalItems": 19},
            {"chain": "Hemköp", "comparable": False, "realPriceItems": 16, "totalItems": 19,
             "matchedItems": [{"name": "Tomatpuré", "rowUncertain": True}],
             "missingItems": [{"name": "Enhörningskött"}]},
        ]})
        self.assertEqual(ut["status"], 200)
        frisk, fallen = ut["results"]
        self.assertNotIn("osäkra", frisk)          # bara den som föll listas
        self.assertEqual(fallen["osäkra"], ["Tomatpuré"])
        self.assertEqual(fallen["saknade"], ["Enhörningskött"])

    def test_ett_last_svar_visar_lasningen_inte_ett_tomt_resultat(self):
        ut = sammanfatta_svar(403, {"locked": True, "feature": "all_store_baskets",
                                    "freeChain": "Hemköp", "error": "Premium"})
        self.assertEqual(ut, {"status": 403, "locked": True, "feature": "all_store_baskets",
                              "freeChain": "Hemköp", "error": "Premium"})

    def test_listsvaret_namnger_varorna_som_saknar_pris(self):
        # Precis det som gör en tillagd extravara till en rad utan pris.
        ut = sammanfatta_svar(200, {"items": [
            {"ingredient": "Pasta", "totalCost": 24.9},
            {"ingredient": "Olivolja", "totalCost": None},
        ]})
        self.assertEqual(ut, {"status": 200, "items": 2, "utanPris": ["Olivolja"]})


if __name__ == "__main__":
    unittest.main()
