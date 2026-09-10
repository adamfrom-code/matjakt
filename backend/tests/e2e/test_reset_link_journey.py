# -*- coding: utf-8 -*-
"""Browser-E2E: resan från återställningsmejlet, i en riktig Chromium (B7).

Mejlet från servern innehåller `{APP_URL}/?reset={token}`, och den token ÄR
kontot: den som har strängen sätter ett nytt lösenord. Förut blev den kvar i
adressfältet - och därmed i historiken och i webbläsarens
sessionsåterställning - ända tills användaren hunnit fylla i formuläret. En
timme lång fullständig kontoövertagning, i klartext, i en URL som dessutom
skickas som sidvisning till besöksstatistiken (plausible.io och
cloud.umami.is är släppta i CSP:n).

Testet prövar BÅDA halvorna, för den ena utan den andra bevisar ingenting:

  1. att token FAKTISKT ANVÄNDS - lösenordet byts och det nya loggar in,
     det gamla nekas. Ett test som bara mätte adressfältet skulle passera
     lika glatt om hela återställningsflödet vore sönderslaget.
  2. att `location.search` är TOM omedelbart efter boot - läst en enda gång,
     utan omförsök, direkt när DOMContentLoaded gått.

Samma sak för `?verify=`.

Servern, databaserna och prisdatan kommer från konsumentresans fixtur
(_Server), så inget externt anropas. Hoppar över sig själv utan Playwright
och utanför tests/run.py (testvakten).
"""

import contextlib
import os
import unittest

from services.data_guard import test_mode_active

from .test_consumer_journey import HAVE_PLAYWRIGHT, MOBILE, PASSWORD, _Server, _skip_reason

if test_mode_active():
    import api_server
    from services.accounts import ratelimit

if HAVE_PLAYWRIGHT:
    from playwright.sync_api import expect, sync_playwright


NYTT_LOSENORD = "annat-hemligt-losen-456"


