# -*- coding: utf-8 -*-
"""H5: hänvisning kopplad till Premium - och premium-koder som går att styra.

FYNDET H5 BYGGER PÅ

`MATJAKT_PREMIUM_CODE` var en enda evig sträng utan förbrukning, utgång eller
räknare. Lades den på Flashback blev varje konto som löste in den PERMANENT
Premium, och att byta env-variabeln återkallade ingenting - de redan inlösta
kontona hade `premium = 1` för alltid, och inget i systemet mindes vilken kod
som gav dem det.

Nu är en kod en rad med `max_uses`, `expires_at`, `uses` och en ägare, och
belöningen är `premium_until` - dagar, inte evighet.

ADAMS REGEL FÖR H5

> Belöningens längd är en konstant på ETT ställe, inte spridd i flödet.

`test_the_reward_length_lives_in_exactly_one_place` är den regeln. J3 gjorde
Premium till enda sättet att dela lista med familjen, så belöningen blir
dyrare i samma stund som den blir mer lockande - och den dagen talet ska
ändras ska det vara en rad, inte en jakt genom flödet.

OCH VILLKORET ÄR ARBETE, INTE EN E-POSTADRESS

Den som bjuder in får betalt när den inbjudna byggt sin FÖRSTA VECKA - inte
när hon registrerade sig. Signalen är J3:s `mark_first_week`, och H5 hänger
sig på den som en krok i stället för att bygga en egen väg.
"""

import http.client
import json
import sys
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

import api_server  # noqa: E402
from services.accounts import AccountStore, ratelimit  # noqa: E402
from services.billing import referral  # noqa: E402
from services.billing.codes import CodeError, PremiumCodeStore, expiry_in, hash_code  # noqa: E402

ITEMS = [{"name": "mjölk", "amount": 1, "unit": "l"}]


def _fake_week(*args, **kwargs):
    return {"results": [], "comparison": {}}


class ReferralTestCase(unittest.TestCase):
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
        self._original = (api_server.ACCOUNT_STORE, api_server.PREMIUM_CODES)
        api_server.ACCOUNT_STORE = AccountStore(Path(self._tmp.name) / "h5.db")
        api_server.PREMIUM_CODES = PremiumCodeStore(api_server.ACCOUNT_STORE.connection,
                                                    lock=api_server.ACCOUNT_STORE.lock)

        def restore():
            api_server.ACCOUNT_STORE.close()
            (api_server.ACCOUNT_STORE, api_server.PREMIUM_CODES) = self._original
        self.addCleanup(restore)

        patch = mock.patch.object(api_server.grocery_api, "price_week", _fake_week)
        patch.start()
        self.addCleanup(patch.stop)
        # KROKEN BYGGS INTE OM HÄR - med flit. Den första versionen av det här
        # testet ersatte `ApiHandler.ACTIVATION_HOOKS` med en egen krok mot
        # det utbytta lagret, och då prövades testets kopia av inkopplingen i
        # stället för serverns: `ACTIVATION_HOOKS = ()` i api_server gick rakt
        # igenom alla trettio testerna. Serverns krok slår i stället upp
        # `api_server.PREMIUM_CODES` vid ANROPET, och raden ovan har redan
        # bytt ut den - belöningen hamnar alltså i den här databasen, och
        # inkopplingsraden är med i det som prövas.

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

    def account(self):
        ratelimit.reset()
        email = f"h5-{uuid.uuid4().hex}@example.com"
        status, payload = self.request("POST", "/api/auth/register",
                                       {"email": email, "password": "hemligt123"})
        self.assertEqual(status, 201, payload)
        return payload["token"]

    def me(self, token):
        return self.request("GET", "/api/auth/me", token=token)[1]["user"]

    def user_id(self, token):
        return api_server.ACCOUNT_STORE.user_id_for_token(token)

    def my_code(self, token) -> str:
        status, payload = self.request("POST", "/api/referral", {}, token=token)
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["code"])
        return payload["code"]

    def build_first_week(self, token):
        """Den inbjudna gör det som faktiskt räknas: skapar en vecka."""
        status, payload = self.request("POST", "/api/pricing/week",
                                       {"items": ITEMS, "people": 2}, token=token)
        self.assertEqual(status, 200, payload)


