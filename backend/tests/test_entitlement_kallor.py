# -*- coding: utf-8 -*-
"""P02b: Premium bärs av en KÄLLA med en GILTIGHETSTID - och Apple är en av dem.

Före P02b fanns Stripe, inlösta koder, den eviga flaggan och provperioden,
och `plan_for_user` läste `premium` + `subscriptionPlan`. Apple fanns inte
alls, och hade den lagts in som "en flagga till" hade en Apple-prenumerant
på årsplanen kallats månad (hon har ingen subscriptionPlan), en utgången
Apple-prenumeration kunnat leva vidare (ingen respitregel), och tratten
räknat henne som kompenserad (premiumSource okänd).

Fallen nedan är briefens: en användare med Stripe-källa, en med kod, en med
Apple, en med flera samtidigt - `plan_for_user` ger rätt plan - och en
utgången Apple-källa ger Free. Plus det som gör modellen sann: en
återbetalning släcker, en äldre notis skriver inte över en nyare, tratten
räknar Apple som betalande, och grandfathering-regeln i `plan_for_user`
("a paying or comped user must never wake up demoted by a refactor") håller
för varje källa som fanns före paketet.
"""

import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.accounts import AccountStore, features  # noqa: E402
from services.accounts.store import APPLE_STATUSES, ENTITLEMENT_SOURCE_OF  # noqa: E402
from services.analytics import AnalyticsStore, manadsvarden  # noqa: E402

MONTHLY = features.PRICING["monthly"]["storekitProductId"]
YEARLY = features.PRICING["yearly"]["storekitProductId"]


