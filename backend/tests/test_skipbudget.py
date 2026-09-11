# -*- coding: utf-8 -*-
"""K6: en skip som ingen räknar är en test som inte finns.

Sviten hoppade över tre-fyra tester i varje körning och skrev ut `skipped=4`.
Ingen räknade dem. Det betyder att dagen de blev fem såg exakt likadan ut som
dagen de var fyra - och dagen de blev trettio också. En svit som tyst slutar
köra en tredjedel av sig själv rapporterar "OK" precis som en som kör allt.

"Noll skip" går inte att kräva: flera av dem beror på vad som finns i miljön
(ingen prisdatabas i en ren checkout, inget `age` på en GitHub-runner), och
de skiljer sig mellan en utvecklarmaskin och CI. Budgeten är därför en lista
över kända och accepterade orsaker, och regeln att en orsak som inte står där
fäller körningen när `MATJAKT_STRICT=1` är satt.

Testerna nedan prövar domaren direkt, med påhittade skiplistor - det är där
regeln bor - och att den faktiskt är inkopplad i run.py och påslagen i CI.
"""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HÄR = Path(__file__).resolve().parent
CI = ROOT / ".github" / "workflows" / "ci.yml"
RUN = HÄR / "run.py"
LISTA = HÄR / "tillatna_skip.txt"


def _ladda():
    spec = importlib.util.spec_from_file_location("skipbudget", HÄR / "skipbudget.py")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


budget = _ladda()

TILLÅTNA = budget.läs_tillåtna(LISTA.read_text(encoding="utf-8"))


def tyst(*_):
    pass


class DomarenSlapperIgenomDetKanda(unittest.TestCase):
    def test_ingen_skip_alls_ar_gront(self):
        self.assertEqual(budget.döm([], TILLÅTNA, skriv=tyst), 0)

    def test_dagens_fyra_skip_ar_kanda(self):
        # Exakt de orsaker sviten hoppar över i dag. Skulle någon av dem sluta
        # matcha listan hade CI blivit röd på en grön körning.
        dagens = [("test_admin (test_api_server.Admin)", "ingen admin-token i den här miljön"),
                  ("test_willys (test_grocery_api.Willys)", "ingen Willys-data lokalt"),
                  ("test_manifest (test_site_video.Manifest)", "clips.json saknas - kör fetch_site_video.py"),
                  ("test_resan (test_household_release_e2e.Dublett)", "täcks av HouseholdReleaseE2ETest")]
        self.assertEqual(budget.otillåtna(dagens, TILLÅTNA), [])

    def test_orsaken_far_bara_detaljer_listan_inte_kanner_till(self):
        # Prefixmatchning. Utan den hade varje orsak som bär ett filnamn eller
        # ett felmeddelande behövt stå ordagrant, och listan blivit ohållbar.
        self.assertTrue(budget.tillåten("openssl saknas (3.0 krävs)", ["openssl saknas"]))
        self.assertTrue(budget.tillåten("clips.json saknas - kör fetch_site_video.py",
                                        ["clips.json saknas"]))


class DomarenStangerVidNyaSkip(unittest.TestCase):
    """Ett CI-steg som inte kan faila är inget CI-steg."""

    def test_en_ny_okand_skip_faller_korningen(self):
        nytt = [("test_pris (test_pricing.Motorn)", "gick inte att köra just nu")]
        self.assertEqual(budget.döm(nytt, TILLÅTNA, skriv=tyst), 1)

    def test_trettio_nya_skip_faller_korningen(self):
        # Fyndets egen formulering: "ingen som märker om de blir trettio".
        trettio = [(f"test_{i} (modul.Klass)", "tillfälligt avstängd") for i in range(30)]
        self.assertEqual(budget.döm(trettio, TILLÅTNA, skriv=tyst), 1)

    def test_en_okand_bland_trettio_kanda_fanges_anda(self):
        blandat = [("k%d" % i, "ingen Willys-data lokalt") for i in range(30)]
        blandat.append(("smyg", "orkade inte"))
        okända = budget.otillåtna(blandat, TILLÅTNA)
        self.assertEqual([namn for namn, _ in okända], ["smyg"])

    def test_skip_utan_orsak_ar_aldrig_tillaten(self):
        # Den som skriver self.skipTest("") har inte tänkt klart, och en tom
        # sträng matchar varje prefix om man inte stoppar den.
        for tomt in ("", "   ", None):
            self.assertFalse(budget.tillåten(tomt, TILLÅTNA), repr(tomt))

    def test_tom_lista_gor_varje_skip_otillaten(self):
        self.assertEqual(len(budget.otillåtna([("a", "vad som helst")], [])), 1)

    def test_en_orsak_som_bara_INNEHALLER_en_kand_racker_inte(self):
        # "fejkat: openssl saknas" är inte samma sak som "openssl saknas".
        self.assertFalse(budget.tillåten("fejkat: openssl saknas", ["openssl saknas"]))


