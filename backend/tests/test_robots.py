# -*- coding: utf-8 -*-
"""D9: robots.txt lästes aldrig för de kedjor som faktiskt skrapas.

Coops och ICA:s robots.txt var utredda och dokumenterade - men det är just
de kedjorna vi INTE hämtar från. Willys, Hemköp och City Gross, de tre som
hämtas varje natt, hade ingen läst. Och insamlaren utgav sig för att vara
Chrome 120 med ett `Matjakt/1.0 (+grocery-collector)` på slutet, utan
kontaktväg: en kedja som vill säga nej kunde inte hitta oss.

ACCEPTANSKRITERIET: en `Disallow`-regel stoppar körningen. Här prövas det
hela vägen - från regeln i filen, genom importen, till att körningen står som
misslyckad med orsaken och att larmkedjan plockar upp den.
"""

import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.grocery import alerts, api as grocery_api, importer, robots  # noqa: E402
from services.grocery.providers.axfood import USER_AGENT as AXFOOD_UA  # noqa: E402
from services.grocery.providers.citygross import USER_AGENT as CG_UA  # noqa: E402
from services.grocery.providers.citygross import CityGrossProvider  # noqa: E402
from services.grocery.providers.willys import WillysProvider  # noqa: E402

TILLÅTANDE = "User-agent: *\nDisallow: /checkout/\nAllow: /\n"


def _svar(text, förklaring="HTTP 200"):
    return lambda url: (text, förklaring)


class Identiteten(unittest.TestCase):
    """En insamlare som inte går att kontakta kan inte heller nekas."""

    def test_user_agent_bar_en_kontaktvag_och_ingen_webblasarmask(self):
        for ua in (robots.USER_AGENT, AXFOOD_UA, CG_UA):
            self.assertNotIn("Mozilla", ua)
            self.assertNotIn("Chrome", ua)
            self.assertIn("https://matjakt.store", ua)
            self.assertTrue(ua.startswith("Matjakt/"))

    def test_alla_tre_skrapade_kedjorna_delar_identitet(self):
        """Samma sträng i providern som i robots-kontrollen: annars prövas
        reglerna mot en annan agent än den som hämtar."""
        self.assertEqual(AXFOOD_UA, robots.USER_AGENT)
        self.assertEqual(CG_UA, robots.USER_AGENT)


class Reglerna(unittest.TestCase):
    def test_ett_disallow_stoppar_precis_den_sokvagen(self):
        beslut = robots.check(["https://www.willys.se/axfood/rest/v1/search?q=mjolk"],
                              chain="Willys",
                              fetch=_svar("User-agent: *\nDisallow: /axfood/\n"))
        self.assertFalse(beslut.allowed)
        self.assertIn("/axfood/", beslut.blocked_url)
        self.assertIn("Willys", beslut.reason)

    def test_en_regel_som_inte_traffar_oss_stoppar_ingenting(self):
        beslut = robots.check(["https://www.willys.se/axfood/rest/v1/store"],
                              chain="Willys", fetch=_svar(TILLÅTANDE))
        self.assertTrue(beslut.allowed)

    def test_en_regel_riktad_mot_just_matjakt_galler(self):
        """RFC 9309: den mest specifika agentgruppen vinner över `*`."""
        text = "User-agent: *\nAllow: /\n\nUser-agent: Matjakt\nDisallow: /api/\n"
        beslut = robots.check(["https://www.citygross.se/api/v1/navigation"],
                              chain="City Gross", fetch=_svar(text))
        self.assertFalse(beslut.allowed)

    def test_en_forbjuden_sokvag_bland_flera_tillatna_racker(self):
        """Kontrollen prövar varje endpoint för sig. Ett förbud mot enbart
        sökningen får inte döljas av att avdelningarna är tillåtna."""
        text = "User-agent: *\nDisallow: /axfood/rest/v1/search\n"
        beslut = robots.check(WillysProvider().robots_urls, chain="Willys",
                              fetch=_svar(text))
        self.assertFalse(beslut.allowed)
        self.assertIn("/search", beslut.blocked_url)

    def test_ingen_robots_txt_alls_betyder_allt_tillatet(self):
        beslut = robots.check(["https://www.willys.se/axfood/rest/v1/store"],
                              fetch=_svar("", "HTTP 404 - ingen robots.txt"))
        self.assertTrue(beslut.allowed)

    def test_en_olasbar_robots_txt_stoppar_inte_natten(self):
        """Medvetet avsteg från RFC 9309, motiverat i modulens docstring: en
        femhundra hos kedjans CDN skulle annars stoppa hela nattens
        insamling för tre kedjor - ett driftfel förklätt till policy.
        Beslutet SÄGER att reglerna inte lästes."""
        beslut = robots.check(["https://www.willys.se/axfood/rest/v1/store"],
                              fetch=lambda url: (None, "HTTP 503"))
        self.assertTrue(beslut.allowed)
        self.assertIn("kunde inte läsas", beslut.reason)

    def test_robots_txt_hamtas_fran_kedjans_egen_vard(self):
        self.assertEqual(robots.robots_url("https://www.hemkop.se/axfood/rest/v1/store"),
                         "https://www.hemkop.se/robots.txt")

    def test_riktiga_hamtningen_behandlar_404_som_tom_fil(self):
        """_fetch är den enda väg som rör nätet; 4xx ska bli "" och inte None."""
        def _höj(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 404, "nix", {}, None)

        original = robots.urllib.request.urlopen
        robots.urllib.request.urlopen = _höj
        try:
            text, förklaring = robots._fetch("https://example.test/robots.txt")
        finally:
            robots.urllib.request.urlopen = original
        self.assertEqual(text, "")
        self.assertIn("404", förklaring)


