# -*- coding: utf-8 -*-
"""K3: frontenden får inte gå live före backenden.

Fyndet: `ci.yml` fyrade Render-hooken när CI blev grön, och `deploy.yml`
startade Pages-jobbet av SAMMA händelse. Pages är live på ~3 minuter, Render
på ~5. Alltså fanns det i varje release ett fönster på ett par minuter där den
nya frontenden talade med den gamla backenden - och klienten har inget
API-versionskontrakt som märker det. Ett fält som tillkom i releasen saknades
helt enkelt i svaret.

Acceptansen är därför två påståenden, och båda prövas här:

  1. GRINDEN GÖR SITT JOBB. `wait_for_deploy.py` säger ja bara när drift
     faktiskt rapporterar den efterfrågade committen, och nej - efter att ha
     väntat ut hela fönstret - i varje annat läge. Det prövas mot en RIKTIG
     HTTP-server som svarar precis som Render gör under en deploy: 502 medan
     instansen startar, sedan gammal commit, sedan ny.

  2. GRINDEN SITTER I KEDJAN. Ett steg som inte kan faila är inget steg, och
     ett steg som ingen anropar är inte heller något steg. Testet kräver att
     `health-gate` finns i ci.yml, att den behöver `deploy-backend`, och att
     deploy.yml fortfarande bara publicerar på en GRÖN CI-körning - för det
     är det villkoret som gör att Pages hamnar efter hälsokontrollen.
"""

import http.server
import importlib.util
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"
SKRIPT = ROOT / "backend" / "scripts" / "wait_for_deploy.py"


def _ladda():
    spec = importlib.util.spec_from_file_location("wait_for_deploy", SKRIPT)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


grind = _ladda()


class FalskKlocka:
    """Driver en åttaminutersvakt på noll riktiga sekunder.

    Utan den hade testet antingen tagit åtta minuter eller bara prövat de två
    första försöken - och det är just beteendet VID fönstrets slut som är
    hela poängen med grinden.
    """

    def __init__(self):
        self.nu = 0.0
        self.sovit = []

    def sova(self, sekunder):
        self.sovit.append(sekunder)
        self.nu += sekunder

    def klocka(self):
        return self.nu


class _Handler(http.server.BaseHTTPRequestHandler):
    svar = []  # klass-attribut sätts per test: lista av (status, kropp)
    räknare = 0

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler kräver namnet
        i = min(_Handler.räknare, len(_Handler.svar) - 1)
        _Handler.räknare += 1
        status, kropp = _Handler.svar[i]
        data = kropp.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass


class Hälsoserver:
    """En riktig HTTP-server som svarar som Render gör under en deploy."""

    def __init__(self, svar):
        _Handler.svar = list(svar)
        _Handler.räknare = 0
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/api/health"

    def __enter__(self):
        self.tråd = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.tråd.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()


NY = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
GAMMAL = "0000111122223333444455556666777788889999"


def _health(commit):
    värde = "null" if commit is None else f'"{commit[:12]}"'
    return f'{{"ok": true, "commit": {värde}}}'


def kör_grinden(url, commit, klocka=None):
    """Samma anrop som CI gör (8 minuter, 15 s mellan försök), fast på nolltid."""
    klocka = klocka or FalskKlocka()
    return grind.vanta(url, commit, timeout=480, interval=15, sova=klocka.sova,
                       klocka=klocka.klocka, skriv=lambda *_: None, http_timeout=5)


class GrindenSlapperIgenomRattCommit(unittest.TestCase):
    def test_drift_som_redan_kor_committen_slapps_igenom_direkt(self):
        with Hälsoserver([(200, _health(NY))]) as s:
            klocka = FalskKlocka()
            kod = kör_grinden(s.url, NY, klocka)
        self.assertEqual(kod, 0)
        self.assertEqual(klocka.sovit, [], "ingen väntan behövdes - drift svarade rätt direkt")

    def test_502_under_omstart_ar_inte_ett_fel_utan_inte_annu(self):
        # Exakt Renders beteende: proxyn svarar 502 medan den nya instansen
        # startar, sedan svarar den gamla instansen, sedan den nya.
        svar = [(502, "<html>Bad Gateway</html>"),
                (502, "<html>Bad Gateway</html>"),
                (200, _health(GAMMAL)),
                (200, _health(NY))]
        with Hälsoserver(svar) as s:
            klocka = FalskKlocka()
            kod = kör_grinden(s.url, NY, klocka)
        self.assertEqual(kod, 0, "en 502 under omstart får inte fälla deployen")
        self.assertEqual(len(klocka.sovit), 3, "tre väntor mellan fyra försök")


class GrindenStangerVidFelCommit(unittest.TestCase):
    """Ett CI-steg som inte kan faila är inget CI-steg."""

    def test_gammal_commit_hela_fonstret_ger_rott(self):
        with Hälsoserver([(200, _health(GAMMAL))]) as s:
            klocka = FalskKlocka()
            kod = kör_grinden(s.url, NY, klocka)
        self.assertEqual(kod, 1, "drift körde aldrig den nya committen - Pages ska inte deployas")
        self.assertGreaterEqual(klocka.nu, 480 - 15, "grinden gav upp före fönstrets slut")

    def test_commit_null_raknas_aldrig_som_traff(self):
        # RENDER_GIT_COMMIT inte satt. Frestelsen är att låta "vet inte"
        # passera; då passerar grinden ALLTID och är värdelös.
        with Hälsoserver([(200, _health(None))]) as s:
            kod = kör_grinden(s.url, NY, FalskKlocka())
        self.assertEqual(kod, 1)

    def test_backend_helt_nere_ger_rott(self):
        # Serverport utan lyssnare: ingen deploy kom upp alls.
        with Hälsoserver([(200, _health(NY))]) as s:
            död_url = s.url
        kod = kör_grinden(död_url, NY, FalskKlocka())
        self.assertEqual(kod, 1)

    def test_tom_commit_avvisas_utan_att_polla(self):
        self.assertEqual(grind.main(["--url", "http://127.0.0.1:1/api/health", "--commit", "  "]), 1)


