# -*- coding: utf-8 -*-
"""K2b: sårbarhetsgrinden ska fällas av sårbarheter, inte av nätet.

2026-09-11, main-committen d34d294, körning 34650990118: steget "Kända
sårbarheter i python-beroendena (pip-audit)" föll med

    requests.exceptions.ConnectionError: ('Connection aborted.',
        ConnectionResetError(104, 'Connection reset by peer'))

En omkörning av samma commit blev grön. "Hemligheter och versioner" är en av
fyra obligatoriska statuscheckar och står sedan K4/K6 i releasekedjan, så en
blipp mot PyPI blockerade varje öppen PR och hela deployen tills en människa
körde om jobbet.

Acceptansen är två påståenden som drar åt VAR SITT håll, och det är först
tillsammans de betyder något:

  RÖTT PÅ EN SÅRBARHET. Grinden kan fortfarande bli röd - på fynd i pip-audit,
  på hög/kritisk i npm audit, och på ett verktyg som går sönder utan
  transportfel. Ett CI-steg som inte kan faila är inget CI-steg.

  INTE RÖTT PÅ EN BLIPP. Ett transportfel görs om, och håller det i sig blir
  det en varning - aldrig ett tyst godkännande som ser ut som ett rent träd.

Nedgraderingen kräver POSITIVT BEVIS: en känd transportsignatur OCH avsaknad
av rapport. Finns en tolkbar rapport är den facit, även om en CVE-text råkar
innehålla ordet "connection reset". Testerna nedan prövar båda riktningarna,
för en grind som bara prövats åt ena hållet är en grind ingen vet något om.

Ingen utgående trafik: verktygen ersätts av attrapper på PATH.
"""

import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _modul(namn, sökväg):
    """Importera per sökväg, som run.py gör med skipbudget.

    backend/scripts ligger inte på sys.path och ska inte läggas där bara för
    det här: insticket gäller hela sviten, och tjugofem skriptnamn som blir
    importerbara överallt är en fälla för nästa fil som heter samma sak.
    """
    spec = importlib.util.spec_from_file_location(namn, sökväg)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


grind = _modul("audit_deps", ROOT / "backend" / "scripts" / "audit_deps.py")

CI = ROOT / ".github" / "workflows" / "ci.yml"

# ── Inspelad utdata, i verktygens egna format ───────────────────────────

# Tracebacken som faktiskt sågs i körning 34650990118.
NÄTFALLET = """Traceback (most recent call last):
  File "/opt/hostedtoolcache/Python/3.12.11/x64/lib/python3.12/site-packages/urllib3/connectionpool.py", line 534, in _make_request
    response = conn.getresponse()
  File "/opt/hostedtoolcache/Python/3.12.11/x64/lib/python3.12/http/client.py", line 1430, in getresponse
    response.begin()
ConnectionResetError: [Errno 104] Connection reset by peer
requests.exceptions.ConnectionError: ('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))
"""

PIP_RENT = json.dumps({
    "dependencies": [
        {"name": "playwright", "version": "1.62.0", "vulns": []},
        {"name": "greenlet", "version": "3.2.4", "vulns": []},
        {"name": "pyee", "version": "13.0.0", "vulns": []},
    ],
    "fixes": [],
})

PIP_SÅRBART = json.dumps({
    "dependencies": [
        {"name": "playwright", "version": "1.62.0", "vulns": []},
        {"name": "jinja2", "version": "3.1.2", "vulns": [
            {"id": "GHSA-h5c8-rqwp-cp95", "fix_versions": ["3.1.3"],
             "description": "Jinja2 does not escape XML attributes."},
        ]},
    ],
    "fixes": [],
})

NPM_RENT = json.dumps({
    "auditReportVersion": 2,
    "vulnerabilities": {},
    "metadata": {"vulnerabilities": {"info": 0, "low": 0, "moderate": 3,
                                     "high": 0, "critical": 0, "total": 3}},
})

NPM_SÅRBART = json.dumps({
    "auditReportVersion": 2,
    "vulnerabilities": {
        "tar-fs": {"name": "tar-fs", "severity": "high", "isDirect": False},
        "minimatch": {"name": "minimatch", "severity": "moderate", "isDirect": False},
    },
    "metadata": {"vulnerabilities": {"info": 0, "low": 0, "moderate": 1,
                                     "high": 1, "critical": 0, "total": 2}},
})

NPM_NÄTFALL = json.dumps({
    "error": {
        "code": "ECONNRESET",
        "summary": "request to https://registry.npmjs.org/-/npm/v1/security/advisories/bulk "
                   "failed, reason: socket hang up",
        "detail": "This is a problem related to network connectivity.",
    },
})


