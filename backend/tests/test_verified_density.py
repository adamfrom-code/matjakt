# -*- coding: utf-8 -*-
"""Tomatketchupens uppmätta volymvikt.

KÄLLA: Livsmedelsverkets PM 2024 "Volymvikter, viktförändringsfaktorer och
avfall", tabell 10 sidan 16 ("Vikter (gram) för olika enheter av
majonnässallader, röror och andra tillbehör"), raden "Tomatketchup".
Uppmätt: tsk 6 g (n=20), msk 18 g (n=20). dl är INTE uppmätt.
Referens 1 = myndighetens egna volymviktsförsök 2022-23.

Testerna prövar tre olika saker och blandar dem inte:
  1. att siffran stämmer med källan,
  2. att omräkningen är konsekvent oavsett vilket mått receptet använder,
  3. att ingenting ANNAT ändrades."""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.grocery.models import RawProduct  # noqa: E402
from services.grocery.pricing import (BAKING_GRAMS_PER_DL, VERIFIED_DENSITY_G_PER_ML,  # noqa: E402
                                      _VOLUME, RecipePricingEngine, dairy_gram_ml_equivalent,
                                      verified_density)
from services.grocery.store import GroceryStore  # noqa: E402


class SiffranStammerMedKallan(unittest.TestCase):

    def test_bada_uppmatta_enheterna_aterges_exakt(self):
        täthet = verified_density("Ketchup")
        self.assertAlmostEqual(_VOLUME["tsk"] * täthet, 6.0, places=2)    # 6 g, n=20
        self.assertAlmostEqual(_VOLUME["msk"] * täthet, 18.0, places=2)   # 18 g, n=20

    def test_msk_ar_tre_tsk_aven_i_gram(self):
        # Motstridiga omräkningsvägar vore ett fel i modellen: samma mängd
        # måste väga lika oavsett om receptet skriver 1 msk eller 3 tsk.
        täthet = verified_density("Ketchup")
        self.assertAlmostEqual(_VOLUME["msk"] * täthet, 3 * _VOLUME["tsk"] * täthet, places=6)

    def test_dl_foljer_samma_densitet_aven_om_kallan_inte_matt_den(self):
        # Dokumenterad extrapolering, inte en mätning. Testet finns för att
        # låsa fast att den följer de två MÄTTA enheterna och inte får ett
        # eget, avvikande tal någonstans.
        täthet = verified_density("Ketchup")
        self.assertAlmostEqual(_VOLUME["dl"] * täthet, 120.0, places=2)

    def test_bara_ketchup_star_i_tabellen(self):
        # "Kör 2" gällde ketchupens omräkning. Andra rader i samma tabell
        # kräver egen produktmatchning - se docs/VOLYMVIKTER_ATT_GRANSKA.md.
        self.assertEqual(set(VERIFIED_DENSITY_G_PER_ML), {"ketchup"})

    def test_ovriga_slata_saser_behaller_kokstandardens_ett(self):
        for namn in ("Senap", "Majonnäs", "Sriracha", "Gräddfil", "Keso",
                     "Crème fraiche", "Grekisk yoghurt", "Filmjölk", "Kvarg", "Mjölk"):
            self.assertIsNone(verified_density(namn), namn)
            self.assertTrue(dairy_gram_ml_equivalent(namn), namn)

    def test_bakvarutabellen_ar_orord(self):
        self.assertEqual(BAKING_GRAMS_PER_DL["vetemjol"], 60)
        self.assertEqual(BAKING_GRAMS_PER_DL["havregryn"], 35)

    def test_de_fyra_osakra_far_ingen_pahittad_siffra(self):
        for namn in ("Tomatpuré", "Sirap", "Currypasta", "Sambal oelek"):
            self.assertIsNone(verified_density(namn), namn)

    def test_vardet_ligger_i_ett_rimligt_spann(self):
        # En felskrivning som gör 1,20 till 12,0 ska falla här, inte i en
        # kundvagn.
        for namn, täthet in VERIFIED_DENSITY_G_PER_ML.items():
            self.assertTrue(0.5 <= täthet <= 1.5, f"{namn}: {täthet}")


