import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.grocery import GroceryStore, RawProduct  # noqa: E402


def raw(**overrides):
    defaults = dict(
        chain="Willys", external_product_id="willys-1", name="Mellanmjölk 1,5%",
        store_id="2103", store_name="Willys Gävle Gestrike", gtin=None, ean=None,
        brand="Arla", description=None, size="1.5 L", quantity=1.5, unit="L",
        category="Mejeri", image_url=None, regular_price=18.9, campaign_price=None,
        member_price=None, multibuy_price=None, unit_price=12.6, currency="SEK",
        source_url="https://www.willys.se/produkt/mellanmjolk", fetched_at=time.time(),
    )
    defaults.update(overrides)
    return RawProduct(**defaults)


class GroceryStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = GroceryStore(Path(self._tmpdir.name) / "grocery.db")

    def tearDown(self):
        self.store.close()
        self._tmpdir.cleanup()

    # ---- Stores ---------------------------------------------------

    def test_upsert_store_then_get(self):
        created = self.store.upsert_store(chain="Willys", external_store_id="2103", name="Willys Gävle Gestrike",
                                           city="Gävle", latitude=60.68, longitude=17.15)
        self.assertIsNotNone(created.id)
        fetched = self.store.get_store(chain="Willys", external_store_id="2103")
        self.assertEqual(fetched.name, "Willys Gävle Gestrike")
        self.assertEqual(fetched.city, "Gävle")

    def test_upsert_store_updates_in_place_not_duplicated(self):
        first = self.store.upsert_store(chain="Willys", external_store_id="2103", name="Willys Gävle")
        second = self.store.upsert_store(chain="Willys", external_store_id="2103", name="Willys Gävle Gestrike")
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(self.store.list_stores(chain="Willys")), 1)
        self.assertEqual(second.name, "Willys Gävle Gestrike")

    def test_list_stores_filters_by_chain_and_active(self):
        self.store.upsert_store(chain="Willys", external_store_id="1", name="A")
        self.store.upsert_store(chain="Coop", external_store_id="1", name="B")
        self.store.upsert_store(chain="Willys", external_store_id="2", name="C", active=False)
        self.assertEqual(len(self.store.list_stores()), 3)
        self.assertEqual(len(self.store.list_stores(chain="Willys")), 2)
        self.assertEqual(len(self.store.list_stores(chain="Willys", active_only=True)), 1)

    # ---- Product matching (spec section 3) -------------------------

    def test_new_product_created_when_nothing_matches(self):
        product = self.store.find_or_create_product(raw())
        self.assertIsNotNone(product.id)
        self.assertEqual(product.name, "Mellanmjölk 1,5%")
        self.assertEqual(product.brand, "Arla")

    def test_same_gtin_from_different_chains_resolves_to_one_product(self):
        """The exact scenario from the spec: ICA, Willys and Coop each phrase
        the same product's name slightly differently, but share one EAN -
        they must all resolve to the same PRODUCT row."""
        ean = "7310865004703"
        ica = self.store.find_or_create_product(raw(
            chain="ICA", external_product_id="ica-9001", ean=ean,
            name="Arla Mellanmjölk 1,5L", brand="Arla", size="1,5L",
        ))
        willys = self.store.find_or_create_product(raw(
            chain="Willys", external_product_id="willys-1", ean=ean,
            name="Arla Mellanmjölk 1,5 L", brand="Arla", size="1.5 L",
        ))
        coop = self.store.find_or_create_product(raw(
            chain="Coop", external_product_id="coop-77", ean=ean,
            name="Mellanmjölk Arla 1,5 liter", brand="Arla", size="1,5 liter",
        ))
        self.assertEqual(ica.id, willys.id)
        self.assertEqual(willys.id, coop.id)
        self.assertEqual(len(self.store.search_products("mellanmjölk")), 1)

    def test_gtin_takes_priority_over_ean(self):
        first = self.store.find_or_create_product(raw(gtin="GTIN-1", ean="EAN-1"))
        # Same GTIN, different EAN reported this time - GTIN match must win,
        # not create a second product keyed on the differing EAN.
        second = self.store.find_or_create_product(raw(
            chain="Coop", external_product_id="coop-2", gtin="GTIN-1", ean="EAN-2",
        ))
        self.assertEqual(first.id, second.id)

    def test_external_id_matches_before_falling_to_name(self):
        """Once a chain's own product id has been linked to a product, a
        later run for that SAME external id must match even if the reported
        name changed slightly (a chain renaming/re-describing a product) -
        that's the whole point of tier 3 existing above the name fallback."""
        first = self.store.find_or_create_product(raw(
            chain="Willys", external_product_id="willys-42", name="Mellanmjölk 1,5%",
        ))
        second = self.store.find_or_create_product(raw(
            chain="Willys", external_product_id="willys-42", name="Mellanmjölk Färsk 1,5%",
        ))
        self.assertEqual(first.id, second.id)

    def test_normalized_name_fallback_is_exact_not_fuzzy(self):
        first = self.store.find_or_create_product(raw(
            chain="Willys", external_product_id="w-1", brand="Arla", name="Mellanmjölk", size="1L",
        ))
        same_normalized = self.store.find_or_create_product(raw(
            chain="Coop", external_product_id="c-1", brand="  ARLA  ", name="mellanmjölk", size="1l",
        ))
        different_size = self.store.find_or_create_product(raw(
            chain="Hemköp", external_product_id="h-1", brand="Arla", name="Mellanmjölk", size="1.5L",
        ))
        self.assertEqual(first.id, same_normalized.id)
        self.assertNotEqual(first.id, different_size.id)

    def test_new_gtin_backfills_a_product_created_without_one(self):
        created = self.store.find_or_create_product(raw(
            chain="Willys", external_product_id="w-1", brand="Arla", name="Mellanmjölk", size="1L", gtin=None,
        ))
        self.assertIsNone(created.gtin)
        updated = self.store.find_or_create_product(raw(
            chain="Willys", external_product_id="w-1", brand="Arla", name="Mellanmjölk", size="1L", gtin="GTIN-9",
        ))
        self.assertEqual(created.id, updated.id)
        self.assertEqual(updated.gtin, "GTIN-9")

    def test_existing_gtin_is_never_overwritten_by_a_blank_one(self):
        first = self.store.find_or_create_product(raw(
            chain="Willys", external_product_id="w-1", gtin="GTIN-9",
        ))
        second = self.store.find_or_create_product(raw(
            chain="Willys", external_product_id="w-1", gtin="GTIN-9", image_url=None,
        ))
        self.assertEqual(first.gtin, "GTIN-9")
        self.assertEqual(second.gtin, "GTIN-9")

    def test_image_backfilled_only_when_missing(self):
        created = self.store.find_or_create_product(raw(
            chain="Willys", external_product_id="w-1", gtin="GTIN-1", image_url=None,
        ))
        self.assertIsNone(created.image_url)
        with_image = self.store.find_or_create_product(raw(
            chain="Willys", external_product_id="w-1", gtin="GTIN-1",
            image_url="https://assets.axfood.se/mjolk.jpg", source_url="https://www.willys.se/produkt/mjolk",
        ))
        self.assertEqual(with_image.image_url, "https://assets.axfood.se/mjolk.jpg")
        # A later run without an image must not blank out the one we already have.
        again = self.store.find_or_create_product(raw(
            chain="Willys", external_product_id="w-1", gtin="GTIN-1", image_url=None,
        ))
        self.assertEqual(again.image_url, "https://assets.axfood.se/mjolk.jpg")

    def test_get_product_by_external_id_returns_none_when_unseen(self):
        self.assertIsNone(self.store.get_product_by_external_id("ICA", "does-not-exist"))

    def test_get_product_by_external_id_finds_linked_product(self):
        created = self.store.find_or_create_product(raw(chain="ICA", external_product_id="ica-123"))
        found = self.store.get_product_by_external_id("ICA", "ica-123")
        self.assertEqual(found.id, created.id)

    def test_different_products_stay_different(self):
        milk = self.store.find_or_create_product(raw(gtin="GTIN-MILK", name="Mellanmjölk"))
        bread = self.store.find_or_create_product(raw(
            chain="Coop", external_product_id="coop-bread", gtin="GTIN-BREAD", name="Rågbröd",
        ))
        self.assertNotEqual(milk.id, bread.id)

    # ---- Prices -----------------------------------------------------

    def test_first_price_write_creates_current_price_and_history(self):
        product = self.store.find_or_create_product(raw())
        store = self.store.upsert_store(chain="Willys", external_store_id="2103", name="Willys Gävle")
        price, changed = self.store.upsert_current_price(
            product_id=product.id, store_id=store.id, regular_price=18.9, campaign_price=16.9,
        )
        self.assertTrue(changed)
        self.assertEqual(price.regular_price, 18.9)
        self.assertEqual(price.campaign_price, 16.9)
        history = self.store.get_price_history(product.id, store.id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].regular_price, 18.9)

    def test_unchanged_price_does_not_duplicate_history(self):
        product = self.store.find_or_create_product(raw())
        store = self.store.upsert_store(chain="Willys", external_store_id="2103", name="Willys Gävle")
        self.store.upsert_current_price(product_id=product.id, store_id=store.id, regular_price=18.9)
        _, changed_again = self.store.upsert_current_price(product_id=product.id, store_id=store.id, regular_price=18.9)
        self.assertFalse(changed_again)
        self.assertEqual(len(self.store.get_price_history(product.id, store.id)), 1)

    def test_price_change_appends_new_history_row_and_updates_current(self):
        product = self.store.find_or_create_product(raw())
        store = self.store.upsert_store(chain="Willys", external_store_id="2103", name="Willys Gävle")
        self.store.upsert_current_price(product_id=product.id, store_id=store.id, regular_price=18.9)
        price, changed = self.store.upsert_current_price(product_id=product.id, store_id=store.id, regular_price=17.5)
        self.assertTrue(changed)
        self.assertEqual(price.regular_price, 17.5)
        self.assertEqual(len(self.store.get_price_history(product.id, store.id)), 2)

    def test_failed_refetch_never_deletes_existing_price(self):
        """spec section 7: a collector that fails must never wipe the last
        known-good price - simulated here as simply not calling
        upsert_current_price again; the row must still be readable exactly
        as it was."""
        product = self.store.find_or_create_product(raw())
        store = self.store.upsert_store(chain="Willys", external_store_id="2103", name="Willys Gävle")
        self.store.upsert_current_price(product_id=product.id, store_id=store.id, regular_price=18.9)
        # ... a later collector run "fails" and simply never calls upsert_current_price again ...
        still_there = self.store.get_current_price(product.id, store.id)
        self.assertEqual(still_there.regular_price, 18.9)

    def test_get_prices_for_product_across_stores_sorted_cheapest_first(self):
        product = self.store.find_or_create_product(raw())
        cheap_store = self.store.upsert_store(chain="Willys", external_store_id="1", name="Willys A")
        pricey_store = self.store.upsert_store(chain="Willys", external_store_id="2", name="Willys B")
        self.store.upsert_current_price(product_id=product.id, store_id=pricey_store.id, regular_price=25.0)
        self.store.upsert_current_price(product_id=product.id, store_id=cheap_store.id, regular_price=15.0)
        prices = self.store.get_prices_for_product(product.id)
        self.assertEqual([p.store_id for p in prices], [cheap_store.id, pricey_store.id])

    # ---- Collector runs -----------------------------------------------

    def test_collector_run_lifecycle(self):
        run = self.store.start_collector_run(chain="Willys")
        self.assertEqual(run.status, "running")
        self.assertIsNone(run.finished_at)
        finished = self.store.finish_collector_run(
            run.id, status="success", products_found=40, products_created=5,
            products_updated=35, prices_updated=40, images_found=38, errors=0,
        )
        self.assertEqual(finished.status, "success")
        self.assertIsNotNone(finished.finished_at)
        self.assertEqual(finished.products_found, 40)

    def test_failed_collector_run_records_error_message(self):
        run = self.store.start_collector_run(chain="ICA")
        finished = self.store.finish_collector_run(
            run.id, status="failed", errors=1, error_message="timeout after 30s",
        )
        self.assertEqual(finished.status, "failed")
        self.assertEqual(finished.error_message, "timeout after 30s")

    def test_latest_collector_run_per_chain(self):
        first = self.store.start_collector_run(chain="Willys")
        self.store.finish_collector_run(first.id, status="success")
        second = self.store.start_collector_run(chain="Willys")
        self.store.finish_collector_run(second.id, status="success")
        self.store.start_collector_run(chain="Coop")
        latest = self.store.latest_collector_run("Willys")
        self.assertEqual(latest.id, second.id)


if __name__ == "__main__":
    unittest.main()
