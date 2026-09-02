# -*- coding: utf-8 -*-
"""Två prisnivåer + butikspartner - de tio fallen Adam beställde:

  1. referenspris används utan partner
  2. verifierat butikspris går före referens
  3. gammalt butikspris faller tillbaka på referens
  4. ogiltigt butikspris går aldrig live
  5. betalande butik påverkar inte rankingen
  6. samma produkt delas mellan butiker via GTIN
  7. kampanjdatum
  8. medlemspris
  9. partneraktivering/avaktivering
 10. grupp- och kedjepartner

Allt körs mot temporära databaser - inga nätverksanrop."""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.grocery import api as grocery_api  # noqa: E402
from services.grocery import partners  # noqa: E402
from services.grocery import register  # noqa: E402
from services.grocery.models import RawProduct  # noqa: E402
from services.grocery.pricing import (  # noqa: E402
    MAX_STORE_PRICE_AGE_SECONDS, RecipePricingEngine, effective_price)
from services.grocery.publish import gate_row, publish_run  # noqa: E402
from services.grocery.store import GroceryStore  # noqa: E402

MILK_GTIN = "07310865093530"


def _raw(chain, store_ext, name="Mellanmjölk 1,5%", gtin=MILK_GTIN, price=13.5, **kw):
    return RawProduct(chain=chain, external_product_id=f"{chain}-{store_ext}-{gtin or name}",
                      name=name, store_id=store_ext, store_name=store_ext, gtin=gtin,
                      size="1000 ml", quantity=1000.0, unit="ml",
                      category="Mejeri, ost & ägg > Mjölk", regular_price=price, **kw)


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "grocery.db"
        self._real = grocery_api.DB_PATH
        grocery_api.DB_PATH = self.db_path
        self.addCleanup(lambda: setattr(grocery_api, "DB_PATH", self._real))
        grocery_api.clear_cache()
        self.addCleanup(grocery_api.clear_cache)
        self.db = GroceryStore(self.db_path)
        self.addCleanup(self.db.close)
        register.ensure_chains(self.db)

    def store(self, chain, ext, name, scope=None, **kw):
        return self.db.upsert_store(chain=chain, external_store_id=ext, name=name,
                                    pricing_scope=scope or register.CHAIN_PRICING_SCOPE[chain], **kw)

    def reference(self, chain, product_id, price, **kw):
        self.db.upsert_reference_price(product_id=product_id, chain=chain, regular_price=price,
                                       source=f"test:{chain}", **kw)

    def store_price(self, product_id, store_id, price, source="test", **kw):
        self.db.upsert_current_price(product_id=product_id, store_id=store_id, regular_price=price,
                                     source=source, **kw)

    def milk_product(self, chain, ext):
        return self.db.find_or_create_product(_raw(chain, ext))

    def price_milk(self, chain, external_store_id=None):
        grocery_api.clear_cache()
        target = grocery_api.resolve_pricing_store(self.db, chain, external_store_id)
        self.assertIsNone(target.reason, target.reason)
        engine = RecipePricingEngine(self.db)
        return engine.price_list([{"name": "Mjölk", "amount": 1, "unit": "l"}], chain, target.store_id)


