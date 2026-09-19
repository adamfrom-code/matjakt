# -*- coding: utf-8 -*-
"""J3: den nya paketeringen, prövad där den faktiskt avgörs.

Paketeringen flyttade gränsen åt båda hållen:

* NER till gratis: alla veckotyper, "Laga med det jag har", näringsfiltret
  och meal prep. De sätts ihop i klienten ur ett lokalt receptregister och
  gick aldrig att skydda - men de är precis det som gör en ny användare
  beroende de första två veckorna.
* UPP till Premium: hushåll bortom två personer, och sparhistoriken. Varje
  hushållsrad går via servern, så det är den enda funktionen i produkten
  som inte går att låsa upp från klienten.
* FREE_MAX_DINNERS 4 -> 5, och sju dagars Premium efter den FÖRSTA skapade
  veckan i stället för vid registrering.

ADAMS REGEL, OCH DEN HÄR FILENS VIKTIGASTE TEST

Att flytta upp hushållet är en beteendeändring för konton som redan finns.
Regeln är: **att bjuda in är den handling som möter betalväggen, medan
befintliga medlemmar aldrig kastas ut.**

`test_an_existing_free_household_keeps_every_member_and_is_only_stopped_at_the_invite`
är den regeln, skriven som ett gratishushåll med fem medlemmar: alla fem är
kvar, alla fem kan läsa och skriva, och den sjätte inbjudan möter 403 med
`locked`. Faller det testet har paketeringen börjat kasta ut folk.
"""

import http.client
import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
import re
import uuid
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

import api_server  # noqa: E402
from services.accounts import AccountStore, ratelimit  # noqa: E402
from services.accounts import features as plan_features  # noqa: E402
from services.billing import activation, savings  # noqa: E402
from services.billing import gate as paywall  # noqa: E402
from services.household import HouseholdStore, MAX_MEMBERS, NotificationStore  # noqa: E402


# En veckas varurader. /api/pricing/week kräver dem; recipeIds ensamt är
# inte en prissättningsbar vecka.
_ITEMS = [{"name": "mjölk", "amount": 1, "unit": "l"}]


def _fake_week(*args, **kwargs):
    return {"results": [{"chain": "Willys", "totalCheckoutCost": 400, "realPriceItems": 3,
                         "totalItems": 3, "comparable": True, "items": [], "missingItemNames": []}],
            "comparison": {"cheapestChain": "Willys", "savings": 80, "priciestTotal": 480}}


