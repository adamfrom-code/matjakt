# -*- coding: utf-8 -*-
"""D7: två providers höll hela katalogen i RAM.

Axfood streamar sedan den skrevs - varje avdelning lämnas till `on_products`
och glöms. City Gross byggde i stället en lista på ~8 700 `RawProduct` och
lämnade den på slutet, och Primat höll en hel Maxi-katalog i tre lager
samtidigt: prisraderna, uppslagssvaren och de normaliserade produkterna.
Processen kör Chromium på en 512 MB-instans.

En OOM under bootstrap är dessutom värre än ett vanligt haveri: databasen
förblir tom, nästa boot ser en tom databas och startar samma bootstrap igen.
En hammarloop som varken lämnar data eller stannar av sig själv.

ACCEPTANSKRITERIET är "minnesmätning, eller minst ett test att `_collect`
inte materialiserar hela listan". Här finns båda, och mätningen räknar
LEVANDE produkter under körningen i stället för minnet efteråt: att inget
läcker när allt är klart är en svagare sak än att katalogen aldrig finns
samlad. `gc.collect()` + weakref ger ett exakt tal, inte ett ungefär.
"""

import gc
import io
import json
import sys
import tracemalloc
import unittest
import urllib.error
import weakref
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.grocery import importer  # noqa: E402
from services.grocery.errors import ProviderBlockedError  # noqa: E402
from services.grocery.providers import citygross as cg_module  # noqa: E402
from services.grocery.providers.citygross import (  # noqa: E402
    CATEGORY_PAGE_SIZE, FOOD_DEPARTMENTS, CityGrossProvider,
)
from services.grocery.providers.primat import (  # noqa: E402
    BATCH_SIZE, PAGE_LIMIT, PrimatProvider,
)
from services.grocery.streaming import DEFAULT_BATCH_SIZE, ProductSink  # noqa: E402

DEPARTMENT_IDS = {name: 1500 + index for index, name in enumerate(sorted(FOOD_DEPARTMENTS))}


