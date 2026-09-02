# -*- coding: utf-8 -*-
"""Nationella butiksmodellen: Matjakt är en svensk rikstjänst - Gävle är
testmarknad, aldrig arkitektur.

Täcker: schema-migreringen, butiksregistret (Primats /stores -> DB),
postnummer->butiker ur egen databas för tio orter över hela landet, och
butiksupplösningen i prissättningen (nationell kedja etiketteras om,
butiksspecifik kedja vägrar hellre än att visa fel butiks priser)."""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.grocery import api as grocery_api  # noqa: E402
from services.grocery import register  # noqa: E402
from services.grocery.models import RawProduct  # noqa: E402
from services.grocery.store import GroceryStore  # noqa: E402

# Tio orter, hela landet - storstad, mellanstad och en glesbygdsort.
# Koordinaterna är testfixturer (verkliga ortmittpunkter).
CITIES = {
    "Stockholm": (59.334, 18.063), "Göteborg": (57.707, 11.967),
    "Malmö": (55.605, 13.003), "Uppsala": (59.858, 17.639),
    "Västerås": (59.611, 16.545), "Örebro": (59.275, 15.213),
    "Norrköping": (58.588, 16.188), "Gävle": (60.675, 17.142),
    "Umeå": (63.826, 20.263), "Sveg": (62.034, 14.363),
}


