# -*- coding: utf-8 -*-
"""Tester för driftlarmen.

Det intressanta är inte att ett mejl kan skickas - det är att det INTE
skickas för ofta. Ett larm som kommer varje natt slutar man läsa, och då är
det värdelöst precis när det behövs. Varje test nedan motsvarar ett sätt
larmen kan bli antingen tysta när de borde höras eller tjatiga när de borde
tiga.
"""

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
        """Om SMTP är nere får larmet försvinna - men körningen ska fortsätta,
        annars byter vi ut ett driftproblem mot ett kundproblem."""
        self.send.side_effect = RuntimeError("SMTP nere")
        resultat = self._kör([_entry("ICA", "failed")], now=1_000.0)
        self.assertEqual(resultat["incidents"], [])
        # Ingen incident sparad: nästa körning ska försöka igen, inte tro att
        # larmet redan gått ut.
        self.assertEqual(self.kv.keys(alerts.NAMESPACE), [])

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
