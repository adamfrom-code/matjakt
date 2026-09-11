"""Runs the backend test suite against a THROWAWAY data directory.

The suite calls api_server.KV_CACHE.clear() - documented "test-only" - nine
times. Against the real backend/data/prices.db that wipes every cached
geocode, store list, campaign and product image the machine holds, which is
exactly what happened: store lookups kept falling back to a full 12-second
recomputation because every test run had emptied the cache underneath them.

Setting MATJAKT_DATA_DIR before api_server is imported gives the tests their
own database files, so a test run can no longer destroy real cached state.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

if __name__ == "__main__":
    # ignore_cleanup_errors: the stores keep their SQLite connections open for
    # the life of the process, and Windows refuses to delete an open file.
    # The directory is in the OS temp area either way.
    with tempfile.TemporaryDirectory(prefix="matjakt-tests-", ignore_cleanup_errors=True) as tmp:
        os.environ["MATJAKT_DATA_DIR"] = tmp
        os.environ["MATJAKT_TEST_MODE"] = "1"  # spärren i services/data_guard.py
        # .env fyller bara TOMMA variabler, så genom att sätta dem här får
        # sviten aldrig utvecklarens riktiga nycklar. (Utan detta gick
        # checkout-testet ut till api.stripe.com och skapade riktiga kunder.)
        for secret in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PRICE_MONTHLY",
                       "STRIPE_PRICE_YEARLY", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD",
                       "SMTP_FROM_EMAIL", "PRIMAT_API_KEY", "DABAS_API_KEY",
                       "MATJAKT_ADMIN_TOKEN", "MATJAKT_PREMIUM_CODE"):
            os.environ[secret] = ""
        here = Path(__file__).resolve().parent
        sys.path.insert(0, str(here.parent))
        # Valfritt filnamnsmönster: `run.py --pattern "test_consumer*"` kör
        # bara browser-E2E:n (CI:s Playwright-jobb), utan argument allt.
        pattern = "test*.py"
        if len(sys.argv) >= 3 and sys.argv[1] == "--pattern":
            pattern = sys.argv[2]
        tests = unittest.defaultTestLoader.discover(str(here), pattern=pattern, top_level_dir=str(here))
        result = unittest.TextTestRunner(verbosity=1).run(tests)

        # K6 - SKIP-BUDGETEN. unittest skriver "skipped=8" och går vidare, så
        # dagen de blir nio ser likadan ut som dagen de var åtta, och dagen de
        # blir trettio också. Två saker här:
        #
        #   1. ORSAKERNA SKRIVS ALLTID UT. "skipped=8" är ett tal ingen kan
        #      agera på; åtta rader med testnamn och orsak går att läsa på tio
        #      sekunder. Det gäller även utan strikt läge.
        #   2. MATJAKT_STRICT=1 (satt i CI) kräver dessutom att varje orsak
        #      står i tillatna_skip.txt.
        #
        # Importeras per sökväg: tests/ ligger inte på sys.path och ska inte
        # läggas där bara för det här.
        import importlib.util
        spec = importlib.util.spec_from_file_location("skipbudget", here / "skipbudget.py")
        skipbudget = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(skipbudget)
        skippade = [(str(test), orsak) for test, orsak in result.skipped]
        if skippade:
            print("\nÖverhoppade tester:")
            for namn, orsak in skippade:
                print(f"    {namn}\n        {orsak}")
        # Budgeten döms ÄVEN när sviten redan är röd, och skrivs ut före
        # exitkoden: den som felsöker en röd körning ska inte behöva laga
        # felet först för att få veta att tolv tester dessutom hoppades över.
        budget_kod = 0
        if skipbudget.strikt_läge():
            lista = os.environ.get("MATJAKT_SKIP_LISTA") or skipbudget.LISTA
            tillåtna = skipbudget.läs_tillåtna(Path(lista).read_text(encoding="utf-8"))
            budget_kod = skipbudget.döm(skippade, tillåtna)
        sys.exit(1 if not result.wasSuccessful() else budget_kod)
