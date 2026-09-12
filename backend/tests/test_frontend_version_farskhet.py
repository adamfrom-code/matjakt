# -*- coding: utf-8 -*-
"""K5 + L9: versionskontrollen kontrollerade likhet, inte färskhet — och sedan
flyttades färskhetskontrollen till bygget.

K5. `check_frontend_version.py` krävde att sw.js CACHE_NAME, `app.js?v=` och
`styles.css?v=` var LIKA. Det är en riktig kontroll, men den sa ingenting om
att talen skulle ha HÖJTS när frontenden faktiskt ändrats. En PR som rörde
`frontend/app/app.js` utan bump var alltså grön hela vägen, och sedan
serverade GitHub Pages HTTP-cache den gamla app.js under exakt samma URL medan
service workern behöll sin kopia tills CACHE_NAME bytte. Det felet har hänt,
och det står i sw.js egen inledning: "sidan var uppdaterad, telefonerna visade
de gamla tre veckotyperna". Den enda kontrollen mot det var att någon kom ihåg.

L9. Kravet gick bara att uppfylla genom att någon redigerade tre rader för
hand, och de tre raderna var det enda åtta parallella grenar konfliktade på.
Nu bär källan en platshållare och bygget stämplar in eran plus en DIGEST över
varje fil under app/. Grinden flyttades med — den TOGS INTE BORT, den bytte
fråga:

    förr:  "har någon höjt ett tal, förhoppningsvis för att innehållet ändrats?"
    nu:    "ÄR cache-nyckeln det som ligger i bygget?"

Den andra frågan är starkare, och den prövas här i båda riktningarna. Ett
bygge vars innehåll gått vidare utan att stämpeln följt med är rött — det är
K5:s fall, ordagrant, bara bevisat i stället för påmint. Ett bygge där
platshållaren står kvar är rött. Och en källa där ett tal smugit tillbaka in
är rött, för då är konfliktraden tillbaka.

Grinden prövas som en PROCESS, precis som CI kör den, mot riktiga kataloger.
Ett textmatchningstest mot ci.yml hade inte bevisat någonting om vad skriptet
gör med ett faktiskt bygge.
"""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKRIPT = ROOT / "backend" / "scripts" / "check_frontend_version.py"
GENERATOR = ROOT / "scripts" / "frontend_version.mjs"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _ladda_grinden():
    """Grinden som modul - bara för att STÄLLA UPP korrekt stämplade byggen.

    Varje påstående nedan prövas mot skriptet som process. Det här är fixturen,
    inte kontrollen: att skriva digesten en tredje gång i testet hade bara
    prövat att testet kan kopiera sig självt.
    """
    spec = importlib.util.spec_from_file_location("_check_frontend_version", SKRIPT)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


GRIND = _ladda_grinden()
PLATSHALLARE = GRIND.PLATSHALLARE
ERA = GRIND.ERA

SW_MALL = '// app shell\nconst CACHE_NAME = "matjakt-shell-v{v}";\n'
HTML_MALL = ('<!doctype html>\n<link rel="stylesheet" href="styles.css?v={v}">\n'
             '<script type="module" src="app.js?v={v}"></script>\n')


def kor(*argv, cwd=ROOT):
    """Samma anrop som CI-steget gör."""
    klar = subprocess.run([sys.executable, str(SKRIPT), *argv], cwd=cwd,
                          capture_output=True, text=True, encoding="utf-8")
    return klar.returncode, klar.stdout + klar.stderr