class Insamlingsadresserna(unittest.TestCase):
    """Kontrollen ska pröva det providern faktiskt hämtar."""

    def test_willys_provar_alla_fyra_endpoints(self):
        urls = WillysProvider().robots_urls
        self.assertEqual(len(urls), 4)
        for del_ in ("/store", "/leftMenu/categorytree", "/c/", "/search?"):
            self.assertTrue(any(del_ in url for url in urls), del_)
        self.assertTrue(all(url.startswith("https://www.willys.se/") for url in urls))

    def test_city_gross_provar_alla_fem(self):
        urls = CityGrossProvider().robots_urls
        self.assertEqual(len(urls), 5)
        for del_ in ("/sites", "/PageData/stores", "/navigation",
                     "/Loop54/category/", "/Loop54/search"):
            self.assertTrue(any(del_ in url for url in urls), del_)

    def test_primat_kontrolleras_inte(self):
        """robots.txt gäller den som hämtar från en webbplats. Primat är ett
        betalt API med ett avtal."""
        class Primatliknande:
            name = "primat"

        beslut = robots.ensure_allowed(Primatliknande())
        self.assertTrue(beslut.allowed)


class FalskProvider:
    """En Willys-lik provider som räknar vad importen hann göra."""

    name = "Willys"
    robots_urls = ["https://www.willys.se/axfood/rest/v1/store"]

    def __init__(self):
        self.hamtade_butiker = 0
        self.hamtade_produkter = 0

    def get_stores(self):
        self.hamtade_butiker += 1
        from services.grocery.models import Store
        return [Store(id=0, chain="Willys", external_store_id="2132", name="Willys Gävle",
                      city="Gävle", postal_code="80265", address="Gestrikevägen",
                      latitude=None, longitude=None, active=True)]

    def get_products(self, store_id):
        self.hamtade_produkter += 1
        return []


class EttForbudStopparKorningen(unittest.TestCase):
    """D9:s acceptanskriterium, hela vägen genom importen."""

    def setUp(self):
        self.provider = FalskProvider()
        original = importer._provider_for
        importer._provider_for = lambda chain: self.provider
        self.addCleanup(setattr, importer, "_provider_for", original)
        self._fetch = robots._fetch
        self.addCleanup(setattr, robots, "_fetch", self._fetch)

    def _kör(self, robots_text):
        robots._fetch = _svar(robots_text)
        importer._run("Willys", "2132", None)
        db = grocery_api.open_store()
        rad = db.connection.execute(
            "SELECT status, error_message FROM grocery_collector_runs "
            "WHERE chain = 'Willys' ORDER BY id DESC LIMIT 1").fetchone()
        return rad

    def test_ett_disallow_gor_korningen_misslyckad_med_orsaken(self):
        rad = self._kör("User-agent: *\nDisallow: /axfood/\n")
        self.assertEqual(rad["status"], "failed")
        self.assertIn("robots.txt", rad["error_message"])
        self.assertIn("/axfood/", rad["error_message"])

    def test_ingenting_hamtas_efter_ett_forbud(self):
        """Stoppet ska ligga FÖRE första anropet mot kedjan. Ett förbud som
        upptäcks efter att katalogen hämtats är inget stopp."""
        self._kör("User-agent: *\nDisallow: /axfood/\n")
        self.assertEqual(self.provider.hamtade_butiker, 0)
        self.assertEqual(self.provider.hamtade_produkter, 0)

    def test_korningen_kraschar_inte_utan_avslutas(self):
        """Importstatusen ska säga varför, inte bara sluta svara."""
        self._kör("User-agent: *\nDisallow: /axfood/\n")
        status = importer.status()
        self.assertFalse(status["running"])
        self.assertEqual(status["status"], "failed")
        self.assertIn("robots.txt", status["message"])

    def test_ett_tillatande_svar_slapper_fram_korningen(self):
        """Motprovet: kontrollen får inte stoppa en natt som är tillåten.

        Körningen i sig blir ändå misslyckad - den falska providern lämnar
        noll produkter och faller på publiceringsgaten, precis som en riktig
        tom natt ska göra (D4). Poängen här är VARFÖR: kedjan hämtades, och
        orsaken har ingenting med robots att göra."""
        rad = self._kör(TILLÅTANDE)
        self.assertNotIn("robots.txt", rad["error_message"] or "")
        self.assertEqual(self.provider.hamtade_butiker, 1)
        self.assertEqual(self.provider.hamtade_produkter, 1)

    def test_larmet_gar(self):
        """D1 gav larmen en mottagare. En robots-stoppad körning ska nå den:
        ett misslyckat SENASTE försök är ett eget larmvillkor (D4), medan
        "blocked" med flit inte larmar - därför är ett förbud failed."""
        self._kör("User-agent: *\nDisallow: /axfood/\n")
        panel = [{
            "chain": "Willys",
            "health": grocery_api.chain_health({
                "chain": "Willys",
                "lastRun": {"status": "failed", "finishedAt": 1.0,
                            "errorMessage": "Willys: robots.txt tillåter inte "
                                            "https://www.willys.se/axfood/rest/v1/store"},
                "lastSuccessfulRun": {"finishedAt": 1.0},
            }),
        }]
        problem = alerts.evaluate(panel)
        self.assertTrue(problem, "ingen larmpost alls")
        nyckel, post = next(iter(problem.items()))
        self.assertEqual(post["severity"], "critical")
        self.assertIn("robots.txt", post["body"])