def _om(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


class Bas(unittest.TestCase):
    def gammal_trial(self, user_id, dagar=7):
        """En trial utdelad före J3b, skriven som data - exakt raden som
        grant_activation_trial skrev när den fanns."""
        ends = (datetime.now(timezone.utc) + timedelta(days=dagar)).isoformat()
        with self.store._lock:
            self.store._connection.execute(
                "UPDATE users SET trial_ends_at = ?, trial_used = 1 WHERE id = ?", (ends, int(user_id)))
            self.store._connection.commit()
        return ends

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = AccountStore(Path(self._tmp.name) / "konton.db")

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def konto(self, epost="a@example.com"):
        token, _ = self.store.register(epost, "hemligt123")
        user_id = self.store.connection.execute(
            "SELECT id FROM users WHERE email = ?", (epost,)).fetchone()[0]
        return token, int(user_id)

    def me(self, token):
        return self.store.user_for_token(token)

    def stripe(self, user_id, plan="monthly", status="active"):
        """Samma kolumner som Stripe-webhooken skriver."""
        self.store.connection.execute(
            "UPDATE users SET subscription_status = ?, subscription_plan = ?, "
            "subscription_period_end = ?, stripe_subscription_id = 'sub_1' WHERE id = ?",
            (status, plan, _om(days=20), user_id))
        self.store.connection.commit()

    def apple(self, user_id, product=YEARLY, status="active", expires=None, **extra):
        return self.store.apply_apple_subscription(
            user_id, original_transaction_id=extra.pop("otid", "2000000123"),
            product_id=product, expires_at_iso=expires or _om(days=20),
            status=status, **extra)


class EnKallaITaget(Bas):
    def test_stripe_kallan_ger_sin_plan(self):
        token, user_id = self.konto()
        self.stripe(user_id, "yearly")
        me = self.me(token)
        self.assertEqual(features.plan_for_user(me), "premium_yearly")
        self.assertEqual(me["entitlementSource"], "stripe")
        self.assertEqual(me["premiumSource"], "subscription")
        self.assertEqual(me["entitlementUntil"], me["subscriptionPeriodEnd"])
        self.assertIsNone(me["appleSubscription"])

    def test_kod_kallan_ar_manad_med_slutdatum(self):
        token, user_id = self.konto()
        until = self.store.extend_premium(user_id, 30)
        me = self.me(token)
        self.assertEqual(features.plan_for_user(me), "premium_monthly")
        self.assertEqual(me["entitlementSource"], "code")
        self.assertEqual(me["entitlementUntil"], until)

    def test_comp_kallan_ar_evig(self):
        token, user_id = self.konto()
        self.store.connection.execute("UPDATE users SET premium = 1 WHERE id = ?", (user_id,))
        self.store.connection.commit()
        me = self.me(token)
        self.assertEqual(features.plan_for_user(me), "premium_monthly")
        self.assertEqual(me["entitlementSource"], "comp")
        self.assertIsNone(me["entitlementUntil"], "comp har inget slutdatum")

    def test_apple_arsplanen_ar_premium_yearly(self):
        # Det här är fallet som inte gick att uttrycka före P02b: hon har
        # ingen subscriptionPlan alls, och skulle ha kallats månad.
        token, user_id = self.konto()
        self.assertEqual(self.apple(user_id, YEARLY), "applied")
        me = self.me(token)
        self.assertTrue(me["premium"])
        self.assertEqual(features.plan_for_user(me), "premium_yearly")
        self.assertEqual(me["plan"], "premium_yearly")
        self.assertEqual(me["entitlementSource"], "apple")
        self.assertEqual(me["premiumSource"], "apple")
        self.assertIsNone(me["subscriptionPlan"], "Apple skriver aldrig Stripes kolumner")
        self.assertEqual(me["appleSubscription"]["productId"], YEARLY)
        self.assertEqual(me["appleSubscription"]["status"], "active")
        self.assertEqual(me["entitlementUntil"], me["appleSubscription"]["expiresAt"])

    def test_apple_manadsplanen_ar_premium_monthly(self):
        token, user_id = self.konto()
        self.apple(user_id, MONTHLY)
        self.assertEqual(features.plan_for_user(self.me(token)), "premium_monthly")

    def test_trial_kallan_har_giltighetstid(self):
        # En trial som delades ut FÖRE beslutet 2026-09-19 (J3b: ingen
        # automatisk trial) är en EGEN källa med slutdatum, och den läses
        # tills den löper ut. Ingen metod skriver den längre - raden är data.
        token, user_id = self.konto()
        ends = self.gammal_trial(user_id)
        me = self.me(token)
        self.assertTrue(me["premium"])
        self.assertEqual(me["entitlementSource"], "trial")
        self.assertEqual(me["premiumSource"], "trial")
        self.assertEqual(me["entitlementUntil"], ends)
        self.assertEqual(features.plan_for_user(me), "premium_monthly")

    def test_utgangen_trial_ger_free(self):
        token, user_id = self.konto()
        self.store.connection.execute(
            "UPDATE users SET trial_ends_at = ?, trial_used = 1 WHERE id = ?", (_om(days=-1), user_id))
        self.store.connection.commit()
        me = self.me(token)
        self.assertFalse(me["premium"])
        self.assertIsNone(me["entitlementSource"])

    def test_apples_respit_bar_premium(self):
        # DID_FAIL_TO_RENEW med GRACE_PERIOD: Apple säger "continue to
        # provide service through the grace period".
        token, user_id = self.konto()
        self.apple(user_id, status="grace", expires=_om(days=10))
        me = self.me(token)
        self.assertTrue(me["premium"])
        self.assertEqual(me["entitlementSource"], "apple")


class UtgangenAppleKallaGerFree(Bas):
    def test_utgangen_apple_kalla_ger_free(self):
        # Briefens fall, ordagrant. Slutdatumet ligger långt bakom oss - även
        # respiten för ett tappat DID_RENEW har passerat.
        token, user_id = self.konto()
        self.apple(user_id, status="active", expires=_om(days=-40))
        me = self.me(token)
        self.assertFalse(me["premium"])
        self.assertEqual(features.plan_for_user(me), "free")
        self.assertIsNone(me["entitlementSource"])
        self.assertIsNone(me["entitlementUntil"])
        # Men raden finns kvar, så kontosidan kan säga vad som hände.
        self.assertEqual(me["appleSubscription"]["status"], "active")

    def test_expired_har_ingen_respit(self):
        # EXPIRED är en notis vi HAR fått. Respiten finns för notiser vi
        # saknar, inte för att ge bort tre dagar till den som sagt upp sig.
        token, user_id = self.konto()
        self.apple(user_id, status="expired", expires=_om(hours=-1))
        self.assertFalse(self.me(token)["premium"])

    def test_billing_retry_utan_respit_ger_free(self):
        # DID_FAIL_TO_RENEW utan GRACE_PERIOD: "you can stop providing the
        # subscription service".
        token, user_id = self.konto()
        self.apple(user_id, status="billing_retry", expires=_om(hours=-1))
        self.assertFalse(self.me(token)["premium"])

    def test_levande_status_utan_slutdatum_ar_inte_premium(self):
        # Fail closed: en rad utan datum är en rad vi inte förstår.
        token, user_id = self.konto()
        self.store.connection.execute(
            "UPDATE users SET apple_status = 'active', apple_expires_at = NULL WHERE id = ?", (user_id,))
        self.store.connection.commit()
        self.assertFalse(self.me(token)["premium"])

    def test_aterbetalning_slacker_allt_apple_gav_och_bakdorren(self):
        # REFUND/REVOKE: samma regel som revoke_after_refund för Stripe - den
        # manuella flaggan och provperioden följer med, annars ligger en
        # gammal kod-inlösning kvar som osynlig bakdörr.
        token, user_id = self.konto()
        self.store.connection.execute(
            "UPDATE users SET premium = 1, trial_ends_at = ? WHERE id = ?", (_om(days=3), user_id))
        self.store.connection.commit()
        self.apple(user_id, status="revoked", expires=_om(hours=-1))
        me = self.me(token)
        self.assertFalse(me["premium"])
        self.assertIsNone(me["trialEndsAt"])
        self.assertEqual(me["appleSubscription"]["status"], "revoked")


class FleraKallorSamtidigt(Bas):
    def test_stripe_och_apple_levande_stripe_vinner_och_planen_ar_stripes(self):
        token, user_id = self.konto()
        self.stripe(user_id, "monthly")
        self.apple(user_id, YEARLY)
        me = self.me(token)
        self.assertEqual(me["entitlementSource"], "stripe")
        self.assertEqual(features.plan_for_user(me), "premium_monthly")

    def test_apple_och_kod_apple_vinner_och_planen_ar_apples(self):
        token, user_id = self.konto()
        self.store.extend_premium(user_id, 30)
        self.apple(user_id, YEARLY)
        me = self.me(token)
        self.assertEqual(me["entitlementSource"], "apple")
        self.assertEqual(features.plan_for_user(me), "premium_yearly")

    def test_apple_gar_fore_stripes_respit(self):
        # En betald period hos Apple är mer sann än en nekad dragning hos
        # Stripe. Respiten står kvar i subscriptionStatus, källan är Apple.
        token, user_id = self.konto()
        self.stripe(user_id, "monthly", status="past_due")
        self.store.connection.execute(
            "UPDATE users SET past_due_since = ? WHERE id = ?", (_om(days=-1), user_id))
        self.store.connection.commit()
        self.apple(user_id, MONTHLY)
        me = self.me(token)
        self.assertEqual(me["entitlementSource"], "apple")
        self.assertEqual(me["subscriptionStatus"], "past_due")

    def test_apple_gar_fore_provperioden(self):
        # Betalande före gåva: den som köpt via App Store mitt i sina sju
        # gratisdagar är en Apple-kund, och planen är den hon köpte.
        token, user_id = self.konto()
        self.gammal_trial(user_id)
        self.apple(user_id, YEARLY)
        me = self.me(token)
        self.assertEqual(me["entitlementSource"], "apple")
        self.assertEqual(features.plan_for_user(me), "premium_yearly")

    def test_utgangen_apple_och_levande_kod_ger_kod(self):
        token, user_id = self.konto()
        self.apple(user_id, status="expired", expires=_om(days=-1))
        until = self.store.extend_premium(user_id, 30)
        me = self.me(token)
        self.assertTrue(me["premium"])
        self.assertEqual(me["entitlementSource"], "code")
        self.assertEqual(me["entitlementUntil"], until)


class GrandfatheringHaller(unittest.TestCase):
    """plan_for_user utan `plan` i payloaden tar exakt den gamla vägen."""

    def test_payload_utan_plan_faller_tillbaka_som_fore_p02b(self):
        self.assertEqual(features.plan_for_user({"premium": True}), "premium_monthly")
        self.assertEqual(features.plan_for_user({"premium": True, "subscriptionPlan": "yearly"}),
                         "premium_yearly")
        self.assertEqual(features.plan_for_user({"premium": False, "plan": "premium_yearly"}), "free",
                         "plan utan premium får aldrig ge Premium")

    def test_plan_ur_payloaden_vinner_over_subscription_plan(self):
        # En Apple-årsprenumerant med en gammal, död Stripe-månadsplan kvar
        # i kolumnen: _to_public har redan avgjort att Apple vinner.
        self.assertEqual(features.plan_for_user(
            {"premium": True, "plan": "premium_yearly", "subscriptionPlan": "monthly"}), "premium_yearly")

    def test_vokabularen_tacker_varje_premiumsource(self):
        for källa in ("subscription", "grace", "apple", "trial", "code", "comped"):
            self.assertIn(källa, ENTITLEMENT_SOURCE_OF)
        self.assertEqual(set(ENTITLEMENT_SOURCE_OF.values()) - {None},
                         {"apple", "stripe", "code", "comp", "trial"})


class OrdningOchIdempotens(Bas):
    def test_en_aldre_notis_skriver_inte_over_en_nyare(self):
        token, user_id = self.konto()
        self.assertEqual(self.apple(user_id, YEARLY, signed_date=2_000), "applied")
        self.assertEqual(self.apple(user_id, MONTHLY, status="expired", expires=_om(days=-1),
                                    signed_date=1_000), "ignored")
        me = self.me(token)
        self.assertTrue(me["premium"])
        self.assertEqual(me["appleSubscription"]["productId"], YEARLY)

    def test_samma_signeringstid_slapps_igenom(self):
        # Appens anmälan och notisen kan bära samma transaktion.
        _, user_id = self.konto()
        self.apple(user_id, YEARLY, signed_date=2_000)
        self.assertEqual(self.apple(user_id, YEARLY, signed_date=2_000), "applied")

    def test_okand_status_avvisas(self):
        _, user_id = self.konto()
        with self.assertRaises(ValueError):
            self.apple(user_id, status="paid")
        self.assertEqual(len(APPLE_STATUSES), 5)

    def test_okant_konto(self):
        self.assertEqual(self.apple(99_999), "unknown_user")

    def test_uppslag_pa_originaltransaktionen(self):
        _, user_id = self.konto()
        self.apple(user_id, otid="2000000999")
        self.assertEqual(self.store.user_id_for_apple_transaction("2000000999"), user_id)
        self.assertIsNone(self.store.user_id_for_apple_transaction("finns-inte"))
        self.assertIsNone(self.store.user_id_for_apple_transaction(None))
        self.assertEqual(self.store.apple_subscription(user_id)["apple_product_id"], YEARLY)

    def test_any_premium_ser_apple(self):
        # Hushållets plan frågas via any_premium - Apple ska räknas där med.
        _, user_id = self.konto()
        self.assertFalse(self.store.any_premium([user_id]))
        self.apple(user_id)
        self.assertTrue(self.store.any_premium([user_id]))

    def test_ingen_metod_kan_dela_ut_en_trial(self):
        # J3b. Den som fick sju dagar före beslutet behåller dem (raden
        # läses); ingen kod kan skriva en ny.
        self.assertFalse(hasattr(self.store, "grant_activation_trial"))


class ExportenOchTratten(Bas):
    def test_exporten_bar_apple_raden(self):
        token, user_id = self.konto()
        self.apple(user_id, YEARLY, otid="2000000555")
        export = self.store.export_account(token)
        apple = export["prenumeration"]["apple"]
        self.assertEqual(apple["produkt"], YEARLY)
        self.assertEqual(apple["originalTransactionId"], "2000000555")
        self.assertEqual(apple["status"], "active")

    def test_tratten_raknar_apple_som_betalande_med_mrr(self):
        # A01/I7: tratten fick inte blanda ihop kompenserad och betalande.
        # En Apple-prenumerant betalar - och årsplanen periodiseras precis
        # som Stripes.
        _, user_id = self.konto()
        self.apple(user_id, YEARLY)
        matning = AnalyticsStore(self.store.connection, lock=self.store.lock)
        totalt = matning.funnel(
            premium_of=lambda row: AccountStore._to_public(row)["premium"],
            premium_source_of=lambda row: AccountStore._to_public(row)["premiumSource"])["totalt"]
        self.assertEqual(totalt["premiumBetalande"], 1)
        self.assertEqual(totalt["premiumApple"], 1)
        self.assertEqual(totalt["premiumStripe"], 0)
        self.assertEqual(totalt["premiumKompenserad"], 0)
        self.assertAlmostEqual(totalt["mrrKronor"], manadsvarden()["yearly"], places=2)
        self.assertEqual(totalt["betalandeUtanKandPlan"], 0)
        self.assertEqual(totalt["harHaftPrenumeration"], 1)

    def test_en_apple_prenumerant_som_stangt_av_fornyelsen_flaggas(self):
        _, user_id = self.konto()
        self.apple(user_id, MONTHLY, auto_renew=False)
        matning = AnalyticsStore(self.store.connection, lock=self.store.lock)
        totalt = matning.funnel(
            premium_of=lambda row: AccountStore._to_public(row)["premium"],
            premium_source_of=lambda row: AccountStore._to_public(row)["premiumSource"])["totalt"]
        self.assertEqual(totalt["sagerUppVidPeriodslut"], 1)


class MigrationenArAdditiv(unittest.TestCase):
    def test_en_databas_fran_fore_p02b_far_kolumnerna_och_behaller_raden(self):
        # Föregående release skrev en rad utan apple_*; dagens kod öppnar
        # filen, lägger till kolumnerna och rör inte raden. Det är
        # rollbackplanen i miniatyr - K6:s test_migrationer gör samma sak
        # mot den committade fixturen.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            väg = Path(tmp) / "konton.db"
            AccountStore(väg).close()
            rå = sqlite3.connect(väg)
            kolumner = {rad[1] for rad in rå.execute("PRAGMA table_info(users)")}
            rå.close()
            for kolumn in ("apple_original_transaction_id", "apple_product_id", "apple_expires_at",
                           "apple_status", "apple_auto_renew", "apple_environment", "apple_signed_date"):
                self.assertIn(kolumn, kolumner)
            # En INSERT med bara gamla kolumner ska gå igenom: inga NOT NULL
            # utan DEFAULT bland de nya.
            rå = sqlite3.connect(väg)
            rå.execute("INSERT INTO users (email, password_hash, salt, premium, created_at) "
                       "VALUES ('x@y.se', 'h', 's', 0, '2026-09-01T00:00:00+00:00')")
            rå.commit()
            rå.close()
            store = AccountStore(väg)
            try:
                self.assertIsNone(store.apple_subscription(1))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
