import sys
import tempfile
import unittest
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
            "email": "ada@example.com", "premium": False, "plan": "free", "trialEndsAt": None, "trialUsed": False,
            "subscriptionStatus": None, "subscriptionPlan": None, "subscriptionPeriodEnd": None,
            "subscriptionCancelAtPeriodEnd": False, "emailVerified": False,
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

    def test_redeem_premium_upgrades_user(self):
        token, _ = self.store.register("ada@example.com", "hemligt123")
        user = self.store.redeem_premium(token, "hemlig-kod", expected_code="hemlig-kod")
        self.assertTrue(user["premium"])
        self.assertTrue(self.store.user_for_token(token)["premium"])

    def test_redeem_premium_rejects_wrong_code(self):
        token, _ = self.store.register("ada@example.com", "hemligt123")
        with self.assertRaises(AccountError):
            self.store.redeem_premium(token, "fel-kod", expected_code="hemlig-kod")

    def test_redeem_premium_rejects_when_not_configured(self):
        token, _ = self.store.register("ada@example.com", "hemligt123")
        with self.assertRaises(AccountError):
            self.store.redeem_premium(token, "hemlig-kod", expected_code="")

    def test_redeem_premium_requires_login(self):
        with self.assertRaises(AccountError):
            self.store.redeem_premium("okant-token", "hemlig-kod", expected_code="hemlig-kod")

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


if __name__ == "__main__":
    unittest.main()
