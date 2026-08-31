# -*- coding: utf-8 -*-
"""Tests for the storage diagnostic.

This exists because a configuration file claimed something that was not true:
render.yaml declares a persistent disk, production lost a completed
10 837-product import on an ordinary deploy anyway. A declared disk is not a
mounted disk. So the check reads the FILESYSTEM - a mount is a separate
device, and st_dev cannot be faked by config.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api_server  # noqa: E402


class StorageInfoTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "data"
        self.dir.mkdir()
        self._real = api_server.DATA_DIR
        api_server.DATA_DIR = self.dir
        self.addCleanup(lambda: setattr(api_server, "DATA_DIR", self._real))

    def test_reports_the_directory_it_actually_uses(self):
        self.assertEqual(api_server.storage_info()["dataDir"], str(self.dir))

    def test_an_ordinary_directory_is_not_a_mount(self):
        """A plain directory inside the container image shares its parent's
        device - which is exactly the situation that lost the import."""
        self.assertFalse(api_server.storage_info()["mounted"])

    def test_mounted_is_true_when_the_device_differs(self):
        """A real mount point sits on its own device. Simulated here by
        making stat report different devices, since a test cannot mount a
        disk - the logic under test is the comparison, not the mounting."""
        real_stat = os.stat
        parent = str(self.dir.parent)

        def fake_stat(path, *args, **kwargs):
            result = real_stat(path, *args, **kwargs)
            if str(path) == parent:
                return os.stat_result(tuple(result))  # unchanged
            return type("S", (), {"st_dev": result.st_dev + 1})()

        os.stat = fake_stat
        try:
            self.assertTrue(api_server.storage_info()["mounted"])
        finally:
            os.stat = real_stat

    def test_a_missing_directory_is_reported_as_unmounted_not_a_crash(self):
        """/api/grocery/status must keep answering even when the data
        directory is gone - that is precisely when we need to see this."""
        api_server.DATA_DIR = self.dir / "finns-inte"
        info = api_server.storage_info()
        self.assertFalse(info["mounted"])

    def test_public_view_hides_file_details(self):
        """The boolean is public so persistence can be checked after every
        deploy; sizes and mount points are operational detail."""
        public = api_server.storage_info()
        self.assertEqual(set(public), {"dataDir", "mounted"})

    def test_detailed_view_lists_the_databases(self):
        (self.dir / "grocery.db").write_bytes(b"x" * 100)
        (self.dir / "matjakt.db").write_bytes(b"y" * 50)
        (self.dir / "inte-en-databas.txt").write_bytes(b"z")
        detail = api_server.storage_info(detail=True)
        self.assertEqual(detail["databases"], {"grocery.db": 100, "matjakt.db": 50})

    def test_detailed_view_survives_a_host_without_proc_mounts(self):
        """Local development on Windows has no /proc - the diagnostic must
        still answer rather than raise."""
        detail = api_server.storage_info(detail=True)
        self.assertIsInstance(detail["mounts"], list)


class DataDirTest(unittest.TestCase):
    def test_both_databases_live_in_the_same_data_dir(self):
        """Grocery data and user accounts must be on the SAME disk - one of
        them persisting is not persistence."""
        self.assertEqual(api_server.ACCOUNT_STORE_PATH.parent, api_server.DATA_DIR)
        self.assertEqual(api_server.PRICE_CACHE_PATH.parent, api_server.DATA_DIR)
        from services.grocery import api as grocery_api
        self.assertEqual(grocery_api.DB_PATH.parent, api_server.DATA_DIR)


if __name__ == "__main__":
    unittest.main()
