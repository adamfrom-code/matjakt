# -*- coding: utf-8 -*-
"""CLAUDE.md finns, säger det den måste säga, och skannas av CI.

A1:s acceptanskriterium är två saker, och båda är prövbara:

  1. filen finns — och innehåller de fyra sakerna den ska innehålla
     (kommandon, zonkartan, en agent = en gren = en PR, de absoluta förbuden),
  2. `secret_scan.py` körs i CI **mot den**.

Punkt 2 är den som annars blir en åsikt. secret_scan itererar över `git
ls-files`, så en fil skyddas först när den är spårad. Testet prövar därför
att CLAUDE.md ligger i exakt den listan secret_scan går igenom, att den är
ren idag, OCH att skannern faktiskt fyrar på en ifylld hemlighet i just den
filen. Utan det sista beviset kunde skannern vara avstängd och de tre andra
kontrollerna skulle fortfarande vara gröna.

Anledningen till att förbudet finns: `.claude/launch.json` läckte en
admin-token i klartext till det publika repot (commit 27edd8a).
"""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLAUDE_MD = ROOT / "CLAUDE.md"


def _ladda_secret_scan():
    """secret_scan ligger i backend/scripts/ och är inget paket - ladda på sökväg."""
    spec = importlib.util.spec_from_file_location(
        "matjakt_secret_scan", ROOT / "backend" / "scripts" / "secret_scan.py")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def _git_finns() -> bool:
    try:
        subprocess.run(["git", "rev-parse", "--git-dir"], cwd=ROOT,
                       capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


class Agentinstruktionen(unittest.TestCase):
    def setUp(self):
        if not CLAUDE_MD.exists():
            self.fail("CLAUDE.md saknas i repo-roten - agenter har ingen arbetsinstruktion")
        self.text = CLAUDE_MD.read_text(encoding="utf-8")

    def test_kommandona_star_i_filen(self):
        for kommando in ("npm test", "backend/tests/run.py", "npm run build"):
            self.assertIn(kommando, self.text, f"{kommando} saknas i CLAUDE.md")

    def test_hela_zonkartan_star_i_filen(self):
        # Samma elva zoner som §2 i docs/UPPDRAG-MATJAKT.md. En zon som
        # saknas här är en zon agenten inte vet att den ska hålla sig ur.
        for zon in ("Z-INFRA", "Z-AUTH", "Z-BILLING", "Z-PRICING", "Z-GROCERY",
                    "Z-FRONT-CORE", "Z-FRONT-VIEW", "Z-STYLE", "Z-MAIL",
                    "Z-SITE", "Z-CI"):
            self.assertIn(zon, self.text, f"zonen {zon} saknas i zonkartan")

    def test_regeln_en_agent_en_gren_en_pr(self):
        self.assertIn("En agent = ett paket = en gren = en PR", self.text)
        self.assertIn("paket/<ID>-<kort-slug>", self.text)
        self.assertIn("Ingen merge på röd CI", self.text)

    def test_de_absoluta_forbuden_star_i_filen(self):
        self.assertIn("*.db", self.text)
        self.assertIn(".env", self.text)
        # Varför förbudet mot nyckelvärden i .claude/ finns alls:
        self.assertIn(".claude/launch.json", self.text)
        self.assertIn("MATJAKT_ADMIN_TOKEN", self.text)
        self.assertIn("CHECKPOINT.md", self.text)
        self.assertIn("secret_scan.py", self.text)

    @unittest.skipUnless(_git_finns(), "inget git-arbetsträd att fråga")
    def test_claude_md_ligger_i_listan_secret_scan_gar_igenom(self):
        # CI:s säkerhetsjobb kör secret_scan.py, och secret_scan skannar
        # exakt de filer git spårar. Ligger CLAUDE.md inte där skannas den
        # inte, hur grön CI än ser ut.
        scan = _ladda_secret_scan()
        # assertIn hade skrivit ut hela filträdet i felet; listan är 400 rader.
        self.assertTrue("CLAUDE.md" in scan.tracked_files(),
                        "CLAUDE.md är inte spårad av git - då skannar CI den inte")

    def test_claude_md_ar_ren_idag(self):
        scan = _ladda_secret_scan()
        for nummer, rad in enumerate(self.text.splitlines(), 1):
            for namn, monster in scan.PATTERNS.items():
                for traff in monster.finditer(rad):
                    if scan.ALLOWLIST.search(traff.group(0)):
                        continue
                    self.fail(f"CLAUDE.md:{nummer} innehåller [{namn}]")

    def test_skannern_fyrar_faktiskt_pa_en_hemlighet_i_claude_md(self):
        # Bevisar att kontrollen är levande och inte dekorativ. Raden byggs
        # ihop i minnet - skrevs den ut som literal skulle secret_scan
        # (helt riktigt) flagga det HÄR testet i stället.
        scan = _ladda_secret_scan()
        variabel = "MATJAKT_" + "ADMIN_TOKEN"
        planterad = f'{variabel} = "{"a1b2c3d4" * 4}"'
        trafffad = any(m.search(planterad) for m in scan.PATTERNS.values())
        self.assertTrue(trafffad, "secret_scan hittar inte ens en ifylld admin-token")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