def _svar(returkod=0, ut="", fel=""):
    """En inspelad körning, i den form audit_deps._kör returnerar."""
    return lambda argv: (returkod, ut, fel)


def _serie(*svar):
    """Flera körningar i tur och ordning, och en räknare över hur många."""
    kvar = list(svar)
    körda = []

    def kör(argv):
        körda.append(argv)
        return kvar.pop(0) if len(kvar) > 1 else kvar[0]

    kör.körda = körda
    return kör


class TransportsignaturenKraverBevis(unittest.TestCase):
    """Bara kända nätfel får nedgraderas. Allt annat är rött."""

    def test_tracebacken_fran_korning_34650990118_kanns_igen(self):
        rad = grind.är_nätfall(NÄTFALLET)
        self.assertIsNotNone(rad, "det observerade nätfallet känns inte igen")
        self.assertIn("Connection aborted", rad)

    def test_npm_socket_hang_up_kanns_igen(self):
        self.assertIsNotNone(grind.är_nätfall(NPM_NÄTFALL))

    def test_vanliga_fel_ar_INTE_natfall(self):
        # Hela poängen med en kort mönsterlista. Varje rad här är ett fel som
        # ska fälla grinden, inte slinka igenom som en blipp.
        for text in (
            "ERROR: Could not open requirements file: backend/requirements.txt",
            "Traceback (most recent call last):\n  ValueError: bad lockfile",
            "error: unknown option '--format=json'",
            "npm ERR! code EUSAGE\nnpm ERR! This command requires an existing lockfile.",
            "pip-audit: command not found",
            "THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE",
        ):
            self.assertIsNone(grind.är_nätfall(text),
                              f"nedgraderas felaktigt till nätfall: {text!r}")


class RottPaEnSarbarhet(unittest.TestCase):
    """Grinden kan fortfarande bli röd - det är hela dess existensberättigande."""

    def test_pip_audit_fynd_ar_rott(self):
        utfall, text = grind.tolka_pip_audit(1, PIP_SÅRBART, "")
        self.assertEqual(utfall, grind.SÅRBARHET)
        self.assertIn("GHSA-h5c8-rqwp-cp95", text)

    def test_npm_hog_ar_rott(self):
        utfall, text = grind.tolka_npm_audit(1, NPM_SÅRBART, "")
        self.assertEqual(utfall, grind.SÅRBARHET)
        self.assertIn("tar-fs", text)

    def test_rapporten_ar_facit_aven_nar_cve_texten_later_som_ett_natfall(self):
        # Regel 1: finns ett svar läses aldrig transportsignaturerna. Utan det
        # här beviset kunde en CVE-beskrivning nedgradera sitt eget fynd.
        rapport = json.dumps({"dependencies": [
            {"name": "urllib3", "version": "1.26.4", "vulns": [
                {"id": "GHSA-xxxx", "fix_versions": ["1.26.5"],
                 "description": "Remote end closed connection; Connection reset by peer"},
            ]},
        ]})
        utfall, _ = grind.tolka_pip_audit(1, rapport, NÄTFALLET)
        self.assertEqual(utfall, grind.SÅRBARHET,
                         "en CVE-text fick nedgradera sitt eget fynd till nätfall")

    def test_samma_radgivning_flera_ganger_rapporteras_en_gang(self):
        # Den riktiga körningen mot jinja2==3.1.2 gav tio poster som var fem
        # rådgivningar. En annotation ska gå att läsa.
        dubbel = json.dumps({"dependencies": [{"name": "jinja2", "version": "3.1.2", "vulns": [
            {"id": "PYSEC-2026-1471"}, {"id": "PYSEC-2026-1472"}, {"id": "PYSEC-2026-1471"},
        ]}]})
        _, text = grind.tolka_pip_audit(1, dubbel, "")
        self.assertEqual(text.count("PYSEC-2026-1471"), 1)
        self.assertIn("PYSEC-2026-1472", text)

    def test_lang_fyndlista_kapas_i_annotationen_men_inte_i_loggen(self):
        # En annotation som GitHub kastar är ingen annotation.
        import io, contextlib
        skärm = io.StringIO()
        with contextlib.redirect_stdout(skärm):
            grind.annotera("error", "R", "x" * 9000)
        rad = skärm.getvalue()
        self.assertLess(len(rad), 4000)
        self.assertIn("hela listan står i steget ovanför", rad)

    def test_verktyg_som_gar_sonder_utan_natfel_ar_rott(self):
        # Fail closed: en trasig låsfil, en borttagen flagga eller ett verktyg
        # som inte startar ska INTE se ut som en blipp.
        utfall, _ = grind.tolka_pip_audit(2, "", "ERROR: Could not open requirements file")
        self.assertEqual(utfall, grind.OKÄNT)
        utfall, _ = grind.tolka_npm_audit(1, "", "npm ERR! code EUSAGE")
        self.assertEqual(utfall, grind.OKÄNT)

    def test_npm_egen_felrapport_utan_natsignatur_ar_rott(self):
        trasig = json.dumps({"error": {"code": "EUSAGE", "summary": "no lockfile", "detail": ""}})
        utfall, _ = grind.tolka_npm_audit(1, trasig, "")
        self.assertEqual(utfall, grind.OKÄNT)


