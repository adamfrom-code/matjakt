# -*- coding: utf-8 -*-
"""O15: fyra tal som alla heter "butiker" och inte får blandas ihop."""
import sys, tempfile, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.grocery import api as grocery_api  # noqa: E402
from services.grocery.models import RawProduct  # noqa: E402
from services.grocery.pricing import MAX_STORE_PRICE_AGE_SECONDS  # noqa: E402
from services.grocery.store import GroceryStore  # noqa: E402


class FyraButiksdefinitioner(unittest.TestCase):

    def _bygg(self, tmp, chain):
        db = GroceryStore(Path(tmp) / "g.db")
        nu = time.time()
        b = {}
        for nyckel, aktiv in (("inaktiv", False), ("aktiv_utan_pris", True),
                              ("aktiv_farsk", True), ("aktiv_gammal", True)):
            b[nyckel] = db.upsert_store(chain=chain, external_store_id=nyckel, name=nyckel, active=aktiv)
        p = db.find_or_create_product(RawProduct(chain=chain, external_product_id="mjolk", name="Mjölk",
            store_id="aktiv_farsk", store_name=chain, gtin=None, brand=None, size="1 l",
            quantity=None, unit=None, category=None))
        for nyckel, alder in (("aktiv_farsk", 3600), ("aktiv_gammal", MAX_STORE_PRICE_AGE_SECONDS + 3600),
                              ("inaktiv", 3600)):
            db.upsert_current_price(product_id=p.id, store_id=b[nyckel].id, regular_price=15.0,
                campaign_price=None, member_price=None, multibuy_price=None, unit_price=None,
                currency="SEK", source_url=None, fetched_at=nu - alder)
        return db, nu

    def test_de_fyra_talen_ar_olika_och_ratt(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, nu = self._bygg(tmp, "Willys")          # släppt kedja
            try:
                r = grocery_api.store_counts(db, "Willys", now=nu)
            finally:
                db.close()
        self.assertEqual(r["iRegistret"], 4)            # alla fyra finns i registret
        self.assertEqual(r["aktiva"], 3)                # en är avstängd
        self.assertEqual(r["farska"], 1)                # bara den aktiva med färskt pris
        self.assertEqual(r["kundtillgangliga"], 1)      # Willys är släppt
        self.assertTrue(r["slapptKedja"])
        self.assertIn("4 dygn", r["farskGrans"])

    def test_en_farsk_butik_i_osläppt_kedja_nar_ingen_kund(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, nu = self._bygg(tmp, "ICA")             # inte i RELEASED_CHAINS
            try:
                r = grocery_api.store_counts(db, "ICA", now=nu)
            finally:
                db.close()
        self.assertEqual(r["farska"], 1)
        self.assertEqual(r["kundtillgangliga"], 0)
        self.assertFalse(r["slapptKedja"])

    def test_ett_farskt_pris_i_en_inaktiv_butik_raknas_inte_som_farsk(self):
        # "inaktiv" har ett färskt pris men är avstängd: den är i registret,
        # inte aktiv, inte färsk - annars smiter avstängda butiker in i talet.
        with tempfile.TemporaryDirectory() as tmp:
            db, nu = self._bygg(tmp, "Willys")
            try:
                r = grocery_api.store_counts(db, "Willys", now=nu)
            finally:
                db.close()
        self.assertEqual(r["farska"], 1)

    def test_talen_bar_kalla_och_mattid(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, nu = self._bygg(tmp, "Willys")
            try:
                r = grocery_api.store_counts(db, "Willys", now=nu)
            finally:
                db.close()
        self.assertEqual(r["mattVid"], nu)
        self.assertIn("grocery_stores", r["kalla"])


if __name__ == "__main__":
    unittest.main()