class AdamsRegel(unittest.TestCase):
    """Belöningens längd är en konstant på ETT ställe."""

    def test_the_reward_length_lives_in_exactly_one_place(self):
        """Talet får förekomma i EN modul och nås därifrån.

        Testet läser den faktiska källkoden i faktureringslagret och kräver
        att ingen annan fil skriver ut antalet dagar - varken den inbjudnas
        direktbelöning, utbetalningen till den som bjöd in, koden som skapas
        eller texten i delningen. Alla fyra läser samma konstant.

        Skälet är konkret: J3 gjorde Premium till enda sättet att dela lista
        med familjen, så belöningen blev dyrare i samma stund som den blev mer
        lockande. Den dagen talet ska ändras ska det vara en rad."""
        days = referral.REFERRAL_REWARD_DAYS
        self.assertEqual(days, 30)

        billing = Path(__file__).resolve().parents[1] / "services" / "billing"
        home = billing / "referral.py"
        # I hemmodulen står talet EN gång: i tilldelningen.
        source = home.read_text(encoding="utf-8")
        body = "\n".join(line for line in source.split("\n")
                         if not line.lstrip().startswith("#"))
        self.assertEqual(body.count(str(days)), 1,
                         "belöningens längd står mer än en gång i referral.py")

        # Och ingen annanstans i faktureringslagret, inte heller i api_server.
        others = [path for path in billing.glob("*.py") if path != home]
        others.append(Path(__file__).resolve().parents[1] / "api_server.py")
        for path in others:
            for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
                stripped = line.lstrip()
                if stripped.startswith("#") or "REFERRAL_REWARD_DAYS" in line:
                    continue
                self.assertNotIn(f"{days} dagar", stripped,
                                 f"{path.name}:{number} skriver ut belöningens längd")

    def test_every_consumer_reads_the_same_constant(self):
        """Koden som skapas, texten som delas och utbetalningen - alla tre
        följer konstanten även om den ändras."""
        with mock.patch.object(referral, "REFERRAL_REWARD_DAYS", 14):
            text = referral.share_text("MJ-TEST", "https://matjakt.store/app")
            self.assertEqual(text["rewardDays"], 14)
            self.assertIn("14 dagar", text["shareText"])


