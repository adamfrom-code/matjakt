# -*- coding: utf-8 -*-
"""K5: versionskontrollen kontrollerade likhet, inte färskhet.

`check_frontend_version.py` krävde att sw.js CACHE_NAME, `app.js?v=` och
`styles.css?v=` var LIKA. Det är en riktig kontroll och den stannar kvar - men
den säger ingenting om att talen ska ha HÖJTS när frontenden faktiskt ändrats.
En PR som rörde `frontend/app/app.js` utan bump var alltså grön hela vägen,
och sedan serverade GitHub Pages HTTP-cache den gamla app.js under exakt samma
URL medan service workern behöll sin kopia tills CACHE_NAME bytte.

Det felet har hänt, och det står i sw.js egen inledning: "the site was updated,
phones still showed the old three week types". Den enda kontrollen mot det var
att någon kom ihåg.

Acceptansen är ett CI-steg som failar när frontenden ändrats utan bump, och
den prövas här mot RIKTIGA git-repon. Ett textmatchningstest mot ci.yml hade
inte bevisat någonting om vad skriptet gör med en faktisk historik; varje fall
nedan bygger därför ett litet repo, gör en gren, och kör skriptet som en
process precis som CI gör.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKRIPT = ROOT / "backend" / "scripts" / "check_frontend_version.py"
CI = ROOT / ".github" / "workflows" / "ci.yml"

SW_MALL = '''// app shell
const CACHE_NAME = "matjakt-shell-v{v}";
'''
HTML_MALL = '''<!doctype html>
<link rel="stylesheet" href="styles.css?v={v}">
<script type="module" src="app.js?v={v}"></script>
'''


def _git_finns() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


@unittest.skipUnless(_git_finns(), "git saknas")
class Färskhetsgrinden(unittest.TestCase):
    """Varje test bygger ett eget repo med det RIKTIGA skriptet i."""

    def setUp(self):
        self.rep = Path(tempfile.mkdtemp(prefix="matjakt-k5-"))
        self.addCleanup(shutil.rmtree, self.rep, ignore_errors=True)
        (self.rep / "backend" / "scripts").mkdir(parents=True)
        (self.rep / "frontend" / "app" / "src").mkdir(parents=True)
        (self.rep / "backend" / "tjanst").mkdir(parents=True)
        shutil.copy(SKRIPT, self.rep / "backend" / "scripts" / "check_frontend_version.py")
        self.skriv_version(1)
        (self.rep / "frontend" / "app" / "app.js").write_text("// app\n", encoding="utf-8")
        (self.rep / "backend" / "tjanst" / "api.py").write_text("# api\n", encoding="utf-8")
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@matjakt.local")
        self.git("config", "user.name", "Test")
        self.commit("bas")
        self.bas = self.git("rev-parse", "HEAD").strip()

    # ── verktyg ────────────────────────────────────────────────────────
    def git(self, *argument) -> str:
        klar = subprocess.run(["git", *argument], cwd=self.rep, capture_output=True,
                              text=True, encoding="utf-8")
        self.assertEqual(klar.returncode, 0, f"git {argument}: {klar.stderr}")
        return klar.stdout

    def commit(self, meddelande):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", meddelande)

    def skriv_version(self, v):
        (self.rep / "frontend" / "app" / "sw.js").write_text(SW_MALL.format(v=v), encoding="utf-8")
        (self.rep / "frontend" / "app" / "index.html").write_text(HTML_MALL.format(v=v), encoding="utf-8")

    def kör(self, *extra):
        """Samma anrop som CI-steget gör."""
        miljö = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull)
        klar = subprocess.run([sys.executable, "backend/scripts/check_frontend_version.py",
                               "--require-bump", *extra],
                              cwd=self.rep, capture_output=True, text=True,
                              encoding="utf-8", env=miljö)
        return klar.returncode, klar.stdout + klar.stderr

    # ── grinden stänger ────────────────────────────────────────────────
    def test_andrad_app_js_utan_bump_ar_rott(self):
        """Fyndet, ordagrant: en PR som rör app.js utan bump var grön."""
        self.git("checkout", "-q", "-b", "paket/nagot")
        (self.rep / "frontend" / "app" / "app.js").write_text("// ny logik\n", encoding="utf-8")
        self.commit("rör app.js")
        kod, ut = self.kör("--base", self.bas)
        self.assertEqual(kod, 1, f"grinden släppte igenom en obumpad frontendändring:\n{ut}")
        self.assertIn("frontend/app/app.js", ut, "felet ska peka ut filen")
        self.assertIn("--bump", ut, "felet ska säga exakt vad man kör för att fixa det")

    def test_andrad_modul_under_src_ar_ocksa_rott(self):
        # src/ är hälften av appen sedan F-vågen. Att bara bevaka app.js hade
        # lämnat den större delen obevakad.
        self.git("checkout", "-q", "-b", "paket/modul")
        (self.rep / "frontend" / "app" / "src" / "http.js").write_text("export const a = 1;\n", encoding="utf-8")
        self.commit("ny modul")
        kod, _ = self.kör("--base", self.bas)
        self.assertEqual(kod, 1)

    def test_andrad_css_ar_rott(self):
        self.git("checkout", "-q", "-b", "paket/stil")
        (self.rep / "frontend" / "app" / "styles.css").write_text(":root{}\n", encoding="utf-8")
        self.commit("ny css")
        self.assertEqual(self.kör("--base", self.bas)[0], 1)

    def test_borttagen_frontendfil_ar_ocksa_en_andring(self):
        self.git("checkout", "-q", "-b", "paket/bort")
        (self.rep / "frontend" / "app" / "app.js").unlink()
        self.commit("bort med app.js")
        self.assertEqual(self.kör("--base", self.bas)[0], 1)

    def test_sankt_version_ar_rott(self):
        # "Höjd", inte "ändrad": en återställning till ett gammalt tal ger en
        # CACHE_NAME som webbläsaren redan har en kopia under.
        self.skriv_version(9)
        self.commit("version 9")
        bas9 = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-q", "-b", "paket/sank")
        (self.rep / "frontend" / "app" / "app.js").write_text("// ny\n", encoding="utf-8")
        self.skriv_version(8)
        self.commit("sänkt version")
        self.assertEqual(self.kör("--base", bas9)[0], 1)

    def test_skev_version_ar_fortfarande_rott(self):
        # Den gamla kontrollen finns kvar och prövas i samma körning.
        self.git("checkout", "-q", "-b", "paket/skev")
        (self.rep / "frontend" / "app" / "sw.js").write_text(SW_MALL.format(v=2), encoding="utf-8")
        self.commit("bara sw.js bumpad")
        kod, ut = self.kör("--base", self.bas)
        self.assertEqual(kod, 1)
        self.assertIn("VERSIONSSKEVHET", ut)

    def test_utan_bas_att_jamfora_mot_svarar_grinden_aldrig_ja(self):
        # En grind som inte vet ska inte gissa "grönt". Ett repo utan main och
        # utan användbar --base är precis det läget.
        self.git("checkout", "-q", "-b", "paket/losryckt")
        (self.rep / "frontend" / "app" / "app.js").write_text("// ny\n", encoding="utf-8")
        self.commit("ändring")
        self.git("branch", "-q", "-D", "main")
        kod, ut = self.kör("--base", "")
        self.assertEqual(kod, 1, f"utan bas måste grinden bli röd:\n{ut}")
        self.assertIn("Hittade ingen bas", ut)

    # ── grinden släpper igenom det den ska ─────────────────────────────
    def test_andrad_app_js_MED_bump_ar_gront(self):
        self.git("checkout", "-q", "-b", "paket/bumpad")
        (self.rep / "frontend" / "app" / "app.js").write_text("// ny logik\n", encoding="utf-8")
        self.skriv_version(2)
        self.commit("rör app.js + bump")
        kod, ut = self.kör("--base", self.bas)
        self.assertEqual(kod, 0, ut)
        self.assertIn("1 -> 2", ut)

    def test_bara_backend_andrad_kraver_ingen_bump(self):
        # De allra flesta paketen rör aldrig frontenden. Skulle grinden kräva
        # en bump av dem hade den blivit en tull, och en tull stängs av.
        self.git("checkout", "-q", "-b", "paket/backend")
        (self.rep / "backend" / "tjanst" / "api.py").write_text("# ny väg\n", encoding="utf-8")
        self.commit("bara backend")
        kod, ut = self.kör("--base", self.bas)
        self.assertEqual(kod, 0, ut)
        self.assertIn("ingen bump krävs", ut)

    def test_ingen_andring_alls_ar_gront(self):
        self.assertEqual(self.kör("--base", self.bas)[0], 0)

    def test_hopp_over_flera_steg_racker(self):
        # Kravet är HÖJD, inte "höjd med exakt ett". Två grenar som båda
        # bumpar och ombaseras efter varandra ska kunna landa på 3, 5, 12.
        self.git("checkout", "-q", "-b", "paket/hopp")
        (self.rep / "frontend" / "app" / "app.js").write_text("// ny\n", encoding="utf-8")
        self.skriv_version(12)
        self.commit("hopp till 12")
        self.assertEqual(self.kör("--base", self.bas)[0], 0)

    def test_bumpen_i_en_tidigare_commit_pa_grenen_raknas(self):
        # Bumpen behöver inte ligga i samma commit som ändringen.
        self.git("checkout", "-q", "-b", "paket/tva-commits")
        self.skriv_version(2)
        self.commit("bump först")
        (self.rep / "frontend" / "app" / "app.js").write_text("// sen koden\n", encoding="utf-8")
        self.commit("sen ändringen")
        self.assertEqual(self.kör("--base", self.bas)[0], 0)

    def test_utan_base_hittar_den_main_sjalv(self):
        # Lokalt kör man utan --base. Då ska merge-base mot main användas.
        self.git("checkout", "-q", "-b", "paket/lokal")
        (self.rep / "frontend" / "app" / "app.js").write_text("// ny\n", encoding="utf-8")
        self.commit("ändring utan bump")
        kod, ut = self.kör()
        self.assertEqual(kod, 1, f"merge-base mot main skulle ha hittats:\n{ut}")

    def test_bumpen_som_fixar_det_gor_korningen_gron(self):
        """Hela poängen: felet går att åtgärda med kommandot felet skriver ut."""
        self.git("checkout", "-q", "-b", "paket/fix")
        (self.rep / "frontend" / "app" / "app.js").write_text("// ny\n", encoding="utf-8")
        self.commit("ändring")
        self.assertEqual(self.kör("--base", self.bas)[0], 1)
        subprocess.run([sys.executable, "backend/scripts/check_frontend_version.py", "--bump"],
                       cwd=self.rep, capture_output=True, check=True)
        self.commit("bump")
        self.assertEqual(self.kör("--base", self.bas)[0], 0)


class StegetFinnsICI(unittest.TestCase):
    """En grind som bara finns i ett skript körs aldrig."""

    def test_ci_kor_require_bump_med_en_bas_ur_handelsen(self):
        ci = CI.read_text(encoding="utf-8")
        self.assertTrue("--require-bump" in ci,
                        "security-jobbet måste köra färskhetskontrollen, inte bara likheten")
        self.assertTrue("github.event.pull_request.base.sha" in ci,
                        "basen måste komma ur händelsen - annars mäts fel sträcka på en PR")
        self.assertTrue("github.event.merge_group.base_sha" in ci,
                        "merge_group har en egen bas; utan den mäter kön mot fel commit")
        self.assertTrue("fetch-depth: 0" in ci,
                        "utan full historia går basen inte att läsa")


if __name__ == "__main__":
    unittest.main()
