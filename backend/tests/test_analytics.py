"""Produktmätningen (services/analytics): händelser per dag och per konto,
och tratten per registreringsvecka som avgör om lanseringen fungerar."""

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.accounts import AccountStore
from services.analytics import ANALYTICS_EVENTS, AnalyticsStore


def _day(days_ago: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=days_ago)).isoformat()


class AnalyticsStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.accounts = AccountStore(Path(self._tmpdir.name) / "test.db")
        self.analytics = AnalyticsStore(self.accounts.connection, lock=self.accounts.lock)

    def tearDown(self):
        self.accounts.close()
        self._tmpdir.cleanup()

    def _user(self, email: str, created_days_ago: int) -> int:
        self.accounts.register(email, "hemligt123")
        user_id = self.accounts.connection.execute(
            "SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
        created = (datetime.now(timezone.utc) - timedelta(days=created_days_ago)).isoformat()
        self.accounts.connection.execute("UPDATE users SET created_at = ? WHERE id = ?", (created, user_id))
        self.accounts.connection.commit()
        return user_id

    def test_unknown_events_are_ignored_not_raised(self):
        self.assertFalse(self.analytics.record("nagot_pahittat", user_id=1))
        self.assertEqual(self.analytics.daily_events()["events"].get("nagot_pahittat"), None)

    def test_events_count_per_day_and_per_account_day(self):
        self.assertTrue(self.analytics.record("vecka_skapad"))
        self.assertTrue(self.analytics.record("vecka_skapad", user_id=7))
        self.assertTrue(self.analytics.record("vecka_skapad", user_id=7))
        events = self.analytics.daily_events()["events"]["vecka_skapad"]
        self.assertEqual(events["total"], 3)
        self.assertEqual(events["unikaKonton"], 1)
        self.assertEqual(events["perDag"][_day(0)], 3)
        self.assertEqual(len(self.analytics.daily_events()["dagar"]), 14)
        self.assertIn("vecka_skapad", ANALYTICS_EVENTS)

    def test_funnel_per_registration_week(self):
        # Anna: registrerad för 20 dagar sedan, skapade en vecka, kom tillbaka dag 10.
        anna = self._user("anna@example.com", 20)
        self.analytics.record("vecka_skapad", user_id=anna, day=_day(20))
        self.analytics.record("view_home", user_id=anna, day=_day(10))
        # Bertil: samma kohort, tittade bara, kom aldrig tillbaka.
        bertil = self._user("bertil@example.com", 20)
        self.analytics.record("view_home", user_id=bertil, day=_day(20))
        # Cilla: registrerad i går - hennes kohort kan inte vara mogen än.
        cilla = self._user("cilla@example.com", 1)
        self.analytics.record("vecka_skapad", user_id=cilla, day=_day(1))

        funnel = self.analytics.funnel(weeks=8)
        by_week = {cohort["vecka"]: cohort for cohort in funnel["kohorter"]}
        old_week = (datetime.now(timezone.utc).date() - timedelta(days=20)).isocalendar()
        old = by_week[f"{old_week[0]}-V{old_week[1]:02d}"]
        self.assertEqual(old["registrerade"], 2)
        self.assertEqual(old["skapadeVecka"], 1)
        self.assertEqual(old["tillbakaEfter7Dagar"], 1)
        self.assertTrue(old["mogen"])

        new_week = (datetime.now(timezone.utc).date() - timedelta(days=1)).isocalendar()
        new = by_week[f"{new_week[0]}-V{new_week[1]:02d}"]
        self.assertGreaterEqual(new["registrerade"], 1)
        self.assertFalse(new["mogen"])

        totals = funnel["totalt"]
        self.assertEqual(totals["registrerade"], 3)
        self.assertEqual(totals["aktivaSenaste7Dagarna"], 1)   # bara Cilla
        self.assertEqual(totals["aktivaSenaste28Dagarna"], 3)
        self.assertEqual(totals["premium"], 0)

    def test_last_active_day_counts_as_activity_even_without_events(self):
        """Ett konto som bara loggar in (inga händelser) syns ändå som
        aktivt, via last_active_day som sessionsuppslaget sätter."""
        token, _ = self.accounts.register("dag@example.com", "hemligt123")
        user_id = self.accounts.connection.execute(
            "SELECT id FROM users WHERE email = ?", ("dag@example.com",)).fetchone()[0]
        created = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        self.accounts.connection.execute("UPDATE users SET created_at = ? WHERE id = ?", (created, user_id))
        self.accounts.connection.commit()
        self.accounts.user_for_token(token)  # sätter last_active_day = i dag
        row = self.accounts.connection.execute("SELECT last_active_day FROM users WHERE id = ?", (user_id,)).fetchone()
        self.assertEqual(row[0], _day(0))
        funnel = self.analytics.funnel()
        self.assertEqual(funnel["totalt"]["aktivaSenaste7Dagarna"], 1)
        # Kohorten är 30 dagar gammal - utanför 8-veckorsfönstret? Nej, 30 dagar < 56.
        cohort = funnel["kohorter"][0]
        self.assertEqual(cohort["tillbakaEfter7Dagar"], 1)

    def test_premium_rule_is_the_account_services_rule(self):
        user_id = self._user("prem@example.com", 3)
        self.accounts.connection.execute("UPDATE users SET premium = 1 WHERE id = ?", (user_id,))
        self.accounts.connection.commit()
        funnel = self.analytics.funnel(premium_of=lambda row: AccountStore._to_public(row)["premium"])
        self.assertEqual(funnel["totalt"]["premium"], 1)
        self.assertEqual(funnel["kohorter"][0]["premium"], 1)

    def test_legacy_counters_are_imported_once_without_overwriting(self):
        legacy = {("view_premium", _day(1)): 5, ("vecka_skapad", _day(3)): 2}
        imported = self.analytics.import_legacy_counters(lambda event, day: legacy.get((event, day)))
        self.assertEqual(imported, 2)
        # Nya händelser efter flytten läggs ovanpå; en ny flytt skriver inte över.
        self.analytics.record("view_premium", day=_day(1))
        self.assertEqual(self.analytics.import_legacy_counters(lambda event, day: legacy.get((event, day))), 0)
        self.assertEqual(self.analytics.daily_events()["events"]["view_premium"]["perDag"][_day(1)], 6)

    def test_deleting_the_account_deletes_its_measurement_rows(self):
        token, _ = self.accounts.register("bort@example.com", "hemligt123")
        user_id = self.accounts.user_id_for_token(token)
        self.analytics.record("vecka_skapad", user_id=user_id)
        self.accounts.delete_account(token)
        left = self.accounts.connection.execute(
            "SELECT COUNT(*) FROM analytics_user_days WHERE user_id = ?", (user_id,)).fetchone()[0]
        self.assertEqual(left, 0)
        # De anonyma dagsräknarna är inte personuppgifter och står kvar.
        self.assertEqual(self.analytics.daily_events()["events"]["vecka_skapad"]["total"], 1)


if __name__ == "__main__":
    unittest.main()


class SharedConnectionUnderLoad(unittest.TestCase):
    """Analytics och kontolagret delar SQLite-anslutning. Utan gemensamt lås
    nollställde en commit() från mätningen ett pågående sessionsuppslag i en
    annan tråd - "401 Inte inloggad" på en giltig session, mitt i betalning.
    /api/analytics/event är öppen (300/min), så det var en angreppsyta."""

    def test_analytics_writes_do_not_break_a_concurrent_session_lookup(self):
        import threading
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        accounts = AccountStore(Path(tmp.name) / "shared.db")
        self.addCleanup(accounts.close)
        analytics = AnalyticsStore(accounts.connection, lock=accounts.lock)
        token, _ = accounts.register("last@example.com", "hemligt123")
        user_id = accounts.identity_for_token(token)[0]
        event = next(iter(ANALYTICS_EVENTS))
        misses, errors = [], []

        def writer():
            for _ in range(150):
                try:
                    analytics.record(event, user_id)
                except Exception as error:   # noqa: BLE001 - allt är ett fel här
                    errors.append(repr(error))

        def reader():
            for _ in range(150):
                try:
                    if accounts.user_for_token(token) is None:
                        misses.append(1)
                except Exception as error:   # noqa: BLE001
                    errors.append(repr(error))

        threads = [threading.Thread(target=writer) for _ in range(3)] + [threading.Thread(target=reader) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertEqual(errors, [])
        self.assertEqual(misses, [], f"{len(misses)} sessionsuppslag misslyckades under mätskrivningar")

