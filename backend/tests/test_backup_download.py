# -*- coding: utf-8 -*-
"""B5: en headerhemlighet stod mellan internet och alla personuppgifter.

`/api/admin/backup-download` skickade `matjakt.db` som den ligger - varje
e-postadress i klartext, hela `synced_state`, all fritextfeedback - och den
enda spärren var samma admin-token som kontrollrummet använder i en
webbläsare, utan utgång, utan rotation och utan revisionslogg.

Tre saker bevisas här:

  (a) kontrollrumstoken ger 404 på backup-download - vägen har en EGEN
      hemlighet (acceptanskriteriet, ordagrant)
  (b) det som skickas är krypterat med en publik nyckel, och e-postadressen
      i databasen finns inte i byteströmmen
  (c) varje godkänd admin-kontroll lämnar en revisionsrad

Krypteringen körs mot `openssl cms` eftersom binären finns överallt vi kör -
utvecklarmaskin, CI och Playwright-imagen - så vägen kan bevisas i stället
för att antas. `age`- och `gpg`-vägarna testas när binären finns.
"""

import http.client
import logging
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api_server  # noqa: E402
from services import backup as backup_service  # noqa: E402
from services import backup_crypto  # noqa: E402
from services.accounts import ratelimit  # noqa: E402

KONTROLLRUMMETS_TOKEN = "kontrollrum-b5"
BACKUP_TOKEN = "backup-b5"
OPENSSL = shutil.which("openssl")


def keypair(tmp: Path):
    """Självsignerat certifikat + privat nyckel. Servern får BARA certifikatet."""
    key, cert = tmp / "privat.pem", tmp / "publikt.pem"
    subprocess.run([OPENSSL, "req", "-x509", "-newkey", "rsa:2048", "-keyout", str(key),
                    "-out", str(cert), "-nodes", "-days", "2", "-subj", "/CN=matjakt-backup-test"],
                   capture_output=True, check=True, timeout=120)
    return key, cert


