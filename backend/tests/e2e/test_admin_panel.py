# -*- coding: utf-8 -*-
"""Kontrollrummet i handen och på skrivbordet (O13), mot den RIKTIGA servern.

Ingen admin-E2E fanns: kontrollrummet verifierades mot en handskriven
fixturserver i webbläsarpanelen, vilket prövade markupen men inte
endpointerna. Här startas api_server med seedad prisdata, admin-token satt,
en misslyckad körning med ett långt felmeddelande och en öppen incident -
och sidan mäts vid 320, 375 och 390 px, med förstorad text, och vid 1 280.

Minskad bredd får inte bero på bortklippt innehåll: varje rad i Kedjor
måste bära exakt tabellhuvudets rubriker som data-label, och felraden
måste synas. Skärmdumparna bär en banderoll som säger att siffrorna är
testdata."""

import os
import re
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.e2e.test_consumer_journey import ARTIFACTS, _Server, _skip_reason  # noqa: E402

try:
    from playwright.sync_api import expect, sync_playwright
except Exception:  # pragma: no cover
    sync_playwright = None

import api_server  # noqa: E402
from services.grocery import alerts, api as grocery_api  # noqa: E402

ADMIN = "admin-e2e-o13"
LANGT_FEL = ("429 Too Many Requests från https://primat.nu/api/v3/products?stores=ica:1003987 "
             "- dygnskvoten är slut; det som hunnit hämtas behålls och täckningen byggs upp "
             "över flera nätter. Retry-After: 43 200 s. " * 2).strip()
BREDDER = (320, 375, 390)