class PackagingTestCase(unittest.TestCase):
    """En riktig server, riktiga konton, riktiga hushåll."""

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
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        path = Path(self._tmpdir.name) / "j3.db"
        originals = (api_server.ACCOUNT_STORE, api_server.HOUSEHOLD_STORE,
                     api_server.NOTIFICATION_STORE, api_server.SAVINGS)
        api_server.ACCOUNT_STORE = AccountStore(path)
        api_server.HOUSEHOLD_STORE = HouseholdStore(path)
        api_server.NOTIFICATION_STORE = NotificationStore(path)
        api_server.SAVINGS = savings.SavingsStore(api_server.ACCOUNT_STORE.connection,
                                                  lock=api_server.ACCOUNT_STORE.lock)

        def restore():
            api_server.ACCOUNT_STORE.close()
            api_server.HOUSEHOLD_STORE.close()
            (api_server.ACCOUNT_STORE, api_server.HOUSEHOLD_STORE,
             api_server.NOTIFICATION_STORE, api_server.SAVINGS) = originals
        self.addCleanup(restore)

        for target, attribute, replacement in (
            (api_server.grocery_api, "price_week", _fake_week),
            (api_server.RECIPE_SERVICE, "search_by_pantry", lambda *a, **k: []),
        ):
            patch = mock.patch.object(target, attribute, replacement)
            patch.start()
            self.addCleanup(patch.stop)

    # ---- verktyg ---------------------------------------------------------

    def request(self, method, path, body=None, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            payload = json.dumps(body).encode("utf-8") if body is not None else None
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
        finally:
            conn.close()

    def account(self, premium=False):
        ratelimit.reset()
        email = f"j3-{uuid.uuid4().hex}@example.com"
        status, payload = self.request("POST", "/api/auth/register",
                                       {"email": email, "password": "hemligt123"})
        self.assertEqual(status, 201, payload)
        if premium:
            self.make_premium(email)
        return payload["token"]

    @staticmethod
    def make_premium(email):
        api_server.ACCOUNT_STORE.connection.execute(
            "UPDATE users SET premium = 1 WHERE email = ?", (email,))
        api_server.ACCOUNT_STORE.connection.commit()

    def user_id(self, token):
        return api_server.ACCOUNT_STORE.user_id_for_token(token)

    def add_member(self, owner_token, member_token):
        """Bjuder in och låter member gå med. Returnerar svaret på join."""
        status, invite = self.request("POST", "/api/household/invite", {}, token=owner_token)
        self.assertEqual(status, 200, invite)
        return self.request("POST", "/api/household/join",
                            {"token": invite["token"]}, token=member_token)

    def seed_household(self, size, premium=False):
        """Ett hushåll med `size` medlemmar, byggt UTANFÖR betalväggen.

        Skrivs direkt i lagret med premiumtaket, precis som ett hushåll som
        fanns innan J3 ändrade paketeringen. Det är just de hushållen regeln
        handlar om - de får inte tappa en enda medlem."""
        owner = self.account(premium=premium)
        status, payload = self.request("POST", "/api/household/create",
                                       {"name": "Familjen From"}, token=owner)
        self.assertEqual(status, 201, payload)
        household_id = payload["household"]["id"]
        members = []
        for _ in range(size - 1):
            member = self.account()
            invite = api_server.HOUSEHOLD_STORE.create_invite(
                household_id, self.user_id(owner), member_cap=MAX_MEMBERS)
            api_server.HOUSEHOLD_STORE.accept_invite(invite["token"], self.user_id(member))
            members.append(member)
        return owner, household_id, members


class TheModelMoved(PackagingTestCase):
    """Paketeringen är EN tabell. De här testerna läser den, inte sitt minne."""

    def test_every_week_type_is_free(self):
        """Veckorna sätts ihop i klienten; att sälja dem var att sälja något
        vi inte kunde leverera på. Nu är de gratis, och därmed finns ingen
        veckotypsgrind kvar att kringgå."""
        for key, feature in paywall.WEEK_TYPE_FEATURES.items():
            with self.subTest(week_type=key):
                self.assertTrue(plan_features.allowed(plan_features.FREE, feature))
        self.assertEqual(paywall.WEEK_TYPE_GATES, {})

    def test_the_features_that_moved_down_are_free_end_to_end(self):
        free = self.account()
        for feature in ("full_pantry", "advanced_nutrition", "meal_prep"):
            with self.subTest(feature=feature):
                self.assertTrue(plan_features.allowed(plan_features.FREE, feature))
                self.assertEqual(paywall.gates_for(feature), [])
        self.assertEqual(self.request("GET", "/api/v1/recipes/by-pantry?items=ris", token=free)[0], 200)
        self.assertEqual(self.request("GET", "/api/recipes?minProtein=30", token=free)[0], 200)
        self.assertEqual(self.request("GET", "/api/recipes?tag=mealprep", token=free)[0], 200)

    def test_free_plans_five_dinners_and_the_server_agrees(self):
        """Talet finns på ETT ställe, och entitlements, grinden och vägen
        läser alla det."""
        self.assertEqual(plan_features.FREE_MAX_DINNERS, 5)
        free = self.account()
        status, entitlements = self.request("GET", "/api/entitlements", token=free)
        self.assertEqual(entitlements["maxDinners"], 5)
        five = [f"r{n}" for n in range(5)]
        self.assertNotEqual(
            self.request("POST", "/api/pricing/week", {"recipeIds": five, "items": _ITEMS, "people": 2}, token=free)[0],
            403)
        status, payload = self.request("POST", "/api/pricing/week",
                                       {"recipeIds": five + ["r5"], "items": _ITEMS, "people": 2}, token=free)
        self.assertEqual(status, 403, payload)
        self.assertEqual(payload["maxDinners"], 5)

    def test_the_two_features_that_moved_up_are_premium_and_guarded(self):
        for feature in ("household_sharing", "savings_history"):
            with self.subTest(feature=feature):
                self.assertFalse(plan_features.allowed(plan_features.FREE, feature))
                self.assertTrue(paywall.gates_for(feature),
                                f"{feature} såldes som Premium utan en enda serverkontroll")

    def test_entitlements_carry_the_household_cap(self):
        """Klienten ska kunna säga "ni är två av två" utan att först få ett
        403 i ansiktet."""
        free, premium = self.account(), self.account(premium=True)
        self.assertEqual(self.request("GET", "/api/entitlements", token=free)[1]["maxHouseholdMembers"],
                         plan_features.FREE_MAX_HOUSEHOLD_MEMBERS)
        self.assertEqual(self.request("GET", "/api/entitlements", token=premium)[1]["maxHouseholdMembers"],
                         plan_features.PREMIUM_MAX_HOUSEHOLD_MEMBERS)


class TheHouseholdPaywall(PackagingTestCase):
    """Adams regel, prövad från båda hållen."""

    def test_two_people_share_for_free(self):
        """Gratis är inte "ensam". Två personer delar lista utan att betala -
        det är den andra personen som gör produkten värd att prata om."""
        owner, member = self.account(), self.account()
        self.assertEqual(self.request("POST", "/api/household/create", {"name": "Vi två"}, token=owner)[0], 201)
        status, payload = self.add_member(owner, member)
        self.assertEqual(status, 200, payload)
        self.assertEqual(len(payload["household"]["members"]), 2)

    def test_the_third_person_meets_the_paywall(self):
        owner, member, third = self.account(), self.account(), self.account()
        self.request("POST", "/api/household/create", {"name": "Vi två"}, token=owner)
        self.add_member(owner, member)
        status, payload = self.request("POST", "/api/household/invite", {}, token=owner)
        self.assertEqual(status, 403, payload)
        self.assertTrue(payload["locked"])
        self.assertEqual(payload["feature"], "household_sharing")
        self.assertEqual(payload["maxMembers"], plan_features.FREE_MAX_HOUSEHOLD_MEMBERS)
        # Och ingen inbjudan skapades som den tredje kunde ha använt.
        self.assertEqual(self.request("POST", "/api/household/join",
                                      {"token": "vadsomhelst"}, token=third)[0], 400)

    def test_premium_anywhere_in_the_household_unlocks_it_for_everyone(self):
        """Ett abonnemang per FAMILJ. Betalväggen får inte bero på vem som
        råkade hålla i telefonen när inbjudan skickades."""
        owner, member, third = self.account(), self.account(premium=True), self.account()
        self.request("POST", "/api/household/create", {"name": "Familjen"}, token=owner)
        self.add_member(owner, member)          # medlem två betalar, ägaren är gratis
        status, payload = self.add_member(owner, third)
        self.assertEqual(status, 200, payload)
        self.assertEqual(len(payload["household"]["members"]), 3)

    def test_an_existing_free_household_keeps_every_member_and_is_only_stopped_at_the_invite(self):
        """ADAMS REGEL, ORDAGRANT.

        Ett gratishushåll som redan har fem medlemmar när paketeringen ändras
        behåller alla fem. Alla fem läser hushållet, alla fem skriver i
        listan. Det enda som inte går är att bli sex."""
        owner, household_id, members = self.seed_household(5)
        self.assertEqual(len(api_server.HOUSEHOLD_STORE.member_user_ids(household_id)), 5)

        # 1. Ingen kastas ut, och alla ser fortfarande hela hushållet.
        for token in [owner] + members:
            status, payload = self.request("GET", "/api/household", token=token)
            self.assertEqual(status, 200, payload)
            self.assertEqual(len(payload["household"]["members"]), 5)

        # 2. Den delade listan fungerar för en medlem långt bortom taket.
        status, payload = self.request("POST", "/api/household/shopping/item",
                                       {"name": "Mjölk", "amount": 1, "unit": "l"},
                                       token=members[-1])
        self.assertEqual(status, 200, payload)
        self.assertEqual(self.request("GET", "/api/household/sync?since=0", token=owner)[0], 200)

        # 3. Men den SJÄTTE möter betalväggen - det är handlingen som kostar.
        status, payload = self.request("POST", "/api/household/invite", {}, token=owner)
        self.assertEqual(status, 403, payload)
        self.assertTrue(payload["locked"])
        self.assertEqual(payload["feature"], "household_sharing")

        # 4. Och efter nekandet är de fortfarande fem. Inget städades bort.
        self.assertEqual(len(api_server.HOUSEHOLD_STORE.member_user_ids(household_id)), 5)

        # 5. Uppgraderar någon i hushållet öppnas dörren igen - utan att
        #    någon behövt läggas till på nytt.
        self.make_premium(api_server.ACCOUNT_STORE.email_for_user_id(self.user_id(owner)))
        self.assertEqual(self.request("POST", "/api/household/invite", {}, token=owner)[0], 200)

    def test_a_stale_invite_cannot_fill_a_household_that_fell_back_to_free(self):
        """Inbjudan är en öppen dörr i 72 timmar, inte ett löfte. Skapas den
        medan hushållet är Premium och prenumerationen tar slut innan någon
        löser in den, är det Free-taket som gäller vid inlösen."""
        owner, household_id, members = self.seed_household(2, premium=True)
        status, invite = self.request("POST", "/api/household/invite", {}, token=owner)
        self.assertEqual(status, 200, invite)
        api_server.ACCOUNT_STORE.connection.execute("UPDATE users SET premium = 0")
        api_server.ACCOUNT_STORE.connection.commit()
        status, payload = self.request("POST", "/api/household/join",
                                       {"token": invite["token"]}, token=self.account())
        self.assertEqual(status, 403, payload)
        self.assertEqual(payload["feature"], "household_sharing")
        self.assertEqual(len(api_server.HOUSEHOLD_STORE.member_user_ids(household_id)), 2)

    def test_a_full_premium_household_is_full_not_for_sale(self):
        """Vid tolv finns inget att köpa, och då får svaret inte låtsas att
        det gör det."""
        owner, household_id, _ = self.seed_household(MAX_MEMBERS, premium=True)
        status, payload = self.request("POST", "/api/household/invite", {}, token=owner)
        self.assertEqual(status, 400, payload)
        self.assertNotIn("locked", payload)

    def test_the_household_payload_says_how_many_fit(self):
        owner, member = self.account(), self.account()
        self.request("POST", "/api/household/create", {"name": "Vi två"}, token=owner)
        status, payload = self.add_member(owner, member)
        household = payload["household"]
        self.assertEqual(household["memberCap"], plan_features.FREE_MAX_HOUSEHOLD_MEMBERS)
        self.assertFalse(household["canInvite"])
        self.assertTrue(household["capLocked"])


class TheSavingsHistory(PackagingTestCase):
    """"Du sparade 1 340 kr i september" - den enda siffran som bevisar att
    prenumerationen betalar sig."""

    def record(self, token, week_key, cheapest, priciest):
        status, payload = self.request("POST", "/api/savings/week",
                                       {"weekKey": week_key, "cheapestTotal": cheapest,
                                        "priciestTotal": priciest, "chain": "Willys"},
                                       token=token)
        self.assertEqual(status, 200, payload)
        return payload

    def test_free_sees_the_latest_week_premium_sees_the_history(self):
        free, premium = self.account(), self.account(premium=True)
        for token in (free, premium):
            self.record(token, "2026-W35", 1000, 1200)
            self.record(token, "2026-W36", 900, 1150)
            self.record(token, "2026-W37", 950, 1100)

        status, payload = self.request("GET", "/api/savings", token=free)
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["locked"])
        self.assertEqual(payload["feature"], "savings_history")
        self.assertEqual(len(payload["weeks"]), plan_features.FREE_SAVINGS_WEEKS)
        self.assertEqual(payload["weeks"][0]["weekKey"], "2026-W37")
        self.assertEqual(payload["months"], [])
        # Free får se HUR MYCKET som ligger bakom låset. Att dölja mängden
        # vore att dölja erbjudandet.
        self.assertEqual(payload["weeksAvailable"], 3)

        status, payload = self.request("GET", "/api/savings", token=premium)
        self.assertFalse(payload["locked"])
        self.assertEqual(len(payload["weeks"]), 3)
        self.assertEqual(payload["totalSavedKr"], 200 + 250 + 150)
        self.assertTrue(payload["months"])

    def test_the_month_report_is_summed_in_ore_and_rounded_once(self):
        """Tre veckor som var för sig avrundas till 33,33 kr blir 99,99 -
        inte 100. Summan ska vara sann om den ska gå att sälja."""
        premium = self.account(premium=True)
        for week in ("2026-W36", "2026-W37", "2026-W38"):
            self.record(premium, week, 100.00, 133.335)
        status, payload = self.request("GET", "/api/savings", token=premium)
        month = payload["months"][0]
        self.assertEqual(month["savedKr"], round(3 * round(33.335 * 100) / 100, 2))
        self.assertEqual(month["weeks"], 3)
        self.assertIn("Du sparade", month["sentence"])

    def test_savings_are_never_negative_and_a_week_is_written_once(self):
        premium = self.account(premium=True)
        # Trasigt underlag: dyraste under billigaste. Noll, inte en lögn.
        self.record(premium, "2026-W37", 1200, 900)
        status, payload = self.request("GET", "/api/savings", token=premium)
        self.assertEqual(payload["weeks"][0]["savedKr"], 0)
        # Samma vecka igen skriver ÖVER, den läggs inte till.
        self.record(premium, "2026-W37", 900, 1200)
        self.record(premium, "2026-W37", 900, 1100)
        status, payload = self.request("GET", "/api/savings", token=premium)
        self.assertEqual(len(payload["weeks"]), 1)
        self.assertEqual(payload["totalSavedKr"], 200)

    def test_a_week_that_straddles_a_month_lands_in_exactly_one_month(self):
        """ISO: torsdagen bestämmer. Annars summerar månadsrapporten till
        mer än året."""
        self.assertEqual(savings.month_of("2026-W39"), "2026-09")   # torsdag 24 sep
        self.assertEqual(savings.month_of("2026-W40"), "2026-10")   # torsdag 1 okt
        self.assertIsNone(savings.month_of("skräp"))
        self.assertEqual(savings.normalize_week_key("2026-W07"), "2026-W07")
        self.assertEqual(savings.normalize_week_key("../etc/passwd"),
                         savings.current_week_key())
        self.assertEqual(savings.normalize_week_key("2026-W99"), savings.current_week_key())

    def test_savings_need_a_login_and_die_with_the_account(self):
        self.assertEqual(self.request("GET", "/api/savings")[0], 401)
        self.assertEqual(self.request("POST", "/api/savings/week", {"savedKr": 10})[0], 401)
        token = self.account(premium=True)
        user_id = self.user_id(token)
        self.record(token, "2026-W37", 900, 1100)
        api_server.SAVINGS.forget_user(user_id)
        self.assertEqual(api_server.SAVINGS.weeks(user_id), [])