class ListanGarAttLasa(unittest.TestCase):
    def test_listan_finns_och_har_poster(self):
        self.assertTrue(LISTA.exists(), "backend/tests/tillatna_skip.txt saknas")
        self.assertGreater(len(TILLÅTNA), 0, "listan är tom")

    def test_kommentarer_och_tomrader_raknas_inte_som_orsaker(self):
        läst = budget.läs_tillåtna("# bara en kommentar\n\n  openssl saknas  # varför\n")
        self.assertEqual(läst, ["openssl saknas"])

    def test_varje_post_ar_forklarad(self):
        # En lista med orsaker men utan skäl blir en soptunna. Varje post ska
        # ha minst en kommentarsrad i sin närhet.
        rader = LISTA.read_text(encoding="utf-8").splitlines()
        for i, rad in enumerate(rader):
            if rad.strip() and not rad.strip().startswith("#"):
                efter = [r for r in rader[i + 1:i + 4] if r.strip().startswith("#")]
                före = [r for r in rader[max(0, i - 3):i] if r.strip().startswith("#")]
                self.assertTrue(efter or före,
                                f"posten {rad.strip()!r} saknar förklaring - "
                                f"nästa person ska se att den är ett beslut")


class BudgetenArInkopplad(unittest.TestCase):
    """En domare som ingen anropar dömer ingenting."""

    def test_run_py_anropar_domaren(self):
        text = RUN.read_text(encoding="utf-8")
        for bit in ("skipbudget", "strikt_läge", "result.skipped"):
            self.assertIn(bit, text, f"run.py anropar inte skip-budgeten ({bit} saknas)")

    def test_ci_slar_pa_strikt_lage(self):
        ci = CI.read_text(encoding="utf-8")
        self.assertTrue('MATJAKT_STRICT: "1"' in ci,
                        "CI kör sviten utan MATJAKT_STRICT - budgeten är då avstängd "
                        "på precis det ställe där den behövs")

    def test_strikt_lage_ar_AV_om_inget_sags(self):
        # Lokalt ska ingen bli stoppad av en saknad prisdatabas.
        self.assertFalse(budget.strikt_läge({}))
        self.assertFalse(budget.strikt_läge({"MATJAKT_STRICT": "0"}))
        self.assertTrue(budget.strikt_läge({"MATJAKT_STRICT": "1"}))

    def test_hela_kedjan_faller_en_korning_med_okand_skip(self):
        """Domaren, run.py och exitkoden - hela vägen, som en riktig process.

        Enhetstesterna ovan prövar regeln. Det här prövar att regeln är
        inkopplad: samma svit, samma skip, en TOM lista. Blir den grön är
        budgeten avstängd utan att någon rad ser annorlunda ut.
        """
        import os
        import subprocess
        import sys
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tom:
            tom.write("# ingen orsak är känd här\n")
            tomlista = tom.name
        self.addCleanup(os.unlink, tomlista)
        # NotificationReleaseTest hoppar alltid över sig själv ("täcks av
        # HouseholdReleaseE2ETest") - ett skip som inte beror på miljön och
        # därför uppför sig likadant på en utvecklarmaskin och i CI.
        miljö = dict(os.environ, MATJAKT_STRICT="1", MATJAKT_SKIP_LISTA=tomlista)
        klar = subprocess.run([sys.executable, str(HÄR / "run.py"), "--pattern",
                               "test_household_release_e2e.py"],
                              capture_output=True, text=True, encoding="utf-8", env=miljö)
        self.assertEqual(klar.returncode, 1,
                         f"körningen blev grön trots ett okänt skip:\n{klar.stdout[-2000:]}")
        self.assertIn("står inte i backend/tests/tillatna_skip.txt", klar.stdout)
        self.assertIn("täcks av HouseholdReleaseE2ETest", klar.stdout,
                      "felet ska säga VILKEN orsak som saknas")


if __name__ == "__main__":
    unittest.main()
