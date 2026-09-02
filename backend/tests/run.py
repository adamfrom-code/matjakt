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
        here = Path(__file__).resolve().parent
        sys.path.insert(0, str(here.parent))
        tests = unittest.defaultTestLoader.discover(str(here), top_level_dir=str(here))
        result = unittest.TextTestRunner(verbosity=1).run(tests)
        sys.exit(0 if result.wasSuccessful() else 1)
