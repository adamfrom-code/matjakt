# -*- coding: utf-8 -*-
"""Regressionstest för spärren i services/data_guard.py.

Ett test får aldrig kunna öppna backend/data/grocery.db (eller matjakt.db,
prices.db, recipes.db) - inte ens ett framtida test som glömmer peka om
DB_PATH. Spärren sitter i koden som öppnar databaserna; här bevisas att den
(1) är aktiv under testkörningen, (2) avvisar riktiga sökvägar innan något
skapas, (3) släpper igenom tempdatabaser och (4) är passiv i produktion.
"""

import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import data_guard  # noqa: E402
from services.data_guard import (  # noqa: E402
    ProductionDatabaseInTestError, check_database_path, guard_database_path,
    is_test_safe_path, isolated_test_data_dir, test_mode_active,
)

BACKEND = Path(__file__).resolve().parents[1]
REAL_DATA_DIR = BACKEND / "data"


class TestModeDetection(unittest.TestCase):
    def test_test_mode_is_active_under_the_test_runner(self):
        """Oavsett om sviten körs via unittest, pytest eller tests/run.py."""
        self.assertTrue(test_mode_active())

    def test_env_flag_alone_activates_test_mode(self):
        with unittest.mock.patch.dict(os.environ, {"MATJAKT_TEST_MODE": "1"}):
            self.assertTrue(test_mode_active())


class RealDatabasesAreRejected(unittest.TestCase):
    """Sökvägarna som produktionen och den lokala utvecklingen använder."""

    def assert_rejected(self, opener, path):
        existed = path.exists()
        with self.assertRaises(ProductionDatabaseInTestError) as ctx:
            opener(path)
        self.assertIn(str(path), str(ctx.exception))
        # Spärren ligger FÖRE mkdir/connect: inget får ha skapats.
        self.assertEqual(path.exists(), existed)

    def test_grocery_store_refuses_the_real_grocery_db(self):
        from services.grocery.store import GroceryStore
        self.assert_rejected(GroceryStore, REAL_DATA_DIR / "grocery.db")

    def test_account_store_refuses_the_real_matjakt_db(self):
        from services.accounts.store import AccountStore
        self.assert_rejected(AccountStore, REAL_DATA_DIR / "matjakt.db")

    def test_price_cache_refuses_the_real_prices_db(self):
        from services.pricing.store import PriceCacheStore
        self.assert_rejected(PriceCacheStore, REAL_DATA_DIR / "prices.db")

    def test_recipe_store_refuses_the_real_recipes_db(self):
        from services.recipes.store import RecipeStore
        self.assert_rejected(RecipeStore, REAL_DATA_DIR / "recipes.db")

    def test_open_store_with_the_default_path_is_rejected(self):
        """Det exakta felet från 2026-09-02: importern anropade
        grocery_api.open_store() med DB_PATH kvar på riktig data."""
        from services.grocery import api as grocery_api
        real = grocery_api.DB_PATH
        grocery_api.DB_PATH = REAL_DATA_DIR / "grocery.db"
        self.addCleanup(lambda: setattr(grocery_api, "DB_PATH", real))
        with self.assertRaises(ProductionDatabaseInTestError):
            grocery_api.open_store()

    def test_recipes_open_store_with_the_default_path_is_rejected(self):
        from services.recipes import api as recipes_api
        real = recipes_api.DB_PATH
        recipes_api.DB_PATH = REAL_DATA_DIR / "recipes.db"
        self.addCleanup(lambda: setattr(recipes_api, "DB_PATH", real))
        with self.assertRaises(ProductionDatabaseInTestError):
            recipes_api.open_store()

    def test_backup_refuses_the_real_data_dir(self):
        """Backupen kopierar varje *.db i katalogen - även den ska stanna."""
        from services import backup
        with self.assertRaises(ProductionDatabaseInTestError):
            backup.take_backup(REAL_DATA_DIR)
        with self.assertRaises(ProductionDatabaseInTestError):
            backup.start_nightly(REAL_DATA_DIR)

    def test_a_path_inside_the_repo_is_rejected_before_anything_is_created(self):
        """Regeln är en vitlista (bara temp), inte en svartlista över kända
        filer: en ny 'lokal' databas i repot stoppas också."""
        from services.grocery.store import GroceryStore
        probe_dir = BACKEND / "tests" / "_far_aldrig_skapas"
        self.assertFalse(probe_dir.exists())
        with self.assertRaises(ProductionDatabaseInTestError):
            GroceryStore(probe_dir / "x.db")
        self.assertFalse(probe_dir.exists())

    def test_matjakt_data_dir_pointing_at_real_data_is_still_rejected(self):
        """Ett MATJAKT_DATA_DIR i utvecklarens skal som pekar på riktig data
        får inte smitta testerna."""
        self.assertFalse(is_test_safe_path(REAL_DATA_DIR / "grocery.db"))
        with self.assertRaises(ProductionDatabaseInTestError):
            check_database_path(REAL_DATA_DIR / "grocery.db", test_mode=True)