class Bygggrinden(unittest.TestCase):
    """Cache-stämpeln i bygget måste VARA digesten av bygget."""

    def setUp(self):
        self.bygge = Path(tempfile.mkdtemp(prefix="matjakt-l9-bygge-"))
        self.addCleanup(shutil.rmtree, self.bygge, ignore_errors=True)
        self.app = self.bygge / "app"
        (self.app / "data").mkdir(parents=True)
        (self.app / "assets").mkdir(parents=True)
        self.skriv("app.js", "// buntad app\n")
        self.skriv("styles.css", ":root{--a:1}\n")
        self.skriv("data/recipes.json", "[]\n")
        self.skriv("assets/chili.jpg", "JPEG-ish\n")
        self.skriv("admin.html", "<h1>admin</h1>\n")
        self.stampla()

    # ── verktyg ────────────────────────────────────────────────────────
    def skriv(self, namn, text):
        (self.app / namn).write_text(text, encoding="utf-8")

    def stampla(self):
        """Gör bygget till ett korrekt stämplat bygge - som byggsteget gör."""
        self.skriv("sw.js", SW_MALL.format(v=PLATSHALLARE))
        self.skriv("index.html", HTML_MALL.format(v=PLATSHALLARE))
        stampel = GRIND.stampel_for(GRIND.filer_i(self.app))
        self.skriv("sw.js", SW_MALL.format(v=stampel))
        self.skriv("index.html", HTML_MALL.format(v=stampel))
        return stampel

    def kor(self):
        return kor("--build", str(self.bygge))

    # ── grinden släpper igenom det den ska ─────────────────────────────
    def test_ett_stamplat_bygge_ar_gront(self):
        kod, ut = self.kor()
        self.assertEqual(kod, 0, ut)
        self.assertIn(f"era {ERA}", ut)

    def test_ett_bygge_utan_app_katalog_gar_ocksa_att_peka_pa(self):
        kod, ut = kor("--build", str(self.app))
        self.assertEqual(kod, 0, ut)

    # ── grinden stänger: innehållet gick vidare, stämpeln stod kvar ────
    def test_andrad_app_js_utan_ny_stampel_ar_rott(self):
        """K5:s fynd, ordagrant: app.js ändrad, cache-nyckeln oförändrad."""
        self.skriv("app.js", "// ny logik\n")
        kod, ut = self.kor()
        self.assertEqual(kod, 1, f"grinden släppte igenom ett bygge med gammal cache-nyckel:\n{ut}")
        self.assertIn("digesten", ut)
        self.assertIn("npm run build", ut, "felet ska säga exakt vad man kör för att fixa det")

    def test_andrad_css_ar_rott(self):
        self.skriv("styles.css", ":root{--a:2}\n")
        self.assertEqual(self.kor()[0], 1)

    def test_andrad_receptbank_ar_rott(self):
        # Den gamla stämpelns tysta hål: data/ ändrade varken app.js eller
        # styles.css men ligger bakom samma cache-nyckel.
        self.skriv("data/recipes.json", '[{"id": 1}]\n')
        self.assertEqual(self.kor()[0], 1)

    def test_utbytt_bild_ar_rott(self):
        self.skriv("assets/chili.jpg", "JPEG-annat\n")
        self.assertEqual(self.kor()[0], 1)

    def test_andrad_adminsida_ar_rott(self):
        self.skriv("admin.html", "<h1>admin 2</h1>\n")
        self.assertEqual(self.kor()[0], 1)

    def test_tillagd_fil_ar_rott(self):
        self.skriv("nytt.js", "export const a = 1;\n")
        self.assertEqual(self.kor()[0], 1)

    def test_borttagen_fil_ar_rott(self):
        (self.app / "data" / "recipes.json").unlink()
        self.assertEqual(self.kor()[0], 1)

    def test_andrad_rad_i_index_html_ar_rott(self):
        # index.html bär själv stämpeln. Normaliseringen får bara nollställa
        # stämpeln, inte resten av filen.
        (self.app / "index.html").write_text(
            (self.app / "index.html").read_text(encoding="utf-8") + "<p>ny rad</p>\n", encoding="utf-8")
        self.assertEqual(self.kor()[0], 1)

    # ── grinden stänger: stämpeln är inte det den utger sig för ────────
    def test_skev_stampel_ar_rott(self):
        # Den gamla likhetskontrollen finns kvar och prövas i samma körning.
        self.skriv("sw.js", SW_MALL.format(v=f"{ERA}-0000000000"))
        kod, ut = self.kor()
        self.assertEqual(kod, 1)
        self.assertIn("VERSIONSSKEVHET", ut)

    def test_sankt_era_ar_rott(self):
        """"Höjd", inte "ändrad": en etikett som går bakåt släpps inte igenom."""
        riktig = self.stampla()
        sankt = f"{ERA - 1}-{riktig.split('-', 1)[1]}"
        self.skriv("sw.js", SW_MALL.format(v=sankt))
        self.skriv("index.html", HTML_MALL.format(v=sankt))
        kod, ut = self.kor()
        self.assertEqual(kod, 1, f"en sänkt era gick igenom:\n{ut}")
        self.assertIn(sankt, ut)

    def test_kvarstaende_platshallare_ar_rott(self):
        # Det farligaste utfallet: en cache-nyckel som aldrig byter. Ett tyst
        # genomsläpp här hade gjort varje deploy efteråt osynlig för en telefon
        # som redan varit inne.
        self.skriv("sw.js", SW_MALL.format(v=PLATSHALLARE))
        self.skriv("index.html", HTML_MALL.format(v=PLATSHALLARE))
        kod, ut = self.kor()
        self.assertEqual(kod, 1, f"grinden släppte igenom en ostämplad cache-nyckel:\n{ut}")
        self.assertIn(PLATSHALLARE, ut)
        self.assertIn("sw.js", ut)

    def test_platshallare_i_en_fil_som_ingen_stamplar_ar_ocksa_rott(self):
        self.skriv("admin.html", f'<script src="admin.js?v={PLATSHALLARE}"></script>\n')
        self.skriv("sw.js", SW_MALL.format(v=PLATSHALLARE))
        self.skriv("index.html", HTML_MALL.format(v=PLATSHALLARE))
        kod, ut = self.kor()
        self.assertEqual(kod, 1)
        self.assertIn("admin.html", ut)

    def test_en_katalog_som_inte_ar_ett_bygge_ar_rott(self):
        # En grind som inte vet ska inte gissa "grönt".
        tom = Path(tempfile.mkdtemp(prefix="matjakt-l9-tomt-"))
        self.addCleanup(shutil.rmtree, tom, ignore_errors=True)
        kod, ut = kor("--build", str(tom))
        self.assertEqual(kod, 1, f"en tom katalog måste bli röd:\n{ut}")
        self.assertIn("npm run build", ut)

    # ── hela vägen ─────────────────────────────────────────────────────
    def test_ombyggnaden_som_fixar_det_gor_korningen_gron(self):
        """Poängen: felet går att åtgärda med det kommandot felet skriver ut."""
        self.skriv("app.js", "// ny logik\n")
        self.assertEqual(self.kor()[0], 1)
        self.stampla()          # det byggsteget gör
        self.assertEqual(self.kor()[0], 0)

    def test_de_gamla_flaggorna_sager_vad_som_galler_nu(self):
        # --require-bump/--bump fanns för ett tal i källan. Att bara ta bort dem
        # hade gett ett argparse-fel utan förklaring i varje gammal körning.
        for flagga in (["--bump"], ["--require-bump", "--base", "HEAD"]):
            kod, ut = kor(*flagga)
            self.assertEqual(kod, 1, ut)
            self.assertIn("npm run build", ut)


