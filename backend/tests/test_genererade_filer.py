# -*- coding: utf-8 -*-
"""Genererad data hör inte i git, och ingen ska behöva komma ihåg det.

A3:s acceptanskriterium är ett CI-steg: bygget ska faila om en
*.tsv/*.json-artefakt eller marketing/build/** är spårad. Grinden ligger i
security-jobbet i .github/workflows/ci.yml. Det här testet är samma grind
lokalt, av två skäl:

  1. Den som råkar `git add audit_result.json` ska få veta det innan CI,
     inte efter en push.
  2. En grind som bara finns i en YAML-fil kan tas bort utan att en enda
     rad kod märker det. Testet håller fast både invarianten OCH att
     CI-steget finns kvar.

Två fel finns i historiken och båda hade fastnat här:

  - audit_pricing.py skrev sitt resultat till repo-roten. Varje agent som
    körde prisauditen fick en diff i roten - den perfekta konfliktgeneratorn.
  - marketing/build/ låg spårad med 73 MB video TROTS raden "marketing/" i
    .gitignore. gitignore avspårar inget som redan är spårat; en regel i en
    fil är inte en grind.
"""

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"

# EXAKT samma mönster som CI-steget "Inga genererade artefakter är spårade".
# Ändras det ena måste det andra ändras - test_grinden_finns_i_ci nedan
# kräver att strängen står ordagrant i ci.yml.
ARTEFAKTMONSTER = ("*.tsv", "audit_*.json", "backend/data/*",
                   "marketing/build/*", "dist/*", "build/*")


def _git(*argument) -> str:
    return subprocess.run(["git", *argument], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8").stdout


def _git_finns() -> bool:
    try:
        subprocess.run(["git", "rev-parse", "--git-dir"], cwd=ROOT,
                       capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


@unittest.skipUnless(_git_finns(), "inget git-arbetsträd att fråga")
class GenereradDataUtanforGit(unittest.TestCase):
    def test_inga_genererade_artefakter_ar_sparade(self):
        sparade = [rad for rad in _git("ls-files", *ARTEFAKTMONSTER).splitlines() if rad]
        self.assertEqual(sparade, [], f"{len(sparade)} spårade genererade artefakter: "
                                      f"{sparade[:5]}")

    def test_de_tre_kanda_syndarna_ar_gitignorerade(self):
        # git rm --cached tar bort ur indexet men inte ur framtiden: utan de
        # här raderna i .gitignore kommer filerna tillbaka nästa gång någon
        # kör `git add -A` med en lokal kopia på disk.
        for sokvag in ("audit_result.json", "audit_flags.tsv",
                       "marketing/build/raw-hero.mp4",
                       "backend/data/audit/audit_result.json"):
            klar = subprocess.run(["git", "check-ignore", "-q", sokvag], cwd=ROOT)
            self.assertEqual(klar.returncode, 0,
                             f"{sokvag} är inte gitignorerad - den kan committas igen")

    def test_auditen_skriver_i_datakatalogen_inte_i_repo_roten(self):
        # Samma MATJAKT_DATA_DIR-override som databaserna. Prövas mot grocery
        # api:ts DB_PATH i stället för mot en egen uträkning - annars hade
        # testet bara jämfört min formel med min formel.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "matjakt_audit_pricing", ROOT / "backend" / "scripts" / "audit_pricing.py")
        modul = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modul)

        from services.grocery import api as gapi
        self.assertEqual(modul.AUDIT_DIR.parent, gapi.DB_PATH.parent,
                         "auditen skriver inte bredvid databaserna den beskriver")
        self.assertEqual(modul.AUDIT_DIR.name, "audit")
        self.assertNotEqual(modul.AUDIT_DIR.parent.resolve(), ROOT.resolve(),
                            "auditen skriver fortfarande i repo-roten")

    def test_audit_pricing_namner_inte_repo_roten_som_utdata(self):
        kalla = (ROOT / "backend" / "scripts" / "audit_pricing.py").read_text(encoding="utf-8")
        self.assertNotIn('ROOT / "audit_result.json"', kalla,
                         "utdatasökvägen pekar tillbaka på repo-roten")

    def test_grinden_finns_i_ci(self):
        # Invarianten ovan är värdelös om ingen kör den på en PR. Testet
        # kräver att CI-steget finns och att det använder samma mönster.
        yaml = CI.read_text(encoding="utf-8")
        self.assertIn("Inga genererade artefakter är spårade", yaml,
                      "CI-steget som failar på spårade artefakter är borta")
        for monster in ARTEFAKTMONSTER:
            self.assertIn(f"'{monster}'", yaml,
                          f"CI-grinden kontrollerar inte {monster}")


if __name__ == "__main__":
    unittest.main()