class TheActivationTrialIsGone(PackagingTestCase):
    """Ingen automatisk trial - beslutet 2026-09-19 (J3b).

    J3 gav sju dagars Premium efter den första skapade veckan. Det är borta:
    varken registreringen, den första prissatta veckan eller klientens
    vecka_skapad-händelse ändrar en entitlement. Signalen (mark_first_week)
    är kvar för hänvisningskroken H5."""

    def _user(self, token):
        return self.request("GET", "/api/auth/me", token=token)[1]["user"]

    def _assert_free(self, token):
        user = self._user(token)
        self.assertFalse(user["premium"], user)
        self.assertIsNone(user["trialEndsAt"], user)
        self.assertFalse(user["trialUsed"], user)
        self.assertFalse(self.request("GET", "/api/entitlements", token=token)[1]["isPremium"])

    def test_registering_grants_nothing(self):
        self._assert_free(self.account())

    def test_the_first_priced_week_grants_nothing(self):
        token = self.account()
        self.assertEqual(self.request("POST", "/api/pricing/week",
                                      {"items": _ITEMS, "people": 2}, token=token)[0], 200)
        self._assert_free(token)
        # ...och inte den andra eller tredje heller.
        for _ in range(2):
            self.request("POST", "/api/pricing/week", {"items": _ITEMS, "people": 2}, token=token)
        self._assert_free(token)

    def test_the_client_event_grants_nothing_either(self):
        token = self.account()
        self.request("POST", "/api/analytics/event", {"event": "vecka_skapad"}, token=token)
        self._assert_free(token)

    def test_the_self_serve_endpoint_still_refuses(self):
        token = self.account()
        status, _ = self.request("POST", "/api/auth/start-trial", {}, token=token)
        self.assertGreaterEqual(status, 400)
        self._assert_free(token)

    def test_the_first_week_signal_still_fires_once_for_the_hooks(self):
        """H5 hänger på övergången. True BARA första gången - och det som
        kommer tillbaka är krokarnas resultat, aldrig en entitlement."""
        token = self.account()
        user_id = self.user_id(token)
        seen = []

        def hook(accounts, uid):
            seen.append(uid)
            return {"hook": "sett"}

        first = activation.on_first_week(api_server.ACCOUNT_STORE, user_id, hooks=(hook,))
        self.assertEqual(first, {"firstWeek": True, "hooks": [{"hook": "sett"}]})
        self.assertIsNone(activation.on_first_week(api_server.ACCOUNT_STORE, user_id, hooks=(hook,)))
        self.assertEqual(seen, [user_id])
        self._assert_free(token)

    def test_a_hook_that_falls_does_not_take_the_signal_with_it(self):
        token = self.account()
        user_id = self.user_id(token)

        def broken(accounts, uid):
            raise RuntimeError("hänvisningen sprack")

        self.assertEqual(activation.on_first_week(api_server.ACCOUNT_STORE, user_id, hooks=(broken,)),
                         {"firstWeek": True, "hooks": []})

    def test_nothing_in_the_code_can_write_a_trial(self):
        """Regressionsvakten. En trial som 'råkar' komma tillbaka kommer
        tillbaka genom en av tre dörrar: konstanten, metoden eller en
        UPDATE som sätter trial_ends_at till något annat än NULL."""
        self.assertFalse(hasattr(activation, "ACTIVATION_TRIAL_DAYS"))
        self.assertFalse(hasattr(api_server.ACCOUNT_STORE, "grant_activation_trial"))
        rot = Path(api_server.__file__).resolve().parent
        skrivningar = []
        for fil in [rot / "api_server.py", *sorted((rot / "services").rglob("*.py"))]:
            for nummer, rad in enumerate(fil.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"trial_ends_at\s*=(?!\s*NULL\b)", rad) and "UPDATE" in rad.upper():
                    skrivningar.append(f"{fil.relative_to(rot)}:{nummer}: {rad.strip()}")
                if "trial_period_days" in rad and "checkout" in rad.lower():
                    skrivningar.append(f"{fil.relative_to(rot)}:{nummer}: {rad.strip()}")
        self.assertEqual(skrivningar, [], "något skriver en trial:\n" + "\n".join(skrivningar))

    def test_an_already_granted_trial_is_still_honoured_until_it_ends(self):
        """Den som fick sina sju dagar före beslutet behåller dem: läsningen
        är kvar, bara skrivningen är borta."""
        token = self.account()
        user_id = self.user_id(token)
        store = api_server.ACCOUNT_STORE
        ends = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        with store._lock:
            store._connection.execute("UPDATE users SET trial_ends_at = ?, trial_used = 1 WHERE id = ?",
                                      (ends, user_id))
            store._connection.commit()
        user = self._user(token)
        self.assertTrue(user["premium"])
        self.assertEqual(user["premiumSource"], "trial")
        self.assertEqual(user["trialEndsAt"], ends)


if __name__ == "__main__":
    unittest.main()
