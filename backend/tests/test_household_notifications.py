# -*- coding: utf-8 -*-
"""Notislagret: rätt person, rätt mängd, rätt konto.

De tre reglerna som skiljer en användbar notis från spam testas här - aldrig
sin egen ändring, gruppering i stället för tio pushar, och att användarens
avstängning faktiskt stoppar raden. Plus säkerhetsdelen: en enhet som byter
konto får inte fortsätta ta emot det gamla kontots hushållsnotiser.
"""

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.household.notifications import (  # noqa: E402
    NotificationStore, PREF_ALL, PREF_INVENTORY, PREF_SHOPPING, PREFERENCES, _device_key,
)


class NotificationTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.notifications = NotificationStore(Path(self._tmp.name) / "notify.db")
        self.addCleanup(self.notifications.close)
        self.adam, self.sara = 1, 2

    def _publish(self, event_type="household.shopping_item_added", actor=None, subject="Mjölk", **kwargs):
        return self.notifications.publish(
            event_type=event_type, household_id=7,
            actor_user_id=self.adam if actor is None else actor,
            recipient_ids=[self.adam, self.sara], actor_name="Adam", subject=subject, **kwargs)

    def _flush(self):
        """Låtsas att debounce-fönstret passerat."""
        self.notifications._connection.execute(
            "UPDATE notification_outbox SET send_after = '2000-01-01T00:00:00+00:00'")
        self.notifications._connection.commit()


class RecipientTest(NotificationTestCase):
    def test_the_actor_never_hears_about_their_own_change(self):
        self.assertEqual(self._publish(), 1)
        self._flush()
        self.assertEqual(self.notifications.due(self.adam), [])
        self.assertEqual(len(self.notifications.due(self.sara)), 1)

    def test_the_text_names_who_did_what(self):
        self._publish()
        self._flush()
        notice = self.notifications.due(self.sara)[0]
        self.assertEqual(notice["title"], "Inköpslistan")
        self.assertEqual(notice["body"], "Adam lade till Mjölk i inköpslistan.")
        self.assertEqual(notice["deeplink"], "/handla")

    def test_unknown_event_types_are_dropped_rather_than_guessed_at(self):
        self.assertEqual(self.notifications.publish(
            event_type="household.something_new", household_id=7, actor_user_id=self.adam,
            recipient_ids=[self.sara]), 0)

    def test_deeplinks_point_at_the_right_screen(self):
        self._publish(event_type="household.inventory_changed", subject="Ris")
        self._publish(event_type="household.week_ready", subject="Familjen From", actor=None)
        self._flush()
        links = {notice["kind"]: notice["deeplink"] for notice in self.notifications.due(self.sara)}
        self.assertEqual(links["household.inventory_changed"], "/skafferi")
        self.assertEqual(links["household.week_ready"], "/vecka")


class BatchingTest(NotificationTestCase):
    def test_ten_items_in_twenty_seconds_become_one_notice(self):
        for index in range(10):
            self._publish(subject=f"Vara {index}")
        self._flush()
        due = self.notifications.due(self.sara)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["body"], "Adam lade till 10 varor i inköpslistan.")
        self.assertEqual(due[0]["count"], 10)

    def test_a_single_item_keeps_its_name(self):
        self._publish(subject="Kaffe")
        self._flush()
        self.assertEqual(self.notifications.due(self.sara)[0]["body"],
                         "Adam lade till Kaffe i inköpslistan.")

    def test_grouping_does_not_merge_different_kinds(self):
        self._publish(event_type="household.shopping_item_added", subject="Mjölk")
        self._publish(event_type="household.shopping_item_purchased", subject="Kaffe")
        self._flush()
        self.assertEqual(len(self.notifications.due(self.sara)), 2)

    def test_grouping_does_not_merge_different_people(self):
        self.notifications.publish(event_type="household.shopping_item_added", household_id=7,
                                   actor_user_id=self.adam, recipient_ids=[self.sara],
                                   actor_name="Adam", subject="Mjölk")
        self.notifications.publish(event_type="household.shopping_item_added", household_id=7,
                                   actor_user_id=3, recipient_ids=[self.sara],
                                   actor_name="Ella", subject="Bröd")
        self._flush()
        bodies = sorted(notice["body"] for notice in self.notifications.due(self.sara))
        self.assertEqual(bodies, ["Adam lade till Mjölk i inköpslistan.",
                                  "Ella lade till Bröd i inköpslistan."])

    def test_nothing_is_delivered_before_the_window_closes(self):
        self._publish()
        self.assertEqual(self.notifications.due(self.sara), [])
        self.assertEqual(self.notifications.pending_count(self.sara), 1)

    def test_a_week_being_ready_is_delivered_immediately(self):
        """Grupperbara händelser väntar; "veckan är klar" gör det inte - den
        kommer en gång och ska inte fördröjas."""
        self.notifications.publish(event_type="household.week_ready", household_id=7,
                                   actor_user_id=None, recipient_ids=[self.adam, self.sara],
                                   subject="Familjen From",
                                   extra={"summary": "5 middagar · 3 favoriter · beräknat 742 kr"})
        due = self.notifications.due(self.sara)
        self.assertEqual(len(due), 1)
        self.assertIn("742 kr", due[0]["body"])

    def test_delivered_notices_are_not_delivered_twice(self):
        self._publish()
        self._flush()
        self.assertEqual(len(self.notifications.due(self.sara)), 1)
        self.assertEqual(self.notifications.due(self.sara), [])