class Kallgrinden(unittest.TestCase):
    """Versionen får inte stå i källan. Den raden VAR konflikten.

    Grinden läser repo-roten relativt sig själv, så varje fall bygger ett eget
    litet repo med det RIKTIGA skriptet i.
    """

    def setUp(self):
        self.rep = Path(tempfile.mkdtemp(prefix="matjakt-l9-kalla-"))
        self.addCleanup(shutil.rmtree, self.rep, ignore_errors=True)
        (self.rep / "backend" / "scripts").mkdir(parents=True)
        (self.rep / "scripts").mkdir(parents=True)
        (self.rep / "frontend" / "app").mkdir(parents=True)
        self.skript = self.rep / "backend" / "scripts" / "check_frontend_version.py"
        shutil.copy(SKRIPT, self.skript)
        shutil.copy(GENERATOR, self.rep / "scripts" / "frontend_version.mjs")
        self.skriv_kalla(PLATSHALLARE)

    def skriv_kalla(self, sw_v, html_v=None):
        (self.rep / "frontend" / "app" / "sw.js").write_text(
            SW_MALL.format(v=sw_v), encoding="utf-8")
        (self.rep / "frontend" / "app" / "index.html").write_text(
            HTML_MALL.format(v=html_v if html_v is not None else sw_v), encoding="utf-8")

    def kor(self, *argv):
        klar = subprocess.run([sys.executable, str(self.skript), *argv], cwd=self.rep,
                              capture_output=True, text=True, encoding="utf-8")
        return klar.returncode, klar.stdout + klar.stderr

    def test_platshallare_pa_alla_tre_ar_gront(self):
        kod, ut = self.kor()
        self.assertEqual(kod, 0, ut)
        self.assertIn(PLATSHALLARE, ut)

    def test_ett_tal_i_sw_js_ar_rott(self):
        self.skriv_kalla("107", PLATSHALLARE)
        kod, ut = self.kor()
        self.assertEqual(kod, 1, f"konfliktraden kom tillbaka utan att något sa till:\n{ut}")
        self.assertIn("sw.js CACHE_NAME", ut)
        self.assertIn("npm run build", ut)

    def test_ett_tal_i_index_html_ar_rott(self):
        self.skriv_kalla(PLATSHALLARE, "107")
        kod, ut = self.kor()
        self.assertEqual(kod, 1)
        self.assertIn("index.html", ut)

    def test_alla_tre_bumpade_pa_gammalt_vis_ar_ocksa_rott(self):
        # Det gamla sättet var att höja alla tre. Det är precis det som ska
        # sluta hända: likheten räcker inte, talet ska inte finnas.
        self.skriv_kalla("107")
        self.assertEqual(self.kor()[0], 1)

    def test_helt_borttagen_version_ar_rott(self):
        (self.rep / "frontend" / "app" / "sw.js").write_text("// inget här\n", encoding="utf-8")
        self.assertEqual(self.kor()[0], 1)

    def test_kallgrinden_kors_aven_nar_bygget_kollas(self):
        # `--build` ska inte kunna användas för att smyga förbi källgrinden.
        bygge = self.rep / "dist"
        (bygge / "app").mkdir(parents=True)
        (bygge / "app" / "sw.js").write_text(SW_MALL.format(v="1-abcdef0123"), encoding="utf-8")
        (bygge / "app" / "index.html").write_text(HTML_MALL.format(v="1-abcdef0123"), encoding="utf-8")
        self.skriv_kalla("107")
        self.assertEqual(self.kor("--build", str(bygge))[0], 1)


