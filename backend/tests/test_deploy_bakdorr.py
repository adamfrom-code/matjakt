# -*- coding: utf-8 -*-
"""K6: den manuella vägen förbi hela grinden, och dubbelarbetet efter den.

`deploy.yml` hade `workflow_dispatch:` i sin `on:`. Två klick i Actions-vyn
publicerade till matjakt.store med `npm test` som enda grind - ingen
hemlighetsskanning, ingen versionskontroll, ingen browser-E2E, ingen kontroll
av att backenden kör samma commit. `github.sha` kunde dessutom peka på vilken
gren som helst.

Det gjorde varje annan grind i det här repot frivillig. Branch protection,
de fyra obligatoriska checkarna, hälsokontrollen från K3 - allt gick att gå
förbi, och den som gjorde det behövde inte ens veta att det var det hon
gjorde.

Samma fil körde dessutom hela backendsviten en gång till på exakt den SHA som
CI redan hade godkänt - två och en halv minut för att ställa en fråga som
redan var besvarad.

Testerna nedan håller fast båda: bakdörren finns inte, dubbelarbetet är borta,
och villkoret som SLÄPPER IGENOM en publicering är kvar och lika strikt.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
GOLV = ROOT / "backend" / "tests" / "tackningsgolv.txt"
COVERAGERC = ROOT / ".coveragerc"


def triggers(text: str):
    """Vad som får starta workflowen: raderna under `on:` till nästa blockstart."""
    efter = text.split("\non:\n", 1)[1]
    block = efter.split("\npermissions:", 1)[0]
    return set(re.findall(r"^  ([a-z_]+):", block, re.MULTILINE))


class BakdorrenArStangd(unittest.TestCase):
    def setUp(self):
        self.deploy = DEPLOY.read_text(encoding="utf-8")

    def test_ingen_manuell_start_av_pages_deployen(self):
        self.assertNotIn("workflow_dispatch", triggers(self.deploy),
                         "deploy.yml går att starta för hand igen - då publiceras "
                         "matjakt.store förbi hemlighetsskanning, versionskontroll, "
                         "E2E och hälsokontroll")

    def test_bara_ci_kan_starta_den(self):
        self.assertEqual(triggers(self.deploy), {"workflow_run"},
                         "en ny trigger i deploy.yml är en ny väg till produktion")

    def test_villkoret_slapper_bara_igenom_en_gron_push_till_main(self):
        # Det som INTE ska försvinna med bakdörren.
        for krav in ("github.event.workflow_run.conclusion == 'success'",
                     "github.event.workflow_run.event == 'push'",
                     "github.event.workflow_run.head_branch == 'main'"):
            self.assertIn(krav, self.deploy, f"villkoret {krav} är borta")

    def test_villkoret_har_ingen_undantagsgren_kvar(self):
        # `github.event_name == 'workflow_dispatch' || (...)` var hela
        # bakdörren. Blir den kvar spelar det ingen roll att triggern är
        # borttagen - nästa person som lägger tillbaka triggern får den gratis.
        self.assertNotIn("github.event_name == 'workflow_dispatch'", self.deploy)

    def test_utcheckningen_har_ingen_fallback_till_godtycklig_sha(self):
        # `github.event.workflow_run.head_sha || github.sha` fanns för att
        # workflow_dispatch inte har någon workflow_run. Utan den manuella
        # vägen är fallbacken bara ett sätt att checka ut fel commit.
        #
        # Kommentarsrader räknas inte: texten som FÖRKLARAR varför fallbacken
        # är borta nämner den med nödvändighet.
        kod = "\n".join(rad for rad in self.deploy.splitlines()
                        if not rad.lstrip().startswith("#"))
        self.assertNotIn("github.sha", kod,
                         "fallbacken till github.sha kan checka ut en commit CI inte testat")
        self.assertIn("ref: ${{ github.event.workflow_run.head_sha }}", kod)


class DubbelarbetetArBorta(unittest.TestCase):
    def setUp(self):
        self.deploy = DEPLOY.read_text(encoding="utf-8")

    def test_hela_sviten_kors_inte_en_gang_till_pa_samma_sha(self):
        self.assertNotIn("run: npm test", self.deploy,
                         "deploy.yml kör om hela sviten på en SHA som CI redan godkänt")

    def test_publiceringsjobbet_ar_kvar_och_bar_villkoret_sjalvt(self):
        # Villkoret satt på `test`-jobbet och nådde `deploy` via `needs`. Tas
        # `test` bort utan att villkoret flyttar blir deployen ovillkorlig.
        self.assertIn("  deploy:", self.deploy)
        efter = self.deploy.split("  deploy:", 1)[1][:600]
        self.assertIn("if: github.event.workflow_run.conclusion == 'success'", efter,
                      "deploy-jobbet publicerar utan villkor")


class TackningenMats(unittest.TestCase):
    def test_golvet_finns_och_ar_ett_tal(self):
        self.assertTrue(GOLV.exists(), "backend/tests/tackningsgolv.txt saknas")
        värde = GOLV.read_text(encoding="utf-8").strip()
        self.assertRegex(värde, r"^\d+(\.\d+)?$", "golvet måste vara ett tal coverage förstår")
        self.assertGreater(float(värde), 0, "ett golv på noll kan inte bli rött")

    def test_ci_kor_coverage_mot_golvet(self):
        ci = CI.read_text(encoding="utf-8")
        self.assertIn("coverage run --rcfile=.coveragerc backend/tests/run.py", ci)
        self.assertIn("--fail-under=", ci, "utan --fail-under är täckningen en siffra "
                                           "ingen behöver bry sig om")
        self.assertIn("backend/tests/tackningsgolv.txt", ci,
                      "golvet ska stå i en fil man kan höja i en egen commit, "
                      "inte inbakat i YAML")

    def test_tackningen_star_i_releasekedjan(self):
        # `success()` på ett jobb ser BARA jobben i dess egen needs. Utan den
        # här raden deployas backenden på en röd täckning medan deploy.yml -
        # som kräver att HELA körningen blev grön - vägrar publicera
        # frontenden. Ny backend, gammal frontend: exakt det omaka par K3
        # byggdes för att förhindra.
        #
        # Medlemskap, inte en ordagrann rad: K1 lade till `lint` i samma lista
        # av samma skäl, och nästa paket kommer att lägga till sitt. Ett test
        # som kräver exakt strängen hade gjort varje sådant tillägg till en
        # falsk röd - och den sortens test lär folk att ändra testet i stället
        # för att läsa det.
        ci = CI.read_text(encoding="utf-8")
        efter = ci.split("  deploy-staging:", 1)[1].split("\n  smoke-staging:", 1)[0]
        rad = next(r for r in efter.splitlines() if r.strip().startswith("needs:"))
        behov = {namn.strip() for namn in rad.split("[", 1)[1].rstrip("]").split(",")}
        self.assertIn("coverage", behov,
                      "en röd täckning skulle deploya backenden men inte frontenden")
        for jobb in ("backend", "frontend", "security", "e2e"):
            self.assertIn(jobb, behov, f"{jobb} är borta ur releasekedjan")

    def test_tackningen_mats_alltid_pa_samma_sak(self):
        # Samma commit mäter 74,7 % med browser-E2E:n och 73,8 % utan. Ett golv
        # går inte att sätta mot ett tal som beror på om en Chromium råkade gå
        # att starta - resorna stängs därför av med flit i täckningsjobbet.
        ci = CI.read_text(encoding="utf-8")
        efter = ci.split("  coverage:", 1)[1].split("\n  frontend:", 1)[0]
        self.assertIn('MATJAKT_E2E: "0"', efter,
                      "täckningstalet varierar med om en webbläsare fanns")

    def test_matningens_egen_datafil_kan_inte_bli_spard(self):
        # .coverage skrivs i repo-roten av var och en som mäter lokalt -
        # samma sorts konfliktgenerator som audit_flags.tsv var, och en som
        # kom till med det här paketet. .gitignore räcker inte: den avspårar
        # inget som redan är spårat, vilket är precis hur marketing/build/
        # kunde ligga kvar med 73 MB video trots en rad i filen.
        ci = CI.read_text(encoding="utf-8")
        # Två rader börjar med samma tilldelning - den ena är databasgrinden.
        # Artefaktgrinden är den som nämner marketing/build.
        rad = next(r for r in ci.splitlines()
                   if "tracked=$(git ls-files" in r and "marketing/build/*" in r)
        for mönster in ("'.coverage'", "'.coverage.*'", "'htmlcov/*'"):
            self.assertIn(mönster, rad, f"artefaktgrinden släpper igenom {mönster}")

    def test_matningen_mater_kallkoden_och_inte_sviten(self):
        # En svit som mäter sig själv ger ett tal som stiger av att man skriver
        # fler tester. Det är precis fel signal.
        rc = COVERAGERC.read_text(encoding="utf-8")
        self.assertIn("backend/tests/*", rc)
        self.assertIn("backend/venv/*", rc)


if __name__ == "__main__":
    unittest.main()