class KodernaHarGranser(ReferralTestCase):
    """En evig sträng utan förbrukning, utgång eller räknare - inte längre."""

    def store(self):
        return api_server.PREMIUM_CODES

    def test_a_code_grants_days_not_eternity(self):
        token = self.account()
        code = self.store().create(label="kampanj", grant_days=30, max_uses=5)
        status, payload = self.request("POST", "/api/auth/redeem", {"code": code}, token=token)
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["grantedDays"], 30)
        me = self.me(token)
        self.assertTrue(me["premium"])
        self.assertEqual(me["premiumSource"], "code")
        self.assertTrue(me["premiumUntil"])

    def test_premium_falls_away_by_itself_when_the_days_run_out(self):
        """Det här är hela skillnaden mot den eviga flaggan: ingen behöver
        städa, och ingen behöver komma ihåg vem som löste in vad."""
        token = self.account()
        code = self.store().create(label="kampanj", grant_days=30)
        self.request("POST", "/api/auth/redeem", {"code": code}, token=token)
        api_server.ACCOUNT_STORE.connection.execute(
            "UPDATE users SET premium_until = ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),))
        api_server.ACCOUNT_STORE.connection.commit()
        self.assertFalse(self.me(token)["premium"])

    def test_a_code_runs_out(self):
        """Flashback-fallet. Med ett tak tar koden slut i stället för att dela
        ut permanent Premium till alla som hinner klicka."""
        code = self.store().create(label="lackt", grant_days=30, max_uses=2)
        tokens = [self.account() for _ in range(3)]
        results = [self.request("POST", "/api/auth/redeem", {"code": code}, token=token)[0]
                   for token in tokens]
        self.assertEqual(results, [200, 200, 400])
        self.assertFalse(self.me(tokens[2])["premium"])

    def test_an_expired_code_is_refused(self):
        token = self.account()
        code = self.store().create(label="gammal", grant_days=30,
                                   expires_at=(datetime.now(timezone.utc)
                                               - timedelta(days=1)).isoformat())
        status, payload = self.request("POST", "/api/auth/redeem", {"code": code}, token=token)
        self.assertEqual(status, 400, payload)
        self.assertIn("gått ut", payload["error"])

    def test_a_revoked_code_stops_working_immediately(self):
        """Att byta env-variabeln återkallade ingenting. Nu går det."""
        code = self.store().create(label="kampanj", grant_days=30)
        first = self.account()
        self.assertEqual(self.request("POST", "/api/auth/redeem",
                                      {"code": code}, token=first)[0], 200)
        self.assertTrue(self.store().revoke(code))
        second = self.account()
        self.assertEqual(self.request("POST", "/api/auth/redeem",
                                      {"code": code}, token=second)[0], 400)
        # Redan utdelade dagar rörs inte - de är givna i förtroende.
        self.assertTrue(self.me(first)["premium"])

    def test_the_same_account_cannot_redeem_the_same_code_twice(self):
        token = self.account()
        code = self.store().create(label="kampanj", grant_days=30, max_uses=10)
        self.assertEqual(self.request("POST", "/api/auth/redeem",
                                      {"code": code}, token=token)[0], 200)
        self.assertEqual(self.request("POST", "/api/auth/redeem",
                                      {"code": code}, token=token)[0], 400)

    def test_two_codes_stack_instead_of_overwriting(self):
        """Räknas det från nu skulle en andra kod FÖRKORTA den första."""
        token = self.account()
        for _ in range(2):
            code = self.store().create(label="kampanj", grant_days=30)
            self.assertEqual(self.request("POST", "/api/auth/redeem",
                                          {"code": code}, token=token)[0], 200)
        until = datetime.fromisoformat(self.me(token)["premiumUntil"])
        self.assertGreater(until, datetime.now(timezone.utc) + timedelta(days=59))

    def test_the_raw_code_is_never_stored(self):
        """Samma regel som för sessionstoken: en läckt databas är inte en
        bunt giltiga koder."""
        code = self.store().create(label="kampanj", grant_days=30)
        rows = api_server.ACCOUNT_STORE.connection.execute(
            "SELECT code_hash FROM premium_codes").fetchall()
        self.assertEqual([row["code_hash"] for row in rows], [hash_code(code)])
        self.assertNotIn(code, [row["code_hash"] for row in rows])

    def test_a_wrong_code_says_nothing_about_which_codes_exist(self):
        token = self.account()
        status, payload = self.request("POST", "/api/auth/redeem",
                                       {"code": "FINNSINTE"}, token=token)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "Fel kod")

    def test_the_counter_holds_under_concurrency(self):
        """Hela kontrollen och räknaren i samma transaktion. Utan det kan
        hundra samtidiga inlösningar av en kod med max_uses = 1 alla läsa
        uses = 0 och alla lyckas."""
        code = self.store().create(label="lackt", grant_days=30, max_uses=1)
        tokens = [self.account() for _ in range(6)]
        ok = []
        barrier = threading.Barrier(len(tokens))

        def attempt(token):
            barrier.wait()
            try:
                self.store().redeem(code, self.user_id(token))
                ok.append(token)
            except CodeError:
                pass

        threads = [threading.Thread(target=attempt, args=(token,)) for token in tokens]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(ok), 1, f"{len(ok)} konton löste in en kod med max_uses = 1")