class MatchningsregelnHallerIsarPrefixen(unittest.TestCase):
    def test_tolv_tecken_mot_fyrtio_matchar(self):
        self.assertTrue(grind.matchar(NY[:12], NY))

    def test_narliggande_men_annan_commit_matchar_inte(self):
        self.assertFalse(grind.matchar(GAMMAL[:12], NY))

    def test_for_kort_prefix_ar_inte_ett_bevis(self):
        # Sex tecken kolliderar i tillräckligt stora repon; grinden ska inte
        # nöja sig med det.
        self.assertFalse(grind.matchar(NY[:6], NY))

    def test_tomt_svar_matchar_aldrig(self):
        self.assertFalse(grind.matchar("", NY))
        self.assertFalse(grind.matchar(None, NY))


class KedjanIWorkflowfilerna(unittest.TestCase):
    """Grinden finns bara om den sitter i kedjan - och kedjan står i YAML."""

    def setUp(self):
        self.ci = CI.read_text(encoding="utf-8")
        self.deploy = DEPLOY.read_text(encoding="utf-8")

    def _krav(self, text, bit, varför):
        # assertIn dumpar hela YAML-filen i felutskriften - 200 rader i
        # CI-loggen för ett saknat ord. Här står bara vad som fattas.
        self.assertTrue(bit in text, f"saknas i workflowen: {bit!r} - {varför}")

    def test_health_gate_finns_och_behover_deploy_backend(self):
        self._krav(self.ci, "health-gate:", "hälsogrinden är borta ur ci.yml")
        efter = self.ci.split("health-gate:", 1)[1][:400]
        self._krav(efter, "needs: [deploy-backend]",
                   "health-gate måste ligga EFTER deploy-backend, annars mäter den ingenting")

    def test_health_gate_hoppas_inte_over_nar_hooken_saknas(self):
        """Den här luckan var öppen i flera timmar utan att något såg rött.

        health-gate var villkorad på `needs.deploy-backend.outputs.triggad ==
        'true'`, alltså "bara om VI startade deployen". RENDER_DEPLOY_HOOK
        lades aldrig in i repots secrets, så flaggan var alltid false och
        grinden hoppades över vid VARJE merge - tyst, som `skipped`, vilket
        ser ut precis som ett jobb som inte behövdes.

        Frontenden deployade därmed utan att någon kontrollerat att backenden
        var uppe med samma commit. Racet K3 stängde var öppet igen, och de
        fyra testerna ovan var alla gröna hela tiden: en överhoppad grind
        finns i filen, behöver deploy-backend och anropar rätt skript.

        Render deployar av sig självt (Auto-Deploy: After CI Checks Pass), så
        committen når produktionen ändå - vi vet bara inte när. Grindens fråga
        är "kör driften den här committen", inte "startade vi en deploy".
        """
        efter = self.ci.split("health-gate:", 1)[1][:2000]
        villkor = [rad.strip() for rad in efter.splitlines()
                   if rad.strip().startswith("if:")]
        self.assertTrue(villkor, "health-gate saknar villkor helt")
        self.assertNotIn(
            "triggad", villkor[0],
            "health-gate är villkorad på att VI startade deployen. Saknas hooken "
            "hoppas grinden över vid varje merge och frontenden går live "
            "oprövad mot backenden.")
        self.assertIn(
            "github.ref == 'refs/heads/main'", villkor[0],
            "health-gate måste köra på varje push till main - det är där "
            "frontenden riskerar att gå före backenden")

    def test_health_gate_anropar_skriptet_som_testas_har(self):
        self._krav(self.ci, "backend/scripts/wait_for_deploy.py",
                   "hälsogrinden måste köra just det skript som testerna ovan prövar")

    def test_deploy_backend_villkoret_ar_orort(self):
        # De tio andra paketen mergar genom samma CI. Fyrar deploy-backend på
        # fel event deployas en PR-gren till produktion.
        self._krav(self.ci, "if: success() && github.event_name == 'push' && github.ref == 'refs/heads/main'",
                   "deploy-backend får bara fyra på en push till main")

    def test_pages_publicerar_bara_pa_gron_ci_korning(self):
        # Det HÄR villkoret är det som gör att Pages hamnar efter
        # hälsokontrollen: en CI-körning är inte klar förrän health-gate är
        # klar, och inte 'success' om den failade.
        self._krav(self.deploy, "github.event.workflow_run.conclusion == 'success'",
                   "utan det publicerar Pages även när hälsogrinden failade")
        self._krav(self.deploy, "workflows: [CI]", "Pages måste hänga på CI-körningen")
        self._krav(self.deploy, "types: [completed]",
                   "completed är det som gör att Pages väntar på HELA CI, health-gate inräknad")


if __name__ == "__main__":
    unittest.main()
