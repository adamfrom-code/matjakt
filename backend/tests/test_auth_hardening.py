# -*- coding: utf-8 -*-
"""Tests for the two auth gaps: rate limiting and changing a password.

Both protect the same thing from different directions - rate limiting stops
someone guessing their way in, changing a password stops someone who already
got in from staying in.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.accounts import ratelimit  # noqa: E402
from services.accounts.store import AccountError, AccountStore  # noqa: E402


class RateLimitTest(unittest.TestCase):
    def setUp(self):
        ratelimit.reset()
        self.addCleanup(ratelimit.reset)

    def test_allows_attempts_up_to_the_limit(self):
        limit, _ = ratelimit.LIMITS["login"]
        for _ in range(limit):
            ratelimit.check("login", "1.2.3.4", "a@example.com")

    def test_refuses_the_attempt_after_the_limit(self):
        limit, _ = ratelimit.LIMITS["login"]
        for _ in range(limit):
            ratelimit.check("login", "1.2.3.4", "a@example.com")
        with self.assertRaises(ratelimit.RateLimited) as caught:
            ratelimit.check("login", "1.2.3.4", "a@example.com")
        self.assertGreater(caught.exception.retry_after, 0)

    def test_a_second_account_from_the_same_ip_is_still_limited(self):
        """Limiting by account alone would let one IP walk a whole user
        list, a few guesses per account."""
        limit, _ = ratelimit.LIMITS["login"]
        for index in range(limit):
            ratelimit.check("login", "1.2.3.4", f"user{index}@example.com")
        with self.assertRaises(ratelimit.RateLimited):
            ratelimit.check("login", "1.2.3.4", "someone-else@example.com")

    def test_the_same_account_from_a_new_ip_is_still_limited(self):
        """Limiting by IP alone would let a botnet spread guesses at one
        account across many addresses."""
        limit, _ = ratelimit.LIMITS["login"]
        for index in range(limit):
            ratelimit.check("login", f"10.0.0.{index}", "target@example.com")
        with self.assertRaises(ratelimit.RateLimited):
            ratelimit.check("login", "10.0.99.99", "target@example.com")

    def test_an_unrelated_account_and_ip_is_unaffected(self):
        limit, _ = ratelimit.LIMITS["login"]
        for _ in range(limit):
            ratelimit.check("login", "1.2.3.4", "a@example.com")
        ratelimit.check("login", "9.9.9.9", "b@example.com")  # must not raise

    def test_success_forgives_earlier_failures(self):
        """A person who mistypes twice and then gets it right must not stay
        throttled for the rest of the window."""
        for _ in range(3):
            ratelimit.check("login", "1.2.3.4", "a@example.com")
        ratelimit.clear_on_success("login", "1.2.3.4", "a@example.com")
        limit, _ = ratelimit.LIMITS["login"]
        for _ in range(limit):
            ratelimit.check("login", "1.2.3.4", "a@example.com")

    def test_actions_have_separate_budgets(self):
        limit, _ = ratelimit.LIMITS["register"]
        for _ in range(limit):
            ratelimit.check("register", "1.2.3.4", "a@example.com")
        ratelimit.check("login", "1.2.3.4", "a@example.com")  # must not raise

    def test_missing_identifiers_do_not_share_one_bucket(self):
        """An empty IP must not put every anonymous caller in the same
        counter - that would let one of them lock out all the others."""
        limit, _ = ratelimit.LIMITS["login"]
        for _ in range(limit * 3):
            ratelimit.check("login", "", "")


class ChangePasswordTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = AccountStore(Path(self._tmp.name) / "accounts.db")
        self.addCleanup(self.store.close)
        self.token, _ = self.store.register("a@example.com", "gammalt-losenord")

    def test_changes_the_password(self):
        self.store.change_password(self.token, "gammalt-losenord", "nytt-losenord")
        with self.assertRaises(AccountError):
            self.store.login("a@example.com", "gammalt-losenord")
        self.store.login("a@example.com", "nytt-losenord")  # must not raise

    def test_requires_the_current_password(self):
        """The session already proves who this is - but a borrowed or stolen
        session must not be enough to lock the real owner out."""
        with self.assertRaises(AccountError):
            self.store.change_password(self.token, "fel-losenord", "nytt-losenord")
        self.store.login("a@example.com", "gammalt-losenord")  # unchanged

    def test_requires_a_session(self):
        with self.assertRaises(AccountError):
            self.store.change_password("inte-en-token", "gammalt-losenord", "nytt-losenord")

    def test_enforces_the_minimum_length(self):
        with self.assertRaises(AccountError):
            self.store.change_password(self.token, "gammalt-losenord", "kort")

    def test_rejects_reusing_the_same_password(self):
        with self.assertRaises(AccountError):
            self.store.change_password(self.token, "gammalt-losenord", "gammalt-losenord")

    def test_other_sessions_are_dropped(self):
        """A password change is what a person does when they think someone
        else has access. Leaving that someone's session alive would make the
        change cosmetic."""
        other, _ = self.store.login("a@example.com", "gammalt-losenord")
        self.assertIsNotNone(self.store.user_for_token(other))
        self.store.change_password(self.token, "gammalt-losenord", "nytt-losenord")
        self.assertIsNone(self.store.user_for_token(other))

    def test_the_session_doing_the_change_survives(self):
        """The user must not be logged out of the device in their hand."""
        self.store.change_password(self.token, "gammalt-losenord", "nytt-losenord")
        self.assertIsNotNone(self.store.user_for_token(self.token))

    def test_a_new_salt_is_used(self):
        """Reusing the salt would make the stored hash comparable with the
        old one across a database leak."""
        before = self.store._connection.execute(
            "SELECT salt FROM users WHERE email = ?", ("a@example.com",)).fetchone()["salt"]
        self.store.change_password(self.token, "gammalt-losenord", "nytt-losenord")
        after = self.store._connection.execute(
            "SELECT salt FROM users WHERE email = ?", ("a@example.com",)).fetchone()["salt"]
        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