class ReferenceAndStorePrices(_Base):
    def test_1_reference_price_is_used_without_partner(self):
        product = self.milk_product("ICA", "1003987")
        self.store("ICA", "1003987", "Maxi Gävle")
        self.store("ICA", "1000123", "ICA Maxi Lindhagen", city="Stockholm")
        self.reference("ICA", product.id, 12.9)

        result = self.price_milk("ICA", "1000123")
        row = result["matchedItems"][0]
        self.assertEqual(row["priceTier"], "REFERENCE_PRICE")
        self.assertEqual(row["totalCost"], 12.9)
        self.assertEqual(result["pricingBasis"], "REFERENCE")

    def test_2_verified_store_price_overrides_reference(self):
        product = self.milk_product("ICA", "1003987")
        lindhagen = self.store("ICA", "1000123", "ICA Maxi Lindhagen")
        self.reference("ICA", product.id, 12.9)
        self.store_price(product.id, lindhagen.id, 14.4, source="primat:ica:1000123")

        result = self.price_milk("ICA", "1000123")
        row = result["matchedItems"][0]
        self.assertEqual(row["priceTier"], "VERIFIED_STORE_PRICE")
        self.assertEqual(row["totalCost"], 14.4)  # dyrare men SANT för butiken
        self.assertEqual(result["pricingBasis"], "VERIFIED")

    def test_3_stale_store_price_falls_back_to_reference(self):
        product = self.milk_product("ICA", "1003987")
        lindhagen = self.store("ICA", "1000123", "ICA Maxi Lindhagen")
        self.reference("ICA", product.id, 12.9)
        self.store_price(product.id, lindhagen.id, 14.4,
                         fetched_at=time.time() - MAX_STORE_PRICE_AGE_SECONDS - 3600)

        result = self.price_milk("ICA", "1000123")
        row = result["matchedItems"][0]
        self.assertEqual(row["priceTier"], "REFERENCE_PRICE")
        self.assertEqual(row["totalCost"], 12.9)

    def test_no_price_at_all_is_missing_never_guessed(self):
        self.milk_product("ICA", "1003987")
        self.store("ICA", "1000123", "ICA Maxi Lindhagen")
        target = grocery_api.resolve_pricing_store(self.db, "ICA", "1000123")
        self.assertEqual(target.reason, "no_data_for_store")

    def test_6_same_gtin_is_one_product_across_stores(self):
        a = self.db.find_or_create_product(_raw("ICA", "1", price=10))
        b = self.db.find_or_create_product(_raw("Coop", "2", price=11))
        c = self.db.find_or_create_product(_raw("Willys", "3", name="Arla Mellanmjölk 1,5% 1l", price=12))
        self.assertEqual(a.id, b.id)
        self.assertEqual(a.id, c.id)  # namnet får skilja - GTIN avgör
        self.assertEqual(self.db.connection.execute(
            "SELECT COUNT(*) FROM grocery_products WHERE gtin = ?", (MILK_GTIN,)).fetchone()[0], 1)

    def test_7_expired_campaign_is_not_a_price(self):
        product = self.milk_product("ICA", "1003987")
        maxi = self.store("ICA", "1003987", "Maxi Gävle")
        self.store_price(product.id, maxi.id, 15.0, campaign_price=9.9,
                         valid_to=time.time() - 60)
        price = self.db.get_current_price(product.id, maxi.id)
        self.assertEqual(effective_price(price), 15.0)  # kampanjen har gått ut
        self.store_price(product.id, maxi.id, 15.0, campaign_price=9.9,
                         valid_to=time.time() + 86400)
        price = self.db.get_current_price(product.id, maxi.id)
        self.assertEqual(effective_price(price), 9.9)

    def test_8_member_price_is_carried_but_never_the_checkout_price(self):
        product = self.milk_product("ICA", "1003987")
        maxi = self.store("ICA", "1003987", "Maxi Gävle")
        self.store_price(product.id, maxi.id, 15.0, member_price=12.0)
        result = self.price_milk("ICA", "1003987")
        row = result["matchedItems"][0]
        self.assertEqual(row["memberPrice"], 12.0)
        self.assertEqual(row["totalCost"], 15.0)  # medlemspris gäller inte alla


