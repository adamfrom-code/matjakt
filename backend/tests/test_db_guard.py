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


if __name__ == "__main__":
    unittest.main()