class OmrakningenIPrissattningen(unittest.TestCase):
    """Hela vägen genom motorn, med riktiga produkter och priser."""

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

    def test_msk_mot_gramforpackning_och_gram_mot_volymflaska(self):
        # Båda riktningarna används i motorn: volymrecept mot gramvara och
        # gramrecept mot volymvara.
        with tempfile.TemporaryDirectory() as tmp:
            db, butik = self._butik(tmp, [("Ketchup", "1000 g", 30.0),
                                          ("Ketchup Flaska", "1000 ml", 30.0)])
            try:
                eng = RecipePricingEngine(db)
                i_gram = eng.price_item("Ketchup", 10, "msk", "Willys", butik.id)
                i_volym = eng.price_item("Ketchup", 180, "g", "Willys", butik.id)
            finally:
                db.close()
        # 10 msk = 150 ml = 180 g -> ryms i 1000 g
        self.assertEqual(i_gram["packages"], 1)
        self.assertTrue(i_gram["exactPackaging"])
        # 180 g åt andra hållet = 150 ml -> ryms i flaskan
        self.assertEqual(i_volym["packages"], 1)
        self.assertTrue(i_volym["exactPackaging"])

    def test_portionsskalning_dubblar_behovet(self):
        # 4 msk för 4 portioner blir 8 msk för 8: 144 g mot en 100 g-flaska
        # är två flaskor, medan 72 g är en.
        with tempfile.TemporaryDirectory() as tmp:
            db, butik = self._butik(tmp, [("Ketchup", "100 g", 12.0)])
            try:
                eng = RecipePricingEngine(db)
                fyra = eng.price_item("Ketchup", 4, "msk", "Willys", butik.id)
                atta = eng.price_item("Ketchup", 8, "msk", "Willys", butik.id)
            finally:
                db.close()
        self.assertEqual((fyra["packages"], fyra["totalCost"]), (1, 12.0))
        self.assertEqual((atta["packages"], atta["totalCost"]), (2, 24.0))

    def test_ketchup_summeras_over_flera_recept_innan_forpackningar_raknas(self):
        # Veckan aggregeras FÖRE paketräkningen: 3 + 3 + 3 msk är 9 msk =
        # 162 g, alltså en 200-gramsflaska - inte tre.
        with tempfile.TemporaryDirectory() as tmp:
            db, butik = self._butik(tmp, [("Ketchup", "200 g", 20.0)])
            try:
                eng = RecipePricingEngine(db)
                lista = eng.price_list([{"name": "Ketchup", "amount": 9, "unit": "msk"}],
                                       "Willys", butik.id)
                var_for_sig = [eng.price_item("Ketchup", 3, "msk", "Willys", butik.id)
                               for _ in range(3)]
            finally:
                db.close()
        self.assertEqual(lista["matchedItems"][0]["packages"], 1)
        self.assertEqual(lista["totalCheckoutCost"], 20.0)
        self.assertEqual(sum(r["totalCost"] for r in var_for_sig), 60.0)

    def test_skafferiavdrag_med_kompatibla_enheter(self):
        # 12 msk behövs, 6 msk finns hemma i ml -> 6 msk kvar = 108 g.
        with tempfile.TemporaryDirectory() as tmp:
            db, butik = self._butik(tmp, [("Ketchup", "150 g", 15.0)])
            try:
                eng = RecipePricingEngine(db)
                utan = eng.price_list([{"name": "Ketchup", "amount": 12, "unit": "msk"}],
                                      "Willys", butik.id)
                med = eng.price_list([{"name": "Ketchup", "amount": 12, "unit": "msk"}],
                                     "Willys", butik.id, pantry={"Ketchup": 90})   # 90 ml
            finally:
                db.close()
        # 12 msk = 216 g -> två flaskor. Med 90 ml hemma: 6 msk = 108 g -> en.
        self.assertEqual(utan["matchedItems"][0]["packages"], 2)
        self.assertEqual(med["matchedItems"][0]["packages"], 1)

    def test_forpackningsgransen_kan_kosta_en_flaska_till(self):
        # DEN HÄR ÄR HELA POÄNGEN. 5 dl ketchup väger 600 g och ryms inte i
        # en 500-gramsflaska. Med köksstandardens 1,0 blev det "precis en
        # flaska" och kassen hade saknat ketchup.
        with tempfile.TemporaryDirectory() as tmp:
            db, butik = self._butik(tmp, [("Ketchup", "500 g", 24.9)])
            try:
                rad = RecipePricingEngine(db).price_item("Ketchup", 5, "dl", "Willys", butik.id)
            finally:
                db.close()
        self.assertEqual(rad["packages"], 2)
        self.assertEqual(rad["totalCost"], 49.8)
        self.assertTrue(rad["exactPackaging"])

    def test_andra_ingredienser_rors_inte(self):
        # Samma mängder, varor utan uppmätt densitet: köksstandardens 1 g =
        # 1 ml gäller som förut, alltså ryms 5 dl i en 500-gramsförpackning.
        with tempfile.TemporaryDirectory() as tmp:
            db, butik = self._butik(tmp, [("Senap", "500 g", 20.0),
                                          ("Crème fraiche", "500 g", 20.0),
                                          ("Mjölk", "500 g", 20.0)])
            try:
                eng = RecipePricingEngine(db)
                rader = {n: eng.price_item(n, 5, "dl", "Willys", butik.id)
                         for n in ("Senap", "Crème fraiche", "Mjölk")}
            finally:
                db.close()
        for namn, rad in rader.items():
            self.assertEqual(rad["packages"], 1, f"{namn} ändrades: {rad}")
            self.assertEqual(rad["totalCost"], 20.0, namn)


if __name__ == "__main__":
    unittest.main()
