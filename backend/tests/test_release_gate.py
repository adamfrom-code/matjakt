# -*- coding: utf-8 -*-
"""RELEASE GATE (2026-09-02): de tre produktionsfelen Adam hittade, som
exakta regressioner, plus paketmatematikens invarianter.

    Fiskpinnar: 224 g behov mot 450 g-paket visades som 224 st och 6 561 kr.
    Persilja:   10 g behov mot 50 g-paket visades i stycken, ~100 kr.
    Kanel:      matchade "Wasa Kanel Veteknäcke" (Bröd & Kakor).

Två grundorsaker: frontends paketfallback behandlade vikt/volym utan
paketinfo som styck (fiskpinnar + persilja, samma rot), och torra kryddor
saknade avdelningskrav så bakverk som LEDER med kryddnamnet godkändes
(kanel, egen rot). Dessa tester låser båda för alltid."""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.grocery.models import RawProduct  # noqa: E402
from services.grocery.pricing import (  # noqa: E402
    RecipePricingEngine,
    convert_amount,
    packages_needed,
    product_matches_ingredient,
)
from services.grocery.store import GroceryStore  # noqa: E402


def _engine_with(products):
    """En motor mot en riktig temporär databas med givna produkter+priser."""
    import tempfile
    tmp = tempfile.TemporaryDirectory()
    db = GroceryStore(Path(tmp.name) / "gate.db")
    store = db.upsert_store(chain="Willys", external_store_id="1", name="Willys test",
                            city=None, postal_code=None, address=None,
                            latitude=None, longitude=None, active=True)
    for spec in products:
        product = db.find_or_create_product(RawProduct(
            chain="Willys", external_product_id=spec["id"], name=spec["name"],
            store_id="1", store_name="Willys", gtin=None, brand=spec.get("brand"),
            size=spec.get("size"), quantity=spec["quantity"], unit=spec["unit"],
            category=spec.get("category")))
        db.upsert_current_price(product_id=product.id, store_id=store.id,
                                regular_price=spec["price"], campaign_price=spec.get("campaign"),
                                member_price=None, multibuy_price=None, unit_price=spec.get("unit_price"),
                                currency="SEK", source_url=None, fetched_at=None)
    engine = RecipePricingEngine(db)
    return engine, store.id, tmp, db


