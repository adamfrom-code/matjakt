import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.pricing import PriceCacheStore  # noqa: E402


class PriceCacheStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_path = Path(self._tmpdir.name) / "prices.db"
        self.store = PriceCacheStore(self._db_path)

    def tearDown(self):
        self.store.close()
        self._tmpdir.cleanup()

    def test_get_on_empty_store_returns_none(self):
        products, updated_at = self.store.get("Willys", "citron", "80252")
        self.assertIsNone(products)
        self.assertIsNone(updated_at)

    def test_set_then_get_round_trip(self):
        products = [{"produktnamn": "Citron Klass 1", "pris_kr": 6.9, "bild": "https://example.com/citron.jpg"}]
        self.store.set("Willys", "citron", "80252", products)
        got_products, updated_at = self.store.get("Willys", "citron", "80252")
        self.assertEqual(got_products, products)
        self.assertIsInstance(updated_at, float)
        self.assertAlmostEqual(updated_at, time.time(), delta=5)

    def test_product_images_survive_the_round_trip(self):
        """Point of this cache existing at all for the shopping list - a
        product's image URL must come back exactly as stored, not dropped or
        mangled, so Handla can show a real photo without waiting on a live
        scrape."""
        products = [
            {"produktnamn": "Paprika Röd Klass 1", "pris_kr": 19.9, "bild": "https://assets.axfood.se/paprika.jpg"},
            {"produktnamn": "Paprika Gul", "pris_kr": 21.9, "bild": ""},
        ]
        self.store.set("Willys", "paprika", "80252", products)
        got_products, _ = self.store.get("Willys", "paprika", "80252")
        self.assertEqual(got_products[0]["bild"], "https://assets.axfood.se/paprika.jpg")
        self.assertEqual(got_products[1]["bild"], "")

    def test_setting_the_same_key_twice_overwrites_not_duplicates(self):
        self.store.set("Willys", "ris", "80252", [{"produktnamn": "Gammalt ris", "pris_kr": 20}])
        self.store.set("Willys", "ris", "80252", [{"produktnamn": "Nytt ris", "pris_kr": 25}])
        products, _ = self.store.get("Willys", "ris", "80252")
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["produktnamn"], "Nytt ris")

    def test_different_chain_or_zip_are_separate_entries(self):
        self.store.set("Willys", "mjolk", "80252", [{"produktnamn": "Willys mjölk", "pris_kr": 12}])
        self.store.set("Coop", "mjolk", "80252", [{"produktnamn": "Coop mjölk", "pris_kr": 14}])
        self.store.set("Willys", "mjolk", "11122", [{"produktnamn": "Willys mjölk (annan butik)", "pris_kr": 13}])
        willys, _ = self.store.get("Willys", "mjolk", "80252")
        coop, _ = self.store.get("Coop", "mjolk", "80252")
        other_zip, _ = self.store.get("Willys", "mjolk", "11122")
        self.assertEqual(willys[0]["produktnamn"], "Willys mjölk")
        self.assertEqual(coop[0]["produktnamn"], "Coop mjölk")
        self.assertEqual(other_zip[0]["produktnamn"], "Willys mjölk (annan butik)")

    def test_updated_at_can_be_overridden_for_tests(self):
        old_timestamp = time.time() - 3600
        self.store.set("Willys", "smor", "80252", [{"produktnamn": "Smör"}], updated_at=old_timestamp)
        _, updated_at = self.store.get("Willys", "smor", "80252")
        self.assertEqual(updated_at, old_timestamp)

    def test_clear_removes_every_entry(self):
        self.store.set("Willys", "citron", "80252", [{"produktnamn": "Citron"}])
        self.store.set("Coop", "paprika", "80252", [{"produktnamn": "Paprika"}])
        self.store.clear()
        self.assertEqual(self.store.get("Willys", "citron", "80252"), (None, None))
        self.assertEqual(self.store.get("Coop", "paprika", "80252"), (None, None))

    def test_survives_a_simulated_restart(self):
        """The entire point of this store existing - reconnecting to the same
        database file (a new PriceCacheStore instance, exactly like a fresh
        process after a Render restart/redeploy) must still see data written
        by the previous instance."""
        products = [{"produktnamn": "Kidneybönor Naturella", "pris_kr": 9.9, "bild": "https://example.com/kidney.jpg"}]
        self.store.set("Willys", "kidneybonor", "80252", products)
        self.store.close()

        reopened = PriceCacheStore(self._db_path)
        try:
            got_products, updated_at = reopened.get("Willys", "kidneybonor", "80252")
            self.assertEqual(got_products, products)
            self.assertIsNotNone(updated_at)
        finally:
            reopened.close()


if __name__ == "__main__":
    unittest.main()