class ResetLinkJourney(unittest.TestCase):
    """Återställningslänken, från mejlets URL till inloggning med nytt lösenord."""

    server = None

    @classmethod
    def setUpClass(cls):
        reason = _skip_reason()
        if reason:
            raise unittest.SkipTest(reason)
        cls.server = _Server()
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True)
        except Exception as error:      # pragma: no cover - Chromium saknas
            cls.playwright.stop()
            cls.server.close()
            raise unittest.SkipTest(f"Chromium kunde inte startas: {str(error)[:120]}")

    @classmethod
    def tearDownClass(cls):
        if cls.server is None:
            return
        with contextlib.suppress(Exception):
            cls.browser.close()
        with contextlib.suppress(Exception):
            cls.playwright.stop()
        cls.server.close()

    def setUp(self):
        ratelimit.reset()
        self.addCleanup(ratelimit.reset)
        self.context = self.browser.new_context(viewport=MOBILE, locale="sv-SE",
                                                service_workers="block")
        self.page = self.context.new_page()
        self.page.set_default_timeout(20_000)

    def tearDown(self):
        with contextlib.suppress(Exception):
            self.context.close()

    # ---- hjälpare --------------------------------------------------------

    def _konto(self):
        """Ett riktigt konto i den riktiga kontodatabasen."""
        email = f"reset-{os.urandom(4).hex()}@example.com"
        status, data = self.server.request("POST", "/api/auth/register",
                                           {"email": email, "password": PASSWORD})
        self.assertEqual(status, 201, data)
        return email

    def _reset_token(self, email):
        """Exakt den token som hade legat i mejlets länk (api_server.py:2664)."""
        token = api_server.ACCOUNT_STORE.request_password_reset(email)
        self.assertTrue(token, "servern gav ingen återställningstoken")
        return token

    def _boota(self, query):
        """Öppnar appen och läser adressfältet EN gång, direkt efter boot.

        Ingen expect(), ingen polling: app.js är en modul och körs före
        DOMContentLoaded, så det som står i adressfältet här är det som stod
        där när starten var klar. Ett omförsök hade dolt precis den lucka
        paketet handlar om.
        """
        self.page.goto(f"{self.server.base}/app/{query}", wait_until="domcontentloaded")
        return self.page.evaluate("() => ({search: location.search, href: location.href})")

    def _stang_onboarding(self):
        """Förstagångsvyn är inte det som prövas här och ligger i vägen för
        klicken i kontomodalen."""
        self.page.evaluate(
            "() => { const m = document.getElementById('onboardingModal'); if (m) m.hidden = true; }")

    # ---- proven ----------------------------------------------------------

    def test_aterstallningen_fungerar_och_token_lamnar_adressen_direkt(self):
        email = self._konto()
        token = self._reset_token(email)

        adress = self._boota(f"?reset={token}")

        # HALVA ETT: adressfältet är rent redan innan användaren gjort något.
        self.assertEqual(adress["search"], "",
                         f"token kvar i adressfältet efter boot: {adress['href']}")
        self.assertNotIn(token, adress["href"],
                         "token finns kvar någonstans i adressen")
        # ... och inte heller i historikposten som en bakåtknapp eller en
        # sessionsåterställning skulle plocka fram.
        self.assertNotIn(token, self.page.evaluate("() => document.location.toString()"))

        # HALVA TVÅ: token togs ändå emot - formuläret för nytt lösenord är
        # öppet, och det öppnas bara när starten fick tag i en token.
        expect(self.page.locator("#accountModal")).to_be_visible()
        expect(self.page.locator("#resetPasswordForm")).to_be_visible()
        self._stang_onboarding()

        self.page.fill("#resetPasswordInput", NYTT_LOSENORD)
        self.page.click('#resetPasswordForm button[type="submit"]')
        expect(self.page.locator("#accountLoginForm")).to_be_visible()
        expect(self.page.locator("#loginError")).to_have_text(
            "Lösenordet är ändrat. Logga in med det nya lösenordet.")

        # Det NYA lösenordet loggar in, genom gränssnittet.
        self.page.fill("#loginEmail", email)
        self.page.fill("#loginPassword", NYTT_LOSENORD)
        self.page.click('#accountLoginForm button[type="submit"]')
        expect(self.page.locator("#accountModal")).to_be_hidden()
        expect(self.page.locator("#profileBtn")).to_have_text(email[:2].upper())

        # Det GAMLA nekas - lösenordet byttes på riktigt, det stod inte bara
        # ett kvitto på skärmen.
        status, _ = self.server.request("POST", "/api/auth/login",
                                        {"email": email, "password": PASSWORD})
        self.assertEqual(status, 401, "det gamla lösenordet fungerar fortfarande")

    def test_token_gar_inte_att_ladda_fram_ur_adressfaltet_igen(self):
        """Sessionsåterställning och F5: det som inte står i adressen kan inte
        återuppstå ur den."""
        email = self._konto()
        token = self._reset_token(email)

        self.assertEqual(self._boota(f"?reset={token}")["search"], "")
        expect(self.page.locator("#resetPasswordForm")).to_be_visible()

        self.page.reload(wait_until="domcontentloaded")
        efter = self.page.evaluate("() => ({search: location.search, href: location.href})")
        self.assertEqual(efter["search"], "", efter["href"])
        self.assertNotIn(token, efter["href"])
        # Ingen token i adressen -> ingen återställningsdialog. Sidan kommer
        # tillbaka som en vanlig start.
        expect(self.page.locator("#resetPasswordForm")).to_be_hidden()

        # Och token är fortfarande obrukad i databasen: det är adressfältet
        # som rensats, inte återställningen som konsumerats i förtid.
        status, _ = self.server.request("POST", "/api/auth/reset-password",
                                        {"token": token, "password": NYTT_LOSENORD})
        self.assertEqual(status, 200, "token slutade gälla av att adressen rensades")

    def test_verifieringslanken_rensas_ocksa_och_verifierar_anda(self):
        email = self._konto()
        token = api_server.ACCOUNT_STORE.create_verification_token_for_email(email)

        adress = self._boota(f"?verify={token}")
        self.assertEqual(adress["search"], "",
                         f"verifieringstoken kvar i adressfältet: {adress['href']}")
        self.assertNotIn(token, adress["href"])

        # Verifieringen sker mot servern efter start; kontot ska bli verifierat.
        expect(self.page.locator("#accountModal")).to_be_visible()
        status, data = self.server.request("POST", "/api/auth/login",
                                           {"email": email, "password": PASSWORD})
        self.assertEqual(status, 200, data)
        self.assertTrue(data["user"]["emailVerified"],
                        "verifieringstoken användes aldrig - länken slutade fungera")

    def test_ofarliga_parametrar_overlever_rensningen(self):
        """Ett delat recept är hela anledningen till besöket och bär ingen
        hemlighet - att svepa hela query-strängen hade tagit det med sig."""
        email = self._konto()
        token = self._reset_token(email)

        adress = self._boota(f"?recept=nagot-recept&reset={token}")
        self.assertNotIn(token, adress["href"])
        self.assertEqual(adress["search"], "?recept=nagot-recept", adress["href"])
        expect(self.page.locator("#resetPasswordForm")).to_be_visible()
