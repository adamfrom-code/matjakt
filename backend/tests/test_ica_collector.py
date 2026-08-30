"""Collector-level tests: the save path a real ICA import runs through.

The network is never touched - these drive GroceryStore with the exact
RawProduct shapes IcaProvider produces, using values copied from the real
2026-08-30 import of Maxi ICA Stormarknad Gävle (account 1003987).

The point of these is FAS B step 7: proving that re-running the same import
UPDATES existing rows instead of creating duplicates. That has to be
provable on demand, not only by catching a live second run in the window
where ICA's WAF happens to be letting automated traffic through.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.grocery import GroceryStore, RawProduct  # noqa: E402

# Verbatim from the real import (see the FAS B report) - same ids, prices,
# image URLs and pack sizes that are sitting in grocery.db right now.
REAL_IMPORTED = [
    RawProduct(
        chain="ICA", external_product_id="2052770",
        name="Mellanmjölk 1,5% Ekologisk 1,5l KRAV ICA I love eco", brand="ICA I love eco",
        store_id="1003987", store_name="Maxi ICA Stormarknad Gävle",
        size="1.5L", quantity=1.5, unit="L", category="Mellanmjölk, laktos",
        image_url="https://handlaprivatkund.ica.se/images-v3/bf7a00ca-390e-4769-865f-dc369586872e/000b7f1c-4ea9-401b-9a9b-44710f62e5dc/300x300.jpg",
        regular_price=19.16, unit_price=12.77, currency="SEK",
        source_url="https://handlaprivatkund.ica.se/stores/1003987/products/produkt/2052770",
        fetched_at=1000.0,
    ),
    RawProduct(
        chain="ICA", external_product_id="1520842",
        name="Mellanmjölk Lite längre hållbarhet 1,5% 1,5l ICA", brand="ICA",
        store_id="1003987", store_name="Maxi ICA Stormarknad Gävle",
        size="1.5L", quantity=1.5, unit="L", category="Mellanmjölk, laktos",
        image_url="https://handlaprivatkund.ica.se/images-v3/bf7a00ca-390e-4769-865f-dc369586872e/f3d472b7-4397-431e-8ea1-226e1cde3e0c/300x300.jpg",
        regular_price=15.90, unit_price=10.60, currency="SEK",
        source_url="https://handlaprivatkund.ica.se/stores/1003987/products/produkt/1520842",
        fetched_at=1000.0,
    ),
    RawProduct(
        chain="ICA", external_product_id="1487001",
        name="Mellanmjölksdryck Laktosfri 1,5% 1l KRAV ICA I love eco", brand="ICA I love eco",
        store_id="1003987", store_name="Maxi ICA Stormarknad Gävle",
        size="1L", quantity=1.0, unit="L", category="Laktosfri mjölk",
        image_url="https://handlaprivatkund.ica.se/images-v3/bf7a00ca-390e-4769-865f-dc369586872e/e17b906d-338f-4e1f-843a-7e2c39ec2549/300x300.jpg",
        regular_price=17.50, unit_price=17.50, currency="SEK",
        source_url="https://handlaprivatkund.ica.se/stores/1003987/products/produkt/1487001",
        fetched_at=1000.0,
    ),
]


def import_batch(db, store, products, fetched_at=None):
    """Mirrors the collector's per-product save path (find_or_create_product
    then upsert_current_price), which is what we're actually asserting on."""
    created = updated = 0
    for raw in products:
        existed = db.get_product_by_external_id(raw.chain, raw.external_product_id) is not None
        product = db.find_or_create_product(raw)
        updated += 1 if existed else 0
        created += 0 if existed else 1
        db.upsert_current_price(
            product_id=product.id, store_id=store.id, regular_price=raw.regular_price,
            campaign_price=raw.campaign_price, member_price=raw.member_price,
            multibuy_price=raw.multibuy_price, unit_price=raw.unit_price,
            currency=raw.currency, source_url=raw.source_url,
            fetched_at=fetched_at if fetched_at is not None else raw.fetched_at,
        )
    return created, updated


class IcaReimportTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db = GroceryStore(Path(self._tmpdir.name) / "grocery.db")
        self.store = self.db.upsert_store(
            chain="ICA", external_store_id="1003987", name="Maxi ICA Stormarknad Gävle", city="Gävle",
        )

    def tearDown(self):
        self.db.close()
        self._tmpdir.cleanup()

    def _count(self, table):
        return self.db.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_first_import_creates_everything(self):
        created, updated = import_batch(self.db, self.store, REAL_IMPORTED)
        self.assertEqual((created, updated), (3, 0))
        self.assertEqual(self._count("grocery_products"), 3)
        self.assertEqual(self._count("grocery_current_prices"), 3)
        self.assertEqual(self._count("grocery_price_history"), 3)

    def test_second_identical_import_updates_and_creates_no_duplicates(self):
        """FAS B step 7: the exact requirement - a repeat run must not create
        a second copy of every product."""
        import_batch(self.db, self.store, REAL_IMPORTED)
        created, updated = import_batch(self.db, self.store, REAL_IMPORTED)

        self.assertEqual(created, 0, "a repeat import must create no new products")
        self.assertEqual(updated, 3)
        self.assertEqual(self._count("grocery_products"), 3, "product rows must not double")
        self.assertEqual(self._count("grocery_current_prices"), 3, "price rows must not double")
        self.assertEqual(self._count("grocery_product_external_ids"), 3)

    def test_unchanged_prices_do_not_grow_history_on_every_run(self):
        """Spec section 11: re-importing an unchanged price must not append a
        duplicate history row, or a year of nightly runs writes a year of
        identical rows."""
        import_batch(self.db, self.store, REAL_IMPORTED)
        self.assertEqual(self._count("grocery_price_history"), 3)
        import_batch(self.db, self.store, REAL_IMPORTED, fetched_at=2000.0)
        import_batch(self.db, self.store, REAL_IMPORTED, fetched_at=3000.0)
        self.assertEqual(self._count("grocery_price_history"), 3, "unchanged prices must not append history")

    def test_changed_price_updates_current_and_appends_one_history_row(self):
        import_batch(self.db, self.store, REAL_IMPORTED)
        cheaper = [RawProduct(**{**REAL_IMPORTED[0].__dict__, "regular_price": 17.50})]
        import_batch(self.db, self.store, cheaper, fetched_at=2000.0)

        product = self.db.get_product_by_external_id("ICA", "2052770")
        price = self.db.get_current_price(product.id, self.store.id)
        self.assertEqual(price.regular_price, 17.50, "current price must reflect the new value")
        self.assertEqual(self._count("grocery_price_history"), 4, "exactly one new history row")
        self.assertEqual(self._count("grocery_products"), 3, "a price change must not fork the product")

    def test_repeat_import_preserves_image_and_metadata(self):
        import_batch(self.db, self.store, REAL_IMPORTED)
        import_batch(self.db, self.store, REAL_IMPORTED)
        product = self.db.get_product_by_external_id("ICA", "2052770")
        self.assertEqual(product.image_url, REAL_IMPORTED[0].image_url)
        self.assertEqual(product.brand, "ICA I love eco")
        self.assertEqual(product.size, "1.5L")

    def test_gtin_stays_null_for_ica_across_repeat_imports(self):
        """ICA exposes no GTIN/EAN - it must stay null rather than being
        invented, however many times the product is re-imported."""
        import_batch(self.db, self.store, REAL_IMPORTED)
        import_batch(self.db, self.store, REAL_IMPORTED)
        for raw in REAL_IMPORTED:
            product = self.db.get_product_by_external_id("ICA", raw.external_product_id)
            self.assertIsNone(product.gtin)
            self.assertIsNone(product.ean)

    def test_blocked_run_saving_nothing_leaves_existing_data_untouched(self):
        """What actually happened live: a WAF-blocked run collected 0 products.
        The previous run's real data must survive completely."""
        import_batch(self.db, self.store, REAL_IMPORTED)
        before = [self.db.get_current_price(
            self.db.get_product_by_external_id("ICA", r.external_product_id).id, self.store.id
        ).regular_price for r in REAL_IMPORTED]

        import_batch(self.db, self.store, [])  # blocked run: nothing to save

        after = [self.db.get_current_price(
            self.db.get_product_by_external_id("ICA", r.external_product_id).id, self.store.id
        ).regular_price for r in REAL_IMPORTED]
        self.assertEqual(before, after)
        self.assertEqual(self._count("grocery_products"), 3)


if __name__ == "__main__":
    unittest.main()