class PreferenceTest(NotificationTestCase):
    def test_everything_is_on_by_default(self):
        prefs = self.notifications.preferences(self.sara)
        self.assertTrue(all(prefs[name] for name in PREFERENCES))
        self.assertTrue(prefs[PREF_ALL])

    def test_turning_a_category_off_stops_it(self):
        self.notifications.set_preferences(self.sara, {PREF_SHOPPING: False})
        self.assertEqual(self._publish(), 0)
        self._publish(event_type="household.inventory_changed", subject="Ris")
        self._flush()
        kinds = [notice["kind"] for notice in self.notifications.due(self.sara)]
        self.assertEqual(kinds, ["household.inventory_changed"])

    def test_the_main_switch_stops_everything(self):
        self.notifications.set_preferences(self.sara, {PREF_ALL: False})
        self._publish()
        self._publish(event_type="household.week_ready", subject="Familjen From", actor=None)
        self._flush()
        self.assertEqual(self.notifications.due(self.sara), [])

    def test_preferences_are_per_user(self):
        self.notifications.set_preferences(self.sara, {PREF_INVENTORY: False})
        self.assertTrue(self.notifications.preferences(self.adam)[PREF_INVENTORY])

    def test_unknown_preference_names_are_ignored(self):
        prefs = self.notifications.set_preferences(self.sara, {"allt_om_allt": False})
        self.assertNotIn("allt_om_allt", prefs)


class DeviceTest(NotificationTestCase):
    def test_device_tokens_are_stored_hashed(self):
        token = "expo-push-token-" + "a" * 24
        self.notifications.register_device(self.adam, token)
        rows = self.notifications._connection.execute("SELECT token_hash FROM push_devices").fetchall()
        self.assertNotIn(token, [row["token_hash"] for row in rows])
        self.assertEqual(rows[0]["token_hash"], _device_key(token))

    def test_logging_out_forgets_the_device(self):
        token = "expo-push-token-" + "b" * 24
        self.notifications.register_device(self.adam, token)
        self.notifications.forget_device(token)
        self.assertEqual(self.notifications.devices_for(self.adam), [])

    def test_a_new_account_on_the_same_phone_takes_over_the_device(self):
        """Annars fortsatte Adams hushållsnotiser till telefonen efter att
        Sara loggat in på den."""
        token = "expo-push-token-" + "c" * 24
        self.notifications.register_device(self.adam, token)
        self.notifications.register_device(self.sara, token)
        self.assertEqual(self.notifications.devices_for(self.adam), [])
        self.assertEqual(len(self.notifications.devices_for(self.sara)), 1)

    def test_a_short_token_is_refused(self):
        with self.assertRaises(ValueError):
            self.notifications.register_device(self.adam, "kort")

    def test_leaving_a_household_drops_its_queued_notices(self):
        self._publish()
        self.notifications.forget_household(self.sara, 7)
        self._flush()
        self.assertEqual(self.notifications.due(self.sara), [])

    def test_forget_user_removes_devices_prefs_and_queue(self):
        self.notifications.register_device(self.sara, "expo-push-token-" + "d" * 24)
        self.notifications.set_preferences(self.sara, {PREF_SHOPPING: False})
        self._publish(event_type="household.inventory_changed")
        self.notifications.forget_user(self.sara)
        self.assertEqual(self.notifications.devices_for(self.sara), [])
        self.assertEqual(self.notifications.pending_count(self.sara), 0)
        self.assertTrue(self.notifications.preferences(self.sara)[PREF_SHOPPING])

    def test_the_queue_is_capped_per_user(self):
        from services.household.notifications import MAX_OUTBOX_PER_USER
        for index in range(MAX_OUTBOX_PER_USER + 20):
            self.notifications.publish(
                event_type="household.week_ready", household_id=7, actor_user_id=None,
                recipient_ids=[self.sara], subject=f"Vecka {index}")
        self.assertLessEqual(self.notifications.pending_count(self.sara), MAX_OUTBOX_PER_USER)


class DebounceWindowTest(NotificationTestCase):
    def test_the_window_is_pushed_forward_by_new_activity(self):
        self._publish(subject="Mjölk")
        first = self.notifications._connection.execute(
            "SELECT send_after FROM notification_outbox").fetchone()["send_after"]
        self._publish(subject="Kaffe")
        second = self.notifications._connection.execute(
            "SELECT send_after FROM notification_outbox").fetchone()["send_after"]
        self.assertGreaterEqual(second, first)

    def test_the_window_is_about_twenty_seconds(self):
        from services.household.notifications import DEBOUNCE_SECONDS
        self._publish()
        send_after = datetime.fromisoformat(self.notifications._connection.execute(
            "SELECT send_after FROM notification_outbox").fetchone()["send_after"])
        gap = send_after - datetime.now(timezone.utc)
        self.assertLessEqual(gap, timedelta(seconds=DEBOUNCE_SECONDS + 2))
        self.assertGreater(gap, timedelta(seconds=DEBOUNCE_SECONDS - 5))


if __name__ == "__main__":
    unittest.main()