class HanvisningenBetalasForArbete(ReferralTestCase):
    """Villkora på vecka_skapad, inte på registrering."""

    def test_the_invitee_gets_a_month_immediately(self):
        inviter, invitee = self.account(), self.account()
        code = self.my_code(inviter)
        status, payload = self.request("POST", "/api/auth/redeem",
                                       {"code": code}, token=invitee)
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["grantedDays"], referral.REFERRAL_REWARD_DAYS)
        self.assertTrue(self.me(invitee)["premium"])

    def test_the_inviter_gets_nothing_until_the_first_week_is_built(self):
        """DET HÄR ÄR VILLKORET. Ett registrerat konto som aldrig skapar en
        vecka är inte en kund - det är en e-postadress."""
        inviter, invitee = self.account(), self.account()
        code = self.my_code(inviter)
        self.request("POST", "/api/auth/redeem", {"code": code}, token=invitee)

        # Inbjuden, inlöst, inloggad - och ändå obetald.
        self.assertFalse(self.me(inviter)["premium"],
                         "belöningen betalades ut redan vid inlösen")
        self.assertEqual(self.request("GET", "/api/referral", token=inviter)[1]["rewarded"], 0)

        self.build_first_week(invitee)

        me = self.me(inviter)
        self.assertTrue(me["premium"])
        self.assertEqual(me["premiumSource"], "code")
        self.assertEqual(self.request("GET", "/api/referral", token=inviter)[1]["rewarded"], 1)

    def test_the_reward_is_paid_once_no_matter_how_many_weeks(self):
        inviter, invitee = self.account(), self.account()
        self.request("POST", "/api/auth/redeem", {"code": self.my_code(inviter)}, token=invitee)
        self.build_first_week(invitee)
        first = self.me(inviter)["premiumUntil"]
        for _ in range(3):
            self.build_first_week(invitee)
        self.request("POST", "/api/analytics/event", {"event": "vecka_skapad"}, token=invitee)
        self.assertEqual(self.me(inviter)["premiumUntil"], first)

    def test_the_client_event_also_pays_out(self):
        """Samma signal från andra hållet - J3:s krok, inte en egen väg."""
        inviter, invitee = self.account(), self.account()
        self.request("POST", "/api/auth/redeem", {"code": self.my_code(inviter)}, token=invitee)
        self.request("POST", "/api/analytics/event", {"event": "vecka_skapad"}, token=invitee)
        self.assertTrue(self.me(inviter)["premium"])

    def test_a_week_from_someone_who_was_not_invited_pays_nobody(self):
        alone = self.account()
        self.build_first_week(alone)
        self.assertFalse(self.me(alone)["premium"] and
                         self.me(alone)["premiumSource"] == "code")

    def test_nobody_can_redeem_their_own_code(self):
        """Annars är hänvisningsprogrammet en knapp som heter "ge mig en
        gratismånad"."""
        token = self.account()
        status, payload = self.request("POST", "/api/auth/redeem",
                                       {"code": self.my_code(token)}, token=token)
        self.assertEqual(status, 400, payload)
        self.assertIn("egen kod", payload["error"])

    def test_the_personal_code_is_handed_out_once_and_then_only_counted(self):
        token = self.account()
        first = self.request("POST", "/api/referral", {}, token=token)[1]
        self.assertTrue(first["code"])
        self.assertTrue(first["new"])
        again = self.request("POST", "/api/referral", {}, token=token)[1]
        self.assertIsNone(again["code"])
        self.assertFalse(again["new"])

    def test_the_share_text_is_ready_to_send(self):
        token = self.account()
        payload = self.request("POST", "/api/referral", {}, token=token)[1]
        self.assertIn(payload["code"], payload["url"])
        self.assertIn("?kod=", payload["url"])
        self.assertIn(str(referral.REFERRAL_REWARD_DAYS), payload["shareText"])

    def test_the_invite_counter_counts_invitees_not_rewards(self):
        inviter = self.account()
        code = self.my_code(inviter)
        invitees = [self.account() for _ in range(2)]
        for token in invitees:
            self.request("POST", "/api/auth/redeem", {"code": code}, token=token)
        stats = self.request("GET", "/api/referral", token=inviter)[1]
        self.assertEqual((stats["invited"], stats["rewarded"]), (2, 0))
        self.build_first_week(invitees[0])
        stats = self.request("GET", "/api/referral", token=inviter)[1]
        self.assertEqual((stats["invited"], stats["rewarded"]), (2, 1))

    def test_referral_needs_a_login(self):
        self.assertEqual(self.request("GET", "/api/referral")[0], 401)
        self.assertEqual(self.request("POST", "/api/referral", {})[0], 401)