class RapportenHittasIBruset(unittest.TestCase):
    """En rapport som inte går att tolka ser ut som "fick inget svar".

    Skulle en dag varenda körning se ut så vore grinden avstängd utan att
    någon märkte det, så tolken ska hitta rapporten även när verktyget skriver
    något runt omkring den.
    """

    def test_notis_fore_rapporten(self):
        brus = "WARNING: pip is being invoked by an old script wrapper\n" + PIP_SÅRBART
        self.assertEqual(grind.tolka_pip_audit(1, brus, "")[0], grind.SÅRBARHET)

    def test_notis_EFTER_rapporten(self):
        brus = PIP_SÅRBART + "\nnpm notice New minor version available\n"
        self.assertEqual(grind.tolka_pip_audit(1, brus, "")[0], grind.SÅRBARHET)

    def test_brus_pa_bada_sidor_om_npm_rapporten(self):
        brus = "npm warn config\n" + NPM_SÅRBART + "\nnpm notice\n"
        self.assertEqual(grind.tolka_npm_audit(1, brus, "")[0], grind.SÅRBARHET)

    def test_ingen_rapport_alls_ar_ingen_rapport(self):
        self.assertIsNone(grind._json_ur("bara text"))
        self.assertIsNone(grind._json_ur(""))


class GrontUtanFynd(unittest.TestCase):
    def test_rent_trad_ar_gront(self):
        self.assertEqual(grind.tolka_pip_audit(0, PIP_RENT, "")[0], grind.REN)

    def test_bara_moderate_blockerar_inte_men_syns(self):
        # Nivån står vid hög med avsikt (K2). De lägre räknas ändå upp.
        utfall, text = grind.tolka_npm_audit(0, NPM_RENT, "")
        self.assertEqual(utfall, grind.REN)
        self.assertIn("3", text)


class BlippenGorsOm(unittest.TestCase):
    """Regel 3: omförsök först, varning sist - och aldrig tyst."""

    def test_ett_natfall_som_gar_over_ger_ratt_svar(self):
        kör = _serie((1, "", NÄTFALLET), (1, PIP_SÅRBART, ""))
        utfall, text = grind.kör_revision(grind.REVISIONER["pip"], försök=3, paus=0,
                                          kör=kör, sov=lambda s: None,
                                          finns=lambda namn: "/usr/bin/" + namn)
        self.assertEqual(utfall, grind.SÅRBARHET,
                         "omförsöket tappade bort sårbarheten som fanns i andra svaret")
        self.assertEqual(len(kör.körda), 2)

    def test_natfall_hela_vagen_blir_natfall_inte_gront(self):
        kör = _serie((1, "", NÄTFALLET))
        utfall, text = grind.kör_revision(grind.REVISIONER["pip"], försök=3, paus=0,
                                          kör=kör, sov=lambda s: None,
                                          finns=lambda namn: "/usr/bin/" + namn)
        self.assertEqual(utfall, grind.NÄTFALL)
        self.assertEqual(len(kör.körda), 3, "gjorde inte om försöket tre gånger")
        self.assertIn("Connection aborted", text)

    def test_en_sarbarhet_gors_INTE_om(self):
        # Omförsök på ett fynd vore bara tre gånger så långsamt rött.
        kör = _serie((1, PIP_SÅRBART, ""))
        utfall, _ = grind.kör_revision(grind.REVISIONER["pip"], försök=3, paus=0,
                                       kör=kör, sov=lambda s: None,
                                       finns=lambda namn: "/usr/bin/" + namn)
        self.assertEqual(utfall, grind.SÅRBARHET)
        self.assertEqual(len(kör.körda), 1)

    def test_pausen_vaxer_mellan_forsoken(self):
        pauser = []
        grind.kör_revision(grind.REVISIONER["npm"], försök=3, paus=5,
                           kör=_serie((1, NPM_NÄTFALL, "")), sov=pauser.append,
                           finns=lambda namn: "/usr/bin/" + namn)
        self.assertEqual(pauser, [5, 10], "pausen växer inte, eller pausar efter sista försöket")

    def test_installationen_racknas_som_kunde_inte_fraga(self):
        # Föll `pip install pip-audit` på nätet kom frågan aldrig fram heller.
        kör = _serie((1, "", "Max retries exceeded with url: /simple/pip-audit/"))
        utfall, _ = grind.kör_revision(grind.REVISIONER["pip"], försök=2, paus=0,
                                       kör=kör, sov=lambda s: None,
                                       finns=lambda namn: None)   # verktyget saknas
        self.assertEqual(utfall, grind.NÄTFALL)

    def test_installation_som_failar_av_annat_skal_ar_rott(self):
        kör = _serie((1, "", "ERROR: No matching distribution found for pip-audit"))
        utfall, _ = grind.kör_revision(grind.REVISIONER["pip"], försök=2, paus=0,
                                       kör=kör, sov=lambda s: None,
                                       finns=lambda namn: None)
        self.assertEqual(utfall, grind.OKÄNT)