class TheThreeProductionErrors(unittest.TestCase):
    def test_fiskpinnar_224g_against_450g_package_is_one_package(self):
        engine, store_id, tmp, db = _engine_with([{
            "id": "fp", "name": "Fiskpinnar Frysta/15-pack", "size": "450g",
            "quantity": 450.0, "unit": "g", "price": 23.5,
            "category": "Fryst > Fisk & skaldjur > Fisk"}])
        try:
            row = engine.price_item("Fiskpinnar", 224, "g", "Willys", store_id)
            self.assertIsNotNone(row)
            self.assertEqual(row["packages"], 1)
            self.assertTrue(row["exactPackaging"])
            self.assertEqual(row["totalCost"], 23.5)
        finally:
            db.close(); tmp.cleanup()

    def test_persilja_10g_against_50g_package_is_one_package(self):
        engine, store_id, tmp, db = _engine_with([{
            "id": "pe", "name": "Persilja Finhackad Fryst", "size": "50g",
            "quantity": 50.0, "unit": "g", "price": 8.9,
            "category": "Fryst > Grönsaker & kryddor > Kryddor"}])
        try:
            row = engine.price_item("Persilja", 10, "g", "Willys", store_id)
            self.assertIsNotNone(row)
            self.assertEqual(row["packages"], 1)
            self.assertTrue(row["exactPackaging"])
            self.assertEqual(row["totalCost"], 8.9)
        finally:
            db.close(); tmp.cleanup()

    def test_kanel_kryddmatt_against_spice_jar_is_one_package_decided(self):
        """2-5 g eller 1 tsk kanel mot en kryddburk är EN förpackning - en
        bestämd regel (<=30 ml kryddmått mot >=15 g-förpackning), inte en
        gissning, så raden får ingå i säkra totaler."""
        engine, store_id, tmp, db = _engine_with([{
            "id": "ka", "name": "Kanel Malen Påse", "size": "19g",
            "quantity": 19.0, "unit": "g", "price": 12.2,
            "category": "Skafferi > Kryddor & smaksättare > Kryddor"}])
        try:
            for amount, unit in ((2, "g"), (5, "g"), (1, "tsk"), (1, "msk")):
                row = engine.price_item("Kanel", amount, unit, "Willys", store_id)
                self.assertIsNotNone(row, f"{amount} {unit}")
                self.assertEqual(row["packages"], 1, f"{amount} {unit}")
                self.assertTrue(row["exactPackaging"], f"{amount} {unit}")
        finally:
            db.close(); tmp.cleanup()

    def test_a_dense_liquid_is_never_one_exact_package(self):
        """2 msk honung behöver ~42 g (densitet ~1,4) och ryms INTE i en
        15-gramsburk. Regeln prövade förut bara mängderna, inte att varan var
        en torr krydda, så honung fick "1 förpackning, exakt" - och en
        underskattad rad räknas in i säkra totaler och går rakt in i
        billigast-jämförelsen mellan kedjor.

        Revisionen fångar den inte heller: audit.py flaggar volym-som-styck
        bara när paketenheten saknas i massregistret, vilket är precis det
        här fallet. Testet är därför enda skyddet."""
        for namn, produkt, kategori in [
            ("Honung", "Honung Flytande", "Skafferi > Sötningsmedel"),
            ("Sirap", "Sirap Ljus", "Skafferi > Sötningsmedel"),
            ("Olivolja", "Olivolja Extra", "Skafferi > Olja & vinäger"),
            ("Tomatpuré", "Tomatpuré", "Skafferi > Konserver"),
        ]:
            engine, store_id, tmp, db = _engine_with([{
                "id": "x", "name": produkt, "size": "20g", "quantity": 20.0,
                "unit": "g", "price": 25.0, "category": kategori}])
            try:
                row = engine.price_item(namn, 2, "msk", "Willys", store_id)
                # Ingen tyst passering: matchas varan inte alls prövar testet
                # ingenting, och då är det värdelöst som skydd.
                self.assertIsNotNone(row, f"{namn} matchades inte - testet mäter inget")
                self.assertFalse(row["exactPackaging"],
                                 f"{namn} markerades som exakt förpackning")
            finally:
                db.close(); tmp.cleanup()

    def test_the_spice_rule_holds_at_its_own_boundary(self):
        """30 ml (2 msk) mot exakt 15 g är regelns yttersta kant och ska
        fortfarande vara exakt. Testas för att en framtida skärpning av
        gränsen inte tyst ska göra kryddor osäkra."""
        engine, store_id, tmp, db = _engine_with([{
            "id": "ka", "name": "Kanel Malen", "size": "15g",
            "quantity": 15.0, "unit": "g", "price": 10.0,
            "category": "Skafferi > Kryddor & smaksättare > Kryddor"}])
        try:
            row = engine.price_item("Kanel", 2, "msk", "Willys", store_id)
            self.assertIsNotNone(row)
            self.assertTrue(row["exactPackaging"])
        finally:
            db.close(); tmp.cleanup()

    def test_kanel_never_matches_kanel_flavoured_bakery(self):
        for product, category in [
            ("Kanel Veteknäcke Runt", "Bröd & Kakor > Knäckebröd & Skorpor"),
            ("Kanelbullar 6-pack", "Bröd & bageri > Kaffebröd"),
            ("Kanelkakor", "Bröd & Kakor > Kex"),
            ("Kanellängd", "Bröd & bageri"),
            ("Kanel & Äpple Gröt", "Skafferi > Frukost"),
        ]:
            self.assertFalse(
                product_matches_ingredient(product, "Kanel", "Wasa", category),
                f"{product!r} får aldrig prissätta kryddan kanel")
        # ...och den äkta varan måste förstås fortsätta matcha.
        self.assertTrue(product_matches_ingredient(
            "Kanel Malen Påse", "Kanel", None, "Skafferi > Kryddor & smaksättare"))

    def test_soltorkade_tomater_live_in_the_pantry_not_produce(self):
        """Utan egen avdelningspost ärvde "soltorkade tomater" ordet
        "tomater" och krävde frukt & grönt - varenda äkta burk hos City
        Gross (Skafferi > Oliver & delikatess) avvisades. Skafferivaran är
        skafferivaran; färdigmat som LEDER med orden avvisas fortfarande."""
        self.assertTrue(product_matches_ingredient(
            "Tomater Soltorkade Bitar", "Soltorkade tomater", None,
            "Skafferi > Oliver & delikatess"))
        self.assertFalse(product_matches_ingredient(
            "Soltorkad Tomat Ätklar Kyckling Skivad", "Soltorkade tomater",
            None, "Kött, chark & fågel > Fågel > Kyckling"))
        # Färsk tomat ska INTE ha vidgats av posten.
        self.assertFalse(product_matches_ingredient(
            "Tomater Soltorkade Bitar", "Tomater", None,
            "Skafferi > Oliver & delikatess"))