class QualityGateNeverLetsBadDataLive(_Base):
    def test_4_invalid_store_prices_never_go_live(self):
        product = self.milk_product("ICA", "1003987")
        maxi = self.store("ICA", "1003987", "Maxi Gävle")
        run = self.db.start_collector_run(chain="ICA", store_id=maxi.id)
        for bad in (0, -5, 99999, "abc"):
            self.db.stage_price(run_id=run.id, store_id=maxi.id, product_id=product.id,
                                regular_price=bad, source="test")
        outcome = publish_run(self.db, run.id, maxi.id, "ICA", source="test")
        self.assertFalse(outcome["published_ok"])
        self.assertEqual(self.db.price_count_for_store(maxi.id), 0)
        self.assertEqual(outcome["gatePercent"], 0.0)

    def test_gate_row_reasons(self):
        self.assertEqual(gate_row({"regular_price": 0}, "Mjölk")[1], "pris_noll_eller_negativt")
        self.assertEqual(gate_row({"regular_price": 50000}, "Mjölk")[1], "pris_orimligt_hogt")
        self.assertEqual(gate_row({"regular_price": 12, "unit_price": 99999}, "Mjölk")[1],
                         "jamforpris_orimligt")
        self.assertEqual(gate_row({"regular_price": 12}, None)[1], "produkt_saknar_namn")
        ok, _, cleaned = gate_row({"regular_price": 12, "campaign_price": 15}, "Mjölk")
        self.assertTrue(ok)
        self.assertIsNone(cleaned["campaign_price"])  # "kampanj" dyrare än ordinarie

    def test_broken_night_keeps_last_approved_dataset(self):
        product = self.milk_product("ICA", "1003987")
        maxi = self.store("ICA", "1003987", "Maxi Gävle")
        self.store_price(product.id, maxi.id, 13.5)
        run = self.db.start_collector_run(chain="ICA", store_id=maxi.id)
        # 19 av 20 rader trasiga -> gaten fäller körningen.
        for i in range(19):
            self.db.stage_price(run_id=run.id, store_id=maxi.id, product_id=product.id, regular_price=-1)
        self.db.stage_price(run_id=run.id, store_id=maxi.id, product_id=product.id, regular_price=99.0)
        outcome = publish_run(self.db, run.id, maxi.id, "ICA", source="test")
        self.assertFalse(outcome["published_ok"])
        self.assertEqual(self.db.get_current_price(product.id, maxi.id).regular_price, 13.5)

    def test_complete_run_with_suspiciously_few_rows_is_refused(self):
        products = [self.db.find_or_create_product(_raw("ICA", "x", name=f"Vara {i}", gtin=None, price=10))
                    for i in range(10)]
        maxi = self.store("ICA", "1003987", "Maxi Gävle")
        for product in products:
            self.store_price(product.id, maxi.id, 10.0)
        run = self.db.start_collector_run(chain="ICA", store_id=maxi.id)
        self.db.stage_price(run_id=run.id, store_id=maxi.id, product_id=products[0].id, regular_price=11.0)
        outcome = publish_run(self.db, run.id, maxi.id, "ICA", source="test", blocked=False)
        self.assertFalse(outcome["published_ok"])
        self.assertIn("misstänkt", outcome["message"])
        # ...men samma körning märkt blocked (källan avbröt) slås ihop.
        run2 = self.db.start_collector_run(chain="ICA", store_id=maxi.id)
        self.db.stage_price(run_id=run2.id, store_id=maxi.id, product_id=products[0].id, regular_price=11.0)
        outcome = publish_run(self.db, run2.id, maxi.id, "ICA", source="test", blocked=True)
        self.assertTrue(outcome["published_ok"])
        self.assertEqual(self.db.get_current_price(products[0].id, maxi.id).regular_price, 11.0)
        self.assertEqual(self.db.price_count_for_store(maxi.id), 10)  # inget raderat

    def test_reference_is_published_from_national_and_reference_stores_only(self):
        product = self.milk_product("Willys", "2132")
        willys = self.store("Willys", "2132", "Willys Gestrike")
        run = self.db.start_collector_run(chain="Willys", store_id=willys.id)
        self.db.stage_price(run_id=run.id, store_id=willys.id, product_id=product.id, regular_price=12.0)
        publish_run(self.db, run.id, willys.id, "Willys", source="axfood:2132")
        self.assertEqual(self.db.reference_price_count("Willys"), 1)

        other_ica = self.store("ICA", "1000123", "ICA Maxi Lindhagen")
        run = self.db.start_collector_run(chain="ICA", store_id=other_ica.id)
        self.db.stage_price(run_id=run.id, store_id=other_ica.id, product_id=product.id, regular_price=14.0)
        publish_run(self.db, run.id, other_ica.id, "ICA", source="primat:ica:1000123")
        self.assertEqual(self.db.reference_price_count("ICA"), 0)  # inte referensbutiken

        maxi = self.store("ICA", register.CHAIN_REFERENCE_STORE["ICA"], "Maxi Gävle")
        run = self.db.start_collector_run(chain="ICA", store_id=maxi.id)
        self.db.stage_price(run_id=run.id, store_id=maxi.id, product_id=product.id, regular_price=13.0)
        publish_run(self.db, run.id, maxi.id, "ICA", source="primat:ica:1003987")
        self.assertEqual(self.db.reference_price_count("ICA"), 1)


