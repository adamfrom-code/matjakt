# -*- coding: utf-8 -*-
"""I7: att händelserna faktiskt HAMNAR i databasen när något händer.

test_matning_kronor.py prövar räkningen. Det här prövar inkopplingen: att
`POST /api/auth/register` lämnar ett `konto_skapat` efter sig, att en skickad
och en accepterad hushållsinbjudan räknas, att kassan räknar både att den
öppnades och vilken plan som valdes, och att kontrollrummet får de fem talen.

En händelse som ingen skickar är en rad i en allowlist, inte en mätning.
"""

import json
import sys
import threading
import unittest
import uuid
from http import client as http_client
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()  # MATJAKT_DATA_DIR -> tempkatalog INNAN api_server importeras

import api_server  # noqa: E402
from services.accounts import ratelimit  # noqa: E402


class Inkoppling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), api_server.ApiHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        # Hinkarna är per IP och alla tester delar 127.0.0.1.
        for hink in ("register", "household", "household_invite", "analytics"):
            ratelimit.clear_on_success(hink, "127.0.0.1")

    # ---- verktyg ----------------------------------------------------------
    def _anrop(self, metod, väg, payload=None, token=None):
        anslutning = http_client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            kropp = json.dumps(payload or {}).encode("utf-8") if metod == "POST" else None
            anslutning.request(metod, väg, body=kropp, headers=headers)
            svar = anslutning.getresponse()
            rå = svar.read()
            return svar.status, (json.loads(rå) if rå else None)
        finally:
            anslutning.close()

    def registrera(self):
        epost = f"matning-{uuid.uuid4().hex}@example.com"
        ratelimit.clear_on_success("register", "127.0.0.1")
        status, kropp = self._anrop("POST", "/api/auth/register",
                                    {"email": epost, "password": "hemligt123"})
        self.assertEqual(status, 201, kropp)
        return kropp["token"], epost

    def antal(self, händelse: str) -> int:
        rad = api_server.ANALYTICS._connection.execute(
            "SELECT COALESCE(SUM(count), 0) FROM analytics_daily WHERE event = ?",
            (händelse,)).fetchone()
        return int(rad[0])

    def konton_for(self, händelse: str) -> int:
        rad = api_server.ANALYTICS._connection.execute(
            "SELECT COUNT(DISTINCT user_id) FROM analytics_user_days WHERE event = ?",
            (händelse,)).fetchone()
        return int(rad[0])

    # ---- konto ------------------------------------------------------------
    def test_registrering_lamnar_ett_konto_skapat_efter_sig(self):
        före = self.antal("konto_skapat")
        före_konton = self.konton_for("konto_skapat")
        self.registrera()
        self.assertEqual(self.antal("konto_skapat"), före + 1)
        # Knuten till kontot, inte bara till dagen - annars kan kohorten inte
        # se vem som registrerade sig.
        self.assertEqual(self.konton_for("konto_skapat"), före_konton + 1)

    def test_en_avvisad_registrering_raknas_inte(self):
        före = self.antal("konto_skapat")
        status, _ = self._anrop("POST", "/api/auth/register",
                                {"email": "inte-en-adress", "password": "x"})
        self.assertEqual(status, 400)
        self.assertEqual(self.antal("konto_skapat"), före)

    # ---- hushållet --------------------------------------------------------
    def test_inbjudan_skickad_och_accepterad_raknas_var_for_sig(self):
        värd, _ = self.registrera()
        gäst, _ = self.registrera()
        skapat = self._anrop("POST", "/api/household/create", {"name": "Hemma"}, token=värd)
        self.assertIn(skapat[0], (200, 201), skapat)
        före_skickad = self.antal("inbjudan_skickad")
        före_accepterad = self.antal("inbjudan_accepterad")

        status, kropp = self._anrop("POST", "/api/household/invite", {}, token=värd)
        self.assertEqual(status, 200, kropp)
        self.assertEqual(self.antal("inbjudan_skickad"), före_skickad + 1)
        self.assertEqual(self.antal("inbjudan_accepterad"), före_accepterad,
                         "en skickad inbjudan är inte en accepterad")

        token = kropp["token"]
        status, kropp = self._anrop("POST", "/api/household/join",
                                    {"token": token}, token=gäst)
        self.assertEqual(status, 200, kropp)
        self.assertEqual(self.antal("inbjudan_accepterad"), före_accepterad + 1)

    def test_en_nekad_inbjudan_raknas_inte_som_skickad(self):
        """Ett tal som räknar försök ser ut som tillväxt när det är en bugg."""
        ensam, _ = self.registrera()          # inget hushåll skapat
        före = self.antal("inbjudan_skickad")
        status, _ = self._anrop("POST", "/api/household/invite", {}, token=ensam)
        self.assertNotEqual(status, 200)
        self.assertEqual(self.antal("inbjudan_skickad"), före)

    def test_ovriga_hushallsvagar_lamnar_inga_matspar(self):
        """Bara de två vägar som betyder något mäts - inte varje bock i en
        inköpslista."""
        värd, _ = self.registrera()
        self._anrop("POST", "/api/household/create", {"name": "Hemma"}, token=värd)
        före = self.antal("inbjudan_skickad") + self.antal("inbjudan_accepterad")
        self._anrop("POST", "/api/household/rename", {"name": "Hemma igen"}, token=värd)
        self.assertEqual(self.antal("inbjudan_skickad") + self.antal("inbjudan_accepterad"), före)

    # ---- kassan -----------------------------------------------------------
    def test_kassan_raknar_bade_oppningen_och_planen(self):
        """Planen mäts på servern, inte i klienten: det klienten säger att den
        valde och det servern skapade en session för är inte nödvändigtvis
        samma sak, och det är serverns version som blir en faktura."""
        hanterare = api_server.ApiHandler.__new__(api_server.ApiHandler)
        före_kassa, före_ar, före_manad = (self.antal("checkout_startad"),
                                           self.antal("plan_vald_ar"),
                                           self.antal("plan_vald_manad"))
        hanterare._matning_checkout(None, "yearly")
        hanterare._matning_checkout(None, "monthly")
        hanterare._matning_checkout(None, "nagot_annat")
        self.assertEqual(self.antal("checkout_startad"), före_kassa + 3)
        self.assertEqual(self.antal("plan_vald_ar"), före_ar + 1)
        self.assertEqual(self.antal("plan_vald_manad"), före_manad + 1)

    def test_betalningen_raknas_bara_nar_webhooken_faktiskt_skrev_nagot(self):
        """En duplicerad webhook är samma betalning en gång till, och Stripe
        återlevererar gärna."""
        hanterare = api_server.ApiHandler.__new__(api_server.ApiHandler)
        före = self.antal("betalning_genomford")
        hanterare._matning_betalning("duplicate", "customer.subscription.created",
                                     {"status": "active"}, None)
        self.assertEqual(self.antal("betalning_genomford"), före)
        hanterare._matning_betalning("applied", "customer.subscription.created",
                                     {"status": "active"}, None)
        self.assertEqual(self.antal("betalning_genomford"), före + 1)

    def test_uppsagning_raknas_pa_cancel_at_period_end_inte_pa_en_oppnad_portal(self):
        """I betalportalen byter man också kort. Ett tal som heter
        uppsagning_paborjad och räknar kortbyten är ett tal man fattar fel
        beslut på."""
        hanterare = api_server.ApiHandler.__new__(api_server.ApiHandler)
        före = self.antal("uppsagning_paborjad")
        hanterare._matning_betalning("applied", "customer.subscription.updated",
                                     {"status": "active"}, None)
        self.assertEqual(self.antal("uppsagning_paborjad"), före)
        hanterare._matning_betalning("applied", "customer.subscription.updated",
                                     {"status": "active", "cancel_at_period_end": True}, None)
        self.assertEqual(self.antal("uppsagning_paborjad"), före + 1)

    def test_matningen_faller_aldrig_anropet_den_hakar_i(self):
        """Mätning som fäller en betalning är värre än ingen mätning."""
        hanterare = api_server.ApiHandler.__new__(api_server.ApiHandler)
        original = api_server.ANALYTICS.record
        api_server.ANALYTICS.record = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("trasig"))
        try:
            hanterare._matning_checkout(None, "yearly")
            hanterare._matning_betalning("applied", "customer.subscription.created",
                                         {"status": "active"}, None)
            hanterare._matning_hushall("/api/household/invite", 200)
        finally:
            api_server.ANALYTICS.record = original

    # ---- klienten ---------------------------------------------------------
    def test_de_nya_handelserna_tas_emot_over_http(self):
        for händelse in ("checkout_avbruten", "mail_klick", "view_stats",
                         "view_comparison", "view_chainlist"):
            ratelimit.clear_on_success("analytics", "127.0.0.1")
            status, kropp = self._anrop("POST", "/api/analytics/event", {"event": händelse})
            self.assertEqual(status, 200, f"{händelse}: {kropp}")

    def test_ett_pahittat_namn_avvisas_fortfarande(self):
        ratelimit.clear_on_success("analytics", "127.0.0.1")
        status, _ = self._anrop("POST", "/api/analytics/event", {"event": "mitt_eget"})
        self.assertEqual(status, 400)

    # ---- kontrollrummet ---------------------------------------------------
    def test_kontrollrummet_far_de_fem_talen_fardigraknade(self):
        """Två ställen som räknar samma andel blir förr eller senare två
        olika andelar."""
        tal = api_server.insights_payload()["veckansTal"]
        self.assertEqual(sorted(tal), sorted([
            "nyaKonton", "skapadeVeckaInomTvaDygn", "tillbakaEfterSjuDagar",
            "aktivaHushallMedFlerAnEn", "betalandeOchMrr"]))
        self.assertIn("mrrKronor", tal["betalandeOchMrr"])

    def test_tratten_bar_kronor(self):
        totalt = api_server.insights_payload()["tratt"]["totalt"]
        for fält in ("mrrKronor", "mrrExMomsKronor", "arpuKronor", "tappadePremium",
                     "betalandeUtanKandPlan", "aktivaHushallMedFlerAnEn"):
            self.assertIn(fält, totalt, f"tratten saknar {fält}")