class VocabularyAliasesStayHonest(unittest.TestCase):
    """Handelsnamn-aliasen från CG-separationen (2026-09-02): varje alias
    breddar bara NAMNET, aldrig råvaran. Här låses både att äkta varan
    matchar och att grannfällan inte gör det."""

    def test_kvarg_naturell_matches_but_flavoured_does_not(self):
        self.assertTrue(product_matches_ingredient(
            "Naturell Kvarg 0,3%", "naturell kvarg", "Eldorado",
            "Mejeri, ost & ägg > Kvarg & Cottage Cheese"))
        for flavoured in ("Päron Kvarg 0,2%", "Jordgubb Hallon Fruktkvarg",
                          "Vanilj Mild Kvarg 0,2%"):
            self.assertFalse(product_matches_ingredient(
                flavoured, "Kvarg", None, "Mejeri, ost & ägg"),
                f"{flavoured!r} är smaksatt och får inte prissätta ren kvarg")

    def test_sallad_is_lettuce_never_a_composed_ready_salad(self):
        self.assertFalse(product_matches_ingredient(
            "Potatissallad Original", "Sallad", None, None))
        self.assertFalse(product_matches_ingredient(
            "Fruktsallad Färsk", "Sallad", None, "Frukt & Grönt > Frukt"))
        self.assertTrue(product_matches_ingredient(
            "Sallad Isberg Klass 1", "sallad isberg", None,
            "Frukt & Grönt > Grönsaker > Sallad"))
        # Frisé är en annan sallad - isberg-aliaset får inte svälja den.
        self.assertFalse(product_matches_ingredient(
            "Isberg Frisé Klass 1", "isberg", None,
            "Frukt & Grönt > Grönsaker > Sallad"))

    def test_seed_kernels_are_the_seeds_but_bread_is_not(self):
        self.assertTrue(product_matches_ingredient(
            "Solroskärnor Skalade", "solroskärnor", None,
            "Skafferi > Torra baljväxter > Fröer"))
        self.assertTrue(product_matches_ingredient(
            "Pumpakärnor Naturell Skalade", "pumpakärnor", None,
            "Glass, godis & snacks > Nyttiga snacks"))
        self.assertFalse(product_matches_ingredient(
            "Rågbröd Solros & Pumpa 6-pack", "Solrosfrön", None,
            "Bröd & Kakor > Bröd > Matbröd"))
        # Jordnötssmör är inte jordnötter - CG:s lucka ska förbli en lucka.
        self.assertFalse(product_matches_ingredient(
            "Jordnötssmör Creamy", "Jordnötter", None,
            "Skafferi > Bakning > Baktillbehör"))


