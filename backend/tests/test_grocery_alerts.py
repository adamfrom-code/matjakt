# -*- coding: utf-8 -*-
"""Tester för driftlarmen.

Det intressanta är inte att ett mejl kan skickas - det är att det INTE
skickas för ofta. Ett larm som kommer varje natt slutar man läsa, och då är
det värdelöst precis när det behövs. Varje test nedan motsvarar ett sätt
larmen kan bli antingen tysta när de borde höras eller tjatiga när de borde
tiga.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.grocery import alerts  # noqa: E402
from services.pricing import KeyValueCacheStore, PriceCacheStore  # noqa: E402

MAIL = {"host": "smtp.example.test", "from_email": "noreply@matjakt.store"}


def _entry(chain, status, reason=None, age=None):
    return {"chain": chain, "health": {"status": status, "reason": reason, "ageHours": age}}


class AlertTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.prices = PriceCacheStore(Path(self._tmp.name) / "prices.db")
        self.kv = KeyValueCacheStore(self.prices.connection, self.prices.lock)
        self.skickade = []
        patcher = mock.patch.object(
            alerts, "send_email",
            side_effect=lambda cfg, to, subject, body, *a, **k: self.skickade.append((to, subject, body)))
        self.send = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.prices.close()
        self._tmp.cleanup()

    def _kör(self, panel, now, quota=None):
        return alerts.process(panel, self.kv, MAIL, quota=quota, now=now,
                              to_email="adam@example.test")

    def test_a_failing_chain_alerts_once_and_then_goes_quiet(self):
        """Kärnan i deduperingen: ICA som spricker varje natt ger ETT mejl,
        inte ett per natt."""
        panel = [_entry("ICA", "failed", reason="429 quota")]
        första = self._kör(panel, now=1_000_000.0)
        self.assertEqual(första["incidents"], ["chain:ICA:failed"])
        self.assertEqual(len(self.skickade), 1)

        andra = self._kör(panel, now=1_000_000.0 + 86400)
        self.assertEqual(andra["incidents"], [])
        self.assertEqual(andra["suppressed"], ["chain:ICA:failed"])
        self.assertEqual(len(self.skickade), 1, "andra natten skickade ett till mejl")

    def test_a_resolved_problem_sends_exactly_one_recovery(self):
        self._kör([_entry("ICA", "failed", reason="timeout")], now=1_000.0)
        self.skickade.clear()

        friskt = [_entry("ICA", "healthy")]
        resultat = self._kör(friskt, now=1_000.0 + 7200)
        self.assertEqual(resultat["recoveries"], ["chain:ICA:failed"])
        self.assertEqual(len(self.skickade), 1)
        self.assertIn("löst", self.skickade[0][1])

        # ...och sedan tystnad. Inget nytt recoverymejl på nästa körning.
        self._kör(friskt, now=1_000.0 + 10800)
        self.assertEqual(len(self.skickade), 1)

    def test_a_problem_that_returns_after_recovery_alerts_again(self):
        """Efter ett recovery ska samma fel få larma igen - annars blir en
        återkommande incident tyst för alltid."""
        trasigt = [_entry("ICA", "failed", reason="timeout")]
        self._kör(trasigt, now=1_000.0)
        self._kör([_entry("ICA", "healthy")], now=2_000.0)
        self.skickade.clear()
        resultat = self._kör(trasigt, now=3_000.0)
        self.assertEqual(resultat["incidents"], ["chain:ICA:failed"])
        self.assertEqual(len(self.skickade), 1)

    def test_stale_is_a_warning_not_a_failure(self):
        """En kedja som inte uppdaterats är ett driftproblem - användarna får
        fortfarande last-good. Mejlet ska säga det."""
        resultat = self._kör([_entry("Coop", "stale", age=48.0)], now=1_000.0)
        self.assertEqual(resultat["incidents"], ["chain:Coop:stale"])
        self.assertIn("inte ett kundproblem", self.skickade[0][2])

    def test_a_failed_attempt_alarms_the_same_night(self):
        """D4:s acceptanskriterium, hela vägen från körningsstatus till mejl.

        Willys hämtade noll rader i natt. Körningen föll på publiceringsgaten
        och märktes "failed" - men i går natt lyckades den, och därför såg
        panelen frisk ut hela dagen. Nu larmar det första morgonen, med samma
        dedupering som allt annat: ett mejl, inte ett per natt."""
        from services.grocery import api as grocery_api
        nu = 1_000_000.0
        rad = {"chain": "Willys", "status": "working",
               "lastRun": {"status": "failed", "finishedAt": nu - 3 * 3600,
                           "errorMessage": "inga rader att publicera"},
               "lastSuccessfulRun": {"status": "success", "finishedAt": nu - 26 * 3600}}
        panel = [{**rad, "health": grocery_api.chain_health(rad, now=nu)}]

        resultat = self._kör(panel, now=nu)
        self.assertEqual(resultat["incidents"], ["chain:Willys:failing"])
        self.assertEqual(len(self.skickade), 1)
        _, ämne, brödtext = self.skickade[0]
        self.assertIn("Willys", ämne)
        self.assertIn("inga rader att publicera", brödtext)
        self.assertIn("senast godkända priser", brödtext)

        # Andra natten: tystnad, precis som för varje annan kvarstående
        # incident.
        andra = self._kör(panel, now=nu + 86400)
        self.assertEqual(andra["incidents"], [])
        self.assertEqual(len(self.skickade), 1)

    def test_a_repaired_import_closes_the_failing_incident(self):
        """Nästa natt går igenom: incidenten ska stängas, inte ligga kvar."""
        from services.grocery import api as grocery_api
        nu = 1_000_000.0
        trasig = {"chain": "Willys", "status": "working",
                  "lastRun": {"status": "failed", "finishedAt": nu - 60,
                              "errorMessage": "timeout"},
                  "lastSuccessfulRun": {"status": "success", "finishedAt": nu - 26 * 3600}}
        self._kör([{**trasig, "health": grocery_api.chain_health(trasig, now=nu)}], now=nu)
        self.skickade.clear()

        lagad = {"chain": "Willys", "status": "working",
                 "lastRun": {"status": "success", "finishedAt": nu + 86400},
                 "lastSuccessfulRun": {"status": "success", "finishedAt": nu + 86400}}
        resultat = self._kör(
            [{**lagad, "health": grocery_api.chain_health(lagad, now=nu + 86400)}],
            now=nu + 86400)
        self.assertEqual(resultat["recoveries"], ["chain:Willys:failing"])
        self.assertIn("löst", self.skickade[0][1])

    def test_a_limited_chain_never_alarms(self):
        """Lidl har för lite data per definition. Det är inte ett fel och får
        aldrig mejla någon."""
        resultat = self._kör([_entry("Lidl", "limited")], now=1_000.0)
        self.assertEqual(resultat["incidents"], [])
        self.assertEqual(self.skickade, [])

    def test_a_chain_that_never_imported_does_not_alarm(self):
        """ICA innan första importen är väntat, inte trasigt."""
        resultat = self._kör([_entry("ICA", "never_imported")], now=1_000.0)
        self.assertEqual(resultat["incidents"], [])

    def test_quota_warns_before_the_ceiling_not_after(self):
        resultat = self._kör([], now=1_000.0,
                             quota={"rowsUsedToday": 17_500, "dailyRowLimit": 20_000})
        self.assertEqual(resultat["incidents"], ["primat:quota"])
        self.assertIn("17500", self.skickade[0][2].replace(" ", ""))

    def test_quota_well_below_the_ceiling_is_silent(self):
        resultat = self._kör([], now=1_000.0,
                             quota={"rowsUsedToday": 4_000, "dailyRowLimit": 20_000})
        self.assertEqual(resultat["incidents"], [])

    def test_without_a_recipient_nothing_is_sent_and_nothing_crashes(self):
        """Larm utan adress ska vara tyst, inte fälla nattjobbet."""
        resultat = alerts.process([_entry("ICA", "failed")], self.kv, MAIL,
                                  now=1_000.0, to_email="")
        self.assertEqual(self.skickade, [])
        self.assertEqual(resultat["skipped"], ["chain:ICA:failed"])

    def test_a_broken_mailer_never_stops_the_night_job(self):
        """Om SMTP är nere ska körningen fortsätta - annars byter vi ut ett
        driftproblem mot ett kundproblem. Incidenten SPARAS (O6: tillståndet
        är sanningen, mejlet ett kvitto), mejlet står som "failed" - aldrig
        som skickat - och nästa körning försöker igen."""
        self.send.side_effect = RuntimeError("SMTP nere")
        resultat = self._kör([_entry("ICA", "failed")], now=1_000.0)
        self.assertEqual(resultat["incidents"], ["chain:ICA:failed"])
        post = alerts.open_incidents(self.kv)["chain:ICA:failed"]
        self.assertEqual(post["mail"]["status"], "failed")
        self.assertIsNone(post.get("lastSent"), "ett misslyckat försök får inte räknas som skickat")
        # Nästa körning, med fungerande SMTP: larmet går ut nu, ingen cooldown
        # hindrar det, och incidenten är fortfarande EN.
        self.send.side_effect = lambda cfg, to, subject, body, *a, **k: self.skickade.append((to, subject, body))
        self._kör([_entry("ICA", "failed")], now=1_000.0 + 3600)
        self.assertEqual(len(self.skickade), 1)
        self.assertEqual(alerts.open_incidents(self.kv)["chain:ICA:failed"]["mail"]["status"], "sent")
        self.assertEqual(len(alerts.open_incidents(self.kv)), 1)

    def test_without_a_recipient_the_incident_is_still_tracked(self):
        """O5: incidenten ska synas i kontrollrummet även utan e-post. Mejlet
        står som pending - inte som skickat, inte som misslyckat."""
        alerts.process([_entry("ICA", "failed")], self.kv, MAIL, now=1_000.0, to_email="")
        post = alerts.open_incidents(self.kv)["chain:ICA:failed"]
        self.assertEqual(post["mail"]["status"], "pending")
        self.assertEqual(post["openedAt"], 1_000.0)
        self.assertEqual(self.skickade, [])

    def test_recovery_writes_history_with_duration_even_if_the_receipt_fails(self):
        """O6: återställd är återställd. Signalen är borta, alltså stängs
        incidenten - och historiken får start, recovery, duration och
        mejlens öde. Ett misslyckat kvitto håller inte incidenten öppen."""
        self._kör([_entry("ICA", "failed")], now=1_000.0)
        self.send.side_effect = RuntimeError("SMTP nere vid recovery")
        resultat = self._kör([_entry("ICA", "healthy")], now=1_000.0 + 5400)
        self.assertEqual(resultat["recoveries"], ["chain:ICA:failed"])
        self.assertEqual(alerts.open_incidents(self.kv), {})
        hist = alerts.history(self.kv)
        self.assertEqual(len(hist), 1)
        rad = hist[0]
        self.assertEqual((rad["openedAt"], rad["recoveredAt"], rad["durationSeconds"]), (1_000.0, 6_400.0, 5400))
        self.assertEqual(rad["mail"], {"opened": "sent", "recovered": "failed"})
        self.assertEqual(rad["chain"], "ICA")

    def test_history_is_capped(self):
        for i in range(alerts.HISTORY_LIMIT + 7):
            t = 10_000.0 + i * 20_000
            self._kör([_entry("ICA", "failed")], now=t)
            self._kör([_entry("ICA", "healthy")], now=t + 3600)
        hist = alerts.history(self.kv)
        self.assertEqual(len(hist), alerts.HISTORY_LIMIT)
        # Nyast först.
        self.assertGreater(hist[0]["openedAt"], hist[-1]["openedAt"])

    def test_a_legacy_record_without_mail_field_still_recovers(self):
        """Poster skrivna före O6 hade bara openedAt/lastSent/severity."""
        self.kv.set(alerts.NAMESPACE, "chain:ICA:failed",
                    {"openedAt": 500.0, "lastSent": 500.0, "severity": "critical"})
        resultat = self._kör([_entry("ICA", "healthy")], now=4_100.0)
        self.assertEqual(resultat["recoveries"], ["chain:ICA:failed"])
        rad = alerts.history(self.kv)[0]
        self.assertEqual(rad["durationSeconds"], 3600)
        self.assertEqual(rad["mail"]["opened"], "sent")

    def test_overview_says_what_is_wrong_who_is_affected_and_what_to_do(self):
        """O5: tre frågor per incident. Kundpåverkan härleds ur släppt +
        ålder mot serveringsregeln, aldrig påstådd utan underlag."""
        from services.grocery.pricing import MAX_STORE_PRICE_AGE_SECONDS
        gräns_h = MAX_STORE_PRICE_AGE_SECONDS / 3600
        panel = [
            _entry("ICA", "failed", reason="429"),                    # inte släppt
            _entry("Willys", "failed", reason="timeout", age=10),     # släppt, färskt
            _entry("Hemköp", "failed", reason="timeout", age=gräns_h + 30),   # släppt, för gammalt
            _entry("City Gross", "failed", reason="timeout"),          # släppt, ålder saknas
        ]
        for e, släppt in zip(panel, (False, True, True, True)):
            e["health"]["released"] = släppt
        self._kör(panel, now=1_000.0)
        vy = alerts.overview(self.kv, panel, now=1_000.0 + 7200)
        per = {a["chain"]: a for a in vy["active"]}
        self.assertEqual(len(per), 4)
        self.assertIn("inte släppt", per["ICA"]["paverkasKunder"])
        self.assertIn("inom serveringsregeln", per["Willys"]["paverkasKunder"])
        self.assertIn("KUNDPÅVERKAN", per["Hemköp"]["paverkasKunder"])
        self.assertIn("okänd", per["City Gross"]["paverkasKunder"])
        for a in vy["active"]:
            self.assertTrue(a["vadArFel"] and a["vadGora"], a)
            self.assertEqual(a["ageHours"], 2.0)
        self.assertEqual(vy["history"], [])

    def test_limited_never_becomes_an_incident_in_the_overview(self):
        self._kör([_entry("Lidl", "limited", reason="inga per-produktpriser")], now=1_000.0)
        self.assertEqual(alerts.overview(self.kv, [], now=1_000.0)["active"], [])

    def test_no_secrets_in_the_mail_body(self):
        panel = [_entry("ICA", "failed", reason="401 from https://primat.nu/api/v3?key=hemlig")]
        self._kör(panel, now=1_000.0)
        self.assertNotIn("hemlig", self.skickade[0][2])

    def test_incident_state_survives_a_restart(self):
        """Tillståndet ligger i databasen, inte i minnet: en deploy mitt i en
        incident får inte återställa räknaren och skicka om larmet."""
        panel = [_entry("ICA", "failed")]
        self._kör(panel, now=1_000.0)
        self.prices.close()
        prices = PriceCacheStore(Path(self._tmp.name) / "prices.db")
        self.addCleanup(prices.close)
        kv = KeyValueCacheStore(prices.connection, prices.lock)
        self.skickade.clear()
        resultat = alerts.process(panel, kv, MAIL, now=1_000.0 + 3600,
                                  to_email="adam@example.test")
        self.assertEqual(resultat["suppressed"], ["chain:ICA:failed"])
        self.assertEqual(self.skickade, [])


if __name__ == "__main__":
    unittest.main()


class HealthAdminAlertsTest(unittest.TestCase):
    """health.adminAlerts ska svara på "går larmen att skicka, och vart?"
    utan att lägga en e-postadress i ett publikt svar."""

    def test_recipient_and_transport_are_separate_signals(self):
        """Ett enda "larm: ja" hade dolt två olika fel: transport utan
        mottagare (tysta larm) och mottagare utan SMTP (når ingen)."""
        import api_server
        with mock.patch.dict(os.environ, {"MATJAKT_ADMIN_EMAIL": "adam@example.test"}):
            self.assertTrue(alerts.admin_email())
            self.assertEqual(api_server._admin_alert_domain(), "example.test")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MATJAKT_ADMIN_EMAIL", None)
            self.assertFalse(alerts.admin_email())
            self.assertIsNone(api_server._admin_alert_domain())

    def test_the_address_itself_is_never_exposed(self):
        import api_server
        with mock.patch.dict(os.environ, {"MATJAKT_ADMIN_EMAIL": "hemlig.adress@example.test"}):
            domän = api_server._admin_alert_domain()
        self.assertEqual(domän, "example.test")
        self.assertNotIn("hemlig.adress", str(domän))

    def test_a_capitalised_address_still_resolves(self):
        """Adressen skrivs som den skrivs i dashboarden; versaler får inte
        göra att larmen tyst slutar fungera."""
        with mock.patch.dict(os.environ, {"MATJAKT_ADMIN_EMAIL": "Adamfrom@icloud.com"}):
            import api_server
            self.assertTrue(alerts.admin_email())
            self.assertEqual(api_server._admin_alert_domain(), "icloud.com")
