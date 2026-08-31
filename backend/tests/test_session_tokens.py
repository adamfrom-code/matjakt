# -*- coding: utf-8 -*-
"""Session tokens must never be stored in the clear.

A session token is a bearer credential: whoever holds it IS the user until it
expires. Stored verbatim, a database leak (a backup, a stray copy of the
Render disk, SQL injection anywhere) hands over every live session - unlike
password hashes, which an attacker still has to crack.

These tests pin both halves: the raw token never reaches the database, and
every way a session is supposed to die still kills it.
"""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.accounts.store import AccountError, AccountStore, _session_key  # noqa: E402

PASSWORD = "ett-riktigt-losenord"


class SessionTokenStorageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "accounts.db"
        self.store = AccountStore(self.db_path)
        self.addCleanup(self.store.close)
        self.token, _ = self.store.register("a@example.com", PASSWORD)

    def stored_tokens(self):
        return [row["token"] for row in
                self.store._connection.execute("SELECT token FROM sessions").fetchall()]

    # --- storage ----------------------------------------------------------

    def test_raw_token_is_not_in_the_database(self):
        self.assertNotIn(self.token, self.stored_tokens())

    def test_what_is_stored_is_the_sha256_of_the_token(self):
        expected = hashlib.sha256(self.token.encode("utf-8")).hexdigest()
        self.assertIn(expected, self.stored_tokens())

    def test_the_raw_token_appears_nowhere_in_the_database_file(self):
        """Not just the sessions table - a leak of the whole file must not
        contain a usable session token anywhere in it."""
        self.store._connection.commit()
        blob = self.db_path.read_bytes()
        self.assertNotIn(self.token.encode("utf-8"), blob)

    def test_a_stolen_stored_value_cannot_be_used_as_a_token(self):
        """The point of hashing: what an attacker reads out of the database
        is not something they can present as a session."""
        stored = self.stored_tokens()[0]
        self.assertIsNone(self.store.user_for_token(stored))

    # --- the session still works -----------------------------------------

    def test_login_returns_a_working_session(self):
        token, user = self.store.login("a@example.com", PASSWORD)
        self.assertEqual(user["email"], "a@example.com")
        self.assertIsNotNone(self.store.user_for_token(token))

    def test_session_lookup_resolves_the_right_user(self):
        other_token, _ = self.store.register("b@example.com", PASSWORD)
        self.assertEqual(self.store.user_for_token(self.token)["email"], "a@example.com")
        self.assertEqual(self.store.user_for_token(other_token)["email"], "b@example.com")

    def test_an_unknown_token_resolves_to_nobody(self):
        self.assertIsNone(self.store.user_for_token("inte-en-token"))
        self.assertIsNone(self.store.user_for_token(""))
        self.assertIsNone(self.store.user_for_token(None))

    def test_synced_state_round_trips_through_the_hashed_session(self):
        self.store.set_synced_state(self.token, '{"budget": 1450}')
        self.assertEqual(self.store.get_synced_state(self.token), '{"budget": 1450}')

    # --- every way a session must die ------------------------------------

    def test_logout_invalidates_the_session(self):
        self.store.logout(self.token)
        self.assertIsNone(self.store.user_for_token(self.token))
        self.assertEqual(self.stored_tokens(), [])

    def test_logout_leaves_other_sessions_alone(self):
        other, _ = self.store.login("a@example.com", PASSWORD)
        self.store.logout(self.token)
        self.assertIsNone(self.store.user_for_token(self.token))
        self.assertIsNotNone(self.store.user_for_token(other))

    def test_password_change_kills_every_other_session(self):
        other, _ = self.store.login("a@example.com", PASSWORD)
        self.store.change_password(self.token, PASSWORD, "nytt-losenord-123")
        self.assertIsNone(self.store.user_for_token(other))
        self.assertIsNotNone(self.store.user_for_token(self.token))

    def test_password_reset_kills_every_session(self):
        other, _ = self.store.login("a@example.com", PASSWORD)
        reset = self.store.request_password_reset("a@example.com")
        self.store.reset_password(reset, "nytt-losenord-123")
        self.assertIsNone(self.store.user_for_token(self.token))
        self.assertIsNone(self.store.user_for_token(other))

    def test_account_deletion_kills_every_session(self):
        other, _ = self.store.login("a@example.com", PASSWORD)
        self.store.delete_account(self.token)
        self.assertIsNone(self.store.user_for_token(self.token))
        self.assertIsNone(self.store.user_for_token(other))


class SessionMigrationTest(unittest.TestCase):
    """Existing sessions were stored raw. The migration must convert them
    WITHOUT signing anyone out - deleting the rows instead would have logged
    out every user on the deploy that shipped hashing, for no benefit."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "accounts.db"

    def open_store(self):
        store = AccountStore(self.db_path)
        self.addCleanup(store.close)
        return store

    def test_a_raw_session_row_still_works_after_migration(self):
        store = self.open_store()
        token, _ = store.register("a@example.com", PASSWORD)
        # Put the row back the way the old code wrote it.
        store._connection.execute("UPDATE sessions SET token = ?", (token,))
        store._connection.commit()
        store.close()

        migrated = self.open_store()
        self.assertIsNotNone(migrated.user_for_token(token),
                             "en befintlig inloggning ska överleva migreringen")
        stored = [row["token"] for row in
                  migrated._connection.execute("SELECT token FROM sessions").fetchall()]
        self.assertEqual(stored, [_session_key(token)])

    def test_running_the_migration_twice_is_a_no_op(self):
        """A double hash would lock every user out - and _init_schema runs on
        every single process start."""
        store = self.open_store()
        token, _ = store.register("a@example.com", PASSWORD)
        store.close()
        for _ in range(3):
            again = self.open_store()
            self.assertIsNotNone(again.user_for_token(token))
            again.close()

    def test_migration_distinguishes_hashed_rows_by_length(self):
        self.assertEqual(len(_session_key("x")), 64)
        store = self.open_store()
        token, _ = store.register("a@example.com", PASSWORD)
        self.assertEqual(len(token), 43, "token_urlsafe(32) ska vara 43 tecken, aldrig 64")


if __name__ == "__main__":
    unittest.main()
