# -*- coding: utf-8 -*-
"""H1: söndagsnotisen.

Acceptansen, fyra påståenden, ett test per påstående:

  1. En prenumererad användare får EXAKT EN notis en söndag 17:00 - och noll
     extra om servern startar om under den minuten.
  2. En användare utan samtycke får INGEN.
  3. Texten bär användarens EGNA tal ur synced_state. Går de inte att läsa
     skickas den generella varianten, aldrig en gissad siffra.
  4. Utan MATJAKT_VAPID_PUBLIC_KEY går allt annat igenom och notisen uteblir
     tyst - inget undantag, ingen rad i loggen som ser ut som ett fel.

Plus krypteringens byggstenar mot RFC 5869:s och RFC 8291:s EGNA testvektorer.
De tre stegen som kräver `cryptography` (ECDH, AES-GCM, ES256) ligger bakom
en valfri import; allt runt dem är stdlib och prövas här på riktigt.

Ingen riktig utgående trafik: avsändaren får sin `opener` injicerad.
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.accounts import AccountStore  # noqa: E402
from services.household import HouseholdStore, NotificationStore  # noqa: E402
from services.household.routes import HouseholdRouter  # noqa: E402
from services.push import PushStore, WeeklyPushScheduler, WebPushGone  # noqa: E402
from services.push import schedule as push_schedule  # noqa: E402
from services.push import webpush  # noqa: E402

# Söndag 13 september 2026, 17:00. Fast klocka: testet betyder samma sak
# oavsett när det körs.
SUNDAY = datetime(2026, 9, 13, 17, 0)
SUBSCRIPTION = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/abc123def456",
    "keys": {"p256dh": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
             "auth": "BTBZMqHH6r4Tts7J_aSIgg"},
}


class FakeSender:
    """Avsändaren utan nät. `blocked` speglar det enda som stoppar en
    riktig avsändare: nycklarna."""

    def __init__(self, blocked=None, gone_for=()):
        self.blocked = blocked
        self.gone_for = set(gone_for)
        self.sent = []

    def blocked_reason(self):
        return self.blocked

    def send(self, subscription, payload, **kwargs):
        if subscription["endpoint"] in self.gone_for:
            raise WebPushGone("borta")
        self.sent.append({"endpoint": subscription["endpoint"], "payload": json.loads(payload)})
        return 201


class SondagsnotisTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        path = Path(self._tmp.name) / "test.db"
        self.accounts = AccountStore(path)
        self.addCleanup(self.accounts.close)
        self.notifications = NotificationStore(path)
        self.addCleanup(self.notifications.close)
        self.push = PushStore(self.accounts.connection, lock=self.accounts.lock)
        self.sender = FakeSender()
        self.scheduler = self._scheduler()

    def _scheduler(self, sender=None):
        return WeeklyPushScheduler(self.push, sender or self.sender, self.notifications,
                                   app_url="https://matjakt.store/app", pause_seconds=0)

    def _user(self, email="adam@example.com", *, middagar=5, personer=4, subscribe=True,
              endpoint=None):
        self.accounts.register(email, "hemligt123")
        connection = self.accounts.connection
        user_id = connection.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
        if middagar is not None or personer is not None:
            blob = {}
            if middagar is not None:
                blob["middagar"] = middagar
            if personer is not None:
                blob["personer"] = personer
            connection.execute("UPDATE users SET synced_state = ? WHERE id = ?",
                               (json.dumps(blob), user_id))
            connection.commit()
        if subscribe:
            subscription = dict(SUBSCRIPTION)
            subscription["endpoint"] = endpoint or f"{SUBSCRIPTION['endpoint']}-{user_id}"
            self.push.subscribe(user_id, subscription)
        return user_id


# ---- 1. exakt en notis per söndag och konto ---------------------------------

class EnNotisPerSondagTest(SondagsnotisTestCase):
    def test_en_prenumerant_far_exakt_en_notis(self):
        self._user()
        summary = self.scheduler.run_due(SUNDAY)
        self.assertIsNone(summary["blockerat"])
        self.assertEqual(summary["skickat"], 1)
        self.assertEqual(len(self.sender.sent), 1)

    def test_en_omstart_klockan_17_ger_inte_tva_notiser(self):
        """`_last_fired` bor i processen och nollställs av en omstart.
        push_log gör det inte: mottagarfrågan filtrerar bort kontot som redan
        fått dagens notis, och det är skillnaden mellan en påminnelse och
        två. (Spärren för två körningar SAMTIDIGT är claim() - se nedan.)"""
        self._user()
        self.scheduler._tick(SUNDAY)
        self.assertEqual(len(self.sender.sent), 1)

        # Ny process, samma minut, samma databas.
        omstartad = self._scheduler()
        self.assertIsNone(omstartad._last_fired)
        summary = omstartad._tick(SUNDAY) or omstartad.last_run
        self.assertEqual(len(self.sender.sent), 1, "andra körningen skickade en notis till")
        self.assertEqual(summary["skickat"], 0)
        self.assertEqual(summary["redanSkickat"], 0,
                         "kontot ska inte ens komma med i mottagarfrågan")

    def test_claim_ger_dagens_plats_till_exakt_en(self):
        """Databasen, inte processen, är den som vet. INSERT OR IGNORE mot
        UNIQUE (user_id, kind, day): den första får platsen, alla andra
        får nej."""
        user_id = self._user(subscribe=False)
        dag = SUNDAY.date()
        self.assertTrue(self.push.claim(user_id, push_schedule.KIND, dag))
        self.assertFalse(self.push.claim(user_id, push_schedule.KIND, dag))
        self.assertFalse(self.push.claim(user_id, push_schedule.KIND, dag))
        self.assertTrue(self.push.claim(user_id, push_schedule.KIND,
                                        (SUNDAY + timedelta(days=7)).date()))

    def test_tva_korningar_som_bada_hann_lasa_mottagarlistan_ger_anda_en(self):
        """Den elaka varianten av omstarten: servern startar om SÅ nära
        17:00 att båda processerna hinner fråga efter mottagare innan någon
        av dem hunnit skriva i push_log. Då filtrerar mottagarfrågan bort
        ingen - det är claim() som är spärren, och den ligger i databasen
        just för det här."""
        self._user()
        lista = self.push.recipients(push_schedule.KIND, SUNDAY.date())
        self.assertEqual(len(lista), 1)

        class FrusenLista:
            """Samma mottagarlista till båda körningarna - som när båda
            hann läsa före den första skrivningen."""

            def __init__(self, store, rows):
                self._store, self._rows = store, rows

            def __getattr__(self, name):
                return getattr(self._store, name)

            def recipients(self, kind, today):
                return self._rows

        for _ in range(2):
            scheduler = self._scheduler()
            scheduler.store = FrusenLista(self.push, lista)
            scheduler.run_due(SUNDAY)
        self.assertEqual(len(self.sender.sent), 1,
                         "claim() är det som gör två samtidiga körningar till en notis")

    def test_samma_sondag_flera_gangar_ger_fortfarande_en(self):
        self._user()
        for _ in range(4):
            self.scheduler.run_due(SUNDAY)
        self.assertEqual(len(self.sender.sent), 1)

    def test_nasta_sondag_ar_en_ny_notis(self):
        self._user()
        self.scheduler.run_due(SUNDAY)
        self.scheduler.run_due(SUNDAY + timedelta(days=7))
        self.assertEqual(len(self.sender.sent), 2)

    def test_tva_enheter_samma_konto_ar_fortfarande_en_notis_i_loggen(self):
        user_id = self._user()
        andra = dict(SUBSCRIPTION)
        andra["endpoint"] = "https://updates.push.services.mozilla.com/wpush/v2/annan"
        self.push.subscribe(user_id, andra)
        summary = self.scheduler.run_due(SUNDAY)
        self.assertEqual(len(self.sender.sent), 2, "båda telefonerna ska få notisen")
        self.assertEqual(summary["skickat"], 1, "men kontot räknas en gång")
        self.assertEqual(self.push.counts(30), {push_schedule.KIND: 1})

    def test_klockan_och_veckodagen_avgor_nar_det_smaller(self):
        self._user()
        for tid, vad in ((SUNDAY.replace(hour=16, minute=59), "en minut för tidigt"),
                         (SUNDAY.replace(hour=17, minute=1), "en minut för sent"),
                         (SUNDAY - timedelta(days=1), "lördag"),
                         (SUNDAY + timedelta(days=1), "måndag")):
            self._scheduler()._tick(tid)
            self.assertEqual(self.sender.sent, [], f"notisen gick ut {vad}")
        self.scheduler._tick(SUNDAY)
        self.assertEqual(len(self.sender.sent), 1)

    def test_ett_konto_utan_prenumeration_ar_inte_med(self):
        self._user(subscribe=False)
        summary = self.scheduler.run_due(SUNDAY)
        self.assertEqual(summary["skickat"], 0)
        self.assertEqual(self.sender.sent, [])

    def test_en_borttappad_prenumeration_stads_bort_och_larmar_inte(self):
        user_id = self._user()
        endpoint = self.push.subscriptions_for(user_id)[0]["endpoint"]
        scheduler = self._scheduler(FakeSender(gone_for=[endpoint]))
        summary = scheduler.run_due(SUNDAY)
        self.assertEqual(summary["borttagna"], 1)
        self.assertEqual(self.push.subscriptions_for(user_id), [])


# ---- 2. samtycke ------------------------------------------------------------

class SamtyckeTest(SondagsnotisTestCase):
    def test_avstangd_veckonotis_ger_ingen_notis(self):
        user_id = self._user()
        self.notifications.set_preferences(user_id, {"week": False})
        summary = self.scheduler.run_due(SUNDAY)
        self.assertEqual(summary["utanSamtycke"], 1)
        self.assertEqual(self.sender.sent, [])

    def test_huvudbrytaren_stanger_av_aven_veckonotisen(self):
        user_id = self._user()
        self.notifications.set_preferences(user_id, {"all": False})
        self.scheduler.run_due(SUNDAY)
        self.assertEqual(self.sender.sent, [])

    def test_ett_nej_tar_ingen_plats_i_loggen_sa_ett_senare_ja_fungerar(self):
        """Avslaget respekteras - men det får inte tysta kontot för evigt
        genom att bränna dagens rad i push_log."""
        user_id = self._user()
        self.notifications.set_preferences(user_id, {"week": False})
        self.scheduler.run_due(SUNDAY)
        self.assertEqual(self.push.counts(30), {})
        self.notifications.set_preferences(user_id, {"week": True})
        self._scheduler().run_due(SUNDAY)
        self.assertEqual(len(self.sender.sent), 1)

    def test_andras_avstangning_stoppar_inte_min_notis(self):
        self._user("adam@example.com")
        sara = self._user("sara@example.com")
        self.notifications.set_preferences(sara, {"week": False})
        summary = self.scheduler.run_due(SUNDAY)
        self.assertEqual(summary["skickat"], 1)
        self.assertEqual(summary["utanSamtycke"], 1)


# ---- 3. användarens egna tal ------------------------------------------------

class TextenTest(unittest.TestCase):
    def test_talen_kommer_ur_kontots_synced_state(self):
        self.assertEqual(push_schedule.week_body(json.dumps({"middagar": 5, "personer": 4})),
                         "5 middagar för 4 personer — förslaget är redan klart.")

    def test_en_middag_och_en_person_boejs_ratt(self):
        self.assertEqual(push_schedule.week_body(json.dumps({"middagar": 1, "personer": 1})),
                         "1 middag för 1 person — förslaget är redan klart.")

    def test_hela_meningen_ar_den_uppdraget_bestallde(self):
        notis = push_schedule.week_notification(json.dumps({"middagar": 5, "personer": 4}))
        self.assertEqual(f"{notis['title']}. {notis['body']}",
                         "Dags att planera veckan. 5 middagar för 4 personer — "
                         "förslaget är redan klart.")

    def test_olasbara_tal_ger_den_generella_texten_aldrig_en_gissning(self):
        for blob in (None, "", "inte json", "[]", "{}", '{"middagar": 5}', '{"personer": 4}',
                     '{"middagar": 0, "personer": 4}', '{"middagar": 99, "personer": 4}',
                     '{"middagar": "fem", "personer": 4}', '{"middagar": 2.5, "personer": 4}',
                     '{"middagar": true, "personer": true}', '{"personer": 400, "middagar": 5}'):
            with self.subTest(blob=blob):
                body = push_schedule.week_body(blob)
                self.assertEqual(body, push_schedule.GENERIC_BODY)
                self.assertNotRegex(body, r"\d", "den generella texten får inte innehålla en siffra")

    def test_notisen_pekar_pa_veckoavsikten_inte_pa_startsidan(self):
        notis = push_schedule.week_notification("{}", "https://matjakt.store/app")
        self.assertEqual(notis["url"], "https://matjakt.store/app/?notis=vecka")

    def test_nyttolasten_ar_liten_nog_for_varje_push_tjanst(self):
        payload = json.dumps(push_schedule.week_notification(
            json.dumps({"middagar": 7, "personer": 12}), "https://matjakt.store/app"))
        self.assertLess(len(payload.encode("utf-8")), 1024)


class TextenNarDetSkickasTest(SondagsnotisTestCase):
    def test_varje_konto_far_sina_egna_tal(self):
        self._user("adam@example.com", middagar=5, personer=4)
        self._user("sara@example.com", middagar=2, personer=1)
        self._user("tom@example.com", middagar=None, personer=None)
        self.scheduler.run_due(SUNDAY)
        texter = sorted(sent["payload"]["body"] for sent in self.sender.sent)
        self.assertEqual(texter, sorted([
            "5 middagar för 4 personer — förslaget är redan klart.",
            "2 middagar för 1 person — förslaget är redan klart.",
            push_schedule.GENERIC_BODY,
        ]))


# ---- 4. fail closed utan nycklar --------------------------------------------

class UtanNycklarTest(SondagsnotisTestCase):
    def test_utan_publik_nyckel_skickas_ingenting_och_ingenting_kraschar(self):
        self._user()
        scheduler = self._scheduler(FakeSender(blocked=webpush.MISSING_PUBLIC))
        summary = scheduler.run_due(SUNDAY)
        self.assertEqual(summary["blockerat"], webpush.MISSING_PUBLIC)
        self.assertEqual(summary["skickat"], 0)
        self.assertEqual(self.push.counts(30), {}, "en blockerad körning får inte bränna dagen")

    def test_dagen_ar_kvar_nar_nyckeln_kommer(self):
        self._user()
        self._scheduler(FakeSender(blocked=webpush.MISSING_PUBLIC)).run_due(SUNDAY)
        summary = self.scheduler.run_due(SUNDAY)
        self.assertEqual(summary["skickat"], 1)

    def test_avsandaren_sager_vad_som_saknas(self):
        self.assertEqual(webpush.WebPushSender().blocked_reason(), webpush.MISSING_PUBLIC)
        self.assertEqual(webpush.WebPushSender(public_key="B_publik").blocked_reason(),
                         webpush.MISSING_PRIVATE)
        full = webpush.WebPushSender(public_key="B_publik", private_key="hemlig")
        self.assertEqual(full.blocked_reason(),
                         None if webpush.crypto_available() else webpush.MISSING_CRYPTO)

    def test_env_utan_nycklar_ger_en_avsandare_som_inte_kraschar(self):
        sender = webpush.WebPushSender.from_env({})
        self.assertFalse(sender.configured())
        self.assertEqual(sender.blocked_reason(), webpush.MISSING_PUBLIC)

    def test_status_gar_att_lasa_aven_nar_allt_ar_avstangt(self):
        self._user()
        status = self._scheduler(FakeSender(blocked=webpush.MISSING_PUBLIC)).status()
        self.assertEqual(status["skickasKl"], "17:00")
        self.assertEqual(status["dag"], "söndag")
        self.assertEqual(status["timezone"], "Europe/Stockholm")
        self.assertEqual(status["prenumeranter"], 1)
        self.assertEqual(status["blockerat"], webpush.MISSING_PUBLIC)


# ---- prenumerationslagret ---------------------------------------------------

class PrenumerationTest(SondagsnotisTestCase):
    def test_en_prenumeration_utan_https_avvisas(self):
        for bad in ({}, {"endpoint": "http://osakert.example/abc123def456"},
                    {"endpoint": "https://ok.example/abc123def456"},
                    {"endpoint": "kort", "keys": {"p256dh": "P", "auth": "A"}},
                    {"endpoint": "https://ok.example/abc123def456", "keys": {"p256dh": "P"}}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.push.subscribe(1, bad)

    def test_samma_webblasare_nytt_konto_byter_agare(self):
        adam = self._user("adam@example.com", endpoint="https://push.example/delad-telefon")
        sara = self._user("sara@example.com", subscribe=False)
        self.push.subscribe(sara, {"endpoint": "https://push.example/delad-telefon",
                                   "keys": {"p256dh": "P2", "auth": "A2"}})
        self.assertEqual(self.push.subscriptions_for(adam), [])
        self.assertEqual(len(self.push.subscriptions_for(sara)), 1)

    def test_bara_agaren_far_saga_upp_sin_prenumeration(self):
        adam = self._user("adam@example.com", endpoint="https://push.example/adams")
        sara = self._user("sara@example.com", subscribe=False)
        self.push.unsubscribe("https://push.example/adams", user_id=sara)
        self.assertEqual(len(self.push.subscriptions_for(adam)), 1)
        self.push.unsubscribe("https://push.example/adams", user_id=adam)
        self.assertEqual(self.push.subscriptions_for(adam), [])

    def test_raderat_konto_lamnar_ingen_prenumeration_kvar(self):
        user_id = self._user()
        self.scheduler.run_due(SUNDAY)
        self.push.forget_user(user_id)
        self.assertEqual(self.push.subscriptions_for(user_id), [])
        self.assertEqual(self.push.counts(30), {})


# ---- vägen in ---------------------------------------------------------------

class PushVagarnaTest(SondagsnotisTestCase):
    def setUp(self):
        super().setUp()
        self.households = HouseholdStore(Path(self._tmp.name) / "test.db")
        self.addCleanup(self.households.close)
        self.token, _user = self.accounts.register("router@example.com", "hemligt123")

    def _router(self, public_key="B_publik"):
        return HouseholdRouter(self.households, self.notifications, self.accounts,
                               "https://matjakt.store/app", push=self.push,
                               push_public_key=public_key)

    def _call(self, path, payload, token=None):
        return self._router().handle("POST", path, {}, payload,
                                     self.token if token is None else token)

    def test_utloggad_kommer_inte_at_prenumerationen(self):
        status, _body = self._call("/api/household/notifications/push",
                                   {"subscription": SUBSCRIPTION}, token="fel-token")
        self.assertEqual(status, 401)

    def test_en_prenumeration_sparas_och_slar_pa_veckonotisen(self):
        self.notifications.set_preferences(self.accounts.identity_for_token(self.token)[0],
                                           {"week": False})
        status, body = self._call("/api/household/notifications/push",
                                  {"subscription": SUBSCRIPTION, "week": True})
        self.assertEqual(status, 200)
        self.assertTrue(body["preferences"]["week"],
                        "brytaren ska följa med prenumerationen - inte gissas")
        user_id = self.accounts.identity_for_token(self.token)[0]
        self.assertEqual(len(self.push.subscriptions_for(user_id)), 1)

    def test_en_trasig_prenumeration_ger_400_inte_500(self):
        status, body = self._call("/api/household/notifications/push",
                                  {"subscription": {"endpoint": "http://osakert.example/abcdefghijklmnop"}})
        self.assertEqual(status, 400)
        self.assertIn("https", body["error"])

    def test_den_publika_nyckeln_foljer_med_notissvaret(self):
        status, body = self._router().handle("GET", "/api/household/notifications", {}, {}, self.token)
        self.assertEqual(status, 200)
        self.assertEqual(body["push"]["publicKey"], "B_publik")
        self.assertFalse(body["push"]["subscribed"])

    def test_utan_nyckel_i_miljon_far_klienten_tom_strang_inte_ett_fel(self):
        status, body = self._router(public_key="").handle(
            "GET", "/api/household/notifications", {}, {}, self.token)
        self.assertEqual(status, 200)
        self.assertEqual(body["push"]["publicKey"], "")

    def test_notissvaret_kraver_inte_ett_hushall(self):
        """Söndagsnotisen går till ett KONTO. Den som planerar ensam behöver
        påminnelsen precis lika mycket."""
        status, body = self._router().handle("GET", "/api/household/notifications", {}, {}, self.token)
        self.assertEqual(status, 200)
        self.assertIn("preferences", body)

    def test_att_saga_upp_tar_bort_raden(self):
        self._call("/api/household/notifications/push", {"subscription": SUBSCRIPTION})
        user_id = self.accounts.identity_for_token(self.token)[0]
        status, _body = self._call("/api/household/notifications/push/forget",
                                   {"endpoint": SUBSCRIPTION["endpoint"]})
        self.assertEqual(status, 200)
        self.assertEqual(self.push.subscriptions_for(user_id), [])


# ---- krypteringen, mot RFC:ernas egna testvektorer --------------------------

class WebPushKryptoTest(unittest.TestCase):
    def test_hkdf_mot_rfc_5869_testfall_1(self):
        okm = webpush.hkdf(bytes.fromhex("000102030405060708090a0b0c"), b"\x0b" * 22,
                           bytes.fromhex("f0f1f2f3f4f5f6f7f8f9"), 42)
        self.assertEqual(okm.hex(),
                         "3cb25f25faacd57a90434f64d0362f2a"
                         "2d2d0a90cf1a5a4c5db02d56ecc4c5bf"
                         "34007208d5b887185865")

    def test_nyckelharledningen_mot_rfc_8291_exemplet(self):
        """RFC 8291 §5 publicerar varje mellanvärde. Med den dokumenterade
        ECDH-hemligheten - det enda steget som kräver ett bibliotek - ska
        CEK och NONCE bli exakt de som står i RFC:n."""
        cek, nonce = webpush.content_keys(
            webpush.b64url_decode("DGv6ra1nlYgDCS1FRnbzlw"),
            webpush.b64url_decode("kyrL1jIIOHEzg3sM2ZWRHDRB62YACZhhSlknJ672kSs"),
            webpush.b64url_decode("BTBZMqHH6r4Tts7J_aSIgg"),
            webpush.b64url_decode("BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"),
            webpush.b64url_decode("BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8"))
        self.assertEqual(webpush.b64url(cek), "oIhVW04MRdy2XN9CiKLxTg")
        self.assertEqual(webpush.b64url(nonce), "4h_95klXJ5E_qnoN")

    def test_ramen_ar_den_rfc_8291_visar(self):
        vantat = webpush.b64url_decode(
            "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3v"
            "CYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXP"
            "XLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")
        byggd = webpush.aes128gcm_body(vantat[:16], vantat[21:86], vantat[86:])
        self.assertEqual(byggd, vantat)
        self.assertEqual(vantat[16:20].hex(), "00001000", "poststorleken ska vara 4096")
        self.assertEqual(vantat[20], 65, "avsändarnyckeln är 65 byte okomprimerad P-256")

    def test_publiken_ar_tjanstens_ursprung_inte_hela_endpointen(self):
        self.assertEqual(
            webpush.vapid_audience("https://fcm.googleapis.com/fcm/send/hemligt-id"),
            "https://fcm.googleapis.com")
        for bad in ("", "http://osakert.example/abc", "inte en adress"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                webpush.vapid_audience(bad)

    def test_jwt_huvudet_ar_es256_och_anspraken_gar_ut(self):
        claims = webpush.vapid_claims("https://push.example/abc", "mailto:adam@example.com", 1_000_000)
        self.assertEqual(claims["aud"], "https://push.example")
        self.assertEqual(claims["sub"], "mailto:adam@example.com")
        self.assertEqual(claims["exp"], 1_000_000 + webpush.JWT_LIFETIME_SECONDS)
        header, body = webpush.jwt_signing_input(claims).decode("ascii").split(".")
        self.assertEqual(json.loads(webpush.b64url_decode(header)), {"typ": "JWT", "alg": "ES256"})
        self.assertEqual(json.loads(webpush.b64url_decode(body)), claims)

    def test_authorization_rubriken_bar_bada_halvorna(self):
        signatur = bytes([1, 2])
        header = webpush.authorization_header(b"huvud.kropp", signatur, "B_publik")
        self.assertEqual(header, "vapid t=huvud.kropp." + webpush.b64url(signatur) + ", k=B_publik")

    def test_en_saknad_prenumeration_blir_WebPushGone_allt_annat_blir_fel(self):
        """404/410 betyder "ta bort raden"; 500 betyder "försök inte städa".
        Skillnaden avgör om en avinstallerad app blir ett larm varje söndag."""
        def opener_for(code):
            def opener(_request):
                raise HTTPError("https://push.example/abc", code, "nej", {}, None)
            return opener
        for code in (404, 410):
            sender = webpush.WebPushSender(opener=opener_for(code))
            with self.assertRaises(WebPushGone):
                sender.deliver("https://push.example/abc", b"kropp", {})
        for code in (429, 500):
            sender = webpush.WebPushSender(opener=opener_for(code))
            with self.assertRaises(webpush.WebPushError) as fel:
                sender.deliver("https://push.example/abc", b"kropp", {})
            self.assertNotIsInstance(fel.exception, WebPushGone)

    def test_send_utan_nycklar_kastar_innan_natet_ens_rors(self):
        rord = []
        sender = webpush.WebPushSender(opener=lambda request: rord.append(request))
        with self.assertRaises(webpush.WebPushError):
            sender.send(SUBSCRIPTION, "{}")
        self.assertEqual(rord, [], "utan nycklar ska ingenting gå ut på nätet")


if __name__ == "__main__":
    unittest.main()
