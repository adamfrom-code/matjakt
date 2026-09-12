# -*- coding: utf-8 -*-
"""D10: kanariefågeln - ett känt GTIN med ett känt prisintervall, per kedja.

Publiceringsgaten räknar rader och radformat, och D2 lade till
medianförändringen. Alla tre svarar på "ser insamlingen normal ut?" utan att
någonsin titta på en vara någon känner igen. En kedja som byter API-form kan
mycket väl fortsätta leverera tiotusen välformade rader - bara inte rätt
rader.

Kanariefågeln är den billigaste möjliga upptäckten av "sajten ändrade sig".
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.grocery import alerts, canary  # noqa: E402
from services.grocery.models import RawProduct  # noqa: E402
from services.grocery.store import GroceryStore  # noqa: E402

WILLYS = canary.CANARIES["Willys"]


class Kanariefageln(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="matjakt-canary-")
        self.addCleanup(self._tmp.cleanup)
        self.store = GroceryStore(Path(self._tmp.name) / "grocery.db")
        self.addCleanup(self.store.close, True)

    def _lagg_in(self, chain="Willys", gtin=None, pris=16.50, kampanj=None):
        butik = self.store.upsert_store(
            chain=chain, external_store_id=f"{chain}-1", name=f"{chain} Gävle",
            city="Gävle", postal_code="80265", address="Gata 1",
            latitude=None, longitude=None, active=True)
        produkt = self.store.find_or_create_product(RawProduct(
            chain=chain, external_product_id=f"{chain}-vara", name="Mellanmjölk",
            store_id=str(butik.external_store_id), store_name=butik.name,
            gtin=gtin or WILLYS["gtin"], brand="GARANT", size="1,5 l",
            quantity=1.5, unit="l", regular_price=pris, currency="SEK",
            fetched_at=time.time()))
        self.store.upsert_current_price(
            product_id=produkt.id, store_id=butik.id, regular_price=pris,
            campaign_price=kampanj, fetched_at=time.time(), source="test")
        return produkt

    def test_ratt_vara_till_rimligt_pris_ar_ok(self):
        self._lagg_in()
        resultat = canary.check(self.store, "Willys")
        self.assertTrue(resultat["ok"], resultat["reason"])
        self.assertEqual(resultat["gtin"], WILLYS["gtin"])
        self.assertAlmostEqual(resultat["price"], 16.50)

    def test_en_forsvunnen_vara_larmar(self):
        """Kedjan byter API-form och varan finns inte längre i prisbilden.
        Katalogen kan se fullstor ut ändå."""
        self._lagg_in(gtin="07310865005168")      # en annan vara, inte vår
        resultat = canary.check(self.store, "Willys")
        self.assertFalse(resultat["ok"])
        self.assertIn(WILLYS["gtin"], resultat["reason"])
        self.assertIn("finns inte längre", resultat["reason"])

    def test_ett_tiodubblat_pris_larmar(self):
        """Öre tolkade som kronor. Varje rad är sund för sig, och gaten som
        räknar radformat ser ingenting."""
        self._lagg_in(pris=1650.0)
        resultat = canary.check(self.store, "Willys")
        self.assertFalse(resultat["ok"])
        self.assertIn("1650.00", resultat["reason"])

    def test_ett_tiondels_pris_larmar_ocksa(self):
        self._lagg_in(pris=1.65)
        resultat = canary.check(self.store, "Willys")
        self.assertFalse(resultat["ok"])

    def test_en_verklig_prisokning_larmar_inte(self):
        """Intervallet ska INTE fånga att mjölken gått upp en krona - det är
        inte ett fel, det är hela anledningen till att appen finns."""
        self._lagg_in(pris=19.90)
        self.assertTrue(canary.check(self.store, "Willys")["ok"])

    def test_kampanjpriset_ar_det_som_galler(self):
        self._lagg_in(pris=16.50, kampanj=12.90)
        self.assertAlmostEqual(canary.check(self.store, "Willys")["price"], 12.90)

    def test_en_annan_kedjas_pris_svarar_inte_for_var(self):
        """Samma GTIN finns hos alla tre kedjorna. Prisradens EGEN butik
        avgör kedjan - annars hade Hemköps rad dolt att Willys tappat varan."""
        self._lagg_in(chain="Hemköp", pris=17.70)
        resultat = canary.check(self.store, "Willys")
        self.assertFalse(resultat["ok"])
        self.assertTrue(canary.check(self.store, "Hemköp")["ok"])

    def test_en_kedja_utan_kanariefagel_sager_det_rakt_ut(self):
        """ICA och Coop har ingen verifierad vara härifrån. Ett påhittat
        GTIN hade gett ett grönt svar på en fråga ingen ställt."""
        resultat = canary.check(self.store, "ICA")
        self.assertFalse(resultat["configured"])
        self.assertTrue(resultat["ok"])
        self.assertNotIn("ICA", canary.CANARIES)
        self.assertNotIn("Coop", canary.CANARIES)

    def test_varje_kanariefagel_ar_daterad_och_har_ett_vitt_intervall(self):
        """Formkrav på tabellen: en rad utan observerat pris och datum är en
        gissning, och ett smalt intervall blir ett larm man slutar läsa."""
        for kedja, rad in canary.CANARIES.items():
            self.assertTrue(rad["gtin"].isdigit(), kedja)
            self.assertEqual(len(rad["gtin"]), 14, f"{kedja}: GTIN-14 som resten av systemet")
            self.assertTrue(rad["observed_at"], kedja)
            self.assertLess(rad["min_price"], rad["observed"], kedja)
            self.assertGreater(rad["max_price"], rad["observed"] * 2, kedja)

    def test_check_all_tacker_alla_konfigurerade_kedjor(self):
        resultat = canary.check_all(self.store)
        self.assertEqual({r["chain"] for r in resultat}, set(canary.CANARIES))


class LarmetGar(unittest.TestCase):
    def test_en_trasig_kanariefagel_blir_ett_larm(self):
        problem = alerts.evaluate([], canaries=[{
            "chain": "Willys", "configured": True, "ok": False,
            "reason": "Mellanmjölk kostar 1650.00 kr hos Willys - utanför 5-60 kr"}])
        self.assertIn("canary:Willys", problem)
        post = problem["canary:Willys"]
        self.assertEqual(post["severity"], "warning")
        self.assertIn("1650.00", post["body"])
        # Larmet ska säga att priserna ändå serveras - annars läses det som
        # ett kundstopp och någon river natten i onödan.
        self.assertIn("serveras", post["body"])

    def test_en_frisk_kanariefagel_larmar_inte(self):
        self.assertEqual(alerts.evaluate([], canaries=[
            {"chain": "Willys", "configured": True, "ok": True}]), {})

    def test_en_okonfigurerad_kedja_larmar_inte(self):
        self.assertEqual(alerts.evaluate([], canaries=[
            {"chain": "ICA", "configured": False, "ok": True}]), {})


class ImportenKorKollen(unittest.TestCase):
    """Kanariefågeln ska kontrolleras EFTER varje import, inte bara i
    driftkollen åtta timmar senare."""

    def setUp(self):
        # Egen databas: den här klassen kör en RIKTIG import som publicerar
        # priser, och sviten delar annars en grocery.db mellan alla
        # testmoduler i processen. Ett test som lämnar produkter efter sig
        # är ett test som gör någon annans test flakigt.
        from services.grocery import api as grocery_api, store as store_module
        self._tmp = tempfile.TemporaryDirectory(prefix="matjakt-canaryimport-")
        self.addCleanup(self._tmp.cleanup)
        self._original = grocery_api.DB_PATH
        grocery_api.DB_PATH = Path(self._tmp.name) / "grocery.db"
        self.addCleanup(setattr, grocery_api, "DB_PATH", self._original)
        self.addCleanup(store_module.release_thread_stores)
        # Receptprissättningen startar en egen tråd efter en lyckad import.
        # Den hinner leva längre än tempkatalogen och loggar då ett
        # "disk I/O error" som inte har med kanariefågeln att göra.
        from services.recipes import prices as recipe_prices
        original = recipe_prices.reprice_in_background
        recipe_prices.reprice_in_background = lambda *a, **k: None
        self.addCleanup(setattr, recipe_prices, "reprice_in_background", original)

    class FalskProvider:
        name = "Willys"

        def get_stores(self):
            from services.grocery.models import Store
            return [Store(id=0, chain="Willys", external_store_id="2132",
                          name="Willys Gävle", city="Gävle", postal_code="80265",
                          address="Gata 1", latitude=None, longitude=None, active=True)]

        def get_products(self, store_id):
            return [RawProduct(
                chain="Willys", external_product_id="101233933_ST",
                name="Mellanmjölk", store_id="2132", store_name="Willys Gävle",
                gtin=WILLYS["gtin"], brand="GARANT", size="1,5 l", quantity=1.5,
                unit="l", regular_price=16.50, currency="SEK", fetched_at=time.time())]

    def test_kollen_kors_nar_importen_publicerat(self):
        from services.grocery import importer
        körda = []
        original_provider = importer._provider_for
        original_check = canary.check
        importer._provider_for = lambda chain: self.FalskProvider()
        canary.check = lambda store, chain: (körda.append(chain) or
                                             {"chain": chain, "configured": True, "ok": True})
        self.addCleanup(setattr, importer, "_provider_for", original_provider)
        self.addCleanup(setattr, canary, "check", original_check)

        importer._run("Willys", "2132", None)
        self.assertEqual(körda, ["Willys"], f"status: {importer.status()}")

    def test_en_trasig_kanariekoll_faller_inte_importen(self):
        """Vi vet att varan ser fel ut, inte vilken siffra som är sann. Att
        kasta en hel natts katalog på en enda rad vore mer skada än fyndet
        är värt."""
        from services.grocery import importer
        original_provider = importer._provider_for
        original_check = canary.check

        def spräng(store, chain):
            raise RuntimeError("kanariekollen sprack")

        importer._provider_for = lambda chain: self.FalskProvider()
        canary.check = spräng
        self.addCleanup(setattr, importer, "_provider_for", original_provider)
        self.addCleanup(setattr, canary, "check", original_check)

        importer._run("Willys", "2132", None)
        self.assertEqual(importer.status()["status"], "done")


if __name__ == "__main__":
    unittest.main()
