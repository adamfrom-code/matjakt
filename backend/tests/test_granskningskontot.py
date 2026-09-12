"""Granskningskontot får inte ligga ifyllt i en spårad fil.

App Store Connect har egna fält för App Review Information. Kontot hör hemma
där, inte i repot - och repot är publikt.

Bakgrunden är konkret: ett riktigt lösenord låg i arbetsträdets
`store/appstore/metadata/review_notes.txt`, ocommitterat men en `git add -A`
från att bli publicerat för alltid. Hemlighetsskanningen såg det och sa
"inga hemligheter". Den hade rätt enligt sina mönster - ett lösenord ser ut
som vilket ord som helst - och det är just därför den här kontrollen inte är
ett mönster utan en PLATS: under store/ ska raderna för konto och lösenord
stå tomma eller bära en hakparentes.
"""

import importlib.util
import unittest
from pathlib import Path

ROT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "secret_scan", ROT / "backend" / "scripts" / "secret_scan.py"
)
secret_scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(secret_scan)

MALL = """Notes for App Review

Testkonto för granskning: skapa ett i appen, eller ange här:
  E-post:    {epost}
  Lösenord:  {losenord}

Betalning: Premium säljs inte i iOS-appen i v1.
"""


class Granskningskontot(unittest.TestCase):
    def _kör(self, epost, losenord, rel="store/appstore/metadata/review_notes.txt"):
        text = MALL.format(epost=epost, losenord=losenord)
        return secret_scan.granskningskontot(rel, text)

    def test_mallen_passerar(self):
        self.assertEqual(self._kör("[FYLLS I AV ADAM - testkonto]", "[FYLLS I AV ADAM]"), [])

    def test_tomma_rader_passerar(self):
        self.assertEqual(self._kör("", ""), [])
        self.assertEqual(self._kör("-", "--"), [])

    def test_ifyllt_losenord_fangas(self):
        träffar = self._kör("[FYLLS I AV ADAM]", "ettriktigtlosenord")
        self.assertEqual(len(träffar), 1, "det ifyllda lösenordet fångades inte")
        self.assertIn("lösenord", träffar[0][2])
        self.assertEqual(träffar[0][1], 5, "fel radnummer")

    def test_ifylld_epost_fangas(self):
        träffar = self._kör("adam@exempel.se", "[FYLLS I AV ADAM]")
        self.assertEqual(len(träffar), 1)
        self.assertIn("e-post", träffar[0][2])

    def test_vardet_skrivs_aldrig_ut(self):
        """En hemlighetsskanning som skriver ut hemligheten är ingen skanning."""
        hemligt = "Detta-Ar-Ett-Losenord-42"
        träffar = self._kör("[FYLLS I AV ADAM]", hemligt)
        self.assertTrue(träffar)
        for träff in träffar:
            for fält in träff:
                self.assertNotIn(hemligt, str(fält), "värdet läckte ut i träffen")

    def test_bara_under_store(self):
        """Resten av repot skannas med mönster, inte med den här regeln.

        `password:` står i kod, i testfixturer och i dokumentation. Skulle
        regeln gälla överallt skulle den larma hela tiden och därmed sluta
        betyda något.
        """
        self.assertEqual(
            self._kör("adam@exempel.se", "losenord", rel="frontend/app/app.js"), []
        )
        self.assertEqual(
            self._kör("adam@exempel.se", "losenord", rel="docs/nagot.md"), []
        )

    def test_repot_som_det_star_ar_rent(self):
        """Skanningen ska vara grön på repot just nu - annars ligger det kvar."""
        for fil in sorted((ROT / "store").rglob("*.txt")):
            rel = str(fil.relative_to(ROT))
            träffar = secret_scan.granskningskontot(
                rel, fil.read_text(encoding="utf-8", errors="ignore")
            )
            self.assertEqual(träffar, [], f"{rel} bär ett ifyllt granskningskonto")


if __name__ == "__main__":
    unittest.main()