class NewChainCatalogsStayHonest(unittest.TestCase):
    """De fyra råvarubyten som ICA/Coop/Lidl-katalogerna (via Primat)
    blottade 2026-09-02. Sammansättningssuffixet gör att fel råvara kan
    SLUTA på ingrediensordet - varje fall låses här, plus att äkta varan
    fortsätter matcha."""

    def test_agg_is_never_a_pork_cut(self):
        self.assertFalse(product_matches_ingredient("Fläsklägg Rimmad", "Ägg", None, None))
        self.assertFalse(product_matches_ingredient("Grislägg Färsk", "Ägg", None, None))
        self.assertTrue(product_matches_ingredient(
            "Ägg 12-pack Frigående", "Ägg", None, "Mejeri, ost & ägg"))

    def test_mjolk_is_cow_milk_not_goat_plant_or_fil(self):
        for wrong in ("Getmjölk 1,7%", "Filmjölk 3%", "Havremjölk Barista",
                      "Kokosmjölk", "Chokladmjölk 1,6%"):
            self.assertFalse(product_matches_ingredient(wrong, "Mjölk", None, None),
                             f"{wrong!r} är inte komjölk")
        self.assertTrue(product_matches_ingredient(
            "Mellanmjölk 1,5% 1l", "Mjölk", None, "Mejeri, ost & ägg > Mjölk"))
        self.assertTrue(product_matches_ingredient(
            "Lättmjölk 0,5%", "Mjölk", None, "Mejeri, ost & ägg > Mjölk"))

    def test_potatis_is_not_sotpotatis(self):
        self.assertFalse(product_matches_ingredient("Sötpotatis", "Potatis", None,
                                                    "Frukt & grönt > Rotfrukter"))
        self.assertTrue(product_matches_ingredient(
            "Potatis Fast ca 100g tvättad Klass 1", "Potatis", None,
            "Frukt & grönt > Rotfrukter"))

    def test_pasta_is_not_a_paste(self):
        for wrong in ("Kryddpasta", "Röd Currypasta", "Tomatpasta Dubbelkoncentrerad"):
            self.assertFalse(product_matches_ingredient(wrong, "Pasta", None, None),
                             f"{wrong!r} är en smaksättare, inte pasta")
        self.assertTrue(product_matches_ingredient(
            "Penne Rigate 500g", "penne", None, "Skafferi > Pasta"))


class PackageMathInvariants(unittest.TestCase):
    """packages = ceil(behov / paket) i RÄTT enhet - för varje familj."""

    def test_weight_invariant(self):
        for required, package in [(224, 450), (10, 50), (500, 500), (501, 500),
                                  (1000, 400), (1, 2000), (999, 100)]:
            self.assertEqual(packages_needed(required, "g", package, "g"),
                             math.ceil(required / package), f"{required}g/{package}g")

    def test_weight_with_kg_conversion(self):
        self.assertEqual(packages_needed(1.5, "kg", 500, "g"), 3)
        self.assertEqual(packages_needed(400, "g", 1, "kg"), 1)

    def test_volume_invariant(self):
        for required, unit, package, punit, expected in [
            (11, "dl", 1000, "ml", 2), (2, "l", 1000, "ml", 2),
            (5, "dl", 2, "dl", 3), (30, "cl", 300, "ml", 1),
            (1, "msk", 500, "ml", 1),
        ]:
            self.assertEqual(packages_needed(required, unit, package, punit), expected,
                             f"{required}{unit} / {package}{punit}")

    def test_count_invariant(self):
        for required, package, expected in [(2, 1, 2), (10, 6, 2), (6, 6, 1), (7, 6, 2)]:
            self.assertEqual(packages_needed(required, "st", package, "st"), expected)

    def test_cross_family_refuses_instead_of_guessing(self):
        self.assertIsNone(packages_needed(2, "st", 450, "g"))
        self.assertIsNone(packages_needed(200, "g", 500, "ml"))
        self.assertIsNone(convert_amount(1, "tsk", "g"))