class HelaKommandotFranSkalet(unittest.TestCase):
    """Samma prov, men genom den riktiga CLI:n - argv, subprocess, returkod.

    Verktygen ersätts av attrapper på PATH. Att attrappen finns gör dessutom
    att installationssteget hoppas över, så testet går aldrig ut på nätet.

    Attrapperna skrivs EN gång per klass och styrs med miljövariabler. macOS
    kör en Gatekeeper-avsökning vid första exec av varje nyskriven körbar fil
    - drygt en sekund styck - så en attrapp per test gjorde den här klassen
    tio gånger långsammare utan att pröva något mer.
    """

    ATTRAPP = (
        "#!/bin/sh\n"
        'n=0\n[ -f "$K2B_RAKNARE" ] && n=$(cat "$K2B_RAKNARE")\n'
        'n=$((n+1))\necho "$n" > "$K2B_RAKNARE"\n'
        'if [ "$n" -le "${K2B_FALLER:-0}" ]; then\n'
        '  printf %s "$K2B_FEL" >&2\n  exit 1\nfi\n'
        'printf %s "$K2B_UT"\nexit "${K2B_KOD:-0}"\n'
    )

    @classmethod
    def setUpClass(cls):
        cls.bin = Path(tempfile.mkdtemp(prefix="matjakt-k2b-"))
        for namn in ("pip-audit", "npm"):
            skript = cls.bin / namn
            skript.write_text(cls.ATTRAPP, encoding="utf-8")
            skript.chmod(skript.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    @classmethod
    def tearDownClass(cls):
        for fil in cls.bin.iterdir():
            fil.unlink()
        cls.bin.rmdir()

    def setUp(self):
        self.räknare = self.bin / "raknare"

    def tearDown(self):
        if self.räknare.exists():
            self.räknare.unlink()

    def _kör(self, ekosystem, *extra, faller=0, felutdata="", utdata="", kod=0):
        """Kör CLI:n med en attrapp som faller `faller` gånger först."""
        miljö = dict(os.environ,
                     PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                     K2B_RAKNARE=str(self.räknare), K2B_FALLER=str(faller),
                     K2B_FEL=felutdata, K2B_UT=utdata, K2B_KOD=str(kod))
        return subprocess.run(
            [sys.executable, "backend/scripts/audit_deps.py", ekosystem, "--paus", "0", *extra],
            cwd=ROOT, capture_output=True, text=True, env=miljö)

    def _försök(self):
        return self.räknare.read_text().strip()

    def test_sarbarhet_failar_steget(self):
        klar = self._kör("pip", utdata=PIP_SÅRBART, kod=1)
        self.assertEqual(klar.returncode, 1, f"grinden blev inte röd:\n{klar.stdout}{klar.stderr}")
        self.assertIn("GHSA-h5c8-rqwp-cp95", klar.stdout)
        self.assertIn("::error", klar.stdout)

    def test_npm_hog_failar_steget(self):
        klar = self._kör("npm", utdata=NPM_SÅRBART, kod=1)
        self.assertEqual(klar.returncode, 1)
        self.assertIn("tar-fs", klar.stdout)

    def test_rent_trad_slapper_igenom_utan_varning(self):
        klar = self._kör("pip", utdata=PIP_RENT, kod=0)
        self.assertEqual(klar.returncode, 0, klar.stdout + klar.stderr)
        self.assertNotIn("::warning", klar.stdout)

    def test_blipp_som_gar_over_pa_forsok_tre_ar_gron_utan_varning(self):
        klar = self._kör("pip", faller=2, felutdata=NÄTFALLET, utdata=PIP_RENT, kod=0)
        self.assertEqual(klar.returncode, 0, klar.stdout + klar.stderr)
        self.assertNotIn("::warning", klar.stdout)
        self.assertEqual(self._försök(), "3")

    def test_natfall_hela_vagen_ar_varning_och_gront(self):
        klar = self._kör("pip", faller=9, felutdata=NÄTFALLET)
        self.assertEqual(klar.returncode, 0,
                         "en blipp fäller fortfarande grinden:\n" + klar.stdout + klar.stderr)
        self.assertIn("::warning", klar.stdout)
        self.assertIn("OSKANNAT", klar.stdout)

    def test_sarbarhet_efter_en_blipp_ar_fortfarande_rott(self):
        # Det farligaste fallet: nätet blinkar, sedan kommer det riktiga svaret.
        klar = self._kör("pip", faller=1, felutdata=NÄTFALLET, utdata=PIP_SÅRBART, kod=1)
        self.assertEqual(klar.returncode, 1,
                         "omförsöket svalde sårbarheten:\n" + klar.stdout + klar.stderr)

    def test_trasigt_verktyg_ar_rott_inte_varning(self):
        klar = self._kör("pip", faller=9, felutdata="ERROR: Could not open requirements file")
        self.assertEqual(klar.returncode, 1, klar.stdout + klar.stderr)
        self.assertNotIn("::warning", klar.stdout)

    def test_forsoken_gar_att_stalla_ned(self):
        self._kör("pip", "--forsok", "1", faller=9, felutdata=NÄTFALLET)
        self.assertEqual(self._försök(), "1")


class GrindenStarICI(unittest.TestCase):
    """Ett steg som bara finns i ett skript körs aldrig."""

    def setUp(self):
        self.ci = CI.read_text(encoding="utf-8")

    def test_bada_revisionerna_gar_genom_omforsoket(self):
        for ekosystem in ("pip", "npm"):
            self.assertIn(f"backend/scripts/audit_deps.py {ekosystem}", self.ci,
                          f"{ekosystem}-revisionen kör förbi omförsöket och faller på en blipp")

    def test_kommandona_bor_inte_langre_lost_i_ci(self):
        # Flaggorna som ger maskinläsbar utdata hör ihop med tolken. Ett löst
        # `pip-audit`-anrop i ci.yml vore en andra, otolkad väg förbi grinden.
        for löst in ("run: pip-audit", "run: npm audit"):
            self.assertNotIn(löst, self.ci)

    def test_jobbnamnen_ar_ororda(self):
        # De fyra obligatoriska statuscheckarna i ruleset 22826769. Ett omdöpt
        # jobb gör kravet omöjligt att uppfylla och varje PR fastnar för
        # evigt på en check som aldrig rapporteras.
        for namn in ("Backend-tester (isolerad data, inga riktiga anrop)",
                     "Frontend-tester och syntax",
                     "Hemligheter och versioner",
                     "Browser-E2E (Playwright: konsumentresan, Premium/Stripe, "
                     "hushållet med två personer)"):
            self.assertIn(namn, self.ci, f"obligatorisk statuscheck omdöpt eller borta: {namn!r}")

    def test_sakerhetsjobbet_star_kvar_i_releasekedjan(self):
        # Det är den andra halvan av varför en blipp kostade så mycket: en
        # röd security stoppar inte bara PR:er utan hela deployen.
        for rad in re.findall(r"needs: \[([^\]]+)\]", self.ci):
            if "smoke-staging" in rad or "coverage" in rad:
                self.assertIn("security", rad, "security lyftes ur releasekedjan")


class SkriptetKorRattKommandon(unittest.TestCase):
    """K2:s garantier, flyttade dit kommandona numera står."""

    def test_pip_audit_laser_lasfilen_inte_miljon(self):
        self.assertEqual(
            grind.REVISIONER["pip"].kommando[:3],
            ["pip-audit", "-r", "backend/requirements.txt"],
            "skanningen ska läsa exakt det träd som installeras i produktionsimagen")

    def test_npm_blockerar_fran_hog_och_uppat(self):
        self.assertIn("--audit-level=high", grind.REVISIONER["npm"].kommando)

    def test_bada_ber_om_maskinlasbar_utdata(self):
        # Utan den kan tolken inte skilja ett facit från ett nätfall, och då
        # blir varje körning ett nätfall - en grind som aldrig kan bli röd.
        self.assertIn("--format=json", grind.REVISIONER["pip"].kommando)
        self.assertIn("--json", grind.REVISIONER["npm"].kommando)


if __name__ == "__main__":
    unittest.main()
