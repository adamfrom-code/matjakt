# -*- coding: utf-8 -*-
"""K2: beroendena var inte låsta, och en av dem var en bomb med tändare.

`backend/requirements.txt` innehöll exakt en rad: `playwright>=1.45`.
Basimagen i `backend/Dockerfile` är pinnad till
`mcr.microsoft.com/playwright/python:v1.62.0-jammy`, och den imagen bär EN
Chromium - den som hör till just 1.62.0. Playwright-biblioteket letar efter
webbläsaren på en versionsstämplad sökväg.

Det gör `>=` till en fälla av ovanligt otrevligt slag: felet uppstår utan att
någon ändrar en rad kod. En Render-omdeploy av en OFÖRÄNDRAD commit, eller en
rensad byggcache, räcker för att `pip install` ska dra in en nyare Playwright
i en image vars webbläsare den inte känner igen. Servern startar med
"Executable doesn't exist", repot ser identiskt ut, och git blame pekar på
ingenting.

Acceptansen är därför tre påståenden, och alla tre prövas här:

  1. TALEN FÖLJS ÅT. Playwright-versionen i requirements.in är samma version
     som taggen på basimagen. Jämförelsen prövas både mot de riktiga filerna
     och mot påhittade filer där de HAR glidit isär - annars bevisar testet
     bara att de råkar stämma i dag, inte att det upptäcks när de slutar.

  2. LÅSET HÅLLER HELA TRÄDET. Varje paket i låsfilen har exakt version och
     minst en sha256. Ett `>=` eller en rad utan hash någonstans i trädet gör
     låset till dekoration.

  3. GRINDARNA FINNS I CI. pip-audit, npm audit och hjulkontrollen mot
     imagens python står i security-jobbet, och Dependabot är påslagen för
     alla tre ekosystemen.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IN = ROOT / "backend" / "requirements.in"
LAS = ROOT / "backend" / "requirements.txt"
DOCKERFILE = ROOT / "backend" / "Dockerfile"
CI = ROOT / ".github" / "workflows" / "ci.yml"
DEPENDABOT = ROOT / ".github" / "dependabot.yml"


def playwright_ur_dockerfile(text: str):
    """Versionen i `FROM .../playwright/python:v1.62.0-jammy`."""
    träff = re.search(r"playwright/python:v(\d+\.\d+\.\d+)", text)
    return träff.group(1) if träff else None


def playwright_ur_krav(text: str):
    """Versionen i `playwright==1.62.0`, om raden är exakt pinnad."""
    träff = re.search(r"^playwright==(\d+\.\d+\.\d+)\s*$", text, re.MULTILINE)
    return träff.group(1) if träff else None


def las_paket(text: str):
    """{namn: (version, antal hashar)} ur en pip-compile-låsfil."""
    paket = {}
    aktuell = None
    for rad in text.splitlines():
        krav = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s\\]+)", rad)
        if krav:
            aktuell = krav.group(1).lower()
            paket[aktuell] = [krav.group(2), rad.count("--hash=sha256:")]
        elif aktuell and "--hash=sha256:" in rad:
            paket[aktuell][1] += rad.count("--hash=sha256:")
        elif rad and not rad.startswith((" ", "\t", "#")):
            aktuell = None
    return {namn: tuple(värde) for namn, värde in paket.items()}


class TalenFoljsAt(unittest.TestCase):
    """Bomben: en Playwright som inte hör ihop med imagens Chromium."""

    def test_requirements_in_pinnar_playwright_exakt(self):
        version = playwright_ur_krav(IN.read_text(encoding="utf-8"))
        self.assertIsNotNone(version, "playwright måste vara pinnad med == i "
                                      "backend/requirements.in, inte >= ")

    def test_samma_version_som_basimagens_tagg(self):
        krav = playwright_ur_krav(IN.read_text(encoding="utf-8"))
        image = playwright_ur_dockerfile(DOCKERFILE.read_text(encoding="utf-8"))
        self.assertIsNotNone(image, "hittade ingen playwright-tagg i backend/Dockerfile")
        self.assertEqual(krav, image,
                         f"playwright=={krav} mot image v{image}: biblioteket letar efter en "
                         f"Chromium som inte finns i imagen. Båda ändras i samma commit.")

    def test_lasfilen_bar_samma_version(self):
        self.assertEqual(playwright_ur_krav(IN.read_text(encoding="utf-8")),
                         las_paket(LAS.read_text(encoding="utf-8")).get("playwright", (None,))[0],
                         "låsfilen är inte regenererad efter att requirements.in ändrades")

    def test_jamforelsen_upptacker_en_glidning(self):
        # Utan det här beviset säger testerna ovan bara att talen råkar stämma
        # i dag. Här HAR de glidit isär, och jämförelsen ska se det.
        image = playwright_ur_dockerfile("FROM mcr.microsoft.com/playwright/python:v1.62.0-jammy\n")
        krav = playwright_ur_krav("playwright==1.70.0\n")
        self.assertEqual(image, "1.62.0")
        self.assertEqual(krav, "1.70.0")
        self.assertNotEqual(image, krav)

    def test_ett_losare_krav_raknas_inte_som_pinnat(self):
        # Exakt raden som fanns före det här paketet.
        self.assertIsNone(playwright_ur_krav("playwright>=1.45\n"))
        self.assertIsNone(playwright_ur_krav("playwright\n"))
        self.assertIsNone(playwright_ur_krav("playwright~=1.62\n"))


class LasetHallerHelaTradet(unittest.TestCase):
    def setUp(self):
        self.paket = las_paket(LAS.read_text(encoding="utf-8"))

    def test_lasfilen_har_hela_tradet_inte_bara_det_direkta(self):
        # playwright drar in greenlet och pyee, och pyee drar typing-extensions.
        # Låser man bara playwright kan greenlet 4.0 komma in i en ombyggnad.
        for beroende in ("playwright", "greenlet", "pyee"):
            self.assertIn(beroende, self.paket,
                          f"{beroende} saknas i låsfilen - trädet är inte helt")

    def test_varje_paket_har_exakt_version_och_hash(self):
        self.assertTrue(self.paket, "låsfilen är tom")
        for namn, (version, hashar) in self.paket.items():
            self.assertRegex(version, r"^\d", f"{namn} har ingen exakt version")
            self.assertGreater(hashar, 0, f"{namn} saknar sha256 - utan hash kan ett paket "
                                          f"bytas ut under samma versionsnummer")

    def test_inget_lost_krav_smiter_in_i_lasfilen(self):
        text = LAS.read_text(encoding="utf-8")
        lösa = [rad for rad in text.splitlines()
                if re.match(r"^[A-Za-z0-9_.\-]+\s*(>=|<=|>|<|~=)", rad)]
        self.assertEqual(lösa, [], f"lösa krav i låsfilen: {lösa}")

    def test_lasfilen_pekar_inte_ut_ett_eget_paketindex(self):
        # En --index-url i en låsfil flyttar var paketen hämtas ifrån, och det
        # hör inte hemma i ett publikt repo.
        self.assertNotIn("--index-url", LAS.read_text(encoding="utf-8"))

    def test_lasaren_ser_ett_olast_trad_som_olast(self):
        # Beviset att kontrollen ovan kan bli röd.
        olåst = las_paket("playwright==1.62.0\ngreenlet==3.5.5\n")
        self.assertEqual(olåst["playwright"][1], 0)
        self.assertEqual(olåst["greenlet"][1], 0)


class GrindarnaFinnsICI(unittest.TestCase):
    """Ett steg som bara finns i en kommentar körs aldrig."""

    def setUp(self):
        self.ci = CI.read_text(encoding="utf-8")

    def _krav(self, bit, varför):
        self.assertTrue(bit in self.ci, f"saknas i ci.yml: {bit!r} - {varför}")

    def test_hjulkontrollen_mot_imagens_python_finns(self):
        # Den viktigaste av de nya: CI kör 3.12, imagen kör 3.10. En låsfil
        # som genererats på 3.12 kan peka ut hjul som inte finns för 3.10, och
        # det upptäcks annars först när Render bygger om.
        self._krav("--python-version 3.10",
                   "utan den kontrolleras låsfilen aldrig mot imagens python")
        self._krav("pip download",
                   "hjulkontrollen hämtar hjulen för imagens plattform utan att installera dem")

    # K2b flyttade SJÄLVA KOMMANDONA till backend/scripts/audit_deps.py, som
    # gör om frågan när den faller på nätet i stället för att fälla en av fyra
    # obligatoriska statuscheckar på en blipp mot PyPI. Flaggorna hör ihop med
    # tolken som läser utdatan, så de står numera på ett ställe. Att de är
    # RÄTT hålls av test_sarbarhetsgrind.SkriptetKorRattKommandon; att de körs
    # över huvud taget hålls här, där K2:s övriga grindar står.
    def test_pip_audit_kors_mot_lasfilen(self):
        self._krav("backend/scripts/audit_deps.py pip",
                   "sårbarhetsskanningen ska läsa exakt det träd som installeras")

    def test_npm_audit_blockerar_fran_hog_och_uppat(self):
        self._krav("backend/scripts/audit_deps.py npm",
                   "en grind som failar på varje moderate blir avstängd inom en vecka")

    def test_e2e_installerar_inte_playwright_forbi_lasfilen(self):
        # `pip install -r requirements.txt playwright` upphävde låsningen OCH
        # hade sprängt --require-hashes-läget.
        self.assertNotIn("pip install -r backend/requirements.txt playwright", self.ci,
                         "e2e-jobbet installerar playwright förbi låsfilen")


class DependabotAr(unittest.TestCase):
    def setUp(self):
        self.text = DEPENDABOT.read_text(encoding="utf-8") if DEPENDABOT.exists() else ""

    def test_filen_finns(self):
        self.assertTrue(DEPENDABOT.exists(), ".github/dependabot.yml saknas")

    def test_alla_tre_ekosystemen(self):
        for ekosystem in ("pip", "npm", "github-actions"):
            self.assertIn(f"package-ecosystem: {ekosystem}", self.text,
                          f"{ekosystem} bevakas inte")

    def test_veckovis(self):
        self.assertIn("interval: weekly", self.text)

    def test_playwright_hojs_inte_av_en_bot(self):
        # Den raden hör ihop med Dockerfile-taggen. En bot som höjer den ena
        # men inte den andra bygger just det fel paketet ska stänga.
        self.assertIn("dependency-name: playwright", self.text,
                      "Dependabot måste hålla fingrarna borta från playwright-raden")


if __name__ == "__main__":
    unittest.main()