def _kan_bygga() -> bool:
    return (ROOT / "node_modules" / "esbuild").exists() and shutil.which("node") is not None


@unittest.skipUnless(_kan_bygga(), "node_modules/esbuild saknas - byggsteget går inte att köra")
class MotEttRiktigtBygge(unittest.TestCase):
    """Den skarpa varianten: två oberoende implementationer måste vara eniga.

    Digestens regel finns två gånger - i scripts/frontend_version.mjs (som
    stämplar) och i check_frontend_version.py (som kontrollerar). Det är hela
    poängen med grinden: en kontroll som bara frågar byggskriptet om dess eget
    svar kontrollerar ingenting. Här körs det riktiga byggsteget och den
    riktiga grinden mot samma katalog.
    """

    def setUp(self):
        self.ut = Path(tempfile.mkdtemp(prefix="matjakt-l9-riktigt-"))
        self.addCleanup(shutil.rmtree, self.ut, ignore_errors=True)
        klar = subprocess.run(["node", "scripts/build_frontend.mjs", str(self.ut)],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(klar.returncode, 0, f"byggsteget failade:\n{klar.stdout}{klar.stderr}")

    def test_det_riktiga_bygget_gar_igenom_den_riktiga_grinden(self):
        kod, ut = kor("--build", str(self.ut))
        self.assertEqual(kod, 0, f"JS-sidan och Python-sidan räknade fram olika digest:\n{ut}")

    def test_en_byte_andrad_i_bygget_gor_grinden_rod(self):
        app_js = self.ut / "app" / "app.js"
        app_js.write_text(app_js.read_text(encoding="utf-8") + "\n// en rad till\n", encoding="utf-8")
        kod, ut = kor("--build", str(self.ut))
        self.assertEqual(kod, 1, f"grinden såg inte att bygget ändrats:\n{ut}")

    def test_bygget_failar_sjalvt_pa_en_platshallare_det_inte_kan_stampla(self):
        # Byggsteget är den första grinden, och den viktigaste: ett tyst
        # genomsläpp hade gett en cache-nyckel som aldrig byter i produktion.
        smuts = ROOT / "frontend" / "app" / "_l9_platshallartest.html"
        smuts.write_text(f'<script src="x.js?v={PLATSHALLARE}"></script>\n', encoding="utf-8")
        self.addCleanup(smuts.unlink, True)
        klar = subprocess.run(["node", "scripts/build_frontend.mjs", str(self.ut / "andra")],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(klar.returncode, 1, "bygget släppte igenom en ostämplad platshållare")
        self.assertIn("_l9_platshallartest.html", klar.stdout + klar.stderr)


class StegetFinnsICI(unittest.TestCase):
    """En grind som bara finns i ett skript körs aldrig."""

    def test_ci_kor_grinden_mot_ett_riktigt_bygge(self):
        ci = CI.read_text(encoding="utf-8")
        self.assertIn("check_frontend_version.py --build", ci,
                      "security-jobbet måste kontrollera BYGGET - källan har ingen version att kontrollera")
        bygg = ci.index("npm run build")
        grind = ci.index("check_frontend_version.py --build")
        self.assertLess(bygg, grind, "grinden måste köras efter att bygget finns")

    def test_ci_kor_ocksa_kallgrinden(self):
        ci = CI.read_text(encoding="utf-8")
        self.assertIn("check_frontend_version.py\n", ci,
                      "utan källgrinden kan konfliktraden smyga tillbaka in")


if __name__ == "__main__":
    unittest.main()