class PartnersNeverBuyTheRanking(_Base):
    def test_5_paying_partner_does_not_affect_ranking(self):
        product = self.milk_product("ICA", "1003987")
        self.milk_product("Willys", "2132")  # samma GTIN, Willys-katalogpost
        ica = self.store("ICA", "1003987", "Maxi Gävle")
        willys = self.store("Willys", "2132", "Willys Gestrike")
        self.store_price(product.id, ica.id, 18.0)
        self.store_price(product.id, willys.id, 12.0)
        created = partners.create_partner(self.db, kind="PER_STORE", name="Maxi Gävle AB",
                                          chain="ICA", store_external_ids=["1003987"])
        partners.set_status(self.db, created["partnerId"], "ACTIVE")
        self.assertEqual(partners.effective_partner_status(self.db, ica.id), ("ACTIVE", created["partnerId"]))

        with patch.object(grocery_api, "RELEASED_CHAINS", ("Willys", "ICA")):
            payload = grocery_api.price_week([{"name": "Mjölk", "amount": 1, "unit": "l"}],
                                             store_selection={"ICA": "1003987", "Willys": "2132"})
        self.assertEqual(payload["comparison"]["cheapestChain"], "Willys")  # betalar inte -> vinner ändå

    def test_9_activation_and_deactivation(self):
        product = self.milk_product("ICA", "1003987")
        maxi = self.store("ICA", "1003987", "Maxi Gävle")
        self.reference("ICA", product.id, 12.9)
        created = partners.create_partner(self.db, kind="PER_STORE", name="Maxi Gävle AB",
                                          chain="ICA", store_external_ids=["1003987"])
        pid = created["partnerId"]
        self.assertTrue(created["apiKey"].startswith("mjp_"))
        self.assertIsNotNone(partners.authenticate_partner(self.db, created["apiKey"]))
        self.assertIsNone(partners.authenticate_partner(self.db, "fel-nyckel"))

        # PENDING får inte leverera.
        with self.assertRaises(PermissionError):
            partners.ingest_feed(self.db, partner_id=pid, store_id=maxi.id, format="JSON",
                                 payload=[{"gtin": MILK_GTIN, "namn": "Mellanmjölk", "pris": "14,40"}])
        partners.set_status(self.db, pid, "ACTIVE")
        outcome = partners.ingest_feed(self.db, partner_id=pid, store_id=maxi.id, format="JSON",
                                       payload=[{"gtin": MILK_GTIN, "namn": "Mellanmjölk 1,5%",
                                                 "storlek": "1000 ml", "pris": "14,40"}])
        self.assertTrue(outcome["publishedOk"], outcome)
        self.assertEqual(self.price_milk("ICA", "1003987")["matchedItems"][0]["priceTier"],
                         "VERIFIED_STORE_PRICE")
        self.assertEqual(self.db.reference_price_count("ICA"), 1)  # partnerpris blev inte referens

        # Paus: partnerpriserna bort, referensen tar över.
        partners.set_status(self.db, pid, "PAUSED")
        self.assertEqual(partners.effective_partner_status(self.db, maxi.id)[0], "PAUSED")
        result = self.price_milk("ICA", "1003987")
        self.assertEqual(result["matchedItems"][0]["priceTier"], "REFERENCE_PRICE")
        self.assertEqual(result["matchedItems"][0]["totalCost"], 12.9)

    def test_invalid_partner_rows_never_go_live(self):
        product = self.milk_product("ICA", "1003987")
        maxi = self.store("ICA", "1003987", "Maxi Gävle")
        created = partners.create_partner(self.db, kind="PER_STORE", name="X", chain="ICA",
                                          store_external_ids=["1003987"])
        partners.set_status(self.db, created["partnerId"], "ACTIVE")
        outcome = partners.ingest_feed(self.db, partner_id=created["partnerId"], store_id=maxi.id,
                                       format="JSON",
                                       payload=[{"gtin": MILK_GTIN, "namn": "Mellanmjölk", "pris": "0"},
                                                {"gtin": MILK_GTIN, "namn": "Mellanmjölk", "pris": "-3"}])
        self.assertFalse(outcome["publishedOk"])
        self.assertEqual(self.db.price_count_for_store(maxi.id), 0)

    def test_10_group_and_chain_partners(self):
        eken = self.store("Coop", "206403", "Coop Eken")
        nian = self.store("Coop", "206401", "Coop Nian")
        other = self.store("Coop", "999999", "Coop Annanstans")
        group = partners.create_partner(self.db, kind="PER_GROUP", name="Coop Mitt",
                                        chain="Coop", store_external_ids=["206403", "206401"])
        partners.set_status(self.db, group["partnerId"], "ACTIVE")
        self.assertEqual(partners.effective_partner_status(self.db, eken.id)[0], "ACTIVE")
        self.assertEqual(partners.effective_partner_status(self.db, nian.id)[0], "ACTIVE")
        self.assertEqual(partners.effective_partner_status(self.db, other.id)[0], "NONE")

        w1 = self.store("Willys", "2132", "Willys Gestrike")
        w2 = self.store("Willys", "2283", "Willys Mariahallen")
        chain_partner = partners.create_partner(self.db, kind="PER_CHAIN", name="Willys AB", chain="Willys")
        self.assertEqual(partners.effective_partner_status(self.db, w1.id)[0], "PENDING")
        partners.set_status(self.db, chain_partner["partnerId"], "ACTIVE")
        for store in (w1, w2):
            self.assertEqual(partners.effective_partner_status(self.db, store.id),
                             ("ACTIVE", chain_partner["partnerId"]))
        partners.set_status(self.db, chain_partner["partnerId"], "CANCELLED")
        self.assertEqual(partners.effective_partner_status(self.db, w2.id)[0], "CANCELLED")

    def test_plan_price_is_data_not_code(self):
        plan = self.db.connection.execute(
            "SELECT monthly_price_sek, billing_model FROM grocery_partner_plans WHERE code = 'matjakt_butik'").fetchone()
        self.assertEqual(plan["monthly_price_sek"], 1495)
        self.db.connection.execute("UPDATE grocery_partner_plans SET monthly_price_sek = 1295")
        created = partners.create_partner(self.db, kind="PER_STORE", name="Ny", chain="ICA",
                                          store_external_ids=[])
        self.assertEqual(self.db.get_partner(created["partnerId"])["monthly_price_sek"], 1295)


