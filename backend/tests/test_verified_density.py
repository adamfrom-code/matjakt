# -*- coding: utf-8 -*-
"""Uppmätta volymvikter slår köksstandardens 1 g = 1 ml.

Källa: Livsmedelsverkets PM 2024 "Volymvikter, viktförändringsfaktorer och
avfall". Varje siffra i VERIFIED_DENSITY_G_PER_ML kommer från en vägning med
angivet n - det är hela skillnaden mot ett antagande, och därför prövar de
här testerna både att siffrorna används och att inget hittas på för det som
källan saknar."""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.grocery.models import RawProduct  # noqa: E402
from services.grocery.pricing import (VERIFIED_DENSITY_G_PER_ML, RecipePricingEngine,  # noqa: E402
                                      dairy_gram_ml_equivalent, verified_density)
from services.grocery.store import GroceryStore  # noqa: E402


class Densiteten(unittest.TestCase):

    def test_ketchup_vager_18_gram_per_msk_inte_15(self):
        # 18 g/msk (n=20) delat på 15 ml = 1,20 g/ml. Köksstandardens 1,0 är
        # 17 % fel för just den här varan.
        self.assertAlmostEqual(verified_density("Ketchup"), 1.20)
        self.assertAlmostEqual(15 * verified_density("Ketchup"), 18.0, places=1)

    def test_langsta_traffen_vinner(self):
        # "grekisk yoghurt" får inte falla tillbaka på "yoghurt", och
        # "mjolk" får inte fånga "filmjolk".
        self.assertAlmostEqual(verified_density("Grekisk yoghurt"), 1.08)
        self.assertAlmostEqual(verified_density("Filmjölk"), 1.10)
        self.assertAlmostEqual(verified_density("Mjölk"), 0.98)

    def test_det_som_kallan_saknar_far_ingen_pahittad_siffra(self):
        # De här är släta såser i DAIRY_DENSITY_ONE och behåller 1,0 - ett
        # antagande vi vet om, i stället för en siffra som ser mätt ut.
        for namn in ("Senap", "Majonnäs", "Sriracha", "Gräddfil", "Keso"):
            self.assertIsNone(verified_density(namn), namn)
            self.assertTrue(dairy_gram_ml_equivalent(namn), namn)

    def test_de_fyra_osakra_star_kvar_som_osakra(self):
        # Tomatpuré, sirap, currypasta och sambal oelek saknas i källan.
        # Att ge dem en densitet vore att gissa för att få grön audit.
        for namn in ("Tomatpuré", "Sirap", "Currypasta", "Sambal oelek"):
            self.assertIsNone(verified_density(namn), namn)

    def test_varje_uppmatt_varde_ligger_i_ett_rimligt_spann(self):
        # En felskrivning som gör 1,20 till 12,0 ska falla här, inte i en
        # kundvagn. Mat mellan 0,5 och 1,5 g/ml täcker allt i tabellen.
        for namn, täthet in VERIFIED_DENSITY_G_PER_ML.items():
            self.assertTrue(0.5 <= täthet <= 1.5, f"{namn}: {täthet}")


class PriseffektVidForpackningsgransen(unittest.TestCase):
    """Densiteten syns först när den flyttar ANTALET förpackningar."""

    def _butik(self, tmp, varor):
        db = GroceryStore(Path(tmp) / "g.db")
        butik = db.upsert_store(chain="Willys", external_store_id="w1", name="W", active=True)
        for namn, storlek, pris in varor:
            p = db.find_or_create_product(RawProduct(
                chain="Willys", external_product_id=namn, name=namn, store_id="w1",
                store_name="Willys", gtin=None, brand=None, size=storlek,
                quantity=None, unit=None, category=None))
            db.upsert_current_price(product_id=p.id, store_id=butik.id, regular_price=pris,
                                    campaign_price=None, member_price=None, multibuy_price=None,
                                    unit_price=None, currency="SEK", source_url=None,
                                    fetched_at=time.time())
        return db, butik

    def test_tyngre_an_antaget_kraver_en_forpackning_till(self):
        # 5 dl ketchup väger 600 g och ryms inte i en 500-gramsflaska.
        # Med 1,0 blev det "precis en flaska" och listan för billig.
        with tempfile.TemporaryDirectory() as tmp:
            db, butik = self._butik(tmp, [("Ketchup", "500 g", 24.9)])
            try:
                rad = RecipePricingEngine(db).price_item("Ketchup", 5, "dl", "Willys", butik.id)
            finally:
                db.close()
        self.assertEqual(rad["packages"], 2)
        self.assertEqual(rad["totalCost"], 49.8)
        self.assertTrue(rad["exactPackaging"])

    def test_lattare_an_antaget_sparar_en_forpackning(self):
        # 2,05 dl crème fraiche väger 195 g och ryms i 200-gramsburken.
        # Med 1,0 tvingades kunden köpa två.
        with tempfile.TemporaryDirectory() as tmp:
            db, butik = self._butik(tmp, [("Crème fraiche", "200 g", 18.5)])
            try:
                rad = RecipePricingEngine(db).price_item("Crème fraiche", 2.05, "dl",
                                                         "Willys", butik.id)
            finally:
                db.close()
        self.assertEqual(rad["packages"], 1)
        self.assertEqual(rad["totalCost"], 18.5)


if __name__ == "__main__":
    unittest.main()
