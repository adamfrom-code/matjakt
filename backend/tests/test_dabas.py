# -*- coding: utf-8 -*-
"""Dabas-masterdata: adapter, normalisering, fältvis merge, paketverifiering,
kanonisk avvisning via Dabas-kategori, statusmetadata - utan nätverk och
utan att API-nyckeln någonsin syns."""

import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.grocery import enrichment  # noqa: E402
from services.grocery.models import RawProduct  # noqa: E402
from services.grocery.pricing import (  # noqa: E402
    RecipePricingEngine, effective_package, product_matches_ingredient)
from services.grocery.providers import dabas  # noqa: E402
from services.grocery.store import GroceryStore  # noqa: E402

MILK = "07310865093530"
KEY = "hemlig-dabas-nyckel-123"


def article(**overrides):
    base = {
        "ARIDENT": 4711, "GTIN": "7310865093530", "Produktnamn": "Standardmjölk 3%",
        "RegleratProduktnamn": "Mjölk", "Artikelkategori": "Mjölk", "GPCKod": "10000025",
        "Konsumentartikel": True, "Variabelmattsindikator": False,
        "Varumarke": {"Varumarke": "Arla", "Tillverkare": {"Namn": "Arla Foods AB"}},
        "Uppgiftslamnare": {"Foretagsnamn": "Arla Foods AB", "GLN": "7310860000000"},
        "Nettoinnehall": [{"Mängd": 1000, "EnhetKod": "MLT", "Enhet": "ml", "Typ": "Volym"}],
        "Ingredienser": [{"Beskrivning": "Standardmjölk 3 % fett", "Sekvens": 1}],
        "Allergener": [{"Allergen": "Mjölk", "Nivakod": "CONTAINS", "NivakodText": "Innehåller"}],
        "Naringsinfo": [{"Basmangdsdeklaration": 100, "Mattkvalificerarebasmangd": "ml",
                         "Naringsvarden": [{"Benamning": "Energi", "Mangd": 264, "Enhet": "kJ"},
                                           {"Benamning": "Fett", "Mangd": 3.0, "Enhet": "g"}]}],
        "KortMarknadsbudskap": [{"Text": "Svensk standardmjölk"}],
        "Bilder": [{"Lank": "https://media.dabas.example/bild.jpg", "Filformat": "jpg", "Informationstyp": "Produktbild"}],
        "SkapadDatum": "2021-01-01T00:00:00", "SenastAndradDatum": "2026-08-30T10:00:00",
        "Forpackningar": [{"Antalenheter": 1}],
    }
    base.update(overrides)
    return base


class _Response(io.BytesIO):
    def __init__(self, body: bytes, content_type="application/json"):
        super().__init__(body)
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def opener_for(handler):
    def opener(request, timeout=None):
        return handler(request.full_url)
    return opener