class SchemaMigration(unittest.TestCase):
    def test_old_database_gets_the_new_columns(self):
        """En databas skapad före nationella modellen (utan provider/
        pricing_scope) ska migreras vid öppning - inte krascha."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gammal.db"
            old = sqlite3.connect(path)
            old.execute("""
                CREATE TABLE grocery_stores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chain TEXT NOT NULL, external_store_id TEXT NOT NULL,
                    name TEXT NOT NULL, city TEXT, postal_code TEXT, address TEXT,
                    latitude REAL, longitude REAL, active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    UNIQUE(chain, external_store_id))""")
            old.execute("INSERT INTO grocery_stores (chain, external_store_id, name,"
                        " created_at, updated_at) VALUES ('Willys', '2132', 'Gestrike', 0, 0)")
            old.commit(); old.close()

            db = GroceryStore(path)
            try:
                columns = {row[1] for row in db.connection.execute(
                    "PRAGMA table_info(grocery_stores)")}
                self.assertIn("provider", columns)
                self.assertIn("pricing_scope", columns)
                survivor = db.get_store(chain="Willys", external_store_id="2132")
                self.assertEqual(survivor.name, "Gestrike")
                self.assertIsNone(survivor.pricing_scope)
            finally:
                db.close()

    def test_upsert_never_erases_known_scope_with_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = GroceryStore(Path(tmp) / "g.db")
            try:
                db.upsert_store(chain="ICA", external_store_id="1", name="Maxi",
                                provider="primat", pricing_scope="STORE_SPECIFIC")
                # En äldre anropare utan scope-kännedom skriver samma butik...
                db.upsert_store(chain="ICA", external_store_id="1", name="Maxi Ny")
                after = db.get_store(chain="ICA", external_store_id="1")
                self.assertEqual(after.name, "Maxi Ny")
                self.assertEqual(after.provider, "primat")          # ...utan att radera
                self.assertEqual(after.pricing_scope, "STORE_SPECIFIC")
            finally:
                db.close()


class RegisterSync(unittest.TestCase):
    def test_national_register_lands_with_honest_active_flags(self):
        payload = {"data": [
            {"chain": "ica", "store_id": "1", "name": "Maxi Lindhagen",
             "city": "Stockholm", "postcode": "112 50", "address": "G 1",
             "coordinates": {"latitude": 59.33, "longitude": 18.02}, "tier": "full"},
            {"chain": "ica", "store_id": "2", "name": "Nära Hörnet",
             "city": "Stockholm", "tier": "offers_only"},
            {"chain": "lidl", "store_id": "SE1", "name": "Lidl Umeå",
             "city": "Umeå", "tier": "offers_only"},
            {"chain": "okand", "store_id": "x", "name": "Okänd", "tier": "full"},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            db = GroceryStore(Path(tmp) / "g.db")
            try:
                with patch.object(register, "_request", return_value=payload):
                    summary = register.sync_store_register(db, "test-nyckel")
                self.assertEqual(summary["totalt"], 3)  # okänd kedja hoppas över
                maxi = db.get_store(chain="ICA", external_store_id="1")
                self.assertTrue(maxi.active)
                self.assertEqual(maxi.postal_code, "11250")  # mellanslag städas
                self.assertEqual(maxi.pricing_scope, "STORE_SPECIFIC")
                self.assertEqual(maxi.provider, "primat")
                # offers_only + STORE_SPECIFIC = kan aldrig prissättas -> inaktiv.
                self.assertFalse(db.get_store(chain="ICA", external_store_id="2").active)
                # offers_only + NATIONAL (Lidl) = kedjans katalog gäller ändå -> aktiv.
                self.assertTrue(db.get_store(chain="Lidl", external_store_id="SE1").active)
            finally:
                db.close()


class _DbTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "grocery.db"
        self._real = grocery_api.DB_PATH
        grocery_api.DB_PATH = self.db_path
        self.addCleanup(lambda: setattr(grocery_api, "DB_PATH", self._real))
        grocery_api.clear_cache()
        self.addCleanup(grocery_api.clear_cache)

    def seed_priced_store(self, db, chain, external_store_id, name,
                          product_name="Mellanmjölk 1,5%", price=13.5, **store_kw):
        store = db.upsert_store(chain=chain, external_store_id=external_store_id,
                                name=name, **store_kw)
        product = db.find_or_create_product(RawProduct(
            chain=chain, external_product_id=f"{chain}-{external_store_id}-p",
            name=product_name, store_id=external_store_id, store_name=name,
            size="1000 ml", quantity=1000.0, unit="ml",
            category="Mejeri, ost & ägg > Mjölk"))
        db.upsert_current_price(product_id=product.id, store_id=store.id,
                                regular_price=price, campaign_price=None,
                                member_price=None, multibuy_price=None,
                                unit_price=None, currency="SEK",
                                source_url=None, fetched_at=None)
        return store


class TenCitiesFindTheirStores(_DbTestCase):
    def test_every_city_gets_its_own_stores_sorted_by_distance(self):
        db = GroceryStore(self.db_path)
        try:
            for city, (lat, lng) in CITIES.items():
                db.upsert_store(chain="ICA", external_store_id=f"ica-{city}",
                                name=f"ICA {city}", city=city,
                                latitude=lat + 0.01, longitude=lng + 0.01,
                                active=True, pricing_scope="STORE_SPECIFIC")
                db.upsert_store(chain="Willys", external_store_id=f"w-{city}",
                                name=f"Willys {city}", city=city,
                                latitude=lat - 0.01, longitude=lng - 0.01,
                                active=True, pricing_scope="NATIONAL")
        finally:
            db.close()

        for city, (lat, lng) in CITIES.items():
            nearby = grocery_api.stores_near(lat, lng, max_km=40)
            names = {row["namn"] for row in nearby}
            self.assertIn(f"ICA {city}", names, f"{city} hittar inte sin ICA")
            self.assertIn(f"Willys {city}", names, f"{city} hittar inte sin Willys")
            for row in nearby:
                # Ingen annan orts butik läcker in: närmaste grannstad i
                # fixturerna ligger >4 mil bort (Uppsala-Stockholm ~60 km).
                self.assertEqual(row["ort"], city,
                                 f"{city} fick {row['namn']} ({row['ort']})")
                self.assertLess(row["avstandKm"], 5)
            distances = [row["avstandKm"] for row in nearby]
            self.assertEqual(distances, sorted(distances))

    def test_per_chain_cap_and_radius(self):
        db = GroceryStore(self.db_path)
        try:
            lat, lng = CITIES["Stockholm"]
            for i in range(10):
                db.upsert_store(chain="ICA", external_store_id=f"s{i}",
                                name=f"ICA {i}", city="Stockholm",
                                latitude=lat + i * 0.001, longitude=lng, active=True)
            db.upsert_store(chain="ICA", external_store_id="langt",
                            name="ICA Sundsvall", city="Sundsvall",
                            latitude=62.39, longitude=17.31, active=True)
        finally:
            db.close()
        nearby = grocery_api.stores_near(lat, lng, max_km=50, per_chain=6)
        self.assertEqual(len(nearby), 6)  # cap, och Sundsvall är utanför radien
        self.assertNotIn("ICA Sundsvall", {row["namn"] for row in nearby})


class PricingStoreResolution(_DbTestCase):
    def test_national_chain_prices_from_catalog_labels_users_store(self):
        db = GroceryStore(self.db_path)
        try:
            self.seed_priced_store(db, "Willys", "2132", "Willys Gävle Gestrike",
                                   pricing_scope="NATIONAL")
            db.upsert_store(chain="Willys", external_store_id="9999",
                            name="Willys Älvsjö", city="Stockholm",
                            pricing_scope="NATIONAL")
            catalog, label, reason = grocery_api.resolve_pricing_store(db, "Willys", "9999")
            self.assertIsNone(reason)
            self.assertEqual(catalog["name"], "Willys Gävle Gestrike")  # priser härifrån
            self.assertEqual(label["name"], "Willys Älvsjö")            # etikett hit
        finally:
            db.close()

    def test_store_specific_chain_refuses_other_stores_prices(self):
        db = GroceryStore(self.db_path)
        try:
            self.seed_priced_store(db, "City Gross", "3209", "City Gross Gävle",
                                   pricing_scope="STORE_SPECIFIC")
            db.upsert_store(chain="City Gross", external_store_id="3203",
                            name="City Gross Malmö", city="Arlöv",
                            pricing_scope="STORE_SPECIFIC")
            catalog, label, reason = grocery_api.resolve_pricing_store(
                db, "City Gross", "3203")
            self.assertIsNone(catalog)  # ALDRIG Gävlepriser under Malmös namn
            self.assertEqual(reason, "no_data_for_store")
            self.assertEqual(label["name"], "City Gross Malmö")
            # ...men utan användarval gäller katalogbutiken som förut.
            catalog, label, reason = grocery_api.resolve_pricing_store(db, "City Gross")
            self.assertEqual(catalog["name"], "City Gross Gävle")
            self.assertIsNone(reason)
        finally:
            db.close()

    def test_default_prefers_the_store_that_has_prices(self):
        """Registret fyller tabellen med tusentals prislösa rader - kedjans
        katalogbutik får inte bli 'raden med lägst id' av en slump."""
        db = GroceryStore(self.db_path)
        try:
            db.upsert_store(chain="Hemköp", external_store_id="0001",
                            name="Hemköp Register Först")
            self.seed_priced_store(db, "Hemköp", "4256", "Hemköp Uppsala")
            row = grocery_api._store_row_for(db, "Hemköp")
            self.assertEqual(row["name"], "Hemköp Uppsala")
        finally:
            db.close()


class PriceWeekWithUserStores(_DbTestCase):
    def test_national_relabel_and_store_specific_honesty(self):
        db = GroceryStore(self.db_path)
        try:
            self.seed_priced_store(db, "Willys", "2132", "Willys Gävle Gestrike",
                                   pricing_scope="NATIONAL")
            self.seed_priced_store(db, "Hemköp", "4256", "Hemköp Uppsala",
                                   pricing_scope="NATIONAL", price=15.5)
            self.seed_priced_store(db, "City Gross", "3209", "City Gross Gävle",
                                   pricing_scope="STORE_SPECIFIC", price=14.0)
            db.upsert_store(chain="Willys", external_store_id="9999",
                            name="Willys Älvsjö", pricing_scope="NATIONAL")
            db.upsert_store(chain="City Gross", external_store_id="3203",
                            name="City Gross Malmö", pricing_scope="STORE_SPECIFIC")
        finally:
            db.close()

        payload = grocery_api.price_week(
            [{"name": "Mjölk", "amount": 1, "unit": "l"}],
            store_selection={"Willys": "9999", "City Gross": "3203"})
        by_chain = {r["chain"]: r for r in payload["results"]}
        # Willys: nationellt pris, användarens butik på etiketten.
        self.assertEqual(by_chain["Willys"]["store"]["name"], "Willys Älvsjö")
        self.assertIsNotNone(by_chain["Willys"]["totalCheckoutCost"])
        # City Gross: användarens butik saknar katalog -> ärligt otillgänglig,
        # aldrig Gävlepriser under Malmönamn.
        self.assertNotIn("City Gross", by_chain)
        self.assertEqual(payload["unavailableChains"],
                         [{"chain": "City Gross", "reason": "no_data_for_store",
                           "storeName": "City Gross Malmö", "externalStoreId": "3203"}])
        # Hemköp utan val: katalogbutiken som förut.
        self.assertEqual(by_chain["Hemköp"]["store"]["name"], "Hemköp Uppsala")

        # Utan butiksval: City Gross är med (testmarknadens butik) - och
        # svaret delar INTE cache med butiksvalsvarianten.
        default_payload = grocery_api.price_week(
            [{"name": "Mjölk", "amount": 1, "unit": "l"}])
        self.assertIn("City Gross", {r["chain"] for r in default_payload["results"]})


if __name__ == "__main__":
    unittest.main()