class AdminPanel(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        reason = _skip_reason()
        if reason:
            raise unittest.SkipTest(reason)
        cls.server = _Server()
        # BROWSERN FÖRST, TILLSTÅNDET SEDAN. Om Chromium saknas (backend-jobbet
        # i CI har ingen) kastar launch, SkipTest reser sig och tearDownClass
        # körs ALDRIG. Sattes ADMIN_TOKEN före den punkten läckte den till
        # resten av sviten: test_the_mail_signing_key_is_not_the_admin_token
        # slutade hoppa över och föll i CI med "1 231 tester, 5 skippade" -
        # gröna lokalt där Chromium finns. Samma ordning som konsumentresan.
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True)
        except Exception as error:  # pragma: no cover
            cls.playwright.stop(); cls.server.close()
            raise unittest.SkipTest(f"Chromium kunde inte startas: {str(error)[:120]}")
        cls._orig_admin = api_server.ADMIN_TOKEN
        api_server.ADMIN_TOKEN = ADMIN
        # En misslyckad ICA-körning med LÅNGT fel + en lyckad Willys-körning
        # med datum: raderna som ska synas i kortet.
        db = grocery_api.open_store()
        try:
            nu = time.time()
            db.connection.execute(
                "INSERT INTO grocery_collector_runs (chain, store_id, started_at, finished_at, status, error_message) "
                "VALUES ('ICA', NULL, ?, ?, 'failed', ?)", (nu - 7200, nu - 7100, LANGT_FEL))
            db.connection.commit()
        finally:
            db.close()
        grocery_api.clear_cache()
        # En öppen incident (ICA misslyckad, ej släppt) + en i historiken.
        panel = grocery_api.provider_status()
        alerts.process(panel, api_server.KV_CACHE, api_server.MAIL_CONFIG, now=time.time(), to_email="")
        alerts._arkivera(api_server.KV_CACHE, {"openedAt": time.time() - 40000, "chain": "Willys",
                                                "severity": "warning", "title": "Willys har inte uppdaterats",
                                                "summary": "Willys har inte uppdaterats", "mail": {"status": "sent"}},
                         "chain:Willys:stale", time.time() - 3600, "failed")

    @classmethod
    def tearDownClass(cls):
        api_server.ADMIN_TOKEN = cls._orig_admin
        for key in list(api_server.KV_CACHE.keys(alerts.NAMESPACE)):
            api_server.KV_CACHE.delete(alerts.NAMESPACE, key)
        cls.browser.close(); cls.playwright.stop(); cls.server.close()

    # ---- hjälpare ----
    def _oppna(self, width, height=812, font_px=None):
        ctx = self.browser.new_context(viewport={"width": width, "height": height}, locale="sv-SE")
        page = ctx.new_page()
        page.goto(f"{self.server.base}/app/admin.html")
        if font_px:
            page.evaluate(f"() => {{ document.documentElement.style.fontSize = '{font_px}px'; }}")
        page.fill("#token", ADMIN)
        page.click("#connect")
        expect(page.locator("#panel")).to_be_visible()
        expect(page.locator("#chains tbody tr").first).to_be_visible(timeout=15_000)
        page.wait_for_function("() => document.getElementById('incidentsActive').innerText !== 'Läser…'", timeout=15_000)
        return ctx, page

    def _banderoll(self, page, text):
        page.evaluate("""(t) => { const b = document.createElement('div');
          b.textContent = t; b.style.cssText = 'position:sticky;top:0;z-index:99;background:#b91c1c;color:#fff;'
          + 'font:700 14px system-ui;padding:.4rem .8rem;text-align:center';
          document.body.prepend(b); }""", text)

    def _skarmdump(self, page, namn):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(ARTIFACTS / f"{namn}.png"), full_page=True)

    def _kontrollera_kort(self, page, width):
        # 1. Sidan overflowar inte.
        self.assertFalse(page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1"),
                         f"{width}px: sidan overflowar")
        # 2. Varje kedjerad bär EXAKT tabellhuvudets rubriker som data-label.
        rubriker = page.evaluate("() => [...document.querySelectorAll('#chains thead th')].map(t => t.textContent.trim())")
        self.assertEqual(len(rubriker), 14, rubriker)
        rader = page.evaluate("""() => [...document.querySelectorAll('#chains tbody tr')]
            .filter(r => !r.querySelector('td[colspan]'))
            .map(r => [...r.querySelectorAll('td')].map(td => td.dataset.label || null))""")
        self.assertGreaterEqual(len(rader), 6, "alla kedjor ska finnas")
        for rad in rader:
            self.assertEqual(rad, rubriker, f"{width}px: etiketter saknas eller i fel ordning: {rad}")
        # 3. Inget dolt: alla celler synliga (kortläge ger display:flex, aldrig none).
        dolda = page.evaluate("""() => [...document.querySelectorAll('#chains tbody td')]
            .filter(td => getComputedStyle(td).display === 'none').length""")
        self.assertEqual(dolda, 0, f"{width}px: {dolda} celler dolda")
        # 4. Felraden med det långa meddelandet syns i sin helhet.
        fel = page.locator("#chains td.wrap", has_text="429 Too Many Requests")
        expect(fel).to_be_visible()
        self.assertFalse(page.evaluate("(el) => el.scrollWidth > el.clientWidth + 1", fel.element_handle()),
                         f"{width}px: felraden klipps")
        # 5. Released och Drift är skilda etiketter med begripliga värden.
        ica = page.locator("#chains tbody tr", has_text="ICA").first
        self.assertEqual(ica.locator('td[data-label="Släppt"]').inner_text().strip().lower(), "nej")
        self.assertIn(ica.locator('td[data-label="Drift"]').inner_text().strip().split()[0], ("Trasig", "Aldrig"))
        willys = page.locator("#chains tbody tr", has_text="Willys").first
        self.assertEqual(willys.locator('td[data-label="Släppt"]').inner_text().strip(), "JA")
        # 6. Saknade värden visas som streck, inte som "undefined".
        self.assertNotIn("undefined", page.locator("#chains").inner_text())
        self.assertNotIn("null", page.locator("#chains").inner_text())
        # 7. Övriga kort finns och har innehåll.
        expect(page.locator("#incidentsActive")).to_contain_text("ICA")
        expect(page.locator("#incidentsActive")).to_contain_text("inte släppt")
        page.locator("#incidentsHistory").locator("xpath=ancestor::details").evaluate("d => d.open = true")
        hist = page.locator("#incidentsHistory tbody tr").first
        expect(hist).to_contain_text("Willys")
        self.assertEqual(page.evaluate("() => [...document.querySelectorAll('#incidentsHistory tbody tr:first-child td')].map(td => td.dataset.label)"),
                         ["Start", "Löst", "Varade", "Kedja", "Vad", "Larm", "Kvitto"])
        expect(page.locator("#scheduler")).not_to_have_text("—")
        expect(page.locator("#opsSystems")).to_contain_text("Prisrevision")
        expect(page.locator("#primatStatus")).to_contain_text("NEJ")
        # 8. Tryckytor.
        små = page.evaluate("""() => [...document.querySelectorAll('button')]
            .filter(b => b.offsetHeight > 0 && b.getBoundingClientRect().height < 44).map(b => b.innerText.slice(0,20))""")
        self.assertEqual(små, [], f"{width}px: knappar under 44 px: {små}")

    # ---- testerna ----
    def test_mobil_320_375_390_och_forstorad_text(self):
        for width in BREDDER:
            ctx, page = self._oppna(width)
            try:
                self._kontrollera_kort(page, width)
                self._banderoll(page, f"TESTDATA – fixtur, inte produktion · {width} px")
                self._skarmdump(page, f"admin-{width}")
            finally:
                ctx.close()
        # Större text: 20 px i stället för 15 - inget får klippas eller overflowa.
        ctx, page = self._oppna(375, font_px=20)
        try:
            self._kontrollera_kort(page, 375)
            self._banderoll(page, "TESTDATA – fixtur, inte produktion · 375 px · text 20 px")
            self._skarmdump(page, "admin-375-stor-text")
        finally:
            ctx.close()

    def test_desktop_1280_ar_en_tabell_med_fungerande_kontroller(self):
        ctx, page = self._oppna(1280, height=900)
        try:
            self.assertTrue(page.evaluate("() => getComputedStyle(document.querySelector('#chains thead')).display !== 'none'"))
            self.assertEqual(page.evaluate("() => getComputedStyle(document.querySelector('#chains tbody tr')).display"), "table-row")
            self.assertEqual(page.evaluate("() => document.querySelectorAll('#chains thead th').length"), 14)
            # Kontrollerna fungerar: Uppdatera ritar om utan fel.
            page.click("#refresh")
            expect(page.locator("#chains tbody tr").first).to_be_visible()
            self.assertNotIn("Kunde inte", page.locator("#totals").inner_text())
            self._banderoll(page, "TESTDATA – fixtur, inte produktion · 1280 px")
            self._skarmdump(page, "admin-1280")
        finally:
            ctx.close()

    def test_fel_token_slapps_inte_in(self):
        ctx = self.browser.new_context(viewport={"width": 375, "height": 812})
        page = ctx.new_page()
        try:
            page.goto(f"{self.server.base}/app/admin.html")
            page.fill("#token", "fel-token")
            page.click("#connect")
            expect(page.locator("#authError")).to_contain_text("Fel admin-token")
            expect(page.locator("#panel")).to_be_hidden()
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main()
