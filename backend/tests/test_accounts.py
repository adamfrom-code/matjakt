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
            "email": "ada@example.com", "premium": False, "trialEndsAt": None, "trialUsed": False,
            "subscriptionStatus": None, "subscriptionPlan": None, "subscriptionPeriodEnd": None,
            "subscriptionCancelAtPeriodEnd": False,
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

    def test_start_trial_grants_premium_with_end_date(self):
        token, _ = self.store.register("ada@example.com", "hemligt123")
        user = self.store.start_trial(token)
        self.assertTrue(user["premium"])
        self.assertIsNotNone(user["trialEndsAt"])
        self.assertTrue(user["trialUsed"])

    def test_start_trial_rejects_second_trial(self):
        token, _ = self.store.register("ada@example.com", "hemligt123")
        self.store.start_trial(token)
        with self.assertRaises(AccountError):
            self.store.start_trial(token)

    def test_start_trial_rejects_existing_premium(self):
        token, _ = self.store.register("ada@example.com", "hemligt123")
        self.store.redeem_premium(token, "hemlig-kod", expected_code="hemlig-kod")
        with self.assertRaises(AccountError):
            self.store.start_trial(token)

    def test_start_trial_requires_login(self):
        with self.assertRaises(AccountError):
            self.store.start_trial("okant-token")


if __name__ == "__main__":
    unittest.main()