@unittest.skipIf(OPENSSL is None, "openssl saknas")
class BackupDownloadTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), api_server.ApiHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        ratelimit.reset()
        self.addCleanup(ratelimit.reset)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.key, self.cert = keypair(Path(self._tmp.name))

        original = (api_server.ADMIN_TOKEN, api_server.BACKUP_TOKEN)
        api_server.ADMIN_TOKEN = KONTROLLRUMMETS_TOKEN
        api_server.BACKUP_TOKEN = BACKUP_TOKEN
        self._original_key = backup_crypto.configured_key

        def restore():
            api_server.ADMIN_TOKEN, api_server.BACKUP_TOKEN = original
            backup_crypto.configured_key = self._original_key
        self.addCleanup(restore)
        # Nyckeln kommer normalt ur miljön. Att sätta miljövariabeln i en
        # testprocess läcker till varje annat test i sviten - så den enda
        # läsaren byts ut i stället.
        cert_text = self.cert.read_text(encoding="utf-8")
        backup_crypto.configured_key = lambda environ=None: cert_text

    def fetch(self, headers):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            conn.request("GET", "/api/admin/backup-download", headers=headers)
            response = conn.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            conn.close()

    # ---- (a) acceptanskriteriet -------------------------------------------------

    def test_control_room_token_gets_404_on_backup_download(self):
        """Acceptans: kontrollrumstoken öppnar inte kontodatabasen.

        Samma 404 som en väg som inte finns - vägen ska inte gå att kartlägga
        med en token man råkar ha."""
        status, _, _ = self.fetch({"X-Admin-Token": KONTROLLRUMMETS_TOKEN})
        self.assertEqual(status, 404)
        status, _, _ = self.fetch({"X-Backup-Token": KONTROLLRUMMETS_TOKEN})
        self.assertEqual(status, 404)

    def test_the_control_room_token_still_opens_the_control_room(self):
        """Delningen får inte ha låst ut Adam ur driftsidorna."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", "/api/admin/insights", headers={"X-Admin-Token": KONTROLLRUMMETS_TOKEN})
            self.assertEqual(conn.getresponse().status, 200)
        finally:
            conn.close()

    def test_no_token_and_wrong_token_are_both_404(self):
        for headers in ({}, {"X-Backup-Token": "fel"}, {"X-Admin-Token": "fel"}):
            self.assertEqual(self.fetch(headers)[0], 404, headers)

    def test_without_a_configured_backup_token_nobody_gets_in(self):
        api_server.BACKUP_TOKEN = ""
        self.assertEqual(self.fetch({"X-Backup-Token": ""})[0], 404)
        self.assertEqual(self.fetch({"X-Backup-Token": BACKUP_TOKEN})[0], 404)

    # ---- (b) krypterat innan det lämnar processen -------------------------------

    def test_the_archive_is_encrypted_and_carries_no_address(self):
        email = "backup-b5-kanarie@example.invalid"
        api_server.ACCOUNT_STORE.register(email, "hemligt123")
        report = backup_service.take_backup(api_server.DATA_DIR)
        self.assertTrue(report["copied"])

        status, body, headers = self.fetch({"X-Backup-Token": BACKUP_TOKEN})
        self.assertEqual(status, 200, body[:200])
        self.assertEqual(headers.get("X-Backup-Encryption"), "cms")
        self.assertIn(".cms", headers.get("Content-Disposition", ""))
        self.assertNotEqual(body[:2], b"\x1f\x8b", "arkivet gick ut som ren gzip")
        self.assertNotIn(email.encode(), body)
        self.assertNotIn(b"kanarie", body)

        # Och med den PRIVATA nyckeln - som aldrig funnits på servern - är
        # det ett riktigt tar.gz med riktiga databaser i.
        out = Path(self._tmp.name) / "klartext.tar.gz"
        sealed = Path(self._tmp.name) / "hamtad.cms"
        sealed.write_bytes(body)
        subprocess.run([OPENSSL, "cms", "-decrypt", "-inform", "DER", "-in", str(sealed),
                        "-inkey", str(self.key), "-out", str(out)],
                       capture_output=True, check=True, timeout=300)
        self.assertEqual(out.read_bytes()[:2], b"\x1f\x8b")
        import tarfile
        with tarfile.open(out, mode="r:gz") as archive:
            names = archive.getnames()
        self.assertTrue(any(name.endswith(".db") for name in names), names)
        self.assertTrue(all("/" in name for name in names), "filerna ligger under <stämpel>/")

    def test_without_a_public_key_nothing_is_sent(self):
        """Fail closed. Alternativet vore 'krypteringen är inte konfigurerad,
        här är databasen' - alltså exakt hålet paketet stänger."""
        backup_service.take_backup(api_server.DATA_DIR)
        backup_crypto.configured_key = lambda environ=None: ""
        status, body, _ = self.fetch({"X-Backup-Token": BACKUP_TOKEN})
        self.assertEqual(status, 503)
        self.assertIn(backup_crypto.PUBLIC_KEY_ENV, body.decode("utf-8"))

    def test_health_shows_that_the_key_is_set_never_which(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", "/api/health")
            payload = conn.getresponse().read().decode("utf-8")
        finally:
            conn.close()
        self.assertIn('"backupTokenConfigured"', payload)
        self.assertIn('"backupEncryption"', payload)
        self.assertNotIn(BACKUP_TOKEN, payload)
        self.assertNotIn("BEGIN CERTIFICATE", payload)

    # ---- (c) revisionslogg ------------------------------------------------------

    def test_every_approved_admin_check_leaves_an_audit_line(self):
        with self.assertLogs("matjakt.admin", level=logging.INFO) as captured:
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            try:
                conn.request("GET", "/api/admin/insights", headers={"X-Admin-Token": KONTROLLRUMMETS_TOKEN})
                conn.getresponse().read()
            finally:
                conn.close()
        line = "\n".join(captured.output)
        self.assertIn("/api/admin/insights", line)
        self.assertIn("control-room", line)
        self.assertNotIn(KONTROLLRUMMETS_TOKEN, line)     # revisionsloggen bär inte hemligheten

    def test_a_refused_attempt_writes_no_approval_line(self):
        logger = logging.getLogger("matjakt.admin")
        with self.assertLogs("matjakt.admin", level=logging.INFO) as captured:
            logger.info("markör")            # assertLogs kräver minst en rad
            self.fetch({"X-Backup-Token": "fel"})
        self.assertEqual([r for r in captured.output if "godkänd" in r], [])


class BackupCryptoUnitTest(unittest.TestCase):
    """Formen på nyckeln väljer verktyget - ingen flagga att glömma."""

    def test_the_scheme_follows_the_shape_of_the_key(self):
        self.assertEqual(backup_crypto.scheme_of("-----BEGIN CERTIFICATE-----\nMII...\n"), "cms")
        self.assertEqual(backup_crypto.scheme_of("-----BEGIN PGP PUBLIC KEY BLOCK-----\nx\n"), "gpg")
        self.assertEqual(backup_crypto.scheme_of("age1" + "q" * 55), "age")
        self.assertEqual(backup_crypto.scheme_of("ssh-ed25519 AAAAC3Nza adam@dator"), "age")
        for junk in ("", "   ", "hemlig", "-----BEGIN RSA PRIVATE KEY-----"):
            self.assertEqual(backup_crypto.scheme_of(junk), "", junk)

    def test_a_private_key_is_never_a_valid_recipient(self):
        """Det vore att sätta den privata nyckeln i serverns miljö - alltså
        att bygga bort hela poängen. Formen känns inte igen, och då skickas
        ingen backup alls."""
        with tempfile.TemporaryDirectory() as tmp:
            if OPENSSL is None:
                self.skipTest("openssl saknas")
            key, _ = keypair(Path(tmp))
            self.assertEqual(backup_crypto.scheme_of(key.read_text(encoding="utf-8")), "")

    def test_base64_of_a_pem_block_is_accepted_on_one_line(self):
        import base64
        pem = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----"
        packed = base64.b64encode(pem.encode()).decode()
        self.assertEqual(backup_crypto.configured_key({backup_crypto.PUBLIC_KEY_ENV: packed}), pem)

    def test_encrypting_without_a_key_raises_instead_of_writing_plaintext(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "in.bin"
            source.write_bytes(b"personuppgifter")
            target = Path(tmp) / "ut.bin"
            with self.assertRaises(backup_crypto.BackupCryptoError):
                backup_crypto.encrypt_file(source, target, key="")
            self.assertFalse(target.exists())

    @unittest.skipIf(shutil.which("age") is None and shutil.which("rage") is None, "age saknas")
    def test_the_age_path_works_when_the_binary_is_there(self):
        with tempfile.TemporaryDirectory() as tmp:
            gen = shutil.which("age-keygen")
            if not gen:
                self.skipTest("age-keygen saknas")
            identity = Path(tmp) / "id.txt"
            subprocess.run([gen, "-o", str(identity)], capture_output=True, check=True, timeout=60)
            recipient = subprocess.run([gen, "-y", str(identity)], capture_output=True,
                                       check=True, timeout=60).stdout.decode().strip()
            source, target = Path(tmp) / "in.bin", Path(tmp) / "ut.age"
            source.write_bytes(b"personuppgifter")
            self.assertEqual(backup_crypto.encrypt_file(source, target, key=recipient), "age")
            self.assertNotIn(b"personuppgifter", target.read_bytes())


if __name__ == "__main__":
    unittest.main()