class LoosePiecesAtKiloPrice(unittest.TestCase):
    def test_small_pieces_at_kilo_price_are_loose_weight_not_ten_packages(self):
        """City Gross 'Potatis Mjölig CA80G' 14,95 kr (= kr/kg): 800 g behov
        visades som 'Köp 10 × CA80G'. Det är lösvikt: kr/kg × behov, ett
        paket, märkt perKg - så listan säger 'ca 800 g' i stället."""
        engine, store_id, tmp, db = _engine_with([{
            "id": "pot", "name": "Potatis Mjölig", "size": "CA80G", "quantity": None, "unit": None,
            "price": 14.95, "unit_price": 14.95, "category": "Frukt & grönt > Potatis & rotsaker > Potatis"}])
        try:
            row = engine.price_item("Potatis", 800, "g", "Willys", store_id)
            self.assertTrue(row["perKg"])
            self.assertEqual(row["packages"], 1)
            self.assertTrue(row["exactPackaging"])
            self.assertAlmostEqual(row["totalCost"], 11.96, places=2)   # 14,95 × 0,8
            self.assertFalse(row["weightPriced"])
        finally:
            db.close(); tmp.cleanup()


class CampaignPricedWeightGoods(unittest.TestCase):
    """C4: kilopris-signaturen jämförs mot priset som GÄLLER, inte ordinarie.

    City Gross sätter unit_price = kampanjens kr/kg medan regular_price är
    ordinariepriset. Under kampanj skiljde de sig alltid åt, signaturen föll,
    och kilopriset användes rakt av som paketpris. Felet gick alltid nedåt -
    och drabbade just kampanjvaror, vilket gjorde kedjan med kampanjen
    orättvist billigast."""

    def test_a_campaign_priced_cut_costs_kilo_price_times_weight(self):
        """Fläskkarré ca 1,2 kg, ordinarie 99 kr/kg, kampanj 79 kr/kg.
        Kassan: 94,80 kr. Före C4: 79 kr, som om 79 vore paketpriset."""
        engine, store_id, tmp, db = _engine_with([{
            "id": "kar", "name": "Fläskkarré Benfri", "size": "ca 1,2kg",
            "quantity": None, "unit": None,
            "price": 99.0, "campaign": 79.0, "unit_price": 79.0,
            "category": "Kött & chark > Fläsk"}])
        try:
            row = engine.price_item("Fläskkarré", 1000, "g", "Willys", store_id)
            self.assertTrue(row["weightPriced"], "kampanjens kr/kg ÄR ett kilopris")
            self.assertEqual(row["packages"], 1)
            self.assertTrue(row["exactPackaging"])
            self.assertAlmostEqual(row["totalCost"], 94.80, places=2)  # 79 × 1,2
        finally:
            db.close(); tmp.cleanup()

    def test_the_same_cut_without_a_campaign_is_unchanged(self):
        """Regressionslås: utan kampanj är ordinarie priset som gäller, och
        signaturen fungerar precis som förut."""
        engine, store_id, tmp, db = _engine_with([{
            "id": "kar", "name": "Fläskkarré Benfri", "size": "ca 1,2kg",
            "quantity": None, "unit": None,
            "price": 99.0, "unit_price": 99.0,
            "category": "Kött & chark > Fläsk"}])
        try:
            row = engine.price_item("Fläskkarré", 1000, "g", "Willys", store_id)
            self.assertTrue(row["weightPriced"])
            self.assertAlmostEqual(row["totalCost"], 118.80, places=2)  # 99 × 1,2
        finally:
            db.close(); tmp.cleanup()

    def test_a_package_price_that_is_not_a_kilo_price_is_still_a_package_price(self):
        """Motpolen: skiljer sig jämförpriset från det man betalar är raden
        ett vanligt paketpris och får inte skalas med cirkavikten."""
        engine, store_id, tmp, db = _engine_with([{
            "id": "kar", "name": "Fläskkarré Benfri", "size": "ca 1,2kg",
            "quantity": None, "unit": None,
            "price": 99.0, "campaign": 79.0, "unit_price": 65.8,
            "category": "Kött & chark > Fläsk"}])
        try:
            row = engine.price_item("Fläskkarré", 1000, "g", "Willys", store_id)
            self.assertFalse(row["weightPriced"])
            self.assertEqual(row["totalCost"], 79.0)
        finally:
            db.close(); tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