class FakeResponse(io.BytesIO):
    def __init__(self, body=b"", *, status=200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _json(payload):
    return FakeResponse(json.dumps(payload).encode("utf-8"))


def _produkt(index):
    """En City Gross-produkt i sajtens egen form, unik per index."""
    return {
        "id": f"{100000 + index}_ST", "gtin": None, "name": f"Vara {index}",
        "brand": "GARANT", "superCategory": "Mejeri, ost & ägg",
        "descriptiveSize": "1,5L",
        "productStoreDetails": {
            "p_has_price": True,
            "prices": {"currentPrice": {"price": 16.5, "unit": "PCE"},
                       "ordinaryPrice": {"price": 16.5, "unit": "PCE"},
                       "memberPrice": None, "promotions": [], "activePromotion": None},
        },
    }


def _navigation(names):
    barn = [{"id": DEPARTMENT_IDS[name], "name": name, "type": "ProductCategoryPage",
             "link": {"url": "/matvaror/x", "categoryPageId": str(DEPARTMENT_IDS[name])},
             "children": []}
            for name in names]
    return {"data": {"tree": {"id": 66, "name": "root", "children": [
        {"id": 69, "name": "Matvaror", "type": "ProductFolderPage",
         "link": {"url": "/matvaror", "categoryPageId": None}, "children": barn}]}}}


def _fingeravtryck(produkter):
    """Produkterna i jämförbar form: allt utom `fetched_at`, som är
    time.time() och alltså aldrig lika mellan två körningar. Kompakt med
    flit - en misslyckad assertEqual på tusentals dataklasser bygger en diff på
    fem megabyte och tar tre minuter."""
    return [(p.external_product_id, p.name, p.size, p.regular_price,
             p.campaign_price, p.category) for p in produkter]


class Levanderäknare:
    """En `on_products` som släpper varje batch och räknar hur många
    produkter som fortfarande LEVER när nästa batch kommer.

    Att räkna så här, i stället för att mäta minne efteråt, är hela poängen:
    en provider som samlar allt och lämnar det på slutet ser städad ut
    efteråt men har haft hela katalogen i minnet på vägen."""

    def __init__(self):
        self.antal = 0
        self.batchar = []          # bara storlekarna, aldrig produkterna
        self._levande = []         # weakrefs, håller ingenting vid liv
        self.max_levande = 0

    def __call__(self, batch):
        self.antal += len(batch)
        self.batchar.append(len(batch))
        for produkt in batch:
            self._levande.append(weakref.ref(produkt))
        del batch
        gc.collect()
        levande = sum(1 for ref in self._levande if ref() is not None)
        self.max_levande = max(self.max_levande, levande)


class CityGrossStrommar(unittest.TestCase):
    """City Gross lämnar avdelningarna vidare medan den hämtar dem."""

    AVDELNINGAR = sorted(FOOD_DEPARTMENTS)
    PER_AVDELNING = 300

    def setUp(self):
        self._orig = cg_module.urllib.request.urlopen
        self._sleep = cg_module.time.sleep
        cg_module.time.sleep = lambda s: None
        cg_module.urllib.request.urlopen = self._open
        self.addCleanup(lambda: setattr(cg_module.time, "sleep", self._sleep))
        self.addCleanup(lambda: setattr(cg_module.urllib.request, "urlopen", self._orig))
        self.blockera_efter = None
        self._svarade = 0

    def _open(self, request, timeout=None):
        url = request.full_url
        if "api/v1/navigation" in url:
            return _json(_navigation(self.AVDELNINGAR))
        if "Loop54/category/" in url:
            kid = int(url.split("Loop54/category/")[1].split("/")[0])
            avdelning = self.AVDELNINGAR.index(
                next(n for n, i in DEPARTMENT_IDS.items() if i == kid))
            skip = int(url.split("skip=")[1].split("&")[0])
            self._svarade += 1
            if self.blockera_efter is not None and self._svarade > self.blockera_efter:
                raise urllib.error.HTTPError(url, 403, "blockerad", {}, io.BytesIO(b""))
            start = avdelning * self.PER_AVDELNING + skip
            items = [_produkt(start + n)
                     for n in range(min(CATEGORY_PAGE_SIZE, self.PER_AVDELNING - skip))]
            return _json({"items": items, "totalCount": self.PER_AVDELNING})
        return _json({"searchResults": {"products": [], "totalCount": 0}})

    @property
    def totalt(self):
        return len(self.AVDELNINGAR) * self.PER_AVDELNING

    def test_streaming_lamnar_allt_vidare_och_returnerar_inget(self):
        räknare = Levanderäknare()
        provider = CityGrossProvider(search_terms=[])
        kvar = provider.get_products("3209", on_products=räknare)
        self.assertEqual(kvar, [], "allt ska redan vara lämnat vidare")
        self.assertEqual(räknare.antal, self.totalt)
        self.assertGreater(len(räknare.batchar), 1, "en enda batch är ingen streaming")
        self.assertLessEqual(max(räknare.batchar), DEFAULT_BATCH_SIZE)

    def test_katalogen_finns_aldrig_samlad_i_minnet(self):
        """Minnesmätningen. Före D7 låg alla 3 300 produkterna i fixturen kvar i
        providerns lista tills körningen var klar."""
        räknare = Levanderäknare()
        CityGrossProvider(search_terms=[]).get_products("3209", on_products=räknare)
        self.assertLessEqual(
            räknare.max_levande, DEFAULT_BATCH_SIZE * 2,
            f"{räknare.max_levande} produkter levde samtidigt - bufferten ska "
            f"vara O(batch), inte O(katalog)")
        self.assertLess(räknare.max_levande, self.totalt // 4)

    def test_utan_callback_ar_beteendet_oforandrat(self):
        """Kontrollrummet och testerna anropar providern direkt. Den vägen
        ska fortfarande ge hela katalogen."""
        produkter = CityGrossProvider(search_terms=[]).get_products("3209")
        self.assertEqual(len(produkter), self.totalt)

    def test_streaming_ger_exakt_samma_produkter(self):
        samlade = []
        CityGrossProvider(search_terms=[]).get_products(
            "3209", on_products=lambda batch: samlade.extend(batch))
        direkt = CityGrossProvider(search_terms=[]).get_products("3209")
        self.assertEqual(_fingeravtryck(samlade), _fingeravtryck(direkt))

    def test_en_blockering_lamnar_ingen_produkt_dubbelt(self):
        """Blockeras körningen stagear importern `partial_products`. Är de
        redan streamade skulle samma rader stagas två gånger - så det som
        redan lämnats vidare får inte komma tillbaka här."""
        self.blockera_efter = 7
        räknare = Levanderäknare()
        provider = CityGrossProvider(search_terms=[])
        with self.assertRaises(ProviderBlockedError) as fångad:
            provider.get_products("3209", on_products=räknare)
        rest = fångad.exception.partial_products
        self.assertLess(len(rest), DEFAULT_BATCH_SIZE)
        ids = [p.external_product_id for p in rest]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreater(räknare.antal, 0)
        # 7 sidor à 100 produkter hann svara innan blockeringen.
        self.assertEqual(räknare.antal + len(rest), 700)


class PrimatStrommar(unittest.TestCase):
    """Primat slår upp paketdata klumpvis i stället för på slutet."""

    def setUp(self):
        self.anrop = []
        self.sidor = 6           # 6 * PAGE_LIMIT prisrader

    def _provider(self, **kwargs):
        provider = PrimatProvider("ICA", api_key="test", book_rows=lambda n: None, **kwargs)
        provider._call = self._call
        return provider

    def _call(self, method, path, params=None, body=None):
        self.anrop.append(f"{method} {path}")
        if path == "/prices":
            sida = int((params or {}).get("cursor") or 0)
            rader = [{"chain": "ica", "store_id": "1", "product_id": f"p{sida}-{n}",
                      "name": f"Vara {sida}-{n}", "price": 10.0, "effective_price": 10.0}
                     for n in range(PAGE_LIMIT)]
            nästa = sida + 1
            return {"data": rader,
                    "next_cursor": str(nästa) if nästa < self.sidor else None}
        if path == "/batch":
            lookups = (body or {}).get("lookups") or []
            return {"data": [{"results": [
                {"chain": "ica", "store_id": "1", "product_id": lookup["product_id"],
                 "name": "Vara", "amount": 750.0, "unit": "g", "package": "750 g",
                 "prices": {"regular": 10.0}} for lookup in lookups]}]}
        raise AssertionError(f"oväntat anrop {method} {path}")

    @property
    def totalt(self):
        return self.sidor * PAGE_LIMIT

    def test_uppslagen_flatas_in_mellan_prissidorna(self):
        """Beviset för att stegen inte längre är staplade: ett /batch ska
        ligga FÖRE den sista prissidan. Förut kom alla /prices först och
        alla /batch sedan, med hela katalogen i minnet emellan."""
        self._provider().get_products("1", on_products=lambda batch: None)
        sista_pris = max(i for i, a in enumerate(self.anrop) if a.endswith("/prices"))
        första_batch = min(i for i, a in enumerate(self.anrop) if a.endswith("/batch"))
        self.assertLess(första_batch, sista_pris)

    def test_streaming_lamnar_allt_vidare_och_returnerar_inget(self):
        räknare = Levanderäknare()
        kvar = self._provider().get_products("1", on_products=räknare)
        self.assertEqual(kvar, [])
        self.assertEqual(räknare.antal, self.totalt)
        self.assertGreater(len(räknare.batchar), 1)

    def test_katalogen_finns_aldrig_samlad_i_minnet(self):
        räknare = Levanderäknare()
        self._provider().get_products("1", on_products=räknare)
        self.assertLessEqual(räknare.max_levande, DEFAULT_BATCH_SIZE * 2)
        self.assertLess(räknare.max_levande, self.totalt // 4)

    def test_streaming_ger_exakt_samma_produkter(self):
        samlade = []
        self._provider().get_products("1", on_products=lambda batch: samlade.extend(batch))
        self.anrop = []
        direkt = self._provider().get_products("1")
        self.assertEqual(_fingeravtryck(samlade), _fingeravtryck(direkt))

    def test_radbokforingen_ar_oforandrad(self):
        """Flätningen får inte kosta en enda extra rad av dygnskvoten (D5).
        Prisrader + ett uppslag per rad, varken mer eller mindre."""
        bokfört = []
        strömmande = self._provider()
        strömmande._book_rows = bokfört.append
        strömmande.get_products("1", on_products=lambda batch: None)
        självt = self._provider()
        självt.get_products("1")
        self.assertEqual(strömmande.rows_spent, självt.rows_spent)
        self.assertEqual(strömmande.rows_spent, self.totalt * 2)
        self.assertEqual(sum(bokfört), self.totalt * 2)

    def test_prisbudgeten_klipper_fortfarande_pa_halva_taket(self):
        """`_rows_spent` bär numera även uppslagsraderna medan prisloopen
        snurrar. Räknade prisloopen på den skulle den klippa dubbelt så
        tidigt - halva katalogen skulle tyst försvinna."""
        self.sidor = 50
        provider = self._provider(max_rows=2 * PAGE_LIMIT * 3)   # prisbudget = 3 sidor
        with self.assertRaises(ProviderBlockedError):
            provider.get_products("1", on_products=lambda batch: None)
        prissidor = sum(1 for a in self.anrop if a.endswith("/prices"))
        self.assertEqual(prissidor, 3)

    def test_taket_ger_rader_utan_paketdata_i_stallet_for_tappade_rader(self):
        """Nås radtaket mitt i uppslagen ska resten av prisraderna ändå bli
        produkter - utan paketdata, som förut. Att tappa raderna vore att
        kasta bort rader vi redan betalat för ur dygnskvoten.

        Tak 1 000 rader, prisbudget 500, sidor om 200:
          sida 1 (200 prisrader) -> 2 uppslag om 100      = 400 spenderade
          sida 2 (200 prisrader) -> 2 uppslag om 100      = 800 spenderade
          sida 3 (200 prisrader)                          = 1 000 spenderade
          prisbudgeten är nådd, och uppslagen ryms inte längre under taket
        Alltså 600 produkter, varav 400 med paketdata och 200 utan - och
        taket exakt respekterat, aldrig överskridet."""
        self.sidor = 10
        provider = self._provider(max_rows=1000)
        with self.assertRaises(ProviderBlockedError) as fångad:
            provider.get_products("1")
        produkter = fångad.exception.partial_products
        self.assertEqual(len(produkter), 600)
        utan_paket = [p for p in produkter if p.size is None]
        self.assertEqual(len(utan_paket), 200, "de sista raderna ska sakna paketdata, inte saknas")
        self.assertLessEqual(provider.rows_spent, 1000)
        self.assertEqual(provider.rows_spent, 1000)


class ImporternSkickarCallbacken(unittest.TestCase):
    """`_collect` ska ge callbacken till den som kan ta emot den, och bara
    till den."""

    class Strommande:
        def __init__(self):
            self.fick_callback = False

        def get_products(self, store_id, on_products=None):
            self.fick_callback = on_products is not None
            if on_products:
                on_products(["a", "b"])
                return []
            return ["a", "b"]

    class Gammal:
        def get_products(self, store_id):
            return ["a", "b"]

    def test_streamande_provider_far_callbacken(self):
        provider = self.Strommande()
        batchar = []
        kvar = importer._collect(provider, "1", None, batchar.extend)
        self.assertTrue(provider.fick_callback)
        self.assertEqual(kvar, [])
        self.assertEqual(batchar, ["a", "b"])

    def test_provider_utan_streaming_anropas_som_forut(self):
        """Ett `on_products` till en provider som inte tar emot det vore ett
        TypeError mitt i nattens import."""
        kvar = importer._collect(self.Gammal(), "1", None, lambda batch: None)
        self.assertEqual(kvar, ["a", "b"])

    def test_de_tva_riktiga_providrarna_kan_strommas(self):
        self.assertTrue(importer.streams_products(CityGrossProvider()))
        self.assertTrue(importer.streams_products(
            PrimatProvider("ICA", api_key="test", book_rows=lambda n: None)))
        self.assertFalse(importer.streams_products(self.Gammal()))


class Sinken(unittest.TestCase):
    def test_utan_callback_samlas_allt(self):
        sink = ProductSink(batch_size=2)
        for n in range(5):
            sink.add(n)
        self.assertEqual(sink.drain(), [0, 1, 2, 3, 4])
        self.assertEqual(sink.count, 5)

    def test_med_callback_slapps_varje_batch(self):
        batchar = []
        sink = ProductSink(batchar.append, batch_size=2)
        for n in range(5):
            sink.add(n)
        self.assertEqual(batchar, [[0, 1], [2, 3]])
        # drain() lämnar vidare det som är kvar och returnerar det som INTE
        # gick att lämna vidare - under streaming alltså ingenting.
        self.assertEqual(sink.drain(), [])
        self.assertEqual(batchar, [[0, 1], [2, 3], [4]])
        self.assertEqual(sink.drain(), [])
        self.assertEqual(sink.peak_buffered, 2)

    def test_batchen_ags_av_mottagaren(self):
        """Sinken återanvänder inte listan - en mottagare som sparar undan
        batchen ska inte se den tömmas under fötterna."""
        batchar = []
        sink = ProductSink(batchar.append, batch_size=2)
        for n in range(4):
            sink.add(n)
        self.assertEqual(batchar, [[0, 1], [2, 3]])


class Minnesmatning(unittest.TestCase):
    """Samma insamling två gånger, en gång strömmande och en gång samlande,
    med tracemalloc emellan. Talen är inte exakta - poängen är
    storleksordningen."""

    def setUp(self):
        self._orig = cg_module.urllib.request.urlopen
        self._sleep = cg_module.time.sleep
        cg_module.time.sleep = lambda s: None
        self.addCleanup(lambda: setattr(cg_module.time, "sleep", self._sleep))
        self.addCleanup(lambda: setattr(cg_module.urllib.request, "urlopen", self._orig))
        harness = CityGrossStrommar("test_utan_callback_ar_beteendet_oforandrat")
        harness.blockera_efter = None
        harness._svarade = 0
        cg_module.urllib.request.urlopen = harness._open
        self.totalt = harness.totalt

    def _topp(self, on_products):
        gc.collect()
        tracemalloc.start()
        CityGrossProvider(search_terms=[]).get_products("3209", on_products=on_products)
        _, topp = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return topp

    def test_strommande_korning_toppar_lagre(self):
        samlande = []
        topp_samlande = self._topp(samlande.append)      # behåller varje batch
        self.assertEqual(sum(len(b) for b in samlande), self.totalt)
        del samlande
        topp_strommande = self._topp(lambda batch: None)  # släpper varje batch
        self.assertLess(topp_strommande, topp_samlande / 2,
                        f"strömmande topp {topp_strommande} B mot samlande "
                        f"{topp_samlande} B - katalogen ligger kvar någonstans")


if __name__ == "__main__":
    unittest.main()
