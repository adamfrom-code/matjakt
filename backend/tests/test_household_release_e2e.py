# -*- coding: utf-8 -*-
"""Hela hushållsloopen över HTTP, i den ordning den faktiskt sker.

Ett enda test som går hela vägen - skapa, bjuda in, gå med, vecka, handla,
köpa, ångra, har hemma, utomstående, borttagen medlem - plus notisreglerna
runt omkring. Det är avsiktligt EN lång berättelse i stället för tjugo små:
det som ska bevisas är att stegen håller ihop, inte att var och en fungerar
isolerat (det gör de andra testfilerna).

Körs mot en riktig ApiHandler med riktiga sessioner och tre riktiga konton.
"""

import http.client
import json
import sys
import tempfile
import threading
import unittest
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

import api_server  # noqa: E402
from services.accounts import AccountStore, ratelimit  # noqa: E402
from services.household import HouseholdStore, NotificationStore  # noqa: E402


class HouseholdReleaseE2ETest(unittest.TestCase):
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
        ratelimit.reset()
        self.addCleanup(ratelimit.reset)
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        path = Path(self._tmp.name) / "test.db"
        self._originals = (api_server.ACCOUNT_STORE, api_server.HOUSEHOLD_STORE,
                           api_server.NOTIFICATION_STORE)
        api_server.ACCOUNT_STORE = AccountStore(path)
        api_server.HOUSEHOLD_STORE = HouseholdStore(path)
        api_server.NOTIFICATION_STORE = NotificationStore(path)
        self.addCleanup(self._restore)

    def _restore(self):
        for store in (api_server.ACCOUNT_STORE, api_server.HOUSEHOLD_STORE,
                      api_server.NOTIFICATION_STORE):
            store.close()
        (api_server.ACCOUNT_STORE, api_server.HOUSEHOLD_STORE,
         api_server.NOTIFICATION_STORE) = self._originals

    # ---- HTTP -------------------------------------------------------------

    def _call(self, method, path, payload=None, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            headers = {}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            body = None
            if payload is not None:
                headers["Content-Type"] = "application/json"
                body = json.dumps(payload).encode("utf-8")
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
        finally:
            conn.close()

    def get(self, path, token=None):
        return self._call("GET", path, None, token)

    def post(self, path, payload=None, token=None):
        return self._call("POST", path, payload or {}, token)

    def _register(self, name):
        email = f"{name}-{uuid.uuid4().hex[:8]}@example.com"
        status, payload = self.post("/api/auth/register",
                                    {"email": email, "password": "hemligt123"})
        self.assertEqual(status, 201, payload)
        return payload["token"], email

    def _deliver_queued_notifications(self):
        """Hoppa över debounce-fönstret utan att sova 20 sekunder."""
        api_server.NOTIFICATION_STORE._connection.execute(
            "UPDATE notification_outbox SET send_after = '2000-01-01T00:00:00+00:00'")
        api_server.NOTIFICATION_STORE._connection.commit()

    def _notices(self, token):
        return self.get("/api/household/notifications", token)[1]["notifications"]

    # ---- hela resan -------------------------------------------------------

    def test_the_whole_release_loop(self):
        adam, adam_email = self._register("adam")
        sara, _ = self._register("sara")
        outsider, _ = self._register("utomstaende")

        # 1. Adam skapar hushåll
        status, created = self.post("/api/household/create", {"name": "Familjen From"}, adam)
        self.assertEqual(status, 201, created)
        self.assertEqual(created["household"]["role"], "admin")

        # 2. ...bjuder in Sara
        status, invite = self.post("/api/household/invite", {}, adam)
        self.assertEqual(status, 200)
        self.assertIn("Familjen From", invite["shareText"])

        # 3. Sara går med
        status, joined = self.post("/api/household/join", {"token": invite["token"]}, sara)
        self.assertEqual(status, 200, joined)
        self.assertEqual(len(joined["household"]["members"]), 2)
        # Inbjudan är engångs.
        self.assertEqual(self.post("/api/household/join", {"token": invite["token"]}, outsider)[0], 400)

        # 4. Veckan skapas och är gemensam
        self.post("/api/household/doc",
                  {"doc": "week", "body": {"weekPlan": ["tacos", "kottfarssas"]}}, adam)
        saras_week = self.get("/api/household/sync", sara)[1]["docs"]["week"]["body"]
        self.assertEqual(saras_week["weekPlan"], ["tacos", "kottfarssas"])

        # 5. Gemensam Handla: veckans varor ut i listan
        self.post("/api/household/shopping/week", {"items": [
            {"name": "Mjölk", "amount": 1, "unit": "l", "category": "Mejeri"},
            {"name": "Kaffe", "amount": 500, "unit": "g", "category": "Skafferi"},
            {"name": "Bröd", "amount": 1, "unit": "st", "category": "Bröd"},
            {"name": "Ketchup", "amount": 1, "unit": "st", "category": "Skafferi"},
        ]}, adam)
        rows = {row["name"]: row for row in self.get("/api/household/sync", sara)[1]["shopping"]}
        self.assertEqual(set(rows), {"Mjölk", "Kaffe", "Bröd", "Ketchup"})

        # 6. Sara markerar tre varor som köpta
        for name in ("Mjölk", "Kaffe", "Bröd"):
            status, bought = self.post("/api/household/shopping/purchased",
                                       {"key": rows[name]["key"], "addToInventory": True,
                                        "location": "kyl" if name == "Mjölk" else "skafferi"}, sara)
            self.assertEqual(status, 200, bought)
            self.assertEqual(bought["item"]["status"], "PURCHASED")

        # 7. Adam ser ändringen
        adams = self.get("/api/household/sync", adam)[1]
        statuses = {row["name"]: row["status"] for row in adams["shopping"]}
        self.assertEqual(statuses, {"Mjölk": "PURCHASED", "Kaffe": "PURCHASED",
                                    "Bröd": "PURCHASED", "Ketchup": "NEED_TO_BUY"})

        # 8. ...och varorna ligger rätt i Kyl respektive Skafferi
        inventory = {row["name"]: row["location"] for row in adams["inventory"] if not row["deleted"]}
        self.assertEqual(inventory, {"Mjölk": "kyl", "Kaffe": "skafferi", "Bröd": "skafferi"})

        # 9. Har hemma på ketchupen: ur behovet OCH in i skafferiet
        status, at_home = self.post("/api/household/shopping/at-home",
                                    {"key": rows["Ketchup"]["key"], "location": "kyl"}, adam)
        self.assertEqual(status, 200)
        self.assertEqual(at_home["item"]["status"], "ALREADY_HAVE")
        self.assertEqual(at_home["inventory"]["location"], "kyl")
        self.assertEqual(at_home["undo"]["status"], "NEED_TO_BUY")
        self.assertEqual(at_home["undo"]["inventoryKey"], rows["Ketchup"]["key"])

        # 10. Ångra: statusen tillbaka OCH skafferiraden som handlingen skapade bort
        status, undone = self.post("/api/household/shopping/undo", at_home["undo"], adam)
        self.assertEqual(status, 200)
        self.assertEqual(undone["item"]["status"], "NEED_TO_BUY")
        live = {row["name"] for row in self.get("/api/household/sync", sara)[1]["inventory"]
                if not row["deleted"]}
        self.assertEqual(live, {"Mjölk", "Kaffe", "Bröd"}, "ketchupen ska inte ligga kvar hemma")

        # 11. Utomstående nekas - läsning som skrivning, oavsett id
        self.assertEqual(self.get("/api/household/sync", outsider)[0], 404)
        self.assertEqual(self.get("/api/household", outsider)[1]["household"], None)
        for path, payload in (
            ("/api/household/shopping/status", {"key": rows["Mjölk"]["key"], "status": "NEED_TO_BUY"}),
            ("/api/household/shopping/at-home", {"id": rows["Mjölk"]["id"]}),
            ("/api/household/doc", {"doc": "week", "body": {"weekPlan": ["kapad"]}}),
        ):
            self.assertIn(self.post(path, payload, outsider)[0], (400, 404), path)
        self.assertEqual(
            self.get("/api/household/sync", adam)[1]["docs"]["week"]["body"]["weekPlan"],
            ["tacos", "kottfarssas"], "utomstående fick inte skriva i veckan")

        # 12. Borttagen medlem tappar åtkomst omedelbart
        sara_id = next(m["userId"] for m in self.get("/api/household", adam)[1]["household"]["members"]
                       if not m["isMe"])
        self.assertEqual(self.post("/api/household/remove-member", {"userId": sara_id}, adam)[0], 200)
        self.assertEqual(self.get("/api/household/sync", sara)[0], 404)
        self.assertEqual(self.post("/api/household/shopping/status",
                                   {"key": rows["Ketchup"]["key"], "status": "PURCHASED"}, sara)[0], 404)
        self.assertEqual(
            {row["name"]: row["status"] for row in self.get("/api/household/sync", adam)[1]["shopping"]}["Ketchup"],
            "NEED_TO_BUY", "den borttagnas skrivning fick inte gå igenom")


class NotificationReleaseTest(HouseholdReleaseE2ETest):
    """§5 i härdningen: eventlagret utan att slå på extern push."""

    def _family(self):
        adam, _ = self._register("adam")
        sara, _ = self._register("sara")
        self.post("/api/household/create", {"name": "Familjen From"}, adam)
        invite = self.post("/api/household/invite", {}, adam)[1]
        self.post("/api/household/join", {"token": invite["token"]}, sara)
        # Konsumera "Sara gick med"-notisen så testerna nedan mäter sitt eget.
        self._deliver_queued_notifications()
        self._notices(adam)
        return adam, sara

    def test_the_whole_release_loop(self):
        self.skipTest("täcks av HouseholdReleaseE2ETest")

    def test_your_own_change_never_notifies_you(self):
        adam, sara = self._family()
        self.post("/api/household/shopping/item", {"name": "Mjölk", "source": "manual"}, adam)
        self._deliver_queued_notifications()
        self.assertEqual(self._notices(adam), [])

    def test_the_other_member_gets_the_event(self):
        adam, sara = self._family()
        self.post("/api/household/shopping/item", {"name": "Mjölk", "source": "manual"}, adam)
        self._deliver_queued_notifications()
        notices = self._notices(sara)
        self.assertEqual([n["kind"] for n in notices], ["household.shopping_item_added"])
        self.assertIn("Mjölk", notices[0]["body"])
        self.assertEqual(notices[0]["deeplink"], "/handla")

    def test_ten_quick_changes_become_one_notice(self):
        adam, sara = self._family()
        for index in range(10):
            self.post("/api/household/shopping/item",
                      {"name": f"Vara {index}", "source": "manual"}, adam)
        self.assertEqual(self.get("/api/household/notifications", sara)[1]["pending"], 1)
        self._deliver_queued_notifications()
        notices = self._notices(sara)
        self.assertEqual(len(notices), 1)
        self.assertIn("10 varor", notices[0]["body"])

    def test_a_device_token_forgotten_at_logout_gets_nothing(self):
        adam, sara = self._family()
        token = "expo-push-token-" + "a" * 24
        self.assertEqual(self.post("/api/household/notifications/device",
                                   {"token": token, "platform": "ios"}, sara)[0], 200)
        sara_id = api_server.ACCOUNT_STORE.identity_for_token(sara)[0]
        self.assertEqual(len(api_server.NOTIFICATION_STORE.devices_for(sara_id)), 1)
        self.post("/api/auth/logout", {"deviceToken": token}, sara)
        self.assertEqual(api_server.NOTIFICATION_STORE.devices_for(sara_id), [],
                         "gammal enhet får inte fortsätta ta emot hushållets notiser")

    def test_a_device_changing_owner_follows_the_new_account(self):
        """Samma telefon, nytt konto. Utan detta fortsatte det gamla kontots
        hushållsnotiser till en enhet som nu tillhör någon annan."""
        adam, sara = self._family()
        token = "expo-push-token-" + "b" * 24
        self.post("/api/household/notifications/device", {"token": token}, adam)
        self.post("/api/household/notifications/device", {"token": token}, sara)
        adam_id = api_server.ACCOUNT_STORE.identity_for_token(adam)[0]
        sara_id = api_server.ACCOUNT_STORE.identity_for_token(sara)[0]
        self.assertEqual(api_server.NOTIFICATION_STORE.devices_for(adam_id), [])
        self.assertEqual(len(api_server.NOTIFICATION_STORE.devices_for(sara_id)), 1)

    def test_leaving_the_household_clears_queued_notices(self):
        adam, sara = self._family()
        self.post("/api/household/shopping/item", {"name": "Mjölk", "source": "manual"}, adam)
        self.assertEqual(self.get("/api/household/notifications", sara)[1]["pending"], 1)
        self.post("/api/household/leave", {}, sara)
        self.assertEqual(self.get("/api/household/notifications", sara)[1]["pending"], 0)

    def test_being_removed_clears_queued_notices(self):
        adam, sara = self._family()
        self.post("/api/household/shopping/item", {"name": "Mjölk", "source": "manual"}, adam)
        sara_id = next(m["userId"] for m in self.get("/api/household", adam)[1]["household"]["members"]
                       if not m["isMe"])
        self.post("/api/household/remove-member", {"userId": sara_id}, adam)
        self.assertEqual(self.get("/api/household/notifications", sara)[1]["pending"], 0)

    def test_no_external_push_is_attempted(self):
        """Push är inte produktionsklart. Eventlagret ska fungera helt utan
        att någon extern tjänst kontaktas - spärren i data_guard skulle ha
        fällt testet om något försökte."""
        adam, sara = self._family()
        self.post("/api/household/shopping/item", {"name": "Mjölk", "source": "manual"}, adam)
        self._deliver_queued_notifications()
        self.assertEqual(len(self._notices(sara)), 1)


if __name__ == "__main__":
    unittest.main()