class ComparisonBasisLabels(_Base):
    def test_reference_only_comparison_says_so(self):
        product = self.milk_product("Willys", "2132")
        self.milk_product("Hemköp", "4256")
        willys = self.store("Willys", "2132", "Willys Gestrike")
        hemkop = self.store("Hemköp", "4256", "Hemköp Uppsala")
        self.store_price(product.id, willys.id, 12.0)
        self.store_price(product.id, hemkop.id, 14.0)
        self.reference("Willys", product.id, 12.0)
        self.reference("Hemköp", product.id, 14.0)
        self.store("Willys", "2283", "Willys Mariahallen")
        self.store("Hemköp", "4297", "Hemköp Stockholm City")
        payload = grocery_api.price_week([{"name": "Mjölk", "amount": 1, "unit": "l"}],
                                         store_selection={"Willys": "2283", "Hemköp": "4297"})
        self.assertEqual(payload["comparison"]["basis"], "reference")
        self.assertEqual(payload["comparison"]["basisLabel"], "Billigast enligt aktuella referenspriser")
        labels = {r["chain"]: r["priceLabel"] for r in payload["results"]}
        self.assertEqual(labels["Willys"], "Willys referenspris")
        # ...och de riktiga katalogbutikerna: verifierade.
        payload = grocery_api.price_week([{"name": "Mjölk", "amount": 1, "unit": "l"}],
                                         store_selection={"Willys": "2132", "Hemköp": "4256"})
        self.assertEqual(payload["comparison"]["basis"], "verified")
        self.assertEqual(payload["comparison"]["basisLabel"], "Billigast bland dina valda butiker")


if __name__ == "__main__":
    unittest.main()
