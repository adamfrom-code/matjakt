import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.grocery import CollectorRun, CurrentPrice, GroceryProvider, PriceHistoryEntry, Product, RawProduct, Store  # noqa: E402


class IncompleteProvider(GroceryProvider):
    name = "incomplete"
    # Deliberately missing every abstract method.


class FakeProvider(GroceryProvider):
    """Minimal concrete provider - proves the interface is actually
    implementable with the exact method set the spec calls for, and gives
    the real provider files (ICA, Willys, ...) in later phases a template."""

    name = "fake"

    def get_stores(self) -> list[Store]:
        return [Store(id=0, chain="Fake", external_store_id="1", name="Fake Store")]

    def get_products(self, store_id: str) -> list[RawProduct]:
        return [self.normalize_product({"id": "1", "name": "Test Product"})]

    def get_product_details(self, product_id: str, store_id: str):
        return self.normalize_product({"id": product_id, "name": "Test Product"})

    def normalize_product(self, raw_product) -> RawProduct:
        return RawProduct(
            chain="Fake", external_product_id=raw_product["id"], name=raw_product["name"],
            store_id="1", store_name="Fake Store",
        )

    def health_check(self) -> bool:
        return True


class GroceryProviderInterfaceTest(unittest.TestCase):
    def test_cannot_instantiate_incomplete_provider(self):
        with self.assertRaises(TypeError):
            IncompleteProvider()

    def test_concrete_provider_implements_full_contract(self):
        provider = FakeProvider()
        self.assertTrue(provider.health_check())
        stores = provider.get_stores()
        self.assertEqual(stores[0].chain, "Fake")
        products = provider.get_products("1")
        self.assertEqual(products[0].name, "Test Product")
        detail = provider.get_product_details("1", "1")
        self.assertEqual(detail.external_product_id, "1")


class ModelSerializationTest(unittest.TestCase):
    def test_raw_product_to_dict_uses_camel_case(self):
        raw = RawProduct(
            chain="Willys", external_product_id="w-1", name="Mellanmjölk", store_id="1",
            store_name="Willys Gävle", gtin="GTIN-1", regular_price=18.9,
        )
        payload = raw.to_dict()
        self.assertEqual(payload["externalProductId"], "w-1")
        self.assertEqual(payload["storeName"], "Willys Gävle")
        self.assertEqual(payload["regularPrice"], 18.9)
        self.assertNotIn("external_product_id", payload)

    def test_product_to_dict_uses_camel_case(self):
        product = Product(id=1, name="Mellanmjölk", image_url="https://example.com/mjolk.jpg")
        payload = product.to_dict()
        self.assertEqual(payload["imageUrl"], "https://example.com/mjolk.jpg")
        self.assertEqual(payload["id"], 1)

    def test_current_price_and_history_and_run_to_dict(self):
        price = CurrentPrice(id=1, product_id=1, store_id=1, regular_price=18.9, campaign_price=None,
                              member_price=None, multibuy_price=None, unit_price=12.6, currency="SEK",
                              source_url=None, fetched_at=0.0, updated_at=0.0)
        self.assertEqual(price.to_dict()["regularPrice"], 18.9)

        history = PriceHistoryEntry(id=1, product_id=1, store_id=1, regular_price=18.9, campaign_price=None,
                                     member_price=None, multibuy_price=None, unit_price=None, timestamp=0.0)
        self.assertEqual(history.to_dict()["productId"], 1)

        run = CollectorRun(id=1, chain="Willys", store_id=1, started_at=0.0, finished_at=None, status="running")
        self.assertEqual(run.to_dict()["startedAt"], 0.0)
        self.assertEqual(run.to_dict()["errorMessage"], None)


if __name__ == "__main__":
    unittest.main()
