# -*- coding: utf-8 -*-
"""Hushållsvägarna över riktig HTTP, med riktiga sessioner.

Tyngdpunkten är scenariot i §34: Adam skapar hushåll, bjuder in Sara, båda
ser samma vecka och samma lista, "Har hemma" flyttar mjölken till kylen hos
båda, ångra tar tillbaka den - och ingen utanför familjen kommer åt något av
det, oavsett vilket id de skickar med.
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


class HouseholdApiTest(unittest.TestCase):
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

    # ---- HTTP-hjälpare ---------------------------------------------------

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

    def _user(self, name):
        email = f"{name}-{uuid.uuid4().hex[:8]}@example.com"
        status, payload = self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
        self.assertEqual(status, 201, payload)
        return payload["token"], email

    def _family(self):
        adam, _ = self._user("adam")
        sara, _ = self._user("sara")
        status, payload = self.post("/api/household/create", {"name": "Familjen From"}, adam)
        self.assertEqual(status, 201, payload)
        status, invite = self.post("/api/household/invite", {}, adam)
        self.assertEqual(status, 200, invite)
        status, joined = self.post("/api/household/join", {"token": invite["token"]}, sara)
        self.assertEqual(status, 200, joined)
        return adam, sara, payload["household"]["id"], invite


class HouseholdLifecycleTest(HouseholdApiTest):
    def test_a_fresh_account_has_no_household(self):
        token, _ = self._user("ensam")
        status, payload = self.get("/api/household", token)
        self.assertEqual(status, 200)
        self.assertIsNone(payload["household"])

    def test_creating_a_household_names_you_admin_with_a_display_name(self):
        token, email = self._user("adam")
        status, payload = self.post("/api/household/create", {"name": "Familjen From"}, token)
        self.assertEqual(status, 201)
        household = payload["household"]
        self.assertEqual(household["name"], "Familjen From")
        self.assertEqual(household["role"], "admin")
        member = household["members"][0]
        self.assertTrue(member["isMe"])
        self.assertEqual(member["email"], email)
        # Visningsnamnet gissas ur e-posten så ingen behöver skriva in det.
        self.assertEqual(member["displayName"], email.split("@")[0][:24].capitalize())

    def test_household_endpoints_need_a_session(self):
        status, payload = self.get("/api/household")
        self.assertEqual(status, 401)
        status, payload = self.post("/api/household/create", {"name": "Kapad"})
        self.assertEqual(status, 401)

    def test_without_a_household_the_shared_paths_answer_no_household(self):
        token, _ = self._user("ensam")
        status, payload = self.get("/api/household/sync", token)
        self.assertEqual(status, 404)
        self.assertEqual(payload["code"], "NO_HOUSEHOLD")

    def test_invite_share_text_is_ready_to_send(self):
        adam, sara, household_id, invite = self._family()
        self.assertIn("Familjen From", invite["shareText"])
        self.assertIn(invite["token"], invite["url"])
        self.assertIn("?invite=", invite["url"])

    def test_invite_preview_works_before_login(self):
        adam, _, _, invite = self._family()
        status, invite2 = self.post("/api/household/invite", {}, adam)
        status, preview = self.get(f"/api/household/invite?token={invite2['token']}")
        self.assertEqual(status, 200)
        self.assertEqual(preview["householdName"], "Familjen From")
        self.assertNotIn("members", preview)

    def test_a_used_invite_previews_as_gone(self):
        adam, sara, household_id, invite = self._family()
        status, payload = self.get(f"/api/household/invite?token={invite['token']}")
        self.assertEqual(status, 410)
        self.assertEqual(payload["code"], "INVITE_INVALID")

    def test_a_guessed_invite_token_reveals_nothing(self):
        self._family()
        status, payload = self.get("/api/household/invite?token=" + "z" * 32)
        self.assertEqual(status, 410)

    def test_leaving_returns_you_to_no_household(self):
        adam, sara, household_id, _ = self._family()
        status, payload = self.post("/api/household/leave", {}, sara)
        self.assertEqual(status, 200)
        self.assertIsNone(payload["household"])
        self.assertEqual(self.get("/api/household", sara)[1]["household"], None)
        self.assertEqual(self.get("/api/household", adam)[1]["household"]["name"], "Familjen From")

    def test_admin_removes_a_member(self):
        adam, sara, household_id, _ = self._family()
        sara_id = next(m["userId"] for m in self.get("/api/household", adam)[1]["household"]["members"]
                       if not m["isMe"])
        status, payload = self.post("/api/household/remove-member", {"userId": sara_id}, adam)
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["household"]["members"]), 1)
        self.assertEqual(self.get("/api/household/sync", sara)[0], 404)

    def test_member_cannot_remove_the_admin(self):
        adam, sara, household_id, _ = self._family()
        adam_id = next(m["userId"] for m in self.get("/api/household", sara)[1]["household"]["members"]
                       if not m["isMe"])
        status, payload = self.post("/api/household/remove-member", {"userId": adam_id}, sara)
        self.assertEqual(status, 400)
        self.assertEqual(len(self.get("/api/household", adam)[1]["household"]["members"]), 2)

    def test_profiles_are_personal_inside_the_shared_household(self):
        adam, sara, household_id, _ = self._family()
        self.post("/api/household/profile",
                  {"displayName": "Adam", "profile": {"spice": "stark"}}, adam)
        self.post("/api/household/profile",
                  {"displayName": "Sara", "profile": {"diet": "vegetarisk", "allergies": ["Nötter"]}}, sara)
        members = {m["displayName"]: m for m in self.get("/api/household", adam)[1]["household"]["members"]}
        self.assertEqual(members["Adam"]["profile"], {"spice": "stark"})
        self.assertEqual(members["Sara"]["profile"]["allergies"], ["Nötter"])

    def test_deleting_an_account_leaves_the_family_intact(self):
        adam, sara, household_id, _ = self._family()
        self.post("/api/household/shopping/item", {"name": "Kaffe", "source": "manual"}, sara)
        status, _ = self.post("/api/auth/delete-account", {}, sara)
        self.assertEqual(status, 200)
        household = self.get("/api/household", adam)[1]["household"]
        self.assertEqual(len(household["members"]), 1)
        items = self.get("/api/household/sync", adam)[1]["shopping"]
        self.assertEqual([item["name"] for item in items], ["Kaffe"])


class SharedShoppingTest(HouseholdApiTest):
    """§34, hela resan - i den ordning kravet beskriver den."""

    def test_the_whole_family_scenario(self):
        adam, sara, household_id, _ = self._family()

        # ... båda ser samma vecka
        self.post("/api/household/doc",
                  {"doc": "week", "body": {"weekPlan": ["tacos", "kottfarssas"]}}, adam)
        saras_week = self.get("/api/household/sync", sara)[1]["docs"]["week"]["body"]
        self.assertEqual(saras_week["weekPlan"], ["tacos", "kottfarssas"])

        # Adam lägger mjölk i Handla -> Sara ser mjölken
        status, added = self.post("/api/household/shopping/item", {
            "name": "Mjölk", "amount": 1, "unit": "l", "source": "manual",
            "product": {"productName": "Arla Mellanmjölk", "brand": "Arla",
                        "packageSize": "1,5 l", "gtin": "7310865004703"},
        }, adam)
        self.assertEqual(status, 200)
        key = added["item"]["key"]
        saras_view = self.get("/api/household/sync", sara)[1]["shopping"]
        self.assertEqual([item["name"] for item in saras_view], ["Mjölk"])
        self.assertEqual(saras_view[0]["status"], "NEED_TO_BUY")

        # Sara väljer Har hemma -> mjölken lämnar behovet och hamnar i kylen
        status, at_home = self.post("/api/household/shopping/at-home",
                                    {"key": key, "location": "kyl"}, sara)
        self.assertEqual(status, 200)
        self.assertEqual(at_home["item"]["status"], "ALREADY_HAVE")
        self.assertEqual(at_home["inventory"]["location"], "kyl")
        self.assertEqual(at_home["inventory"]["product"]["brand"], "Arla")

        # Adam ser samma förändring
        adams_view = self.get("/api/household/sync", adam)[1]
        self.assertEqual(adams_view["shopping"][0]["status"], "ALREADY_HAVE")
        fridge = [item for item in adams_view["inventory"] if item["location"] == "kyl"]
        self.assertEqual([item["name"] for item in fridge], ["Arla Mellanmjölk"])

        # Sara lägger tillbaka den som Behöver köpa
        status, back = self.post("/api/household/shopping/status",
                                 {"key": key, "status": "NEED_TO_BUY"}, sara)
        self.assertEqual(status, 200)
        self.assertEqual(back["item"]["status"], "NEED_TO_BUY")
        self.assertEqual(self.get("/api/household/sync", adam)[1]["shopping"][0]["status"], "NEED_TO_BUY")

        # ... och ingen utomstående kan läsa Familjen From
        outsider, _ = self._user("inkraktare")
        self.assertEqual(self.get("/api/household/sync", outsider)[0], 404)
        self.assertEqual(self.get("/api/household", outsider)[1]["household"], None)

    def test_undo_puts_everything_back(self):
        adam, sara, household_id, _ = self._family()
        added = self.post("/api/household/shopping/item",
                          {"name": "Ketchup", "source": "manual"}, adam)[1]["item"]
        at_home = self.post("/api/household/shopping/at-home", {"key": added["key"]}, sara)[1]
        self.assertEqual(at_home["undo"]["status"], "NEED_TO_BUY")
        self.assertEqual(at_home["undo"]["inventoryKey"], added["key"])

        status, undone = self.post("/api/household/shopping/undo", at_home["undo"], sara)
        self.assertEqual(status, 200)
        self.assertEqual(undone["item"]["status"], "NEED_TO_BUY")
        pantry = [item for item in self.get("/api/household/sync", adam)[1]["inventory"]
                  if not item["deleted"]]
        self.assertEqual(pantry, [])

    def test_undo_does_not_delete_something_that_was_already_at_home(self):
        """Ketchupen stod redan i skafferiet. En ångrad felklickning i Handla
        får inte ta bort familjens riktiga ketchup."""
        adam, sara, household_id, _ = self._family()
        self.post("/api/household/inventory/item",
                  {"name": "Ketchup", "amount": 1, "location": "kyl"}, adam)
        added = self.post("/api/household/shopping/item",
                          {"name": "Ketchup", "source": "manual"}, adam)[1]["item"]
        at_home = self.post("/api/household/shopping/at-home", {"key": added["key"]}, sara)[1]
        self.assertIsNone(at_home["undo"]["inventoryKey"])
        self.post("/api/household/shopping/undo", at_home["undo"], sara)
        pantry = [item for item in self.get("/api/household/sync", adam)[1]["inventory"]
                  if not item["deleted"]]
        self.assertEqual([item["name"] for item in pantry], ["Ketchup"])

    def test_purchased_is_not_the_same_as_already_have(self):
        adam, sara, household_id, _ = self._family()
        milk = self.post("/api/household/shopping/item",
                         {"name": "Mjölk", "source": "manual"}, adam)[1]["item"]
        ketchup = self.post("/api/household/shopping/item",
                            {"name": "Ketchup", "source": "manual"}, adam)[1]["item"]
        bought = self.post("/api/household/shopping/purchased",
                           {"key": milk["key"], "addToInventory": True, "location": "kyl"}, sara)[1]
        self.post("/api/household/shopping/at-home", {"key": ketchup["key"]}, sara)
        statuses = {item["name"]: item["status"]
                    for item in self.get("/api/household/sync", adam)[1]["shopping"]}
        self.assertEqual(statuses, {"Mjölk": "PURCHASED", "Ketchup": "ALREADY_HAVE"})
        self.assertEqual(bought["inventory"]["location"], "kyl")

    def test_purchased_without_asking_does_not_touch_the_pantry(self):
        adam, sara, household_id, _ = self._family()
        milk = self.post("/api/household/shopping/item",
                         {"name": "Mjölk", "source": "manual"}, adam)[1]["item"]
        self.post("/api/household/shopping/purchased", {"key": milk["key"]}, sara)
        self.assertEqual(self.get("/api/household/sync", adam)[1]["inventory"], [])

    def test_two_members_editing_at_once_both_survive(self):
        adam, sara, household_id, _ = self._family()
        milk = self.post("/api/household/shopping/item",
                         {"name": "Mjölk", "source": "manual"}, adam)[1]["item"]
        coffee = self.post("/api/household/shopping/item",
                           {"name": "Kaffe", "source": "manual"}, adam)[1]["item"]
        baseline = self.get("/api/household/sync", adam)[1]["revision"]
        self.post("/api/household/shopping/purchased", {"key": milk["key"]}, adam)
        self.post("/api/household/shopping/at-home", {"key": coffee["key"]}, sara)
        delta = self.get(f"/api/household/sync?since={baseline}", adam)[1]
        statuses = {item["name"]: item["status"] for item in delta["shopping"]}
        self.assertEqual(statuses, {"Mjölk": "PURCHASED", "Kaffe": "ALREADY_HAVE"})

    def test_every_sync_says_which_member_is_you(self):
        """Hittat i webbläsaren: en delta-sync skrev över den berikade
        medlemslistan med lagrets råa, klienten tappade isMe - och
        "Ta bort medlem" dök upp bredvid ens eget namn."""
        adam, sara, household_id, _ = self._family()
        for path in ("/api/household/sync", "/api/household/sync?since=1"):
            members = self.get(path, adam)[1]["members"]
            me = [member for member in members if member["isMe"]]
            self.assertEqual(len(me), 1, path)
            self.assertTrue(me[0]["email"], path)

    def test_sync_since_only_returns_the_difference(self):
        adam, sara, household_id, _ = self._family()
        first = self.get("/api/household/sync", sara)[1]
        self.assertIsNotNone(first["household"])
        nothing = self.get(f"/api/household/sync?since={first['revision']}", sara)[1]
        self.assertEqual(nothing["shopping"], [])
        self.assertIsNone(nothing["household"])
        self.post("/api/household/shopping/item", {"name": "Bröd", "source": "manual"}, adam)
        delta = self.get(f"/api/household/sync?since={first['revision']}", sara)[1]
        self.assertEqual([item["name"] for item in delta["shopping"]], ["Bröd"])

    def test_the_week_replaces_its_own_rows_but_not_the_manual_ones(self):
        adam, sara, household_id, _ = self._family()
        self.post("/api/household/shopping/week", {"items": [
            {"name": "Mjölk", "amount": 1, "unit": "l", "category": "Mejeri"},
            {"name": "Ris", "amount": 500, "unit": "g", "category": "Torrvaror"},
        ]}, adam)
        self.post("/api/household/shopping/item", {"name": "Toalettpapper", "source": "manual"}, sara)
        self.post("/api/household/shopping/week", {"items": [
            {"name": "Mjölk", "amount": 2, "unit": "l", "category": "Mejeri"},
        ]}, adam)
        names = sorted(item["name"] for item in self.get("/api/household/sync", sara)[1]["shopping"])
        self.assertEqual(names, ["Mjölk", "Toalettpapper"])

    def test_a_bad_week_payload_is_refused(self):
        adam, _, _, _ = self._family()
        status, payload = self.post("/api/household/shopping/week", {"items": "allt"}, adam)
        self.assertEqual(status, 400)


class PantryApiTest(HouseholdApiTest):
    def test_generic_and_specific_items_live_side_by_side(self):
        adam, sara, household_id, _ = self._family()
        self.post("/api/household/inventory/item",
                  {"name": "Lök", "amount": 3, "unit": "st", "location": "skafferi"}, adam)
        self.post("/api/household/inventory/item", {
            "name": "Arla Mellanmjölk", "amount": 1, "unit": "st", "location": "kyl",
            "gtin": "7310865004703",
            "product": {"productName": "Arla Mellanmjölk", "brand": "Arla", "packageSize": "1,5 l",
                        "imageUrl": "https://bilder.example/mjolk.jpg"},
        }, sara)
        inventory = {item["name"]: item for item in self.get("/api/household/sync", adam)[1]["inventory"]}
        self.assertIsNone(inventory["Lök"]["product"])
        self.assertEqual(inventory["Arla Mellanmjölk"]["product"]["imageUrl"],
                         "https://bilder.example/mjolk.jpg")

    def test_stepping_down_to_zero_removes_it_for_everyone(self):
        adam, sara, household_id, _ = self._family()
        item = self.post("/api/household/inventory/item",
                         {"name": "Ris", "amount": 1}, adam)[1]["item"]
        self.post("/api/household/inventory/adjust", {"key": item["key"], "delta": -1}, sara)
        inventory = self.get("/api/household/sync", adam)[1]["inventory"]
        self.assertTrue(inventory[0]["deleted"])

    def test_removing_an_item_is_visible_to_the_other_member(self):
        adam, sara, household_id, _ = self._family()
        item = self.post("/api/household/inventory/item",
                         {"name": "Ris", "amount": 2}, adam)[1]["item"]
        self.post("/api/household/inventory/remove", {"key": item["key"]}, sara)
        self.assertTrue(self.get("/api/household/sync", adam)[1]["inventory"][0]["deleted"])


class HorizontalEscalationApiTest(HouseholdApiTest):
    """§24 över HTTP: byt id i payloaden och se att ingenting händer."""

    def setUp(self):
        super().setUp()
        self.adam, self.sara, self.family_id, _ = self._family()
        self.outsider, _ = self._user("inkraktare")
        self.post("/api/household/create", {"name": "Familjen Annan"}, self.outsider)
        self.milk = self.post("/api/household/shopping/item",
                              {"name": "Mjölk", "source": "manual"}, self.adam)[1]["item"]
        self.rice = self.post("/api/household/inventory/item",
                              {"name": "Ris", "amount": 1}, self.adam)[1]["item"]

    def _family_state(self):
        payload = self.get("/api/household/sync", self.adam)[1]
        return ({item["name"]: item["status"] for item in payload["shopping"]},
                {item["name"]: item["deleted"] for item in payload["inventory"]})

    def test_an_outsider_reading_their_own_household_never_sees_ours(self):
        payload = self.get("/api/household/sync", self.outsider)[1]
        self.assertEqual(payload["shopping"], [])
        self.assertEqual(payload["inventory"], [])
        self.assertEqual(payload["household"]["name"], "Familjen Annan")

    def test_a_known_item_id_from_another_household_changes_nothing(self):
        """Radernas id är globala. Att kunna gissa ett id får inte räcka."""
        before = self._family_state()
        for path, payload in (
            ("/api/household/shopping/status", {"id": self.milk["id"], "status": "PURCHASED"}),
            ("/api/household/shopping/at-home", {"id": self.milk["id"]}),
            ("/api/household/shopping/purchased", {"id": self.milk["id"]}),
            ("/api/household/shopping/delete", {"id": self.milk["id"]}),
            ("/api/household/inventory/adjust", {"id": self.rice["id"], "delta": -5}),
            ("/api/household/inventory/remove", {"id": self.rice["id"]}),
        ):
            status, body = self.post(path, payload, self.outsider)
            self.assertIn(status, (400, 404), f"{path} svarade {status}: {body}")
        self.assertEqual(self._family_state(), before)

    def test_a_known_item_key_from_another_household_changes_nothing(self):
        before = self._family_state()
        for path, payload in (
            ("/api/household/shopping/status", {"key": self.milk["key"], "status": "PURCHASED"}),
            ("/api/household/shopping/at-home", {"key": self.milk["key"]}),
            ("/api/household/inventory/remove", {"key": self.rice["key"]}),
        ):
            status, body = self.post(path, payload, self.outsider)
            self.assertIn(status, (400, 404), f"{path} svarade {status}: {body}")
        self.assertEqual(self._family_state(), before)

    def test_an_outsider_cannot_write_into_our_household_docs(self):
        self.post("/api/household/doc", {"doc": "week", "body": {"weekPlan": ["kapad"]}}, self.outsider)
        week = self.get("/api/household/sync", self.adam)[1]["docs"].get("week")
        self.assertIsNone(week)

    def test_an_outsider_cannot_invite_themselves_or_remove_our_members(self):
        sara_id = next(m["userId"] for m in self.get("/api/household", self.adam)[1]["household"]["members"]
                       if not m["isMe"])
        status, _ = self.post("/api/household/remove-member", {"userId": sara_id}, self.outsider)
        self.assertEqual(status, 404)
        self.assertEqual(len(self.get("/api/household", self.adam)[1]["household"]["members"]), 2)

    def test_a_logged_out_token_reaches_nothing(self):
        self.post("/api/auth/logout", {}, self.sara)
        self.assertEqual(self.get("/api/household/sync", self.sara)[0], 401)
        self.assertEqual(self.post("/api/household/shopping/item",
                                   {"name": "Hack"}, self.sara)[0], 401)

    def test_a_removed_member_loses_access_immediately(self):
        sara_id = next(m["userId"] for m in self.get("/api/household", self.adam)[1]["household"]["members"]
                       if not m["isMe"])
        self.post("/api/household/remove-member", {"userId": sara_id}, self.adam)
        self.assertEqual(self.get("/api/household/sync", self.sara)[0], 404)
        self.assertEqual(self.post("/api/household/shopping/status",
                                   {"key": self.milk["key"], "status": "PURCHASED"}, self.sara)[0], 404)
        self.assertEqual(self._family_state()[0]["Mjölk"], "NEED_TO_BUY")

    def test_unknown_household_paths_are_404_not_500(self):
        status, _ = self.get("/api/household/hemligheter", self.adam)
        self.assertEqual(status, 404)
        status, _ = self.post("/api/household/hemligheter", {}, self.adam)
        self.assertEqual(status, 404)


class NotificationApiTest(HouseholdApiTest):
    def test_a_members_change_reaches_the_other_but_not_themselves(self):
        adam, sara, household_id, _ = self._family()
        self.post("/api/household/shopping/item", {"name": "Mjölk", "source": "manual"}, adam)
        api_server.NOTIFICATION_STORE._connection.execute(
            "UPDATE notification_outbox SET send_after = '2000-01-01T00:00:00+00:00'")
        api_server.NOTIFICATION_STORE._connection.commit()
        saras = self.get("/api/household/notifications", sara)[1]["notifications"]
        adams = self.get("/api/household/notifications", adam)[1]["notifications"]
        self.assertEqual([notice["kind"] for notice in saras], ["household.shopping_item_added"])
        self.assertIn("Mjölk", saras[0]["body"])
        # Adam får veta att Sara gick med (det gjorde HON), men inte ett ord
        # om mjölken han själv lade till.
        self.assertEqual([notice["kind"] for notice in adams], ["household.member_joined"])

    def test_preferences_round_trip(self):
        adam, sara, household_id, _ = self._family()
        status, payload = self.post("/api/household/notifications/prefs",
                                    {"preferences": {"shopping": False, "all": True}}, sara)
        self.assertEqual(status, 200)
        self.assertFalse(payload["preferences"]["shopping"])
        self.assertEqual(self.get("/api/household/notifications", sara)[1]["preferences"]["shopping"], False)

    def test_turning_shopping_off_stops_those_notices(self):
        adam, sara, household_id, _ = self._family()
        self.post("/api/household/notifications/prefs", {"preferences": {"shopping": False}}, sara)
        self.post("/api/household/shopping/item", {"name": "Mjölk", "source": "manual"}, adam)
        self.assertEqual(self.get("/api/household/notifications", sara)[1]["pending"], 0)

    def test_a_device_is_forgotten_at_logout(self):
        adam, sara, household_id, _ = self._family()
        token = "expo-push-token-" + "a" * 24
        self.assertEqual(self.post("/api/household/notifications/device",
                                   {"token": token, "platform": "ios"}, sara)[0], 200)
        self.assertEqual(len(api_server.NOTIFICATION_STORE.devices_for(
            api_server.ACCOUNT_STORE.identity_for_token(sara)[0])), 1)
        sara_id = api_server.ACCOUNT_STORE.identity_for_token(sara)[0]
        self.post("/api/auth/logout", {"deviceToken": token}, sara)
        self.assertEqual(api_server.NOTIFICATION_STORE.devices_for(sara_id), [])

    def test_a_short_device_token_is_refused(self):
        adam, _, _, _ = self._family()
        self.assertEqual(self.post("/api/household/notifications/device", {"token": "kort"}, adam)[0], 400)

    def test_leaving_the_household_drops_queued_notices(self):
        adam, sara, household_id, _ = self._family()
        self.post("/api/household/shopping/item", {"name": "Mjölk", "source": "manual"}, adam)
        self.post("/api/household/leave", {}, sara)
        self.assertEqual(self.get("/api/household/notifications", sara)[1]["pending"], 0)


if __name__ == "__main__":
    unittest.main()