class KontrollrummetVisarTalen(unittest.TestCase):
    """Samma mönster som test_frontend_contract.py: fälten servern skickar
    ska faktiskt ritas ut. Ett tal som bara finns i JSON är inget någon ser."""

    def setUp(self):
        rot = Path(__file__).resolve().parents[2] / "frontend" / "app"
        self.js = (rot / "admin.js").read_text(encoding="utf-8")
        self.html = (rot / "admin.html").read_text(encoding="utf-8")

    def test_kortet_med_de_fem_talen_finns(self):
        self.assertIn('id="femTal"', self.html)
        self.assertIn("Veckans fem tal", self.html)
        self.assertIn("renderFemTal", self.js)

    def test_varje_tal_hamtas_ur_serverns_svar(self):
        for fält in ("nyaKonton", "skapadeVeckaInomTvaDygn", "tillbakaEfterSjuDagar",
                     "aktivaHushallMedFlerAnEn", "betalandeOchMrr", "veckansTal"):
            self.assertIn(fält, self.js, f"kontrollrummet läser aldrig {fält}")

    def test_namnaren_ritas_ut_bredvid_andelen(self):
        """En andel utan nämnare är en gissning med decimaler."""
        self.assertIn("av ${", self.js)

    def test_mrr_visas_i_kronor_och_kohorterna_med(self):
        self.assertIn("mrrKronor", self.js)
        self.assertIn("MRR", self.html)

    def test_ett_okant_pris_id_syns_som_en_varning_inte_som_ett_lagre_tal(self):
        self.assertIn("utanKandPlan", self.js)


if __name__ == "__main__":
    unittest.main()
