import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.accounts import AccountError, AccountStore  # noqa: E402


class AccountStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = AccountStore(Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self.store.close()
        self._tmpdir.cleanup()

    def test_register_then_login(self):
        token, user = self.store.register("Ada@Example.com", "hemligt123")
        self.assertTrue(token)
        self.assertEqual(user, {
            "email": "ada@example.com", "premium": False, "premiumSource": None, "plan": "free", "trialEndsAt": None, "trialUsed": False,
            "subscriptionStatus": None, "subscriptionPlan": None, "subscriptionPeriodEnd": None,
            "subscriptionCancelAtPeriodEnd": False,
            # J5: respiten vid nekat kort, och adressbytet som väntar på
            # bekräftelse. Null när inget är på gång - en banderoll ska inte
            # kunna ritas av misstag.
            "subscriptionGraceUntil": None, "pendingEmail": None,
            "premiumUntil": None,
            # P02b: en entitlement-sanning - källan i briefens vokabulär, när
            # den tar slut, och Apples egen rad. Null på ett nytt konto.
            "entitlementSource": None, "entitlementUntil": None, "appleSubscription": None,
            "emailVerified": False, "marketingConsent": False,
        })
        login_token, login_user = self.store.login("ada@example.com", "hemligt123")
        self.assertTrue(login_token)
        self.assertEqual(login_user, user)

    def test_register_rejects_duplicate_email(self):
        self.store.register("ada@example.com", "hemligt123")
        with self.assertRaises(AccountError):
            self.store.register("ada@example.com", "annat-losenord")

    def test_register_rejects_short_password(self):
        with self.assertRaises(AccountError):
            self.store.register("ada@example.com", "kort")

    def test_register_rejects_invalid_email(self):
        with self.assertRaises(AccountError):
            self.store.register("inte-en-epost", "hemligt123")

    def test_login_rejects_wrong_password(self):
        self.store.register("ada@example.com", "hemligt123")
        with self.assertRaises(AccountError):
            self.store.login("ada@example.com", "fel-losenord")

    def test_login_rejects_unknown_email(self):
        with self.assertRaises(AccountError):
            self.store.login("okand@example.com", "hemligt123")

    def test_user_for_token_returns_none_for_unknown_token(self):
        self.assertIsNone(self.store.user_for_token("okant-token"))

    def test_user_for_token_returns_user_for_valid_session(self):
        token, user = self.store.register("ada@example.com", "hemligt123")
        self.assertEqual(self.store.user_for_token(token), user)

    def test_logout_invalidates_token(self):
        token, _ = self.store.register("ada@example.com", "hemligt123")
        self.store.logout(token)
        self.assertIsNone(self.store.user_for_token(token))

    # H5: `redeem_premium` är borta. Den jämförde mot en EVIG env-sträng och
    # satte en evig boolean. Inlösen är numera en rad i premium_codes - med
    # tak, utgång och räknare, prövad i test_referral_h5 - och kontolagrets
    # halva är den här: att lägga på TID.
    def test_extend_premium_grants_days_not_eternity(self):
        token, _ = self.store.register("ada@example.com", "hemligt123")
        user_id = self.store.user_id_for_token(token)
        until = self.store.extend_premium(user_id, 30)
        self.assertTrue(until)
        user = self.store.user_for_token(token)
        self.assertTrue(user["premium"])
        self.assertEqual(user["premiumSource"], "code")
        self.assertEqual(user["premiumUntil"], until)

    def test_extend_premium_stacks_instead_of_overwriting(self):
        """Räknas det från nu skulle en andra kod FÖRKORTA den första."""
        token, _ = self.store.register("ada@example.com", "hemligt123")
        user_id = self.store.user_id_for_token(token)
        first = self.store.extend_premium(user_id, 30)
        second = self.store.extend_premium(user_id, 30)
        self.assertGreater(second, first)

    def test_expired_days_stop_counting_by_themselves(self):
        """Hela skillnaden mot den eviga flaggan: ingen behöver städa."""
        token, _ = self.store.register("ada@example.com", "hemligt123")
        user_id = self.store.user_id_for_token(token)
        self.store.extend_premium(user_id, 30)
        self.store.connection.execute(
            "UPDATE users SET premium_until = ? WHERE id = ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), user_id))
        self.store.connection.commit()
        self.assertFalse(self.store.user_for_token(token)["premium"])

    def test_extend_premium_on_a_missing_account_does_nothing(self):
        self.assertIsNone(self.store.extend_premium(99999, 30))

    def test_verify_email_marks_account_verified(self):
        self.store.register("ada@example.com", "hemligt123")
        token = self.store.create_verification_token_for_email("ada@example.com")
        user = self.store.verify_email(token)
        self.assertTrue(user["emailVerified"])

    def test_verify_email_rejects_unknown_token(self):
        with self.assertRaises(AccountError):
            self.store.verify_email("okant-token")

    def test_verify_email_token_is_single_use(self):
        self.store.register("ada@example.com", "hemligt123")
        token = self.store.create_verification_token_for_email("ada@example.com")
        self.store.verify_email(token)
        with self.assertRaises(AccountError):
            self.store.verify_email(token)

    def test_resend_verification_rejects_already_verified(self):
        session_token, _ = self.store.register("ada@example.com", "hemligt123")
        verify_token = self.store.create_verification_token_for_email("ada@example.com")
        self.store.verify_email(verify_token)
        with self.assertRaises(AccountError):
            self.store.resend_verification(session_token)

    def test_password_reset_flow(self):
        self.store.register("ada@example.com", "hemligt123")
        reset_token = self.store.request_password_reset("ada@example.com")
        self.assertIsNotNone(reset_token)
        self.store.reset_password(reset_token, "nyttlosenord123")
        with self.assertRaises(AccountError):
            self.store.login("ada@example.com", "hemligt123")
        new_token, _ = self.store.login("ada@example.com", "nyttlosenord123")
        self.assertTrue(new_token)

    def test_password_reset_unknown_email_returns_none_not_error(self):
        result = self.store.request_password_reset("okand@example.com")
        self.assertIsNone(result)

    def test_password_reset_invalidates_other_sessions(self):
        old_session, _ = self.store.register("ada@example.com", "hemligt123")
        reset_token = self.store.request_password_reset("ada@example.com")
        self.store.reset_password(reset_token, "nyttlosenord123")
        self.assertIsNone(self.store.user_for_token(old_session))

    def test_password_reset_rejects_expired_or_unknown_token(self):
        with self.assertRaises(AccountError):
            self.store.reset_password("okant-token", "nyttlosenord123")

    def test_password_reset_rejects_short_password(self):
        self.store.register("ada@example.com", "hemligt123")
        reset_token = self.store.request_password_reset("ada@example.com")
        with self.assertRaises(AccountError):
            self.store.reset_password(reset_token, "kort")

    def test_delete_account_removes_login_and_session(self):
        token, _ = self.store.register("ada@example.com", "hemligt123")
        self.store.delete_account(token)
        self.assertIsNone(self.store.user_for_token(token))
        with self.assertRaises(AccountError):
            self.store.login("ada@example.com", "hemligt123")

    def test_delete_account_requires_login(self):
        with self.assertRaises(AccountError):
            self.store.delete_account("okant-token")


class ResetTokenIsSingleUse(unittest.TestCase):
    """Release gate: en förbrukad återställningslänk får inte fungera igen."""

    def test_used_reset_token_is_rejected_the_second_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AccountStore(Path(tmp) / "t.db")
            try:
                store.register("engang@example.com", "hemligt123")
                token = store.request_password_reset("engang@example.com")
                store.reset_password(token, "nyttlosen456")
                with self.assertRaises(AccountError):
                    store.reset_password(token, "annatlosen789")
                store.login("engang@example.com", "nyttlosen456")     # det första bytet gäller
            finally:
                store.close()


class SharedConnectionIsThreadSafe(unittest.TestCase):
    """Alla servertrådar delar en SQLite-anslutning. Utan lås kunde en
    tråds commit() nollställa en annan tråds pågående SELECT, så en giltig
    session svarade "inte inloggad" mitt i en annan begäran (sett i CI
    under Premium-aktiveringen). Läsningar och skrivningar i parallell ska
    aldrig ge ett falskt None för en giltig token."""

    def test_concurrent_reads_never_lose_a_valid_session(self):
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            store = AccountStore(Path(tmp) / "t.db")
            try:
                token, _ = store.register("tradsaker@example.com", "hemligt123")
                misses, errors = [], []
                stop = threading.Event()

                def reader():
                    while not stop.is_set():
                        try:
                            if store.user_for_token(token) is None:
                                misses.append(1)
                        except Exception as error:   # pragma: no cover - ska inte hända
                            errors.append(repr(error))

                def writer():
                    for i in range(300):
                        try:
                            store.set_synced_state(token, '{"i": %d}' % i)
                            store.apply_subscription_event("cus_x", "sub_x", "active", None, False, "monthly",
                                                           event_created=i)
                        except Exception as error:   # pragma: no cover
                            errors.append(repr(error))
                    stop.set()

                threads = [threading.Thread(target=reader) for _ in range(4)] + [threading.Thread(target=writer)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=60)
                self.assertEqual(errors, [])
                self.assertEqual(misses, [])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