class Reservvagen(unittest.TestCase):
    """Axfood kan lägga på en WAF vilken natt som helst. Då ska Willys och
    Hemköp kunna flyttas till Primat utan en deploy."""

    def setUp(self):
        import os
        self._miljö = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._miljö)))

    def _sätt(self, värde, nyckel="hemlig-nyckel"):
        import os
        os.environ["MATJAKT_PRIMAT_CHAINS"] = värde
        os.environ["PRIMAT_API_KEY"] = nyckel

    def test_avstangd_som_standard(self):
        import os
        os.environ.pop("MATJAKT_PRIMAT_CHAINS", None)
        self.assertEqual(importer.primat_fallback_stores(), {})
        self.assertIsInstance(importer._provider_for("Willys"), WillysProvider)

    def test_en_paslagen_kedja_gar_till_primat(self):
        self._sätt("Willys=2178")
        provider = importer._provider_for("Willys")
        self.assertEqual(provider.name, "primat")
        self.assertEqual(provider.chain, "Willys")
        self.assertEqual(importer.primat_fallback_stores()["Willys"], "2178")

    def test_en_kedja_utan_butiksid_sager_ifran(self):
        """Primats butiksnummer är en annan nummerrymd än Axfoods. Utan id
        hade körningen dött på "butiken finns inte" den natt reservvägen
        behövdes."""
        self._sätt("Willys")
        with self.assertRaises(ValueError) as fångad:
            importer._provider_for("Willys")
        self.assertIn("butiks-id", str(fångad.exception))

    def test_reservvagen_omfattas_av_kvotsparren(self):
        """En kedja på reservvägen kostar dygnskvot som alla andra
        Primat-kedjor. Utan det här vore reservvägen ett sätt att gå förbi
        den enda kontroll som står mellan oss och ett 429 (D5)."""
        from services.grocery import quota, scheduler
        original = quota.can_start
        quota.can_start = lambda **kwargs: (False, "kvoten är slut för i dag")
        self.addCleanup(setattr, quota, "can_start", original)

        import os
        os.environ.pop("MATJAKT_PRIMAT_CHAINS", None)
        self.assertTrue(scheduler.SCHEDULER._primat_quota_allows("Willys"),
                        "utan reservväg kostar Willys ingen kvot alls")
        self._sätt("Willys=2178")
        self.assertFalse(scheduler.SCHEDULER._primat_quota_allows("Willys"))
        # ICA och de andra Primat-kedjorna gäller som förut.
        self.assertFalse(scheduler.SCHEDULER._primat_quota_allows("ICA"))

    def test_utan_nyckel_sager_den_ifran(self):
        self._sätt("Willys=2178", nyckel="")
        import os
        os.environ["PRIMAT_API_KEY"] = ""
        with self.assertRaises(ValueError) as fångad:
            importer._provider_for("Willys")
        self.assertIn("PRIMAT_API_KEY", str(fångad.exception))


if __name__ == "__main__":
    unittest.main()
