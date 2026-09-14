# -*- coding: utf-8 -*-
"""K6c: kontoschemats baslinje får inte halka efter koden.

`fixturer/scheman/konton.sql` är databasen K6:s rollback-tester kör dagens
migrationer MOT. Den är värd något bara så länge den är schemat som faktiskt
står i drift. Backenden deployas på push till main (`ci.yml`, jobbet
`deploy-backend`, `github.event_name == 'push'`), så varje merge är en
release och det K4:s `rollback`-jobb startar är föregående main-commit.

Ligger fixturen efter main har `test_ingen_tabell_och_ingen_kolumn_forsvinner`
färre kolumner att skydda, och en icke-additiv ändring i någon av de
mellanliggande releaserna passerar obemärkt. Sviten blir inte röd av det —
den blir tyst, vilket är värre.

Grinden failade när den skrevs: `users` hade åtta kolumner som fixturen inte
kände till — `withdrawal_consent_at`/`_version` (B3, #63), `first_week_at`
(J3, #114) samt `past_due_since`, `pending_email`, `pending_email_token`,
`pending_email_expires_at` och `renewal_reminder_for` (J5, #135).

Failar den igen har någon ändrat kontoschemat utan att ta med baslinjen:

    backend/venv/bin/python backend/tests/test_migrationer.py --spara

och committa `konton.sql` i SAMMA commit som schemaändringen, enligt
docstringen i `test_migrationer.py`. Kommandot skriver om alla fem
fixturerna — de andra fyra hör till andra zoner och ska inte med.
"""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HÄR = Path(__file__).resolve().parent
sys.path.insert(0, str(HÄR.parent))

from services.accounts.store import AccountStore  # noqa: E402

FIXTUR = HÄR / "fixturer" / "scheman" / "konton.sql"


def objekt(anslutning):
    """{namn: CREATE-satsen} för allt utom sqlite:s egna tabeller.

    Jämför man CREATE-satsen och inte bara kolumnnamnen syns även ett index
    eller en unik-villkor som tillkommit — `ALTER TABLE ADD COLUMN` skriver
    om den lagrade satsen, så en tillagd kolumn ger en textskillnad.
    """
    return {rad[0]: rad[1] for rad in anslutning.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")}


class KontofixturenArDagensSchema(unittest.TestCase):
    def setUp(self):
        ur_fixturen = sqlite3.connect(":memory:")
        self.addCleanup(ur_fixturen.close)
        ur_fixturen.executescript(FIXTUR.read_text(encoding="utf-8"))
        self.fixtur = objekt(ur_fixturen)

        katalog = tempfile.TemporaryDirectory()
        self.addCleanup(katalog.cleanup)
        väg = Path(katalog.name) / "konton.db"
        AccountStore(väg)          # dagens kod bygger schemat från tomt
        ur_koden = sqlite3.connect(väg)
        self.addCleanup(ur_koden.close)
        self.koden = objekt(ur_koden)

    def test_ingen_tabell_saknas_i_baslinjen(self):
        saknade = sorted(set(self.koden) - set(self.fixtur))
        self.assertEqual(saknade, [], f"konton.sql saknar {saknade} - kör "
                                      f"`test_migrationer.py --spara`")

    def test_ingen_kolumn_i_dagens_schema_saknas_i_baslinjen(self):
        for namn, sats in self.koden.items():
            with self.subTest(objekt=namn):
                self.assertEqual(
                    self.fixtur.get(namn), sats,
                    f"konton.sql:s {namn} är inte dagens {namn}. Baslinjen är "
                    f"föregående deploy av main - halkar den efter skyddar "
                    f"rollback-testerna färre kolumner än som finns i drift. "
                    f"Kör `backend/venv/bin/python backend/tests/"
                    f"test_migrationer.py --spara` och committa konton.sql.")


if __name__ == "__main__":
    unittest.main()
