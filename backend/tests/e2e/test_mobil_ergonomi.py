# -*- coding: utf-8 -*-
"""AO1: mobil ergonomi - det iOS gör med små fält och små tryckytor.

Mätt i en 375 px viewport (docs/changelog.d/AO1.md): sökfältet var 15 px,
filtren 13 px, "Lägg till vara" 15 px och onboardingens budgetfält 15 px.
iOS Safari och WKWebView ZOOMAR IN SIDAN när ett fält med typsnitt under
16 px får fokus - och zoomar inte ut igen. Dagens ＋ i Veckan var 34 px
bred och receptchipsen 32 px höga; Apple kräver tumytor (matt.TUMYTA_PX).

Testet läser DATORNS beräknade stil, inte en skärmdump: i en 375 px
kontext ska fälten vara 16 px och ytorna stora nog, och i en bred
kontext ska ingenting ha ändrats.
"""

import contextlib
import unittest

from services.data_guard import test_mode_active

if test_mode_active():
    from tests.e2e import matt
    from tests.e2e.test_consumer_journey import HAVE_PLAYWRIGHT, _Server, _skip_reason
    if HAVE_PLAYWRIGHT:
        from playwright.sync_api import sync_playwright

LITEN = {"width": 375, "height": 667}      # iPhone SE / 8: den minsta appen stöder
BRED = {"width": 1024, "height": 800}

# (vy att öppna, väljare) -> fältet får inte ha typsnitt under 16 px på telefon.
FALT = (
    ("recipes", "#recipeSearch"),
    ("recipes", "#kcalFilter"),
    ("basket", "#manualItemInput"),
    ("onboarding-steg-2", "#obBudget"),   # budgetfältet finns först på arkets andra steg
    (None, "#premiumCode"),
)


class MobilErgonomi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reason = _skip_reason()
        if reason:
            raise unittest.SkipTest(reason)
        cls.server = _Server()
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True)
        except Exception as error:  # pragma: no cover - Chromium saknas
            cls.playwright.stop()
            cls.server.close()
            raise unittest.SkipTest(f"Chromium kunde inte startas: {str(error)[:120]}")

    @classmethod
    def tearDownClass(cls):
        for stang in (lambda: cls.browser.close(), cls.playwright.stop, cls.server.close):
            with contextlib.suppress(Exception):
                stang()

    def sida(self, viewport):
        context = self.browser.new_context(viewport=viewport, locale="sv-SE", service_workers="block",
                                           is_mobile=viewport is LITEN, has_touch=viewport is LITEN)
        self.addCleanup(lambda: contextlib.suppress(Exception) and context.close())
        page = context.new_page()
        page.goto(f"{self.server.base}/app/")
        page.wait_for_selector(".bottom-nav-item")
        return page

    @staticmethod
    def visa(page, view):
        # Via DOM, inte via klick: onboardingens ark ligger över fliken i en
        # ny kontext, och det är vyernas stil som prövas - inte arket.
        if view == "onboarding-steg-2":
            page.evaluate("[...document.querySelectorAll('#onboardingModal button')]"
                          ".find(b => /Nästa/.test(b.textContent)).click()")
            return
        page.evaluate("v => document.querySelector(`.bottom-nav-item[data-view=${v}]`).click()", view)

    @staticmethod
    def typsnitt(page, selector):
        return page.evaluate(
            "s => { const e = document.querySelector(s); return e ? parseFloat(getComputedStyle(e).fontSize) : null }",
            selector)

    @staticmethod
    def yta(page, selector):
        return page.evaluate(
            "s => { const e = document.querySelector(s); if (!e) return null;"
            " const r = e.getBoundingClientRect(); return { w: r.width, h: r.height }; }", selector)

    def test_falt_har_16_px_pa_telefon_sa_ios_inte_zoomar(self):
        page = self.sida(LITEN)
        for view, selector in FALT:
            with self.subTest(selector=selector):
                if view:
                    self.visa(page, view)
                    page.wait_for_selector(selector, state="attached")
                storlek = self.typsnitt(page, selector)
                self.assertIsNotNone(storlek, f"{selector} finns inte")
                self.assertGreaterEqual(storlek, 16, f"{selector}: {storlek}px - iOS zoomar in vid fokus")

    def test_tryckytorna_ar_stora_nog(self):
        page = self.sida(LITEN)
        self.visa(page, "recipes")
        page.wait_for_selector(".recipe-tag")
        chip = self.yta(page, ".recipe-tag")
        # Tröskeln är matt.TUMYTA_PX (Apples tumyta), aldrig ett tal här.
        self.assertTrue(matt.minst(chip["h"]), f"receptchip {chip} under {matt.golv()} px")
        self.visa(page, "week")
        page.wait_for_selector(".vecka-dag-lagg")
        plus = self.yta(page, ".vecka-dag-lagg")
        self.assertTrue(matt.minst(plus["w"]), f"dagens ＋ {plus} smalare än {matt.golv()} px")
        self.assertTrue(matt.minst(plus["h"]), f"dagens ＋ {plus} lägre än {matt.golv()} px")

    def test_desktop_star_orord(self):
        """Regeln är telefonens. På en bred skärm är sökfältet som förut -
        annars har någon bytt det globala typsnittet i stället för att lösa
        zoomen."""
        page = self.sida(BRED)
        self.visa(page, "recipes")
        page.wait_for_selector("#recipeSearch", state="attached")
        self.assertEqual(self.typsnitt(page, "#recipeSearch"), 15)
        self.assertEqual(self.typsnitt(page, "#kcalFilter"), 13)


if __name__ == "__main__":
    unittest.main()