class TempDatabasesAreAllowed(unittest.TestCase):
    def test_a_temp_grocery_db_opens_normally(self):
        from services.grocery.store import GroceryStore
        with tempfile.TemporaryDirectory() as tmp:
            db = GroceryStore(Path(tmp) / "grocery.db")
            try:
                self.assertTrue((Path(tmp) / "grocery.db").exists())
            finally:
                db.close()

    def test_mkdtemp_and_memory_are_safe(self):
        self.assertTrue(is_test_safe_path(Path(tempfile.mkdtemp()) / "x.db"))
        self.assertTrue(is_test_safe_path(":memory:"))

    def test_guard_is_silent_for_a_temp_path(self):
        guard_database_path(Path(tempfile.gettempdir()) / "vad-som-helst.db")

    def test_isolated_data_dir_lives_under_temp_and_sets_the_env(self):
        data_dir = isolated_test_data_dir()
        self.assertTrue(is_test_safe_path(data_dir))
        self.assertEqual(os.environ.get("MATJAKT_DATA_DIR"), str(data_dir))
        self.assertEqual(os.environ.get("MATJAKT_TEST_MODE"), "1")
        # Idempotent: samma katalog varje gång i processen.
        self.assertEqual(isolated_test_data_dir(), data_dir)


class GuardIsPassiveInProduction(unittest.TestCase):
    """Servern, skripten och kollektorerna ska öppna riktig data som förut.
    Ren kontroll utan att öppna något: check_database_path är sidoeffektsfri."""

    def test_real_paths_pass_when_no_test_is_running(self):
        check_database_path(REAL_DATA_DIR / "grocery.db", test_mode=False)
        check_database_path(Path("/app/backend/data/matjakt.db"), test_mode=False)

    def test_detection_is_false_without_any_test_signal(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MATJAKT_TEST_MODE", None)
            os.environ.pop("PYTEST_CURRENT_TEST", None)
            with unittest.mock.patch.object(sys, "argv", ["api_server.py"]):
                fake_main = type("M", (), {"__spec__": None})()
                with unittest.mock.patch.dict(sys.modules, {"__main__": fake_main}):
                    self.assertFalse(test_mode_active())


class OutboundCallsAreBlockedInTests(unittest.TestCase):
    """Sviten skapade riktiga Stripe-kunder så fort .env hade en nyckel.
    Spärren är densamma som för databasen: fail closed i botten."""

    def test_stripe_request_refuses_to_leave_the_machine(self):
        from services.billing import stripe_client
        from services.data_guard import OutboundCallInTestError
        with self.assertRaises(OutboundCallInTestError):
            stripe_client.create_customer("sk_test_riktig", "a@b.se", 1)
        with self.assertRaises(OutboundCallInTestError):
            stripe_client.fetch_price("sk_test_riktig", "price_x")

    def test_sending_mail_refuses_to_leave_the_machine(self):
        from services.data_guard import OutboundCallInTestError
        from services.email import check_transport, send_email
        config = {"host": "smtp.example.com", "from_email": "noreply@example.com"}
        with self.assertRaises(OutboundCallInTestError):
            send_email(config, "a@b.se", "Ämne", "Text")
        with self.assertRaises(OutboundCallInTestError):
            check_transport(config)

    def test_a_test_that_mocks_the_transport_is_let_through(self):
        from unittest.mock import patch
        from services.billing import stripe_client
        from services.data_guard import mocked_outbound

        class _Response:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"id": "cus_mock"}'

        with mocked_outbound(), patch.object(stripe_client.urllib.request, "urlopen", lambda *a, **k: _Response()):
            self.assertEqual(stripe_client.create_customer("sk_test_x", "a@b.se", 1), "cus_mock")

    def test_guard_is_passive_outside_test_mode(self):
        import os
        from services.data_guard import guard_outbound_call
        original = os.environ.get("MATJAKT_TEST_MODE")
        argv, main = sys.argv[:], sys.modules.get("__main__")
        spec = getattr(main, "__spec__", None)
        try:
            os.environ["MATJAKT_TEST_MODE"] = "0"
            sys.argv = ["matjakt-server"]
            if main is not None:
                main.__spec__ = None
            guard_outbound_call("Stripe")      # kastar inte i skarp drift
        finally:
            if original is None:
                os.environ.pop("MATJAKT_TEST_MODE", None)
            else:
                os.environ["MATJAKT_TEST_MODE"] = original
            sys.argv = argv
            if main is not None:
                main.__spec__ = spec


if __name__ == "__main__":
    unittest.main()