class GamlaKontonTappasInte(ReferralTestCase):
    def test_a_grandfathered_eternal_flag_still_counts(self):
        """Ingen ska vakna degraderad av en refaktorering."""
        token = self.account()
        api_server.ACCOUNT_STORE.connection.execute("UPDATE users SET premium = 1")
        api_server.ACCOUNT_STORE.connection.commit()
        me = self.me(token)
        self.assertTrue(me["premium"])
        self.assertEqual(me["premiumSource"], "comped")

    def test_a_subscription_still_outranks_a_code(self):
        """Sanningsordning, inte prioritetsordning: den som HAR en aktiv
        prenumeration betalar."""
        token = self.account()
        code = api_server.PREMIUM_CODES.create(label="kampanj", grant_days=30)
        self.request("POST", "/api/auth/redeem", {"code": code}, token=token)
        api_server.ACCOUNT_STORE.connection.execute(
            """UPDATE users SET subscription_status = 'active', subscription_plan = 'monthly',
                   subscription_period_end = ?""",
            ((datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),))
        api_server.ACCOUNT_STORE.connection.commit()
        self.assertEqual(self.me(token)["premiumSource"], "subscription")

    def test_codes_and_redemptions_die_with_the_account(self):
        token = self.account()
        user_id = self.user_id(token)
        self.my_code(token)
        api_server.PREMIUM_CODES.forget_user(user_id)
        self.assertIsNone(api_server.PREMIUM_CODES.owned_by(user_id))


class AdminKanMinta(ReferralTestCase):
    def test_the_admin_route_is_hidden_without_a_token(self):
        self.assertEqual(self.request("GET", "/api/admin/premium-code?dagar=30")[0], 404)

    def test_a_minted_code_carries_the_limits_it_was_given(self):
        with mock.patch.object(api_server, "ADMIN_TOKEN", "hemlig"):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            try:
                conn.request("GET", "/api/admin/premium-code?dagar=14&antal=3&giltig=7&etikett=press",
                             headers={"X-Admin-Token": "hemlig"})
                response = conn.getresponse()
                payload = json.loads(response.read())
                self.assertEqual(response.status, 200, payload)
            finally:
                conn.close()
        self.assertEqual(payload["grantDays"], 14)
        self.assertEqual(payload["maxUses"], 3)
        row = api_server.PREMIUM_CODES.describe(hash_code(payload["code"]))
        self.assertEqual((row["label"], row["grant_days"], row["max_uses"]), ("press", 14, 3))
        self.assertTrue(row["expires_at"])


class Hjalpfunktioner(unittest.TestCase):
    def test_codes_are_readable_off_a_phone_screen(self):
        """Inga 0/O/1/I/l: koden skrivs av från en skärm."""
        from services.billing.codes import new_code
        for _ in range(200):
            self.assertFalse(set(new_code()) & set("01OIl"))

    def test_hashing_ignores_case_and_whitespace(self):
        self.assertEqual(hash_code(" mj-abc123 "), hash_code("MJ-ABC123"))

    def test_expiry_is_in_the_future(self):
        self.assertGreater(expiry_in(1), datetime.now(timezone.utc).isoformat())


if __name__ == "__main__":
    unittest.main()