class Client(unittest.TestCase):
    def test_valid_gtin_json(self):
        calls = []
        def handler(url):
            calls.append(url)
            return _Response(json.dumps(article()).encode("utf-8"))
        client = dabas.DabasClient(api_key=KEY, opener=opener_for(handler))
        product = client.get_product(MILK)
        self.assertEqual(product.gtin, MILK)
        self.assertEqual(product.name, "Standardmjölk 3%")
        self.assertEqual(product.brand, "Arla")
        self.assertEqual(product.manufacturer, "Arla Foods AB")
        self.assertEqual(product.package.quantity, 1000.0)
        self.assertEqual(product.package.unit, "ml")
        self.assertEqual(product.package.kind, "VOLYM")
        self.assertEqual(product.allergens[0]["allergen"], "Mjölk")
        self.assertEqual(product.nutrition[0]["values"][0]["name"], "Energi")
        # GTIN-14 med inledande nolla - Dabas svarar 404 på 13-siffrig form.
        self.assertIn("/V2/article/gtin/07310865093530/JSON", calls[0])

    def test_xml_is_parsed_like_json(self):
        xml = b"""<?xml version="1.0"?><ArticleModel><GTIN>7310865093530</GTIN><Produktnamn>Standardmj\xc3\xb6lk 3%</Produktnamn>
        <Nettoinnehall><NetContentModel><M\xc3\xa4ngd>1000</M\xc3\xa4ngd><EnhetKod>MLT</EnhetKod><Typ>Volym</Typ></NetContentModel></Nettoinnehall>
        <Varumarke><Varumarke>Arla</Varumarke></Varumarke></ArticleModel>"""
        client = dabas.DabasClient(api_key=KEY, fmt="XML", opener=opener_for(lambda url: _Response(xml, "application/xml")))
        product = client.get_product(MILK)
        self.assertEqual(product.name, "Standardmjölk 3%")
        self.assertEqual(product.package.quantity, 1000.0)
        self.assertEqual(product.brand, "Arla")

    def test_invalid_gtin_never_calls_the_api(self):
        client = dabas.DabasClient(api_key=KEY, opener=opener_for(lambda url: self.fail("skulle inte anropas")))
        with self.assertRaises(dabas.DabasNotFound):
            client.get_product("12345")

    def test_404_is_not_found(self):
        def handler(url):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
        client = dabas.DabasClient(api_key=KEY, opener=opener_for(handler))
        with self.assertRaises(dabas.DabasNotFound):
            client.get_product(MILK)

    def test_timeout_retries_then_raises_clear_error(self):
        attempts = []
        def handler(url):
            attempts.append(1)
            raise TimeoutError("timed out")
        client = dabas.DabasClient(api_key=KEY, opener=opener_for(handler))
        with patch.object(dabas, "RETRY_DELAYS", (0, 0)):
            with self.assertRaises(dabas.DabasError) as ctx:
                client.get_product(MILK)
        self.assertEqual(len(attempts), 3)
        self.assertIn("nätverksfel", str(ctx.exception))
        self.assertNotIn(KEY, str(ctx.exception))

    def test_malformed_payload_is_a_clear_error(self):
        client = dabas.DabasClient(api_key=KEY, opener=opener_for(lambda url: _Response(b"{not json")))
        with self.assertRaises(dabas.DabasError):
            client.get_product(MILK)
        client = dabas.DabasClient(api_key=KEY, fmt="XML", opener=opener_for(lambda url: _Response(b"<broken", "text/xml")))
        with self.assertRaises(dabas.DabasError):
            client.get_product(MILK)

    def test_401_and_429_are_distinct(self):
        def unauthorized(url):
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b""))
        with self.assertRaises(dabas.DabasUnauthorized):
            dabas.DabasClient(api_key=KEY, opener=opener_for(unauthorized)).get_product(MILK)
        def limited(url):
            raise urllib.error.HTTPError(url, 429, "Too Many", {}, io.BytesIO(b""))
        with patch.object(dabas, "RETRY_DELAYS", (0, 0)):
            with self.assertRaises(dabas.DabasRateLimited):
                dabas.DabasClient(api_key=KEY, opener=opener_for(limited)).get_product(MILK)

    def test_api_key_never_appears_in_errors_or_products(self):
        def handler(url):
            raise urllib.error.URLError(f"boom {url}")  # URL:en bär nyckeln
        client = dabas.DabasClient(api_key=KEY, opener=opener_for(handler))
        with patch.object(dabas, "RETRY_DELAYS", (0,)):
            with self.assertRaises(dabas.DabasError) as ctx:
                client.get_product(MILK)
        self.assertNotIn(KEY, str(ctx.exception))
        product = dabas.normalize_article(article())
        self.assertNotIn(KEY, product.to_json())

    def test_missing_key_is_unauthorized_without_network(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("DABAS_API_KEY", None)
            client = dabas.DabasClient(opener=opener_for(lambda url: self.fail("skulle inte anropas")))
            self.assertFalse(client.configured)
            with self.assertRaises(dabas.DabasUnauthorized):
                client.get_product(MILK)


class PackageNormalisation(unittest.TestCase):
    def test_drained_weight_beats_net_weight(self):
        product = dabas.normalize_article(article(Nettoinnehall=[
            {"Mängd": 400, "EnhetKod": "GRM", "Typ": "Nettovikt"},
            {"Mängd": 240, "EnhetKod": "GRM", "Typ": "Avrunnen vikt"}]))
        self.assertEqual(product.package.quantity, 240.0)
        self.assertEqual(product.package.kind, "AVRUNNEN_VIKT")
        self.assertEqual(product.package.drained_quantity, 240.0)

    def test_kg_and_liters_become_canonical(self):
        product = dabas.normalize_article(article(Nettoinnehall=[{"Mängd": "1,5", "EnhetKod": "KGM", "Typ": "Nettovikt"}]))
        self.assertEqual((product.package.quantity, product.package.unit), (1500.0, "g"))
        product = dabas.normalize_article(article(Nettoinnehall=[{"Mängd": 0.5, "EnhetKod": "LTR", "Typ": "Volym"}]))
        self.assertEqual((product.package.quantity, product.package.unit), (500.0, "ml"))

    def test_missing_package_size_is_none_not_guessed(self):
        product = dabas.normalize_article(article(Nettoinnehall=[], T4330_Nettovikt=None))
        self.assertIsNone(product.package.quantity)
        product = dabas.normalize_article(article(Nettoinnehall=[{"Mängd": 6, "EnhetKod": "XYZ", "Typ": "?"}]))
        self.assertIsNone(product.package.quantity)  # okänd enhet -> okänt

    def test_multipack_count_and_variable_measure(self):
        product = dabas.normalize_article(article(Forpackningar=[{"Antalenheter": 6}, {"Antalenheter": 1}]))
        self.assertEqual(product.package.multipack_count, 6)
        product = dabas.normalize_article(article(Variabelmattsindikator=True))
        self.assertTrue(product.package.variable_measure)


class _DbCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = GroceryStore(Path(self._tmp.name) / "g.db")
        self.addCleanup(self.db.close)

    def product(self, name="Standardmjölk 3% 1l", size="1000 ml", quantity=1000.0, unit="ml",
                gtin=MILK, brand=None, category=None, description=None):
        return self.db.find_or_create_product(RawProduct(
            chain="Willys", external_product_id=f"w-{gtin}-{name}", name=name, store_id="2132",
            store_name="Willys", gtin=gtin, brand=brand, size=size, quantity=quantity, unit=unit,
            category=category, description=description))


class FieldLevelMerge(_DbCase):
    def test_dabas_fills_and_overrides_but_null_never_erases(self):
        product = self.product(brand="Garant", category="Mejeri > Mjölk", description="Bra mjölk")
        dabas_product = dabas.normalize_article(article(
            KortMarknadsbudskap=[], Marknadsbudskap=[], Variantbeskrivning=[], Artikelkategori="Mjölk"))
        fields = enrichment.merge_fields(product, dabas_product)
        self.assertEqual(fields["brand"], "Arla")               # Dabas > provider
        self.assertEqual(fields["manufacturer"], "Arla Foods AB")
        self.assertEqual(fields["dabas_category"], "Mjölk")
        self.assertNotIn("description", fields)                # Dabas saknar -> behåll
        self.assertNotIn("name", fields)                       # hyllnamnet stannar
        self.assertNotIn("category", fields)                   # providerkategorin stannar
        self.assertEqual(fields["package_confidence"], "high")
        self.assertEqual(fields["package_source"], "DABAS_VERIFIED")
        self.db.apply_product_fields(product.id, fields)
        after = self.db.get_product(product.id)
        self.assertEqual(after.description, "Bra mjölk")
        self.assertEqual(after.brand, "Arla")
        self.assertEqual(after.category, "Mejeri > Mjölk")

    def test_nameless_product_gets_dabas_name(self):
        product = self.product(name="")
        fields = enrichment.merge_fields(product, dabas.normalize_article(article()))
        self.assertEqual(fields["name"], "Standardmjölk 3%")

    def test_dabas_data_snapshot_never_carries_image_urls(self):
        product = self.product()
        fields = enrichment.merge_fields(product, dabas.normalize_article(article()))
        snapshot = json.loads(fields["dabas_data"])
        self.assertNotIn("url", json.dumps(snapshot["images"]))


class PackageVerification(_DbCase):
    def test_agreement_is_high_confidence(self):
        product = self.product(size="450 g", quantity=450.0, unit="g")
        verdict = enrichment.package_verdict(product, dabas.normalize_article(article(
            Nettoinnehall=[{"Mängd": 450, "EnhetKod": "GRM", "Typ": "Nettovikt"}])))
        self.assertEqual(verdict["package_confidence"], "high")
        self.assertIsNone(verdict["package_conflict"])

    def test_conflict_is_flagged_and_fails_closed_in_engine(self):
        product = self.product(size="450 g", quantity=450.0, unit="g")
        verdict = enrichment.package_verdict(product, dabas.normalize_article(article(
            Nettoinnehall=[{"Mängd": 500, "EnhetKod": "GRM", "Typ": "Nettovikt"}])))
        self.assertEqual(verdict["package_confidence"], "conflict")
        self.assertIn("450 g / Dabas 500 g", verdict["package_conflict"])
        self.db.apply_product_fields(product.id, verdict)
        flagged = self.db.get_product(product.id)
        self.assertEqual(effective_package(flagged), (None, None))  # mängden används inte

    def test_dabas_fills_missing_provider_package(self):
        product = self.product(size=None, quantity=None, unit=None)
        verdict = enrichment.package_verdict(product, dabas.normalize_article(article()))
        self.assertEqual(verdict["package_source"], "DABAS_VERIFIED")
        self.assertEqual((verdict["quantity"], verdict["unit"]), (1000.0, "ml"))

    def test_liquid_weight_in_grams_is_not_a_conflict(self):
        """Dabas anger nettovikt i gram även för mjölk: 1 500 ml = 1 500 g."""
        product = self.product(size="1,5l", quantity=1.5, unit="l")
        verdict = enrichment.package_verdict(product, dabas.normalize_article(article(
            Nettoinnehall=[{"Mängd": 1500, "EnhetKod": "GRM", "Typ": "Nettovikt"}])))
        self.assertEqual(verdict["package_confidence"], "high")
        self.assertIsNone(verdict["package_conflict"])

    def test_drained_weight_choice_agrees_with_dabas_net_weight(self):
        """"370/240g": providern valde avrunnen 240 g, Dabas säger 370 g
        nettovikt - samma paket, ingen konflikt, avrunnen-regeln står."""
        product = self.product(name="Smörgåsgurka", size="370/240g", quantity=None, unit=None)
        verdict = enrichment.package_verdict(product, dabas.normalize_article(article(
            Nettoinnehall=[{"Mängd": 370, "EnhetKod": "GRM", "Typ": "Nettovikt"}])))
        self.assertEqual(verdict["package_confidence"], "high")
        # 240 g (avrunnen) förblir mängden: ingen explicit mängd skrivs,
        # providerns size-text står (None = tolkas ur "370/240g" som förut).
        self.assertIsNone(verdict.get("quantity"))
        self.assertEqual(verdict.get("size"), "370/240g")

    def test_dry_goods_with_prepared_volume_dabas_wins(self):
        """"800g/6l": providern tolkade 6 l, Dabas säger 800 g - Dabas
        pekar ut förpackningen och vinner (providerns var en texttolkning)."""
        product = self.product(name="Baby Semp 4 Mjölkdryck", size="800g/6l", quantity=None, unit=None)
        self.assertEqual(effective_package(product), (6.0, "l"))  # providerns feltolkning
        verdict = enrichment.package_verdict(product, dabas.normalize_article(article(
            Nettoinnehall=[{"Mängd": 800, "EnhetKod": "GRM", "Typ": "Nettovikt"}])))
        self.assertEqual(verdict["package_source"], "DABAS_VERIFIED")
        self.assertEqual((verdict["quantity"], verdict["unit"]), (800.0, "g"))

    def test_count_versus_weight_is_not_a_conflict(self):
        product = self.product(name="Skärgårdskaka 18-pack", size="750g", quantity=750.0, unit="g")
        verdict = enrichment.package_verdict(product, dabas.normalize_article(article(
            Nettoinnehall=[{"Mängd": 18, "EnhetKod": "H87", "Typ": "Antal"}])))
        self.assertIsNone(verdict["package_conflict"])
        self.assertEqual(verdict["package_source"], "PROVIDER_VERIFIED")

    def test_explicit_disagreement_in_same_family_is_a_real_conflict(self):
        product = self.product(name="Vallmolevain", size="560g", quantity=560.0, unit="g")
        verdict = enrichment.package_verdict(product, dabas.normalize_article(article(
            Nettoinnehall=[{"Mängd": 500, "EnhetKod": "GRM", "Typ": "Nettovikt"}])))
        self.assertEqual(verdict["package_confidence"], "conflict")

    def test_recompute_verdicts_from_snapshot_without_api(self):
        product = self.product(size="1,5l", quantity=1.5, unit="l")
        d = dabas.normalize_article(article(Nettoinnehall=[{"Mängd": 1500, "EnhetKod": "GRM", "Typ": "Nettovikt"}]))
        fields = enrichment.merge_fields(product, d)
        self.db.apply_product_fields(product.id, {**fields, "package_confidence": "conflict",
                                                  "package_conflict": "gammal regel"})
        self.db.record_dabas_check(product.id, status="ok")
        counts = enrichment.recompute_verdicts(self.db)
        self.assertEqual(counts, {"high": 1})
        self.assertIsNone(self.db.get_product(product.id).package_conflict)

    def test_conflict_never_overwrites_provider_and_recompute_keeps_it(self):
        """Produktion: Vallmolevain 560 g (provider) mot 500 g (Dabas) blev
        DABAS_VERIFIED 500 g efter omräkning - konfliktflaggan fick motorn
        att säga "okänt" och omräkningen lät Dabas fylla. Aldrig igen."""
        product = self.product(name="Vallmolevain", size="560g", quantity=560.0, unit="g")
        d = dabas.normalize_article(article(Nettoinnehall=[{"Mängd": 500, "EnhetKod": "GRM", "Typ": "Nettovikt"}]))
        fields = enrichment.merge_fields(product, d)
        self.assertEqual(fields["package_confidence"], "conflict")
        self.db.apply_product_fields(product.id, fields)
        self.db.record_dabas_check(product.id, status="ok")
        flagged = self.db.get_product(product.id)
        self.assertEqual((flagged.quantity, flagged.unit, flagged.size), (560.0, "g", "560g"))
        self.assertEqual(effective_package(flagged), (None, None))  # fail closed i motorn
        # Omräkning ur snapshot: konflikten står kvar, providerns värde orört.
        counts = enrichment.recompute_verdicts(self.db)
        self.assertEqual(counts, {"conflict": 1})
        after = self.db.get_product(product.id)
        self.assertEqual((after.quantity, after.unit), (560.0, "g"))
        self.assertIsNotNone(after.package_conflict)

    def test_provider_fields_follow_every_import_and_heal_overwritten_rows(self):
        """provider_* uppdateras vid varje import; en rad som (felaktigt)
        fått Dabas-värden i de upplösta fälten återställs när providern
        levererar igen och verdiktet räknas om."""
        product = self.product(name="Vallmolevain", size="560g", quantity=560.0, unit="g")
        self.assertEqual(self.db.get_product(product.id).provider_quantity, 560.0)
        # Simulera den gamla överskrivningen: upplösta fält = Dabas, provider_* okända.
        self.db.apply_product_fields(product.id, {"size": "500 g", "quantity": 500.0, "unit": "g",
                                                  "package_source": "DABAS_VERIFIED", "package_confidence": "high",
                                                  "provider_size": None, "provider_quantity": None, "provider_unit": None})
        d = dabas.normalize_article(article(Nettoinnehall=[{"Mängd": 500, "EnhetKod": "GRM", "Typ": "Nettovikt"}]))
        self.db.apply_product_fields(product.id, {"dabas_data": d.to_json()})
        self.db.record_dabas_check(product.id, status="ok")
        # Utan providervärde: omräkningen rör ingenting.
        enrichment.recompute_verdicts(self.db)
        self.assertEqual(self.db.get_product(product.id).quantity, 500.0)
        # Nästa import levererar providerns 560 g -> provider_* fylls, verdikt = konflikt, 560 återställt.
        self.db.find_or_create_product(RawProduct(
            chain="Willys", external_product_id="w-again", name="Vallmolevain", store_id="2132",
            store_name="Willys", gtin=product.gtin, size="560g", quantity=560.0, unit="g"))
        self.assertEqual(self.db.get_product(product.id).provider_quantity, 560.0)
        self.assertEqual(enrichment.recompute_verdicts(self.db), {"conflict": 1})
        healed = self.db.get_product(product.id)
        self.assertEqual((healed.quantity, healed.unit, healed.size), (560.0, "g", "560g"))

    def test_agreement_keeps_the_providers_unit_family(self):
        """Sojasås: providern tolkade "176ml" ur texten, Dabas säger 176 g.
        Eniga - men enheten som skrivs är providerns (ml), annars blir varje
        msk-recept "volym mot vikt" och raden osäker."""
        product = self.product(name="Sojasås Japansk Vegan 176ml", size=None, quantity=None, unit=None)
        verdict = enrichment.package_verdict(product, dabas.normalize_article(article(
            Nettoinnehall=[{"Mängd": 176, "EnhetKod": "GRM", "Typ": "Nettovikt"}])))
        self.assertEqual(verdict["package_confidence"], "high")
        self.assertEqual((verdict["quantity"], verdict["unit"]), (176.0, "ml"))

    def test_cross_family_disagreement_is_unverifiable_not_a_conflict(self):
        """250 ml sojasås mot Dabas 293 g: densitet, inte fel. Ingen flagga,
        providerns värde och nivå står - Dabas skapar inga hål."""
        product = self.product(name="Sojasås 250ml Kikkoman", size="250ml", quantity=250.0, unit="ml")
        verdict = enrichment.package_verdict(product, dabas.normalize_article(article(
            Nettoinnehall=[{"Mängd": 293, "EnhetKod": "GRM", "Typ": "Nettovikt"}])))
        self.assertIsNone(verdict["package_conflict"])
        self.assertEqual(verdict["package_source"], "PROVIDER_VERIFIED")
        self.assertEqual((verdict["quantity"], verdict["unit"]), (250.0, "ml"))

    def test_rounding_within_tolerance_is_agreement(self):
        product = self.product(size="ca 750 g", quantity=745.0, unit="g")
        verdict = enrichment.package_verdict(product, dabas.normalize_article(article(
            Nettoinnehall=[{"Mängd": 750, "EnhetKod": "GRM", "Typ": "Nettovikt"}])))
        self.assertEqual(verdict["package_confidence"], "high")


class CanonicalRejectionViaDabasCategory(_DbCase):
    def test_kanel_against_dabas_knackebrod_is_rejected(self):
        # Namnet ensamt passerar (leder med kanel, inget uteslutet ord,
        # ingen kedjekategori) - bara Dabas vet att det är ett knäckebröd.
        self.assertTrue(product_matches_ingredient("Kanel Special", "Kanel", None, None))
        product = self.product(name="Kanel Special", gtin="07300400481861", size="250 g",
                               quantity=250.0, unit="g", category=None)
        engine = RecipePricingEngine(self.db)
        self.assertIn("Kanel Special", [p.name for p in engine._candidates("Kanel", "Willys")])
        self.db.apply_product_fields(product.id, {"dabas_category": "Knäckebröd"})
        from services.grocery import pricing
        pricing._INDEX_CACHE.clear(); pricing._PRICE_CACHE.clear()
        engine = RecipePricingEngine(self.db)
        names = [p.name for p in engine._candidates("Kanel", "Willys")]
        self.assertNotIn("Kanel Special", names)

    def test_dabas_category_strengthens_but_does_not_replace(self):
        product = self.product(name="Kanel Malen Påse", gtin="07311041014455", size="19 g",
                               quantity=19.0, unit="g", category="Skafferi > Kryddor")
        self.db.apply_product_fields(product.id, {"dabas_category": "Kryddor"})
        engine = RecipePricingEngine(self.db)
        self.assertIn("Kanel Malen Påse", [p.name for p in engine._candidates("Kanel", "Willys")])


class EnrichmentPipeline(_DbCase):
    def test_duplicate_gtin_is_one_product_one_lookup(self):
        a = self.product()
        b = self.db.find_or_create_product(RawProduct(
            chain="ICA", external_product_id="ica-1", name="Standardmjölk 3% Arla", store_id="1",
            store_name="ICA", gtin=MILK, size="1000 ml", quantity=1000.0, unit="ml"))
        self.assertEqual(a.id, b.id)
        calls = []
        def handler(url):
            calls.append(url)
            return _Response(json.dumps(article()).encode("utf-8"))
        client = dabas.DabasClient(api_key=KEY, opener=opener_for(handler))
        summary = enrichment.run_enrichment(self.db, client)
        self.assertEqual(summary["ok"], 1)
        self.assertEqual(len(calls), 1)
        # Full data i DB -> inget nytt anrop.
        summary = enrichment.run_enrichment(self.db, client)
        self.assertEqual(summary["checked"], 0)
        self.assertEqual(len(calls), 1)
        row = self.db.connection.execute(
            "SELECT dabas_status, dabas_last_success, dabas_source_version FROM grocery_products WHERE id = ?",
            (a.id,)).fetchone()
        self.assertEqual(row[0], "ok")
        self.assertIsNotNone(row[1])
        self.assertEqual(row[2], "2026-08-30T10:00:00")

    def test_not_found_and_errors_are_recorded_never_raised(self):
        product = self.product()
        def missing(url):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
        summary = enrichment.run_enrichment(self.db, dabas.DabasClient(api_key=KEY, opener=opener_for(missing)))
        self.assertEqual(summary["not_found"], 1)
        self.assertEqual(self.db.get_product(product.id).dabas_status, "not_found")
        other = self.product(name="Torsk", gtin="07315632004009")
        def broken(url):
            return _Response(b"nonsense")
        with patch.object(dabas, "RETRY_DELAYS", (0,)):
            summary = enrichment.run_enrichment(self.db, dabas.DabasClient(api_key=KEY, opener=opener_for(broken)))
        self.assertEqual(summary["error"], 1)
        self.assertIn("tolka", self.db.connection.execute(
            "SELECT dabas_error FROM grocery_products WHERE id = ?", (other.id,)).fetchone()[0])

    def test_unauthorized_stops_the_run_and_wrong_gtin_answer_is_rejected(self):
        self.product()
        def unauthorized(url):
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b""))
        summary = enrichment.run_enrichment(self.db, dabas.DabasClient(api_key=KEY, opener=opener_for(unauthorized)))
        self.assertIn("401", summary["stopped"])
        wrong = self.product(name="Annan", gtin="07315632004009")
        client = dabas.DabasClient(api_key=KEY, opener=opener_for(lambda url: _Response(json.dumps(article()).encode())))
        self.assertEqual(enrichment.enrich_product(self.db, wrong, client), "error")

    def test_enrichment_is_on_with_key_and_off_by_optout(self):
        with patch.dict("os.environ", {"DABAS_API_KEY": KEY, "MATJAKT_DABAS_ENRICHMENT_ENABLED": "0"}):
            self.assertFalse(enrichment.enrichment_enabled())
        with patch.dict("os.environ", {"DABAS_API_KEY": KEY}, clear=False):
            import os
            os.environ.pop("MATJAKT_DABAS_ENRICHMENT_ENABLED", None)
            self.assertTrue(enrichment.enrichment_enabled())  # standard PÅ med nyckel
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("DABAS_API_KEY", None)
            self.assertFalse(enrichment.enrichment_enabled())  # aldrig utan nyckel

    def test_package_source_tiers_exist_without_dabas(self):
        """Varje produkt bär sin nivå: PROVIDER_VERIFIED (mängd+enhet från
        kedjan), NORMALIZED (tolkad ur text), NONE (inget). Dabas saknad
        träff får aldrig skapa ett hål - nivån står kvar."""
        verified = self.product(name="Mjölk", gtin=MILK, size="1000 ml", quantity=1000.0, unit="ml")
        normalized = self.product(name="Torskfilé 400g", gtin="07315632004009", size=None, quantity=None, unit=None)
        nothing = self.product(name="Persilja kruka", gtin="07311042001768", size=None, quantity=None, unit=None)
        counts = enrichment.classify_package_sources(self.db)
        self.assertEqual(counts, {"PROVIDER_VERIFIED": 1, "NORMALIZED": 1, "NONE": 1})
        self.assertEqual(self.db.get_product(verified.id).package_source, "PROVIDER_VERIFIED")
        self.assertEqual(self.db.get_product(normalized.id).package_source, "NORMALIZED")
        self.assertEqual(self.db.get_product(nothing.id).package_source, "NONE")
        # Dabas utan mängd -> providerns nivå orörd.
        verdict = enrichment.package_verdict(self.db.get_product(verified.id),
                                             dabas.normalize_article(article(Nettoinnehall=[])))
        self.assertEqual(verdict["package_source"], "PROVIDER_VERIFIED")
        self.assertIsNone(verdict["package_conflict"])
        self.assertEqual(enrichment.classify_package_sources(self.db), {})  # idempotent

    def test_coverage_report_per_chain_and_brand_type(self):
        a = self.product(name="Arla mjölk", gtin=MILK, brand="Arla")
        b = self.product(name="Garant mjölk", gtin="07340083443893", brand="Garant")
        self.db.record_dabas_check(a.id, status="ok")
        self.db.record_dabas_check(b.id, status="not_found")
        report = enrichment.coverage_report(self.db)
        self.assertEqual(report["totalt"], {"uppslagna": 2, "traff": 1, "procent": 50.0})
        self.assertEqual(report["perVarumarkestyp"]["märkesvara"]["procent"], 100.0)
        self.assertEqual(report["perVarumarkestyp"]["private label"]["procent"], 0.0)
        self.assertEqual(report["perKedja"]["Willys"]["uppslagna"], 2)


if __name__ == "__main__":
    unittest.main()
