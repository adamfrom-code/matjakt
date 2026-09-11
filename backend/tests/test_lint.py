# -*- coding: utf-8 -*-
"""K1: att linten finns, kör, och failar på rätt saker.

`ci.yml` körde `node --check` och `compileall`. Det är syntax: att filen går
att PARSA. Ingen av dem säger något om att koden gör något annat än det som
står skrivet - och det var precis där felen låg. Den första ruff-körningen i
det här repots historia hittade bland annat sex literala backsteg-tecken i
hemlighetsskannern, som tyst avväpnade fem av dess mönster i ett publikt repo
som redan läckt en token en gång.

Testerna nedan prövar inte koden. De prövar att GRINDEN finns kvar: att
regelverken existerar, att CI kör dem, att de rules som fångar riktiga fel
fortfarande är valda, och att baslinjen inte har ruttnat.

Varför det behövs: en lint är den lättaste grinden i världen att avväpna av
misstag. Ett `select` som krymper, en `--exit-zero` som smyger in, en
`per-file-ignores`-rad som blir kvar sedan filen städats - inget av det syns
i en diff som något annat än en konfigrad.
"""

import re
import tomllib
import unittest
from pathlib import Path

def jobb(ci: str, namn: str) -> str:
    """Ett jobbs egen del av ci.yml, oavsett vad som ligger efter det.

    Att klippa fram till NÄSTA JOBB i stället för till ett jobb vid namn är
    inte pedanteri: ett test som kräver att `lint:` står precis före
    `backend:` blir rött den dag någon lägger ett jobb emellan, på en ändring
    som inte har något med linten att göra - och den sortens test lär folk att
    ändra testet i stället för att läsa det.
    """
    import re as _re
    efter = ci.split(f"\n  {namn}:\n", 1)[1]
    nästa = _re.search(r"^  [a-z][a-z0-9-]*:\s*$", efter, _re.MULTILINE)
    return efter[:nästa.start()] if nästa else efter


ROT = Path(__file__).resolve().parents[2]
PYPROJECT = ROT / "pyproject.toml"
ESLINT = ROT / "eslint.config.js"
CI = ROT / ".github" / "workflows" / "ci.yml"


class RegelverkenFinns(unittest.TestCase):
    def test_pyproject_och_eslintkonfig_finns(self):
        self.assertTrue(PYPROJECT.exists(), "pyproject.toml saknas")
        self.assertTrue(ESLINT.exists(), "eslint.config.js saknas")


class RuffValjerDetSomBetyderNagot(unittest.TestCase):
    def setUp(self):
        self.konf = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        self.lint = self.konf["tool"]["ruff"]["lint"]

    def test_reglerna_som_fangar_riktiga_fel_ar_valda(self):
        vald = set(self.lint["select"])
        for regel, varför in (
            ("F", "odefinierade namn, dubblerade nycklar i dict-literal, död kod"),
            ("E9", "syntax- och IO-fel - koden går inte att köra"),
            ("B", "muterbara defaultargument, loopvariabler bundna i closures"),
            ("PLE", "pylints ENTYDIGA fel - hit hör PLE2510, som hittade "
                    "backstegen i hemlighetsskannern"),
        ):
            self.assertIn(regel, vald, f"ruff slutade välja {regel}: {varför}")

    def test_formatering_ar_inte_en_grind(self):
        # En lint som failar på radlängd och importordning stängs av inom en
        # vecka, och då fångas inte heller de fel som betyder något.
        ignorerade = set(self.lint["ignore"])
        for regel in ("E501", "I001", "UP"):
            self.assertIn(regel, ignorerade,
                          f"{regel} är en formateringsregel och får inte fälla bygget")

    def test_versionen_ar_pinnad_i_ci(self):
        # En olåst linter ändrar grindens innebörd av sig själv: nästa
        # ruff-release kan lägga till en regel i en vald familj och göra varje
        # öppen PR röd, utan att någon ändrat en rad kod.
        ci = CI.read_text(encoding="utf-8")
        self.assertRegex(ci, r'ruff==\d+\.\d+\.\d+',
                         "ruff installeras utan pinnad version i ci.yml")

    def test_baslinjen_pekar_bara_pa_filer_som_finns(self):
        # En per-file-ignore som blir kvar sedan filen städats eller döpts om
        # är ett hål ingen ser: regeln är avstängd för en fil som inte finns,
        # och den dagen någon skapar en fil med samma namn är den avstängd
        # där i stället.
        for fil in self.lint.get("per-file-ignores", {}):
            self.assertTrue((ROT / fil).exists(),
                            f"baslinjen undantar {fil}, som inte finns längre - "
                            f"ta bort raden")

    def test_baslinjen_ar_forklarad_fil_for_fil(self):
        # Listan ska krympa, och den krymper bara om nästa person kan se vad
        # varje rad handlar om.
        text = PYPROJECT.read_text(encoding="utf-8")
        efter = text.split("[tool.ruff.lint.per-file-ignores]", 1)[1]
        rader = efter.splitlines()
        for i, rad in enumerate(rader):
            if rad.strip().startswith('"') and "=" in rad:
                före = [r for r in rader[max(0, i - 8):i] if r.strip().startswith("#")]
                self.assertTrue(före, f"baslinjeraden {rad.strip()[:60]!r} saknar förklaring")


class EslintFangarDetSomGarSonderIWebblasaren(unittest.TestCase):
    def setUp(self):
        self.text = ESLINT.read_text(encoding="utf-8")

    def test_no_undef_ar_fel(self):
        # Den viktigaste regeln i hela filen. Ett felstavat namn, en borttagen
        # import, en funktion som bytt modul - allt blir ett ReferenceError
        # först när användaren trycker på knappen. tests/app-imports.test.js
        # skrevs en gång för att fånga just den klassen av fel; nu finns
        # grinden före testet.
        self.assertIn('"no-undef": "error"', self.text)

    def test_dubblerade_nycklar_ar_fel(self):
        # Samma fel som ruffs F601 i backend, där det tappade tolv
        # receptbilder och en buljongpost utan ett ljud.
        self.assertIn('"no-dupe-keys": "error"', self.text)

    def test_tilldelning_i_villkor_slapper_igenom_den_parentessatta_formen(self):
        # "always" fäller `for (let m; (m = re.exec(s)); )`, som är den
        # etablerade formen för att gå igenom varje träff - och de extra
        # parenteserna ÄR författarens sätt att säga "jag menade tilldelning".
        # En regel som är röd på idiomet lär folk att ignorera rött.
        self.assertIn('"no-cond-assign": ["error", "except-parens"]', self.text)

    def test_ingen_formateringsregel_har_smugit_in(self):
        # Semikolon, citattecken, indrag och radlängd ändrar inte vad
        # programmet gör. De hör inte i en grind.
        for smak in ("semi", "quotes", "indent", "max-len", "comma-dangle",
                     "object-curly-spacing", "space-before-function-paren"):
            self.assertNotIn(f'"{smak}":', self.text,
                             f"{smak} är formatering, inte ett fel")


class CiKorLinten(unittest.TestCase):
    def setUp(self):
        self.ci = CI.read_text(encoding="utf-8")

    def test_lintjobbet_finns_och_kor_bada(self):
        self.assertIn("\n  lint:", self.ci, "inget lint-jobb i ci.yml")
        efter = jobb(self.ci, "lint")
        self.assertIn("ruff check", efter, "lint-jobbet kör inte ruff")
        self.assertIn("eslint", efter, "lint-jobbet kör inte eslint")

    def test_linten_kan_faila(self):
        # Ett CI-steg som inte kan faila är inget CI-steg. `--exit-zero`,
        # `|| true` och `continue-on-error` på själva grindsteget gör den till
        # en logg ingen läser.
        efter = jobb(self.ci, "lint")
        grind = efter.split("Död kod", 1)[0]     # rapportsteget får ha || true
        for avväpning in ("--exit-zero", "continue-on-error: true", "|| true"):
            self.assertNotIn(avväpning, grind,
                             f"{avväpning} gör lint-grinden till en logg ingen läser")

    def test_linten_star_i_releasekedjan(self):
        # Samma skäl som täckningen i K6: `success()` på ett jobb ser BARA
        # jobben i dess egen needs. Utan raden deployas backenden på en röd
        # lint medan deploy.yml - som kräver att HELA körningen blev grön -
        # vägrar publicera frontenden. Ny backend, gammal frontend.
        efter = jobb(self.ci, "deploy-staging")
        rad = next(r for r in efter.splitlines() if r.strip().startswith("needs:"))
        self.assertIn("lint", rad, "en röd lint skulle deploya backenden men inte frontenden")

    def test_eslint_har_ett_tak_for_varningarna(self):
        # no-unused-vars är en VARNING, inte ett fel: elva av dagens tolv
        # ligger i frontend/app/app.js som F-vågen refaktorerar just nu, och en
        # grind som är röd på filer man inte får röra blir avstängd. Taket är
        # det som gör att kategorin ändå inte kan tredubblas i tysthet.
        efter = jobb(self.ci, "lint")
        self.assertRegex(efter, r"--max-warnings[= ]\d+",
                         "utan ett tak är varningarna en logg ingen läser")


class SyntaxkontrollenFinnsKvar(unittest.TestCase):
    """Linten ERSÄTTER inte `node --check` och `compileall`.

    Ruff och eslint läser filer var för sig. `python -m compileall` prövar att
    varje fil i trädet går att kompilera - inklusive de ruff exkluderar - och
    `node --check` prövar bundlets två största filer i sin helhet. De är
    billiga och svarar på en annan fråga.
    """

    def test_compileall_och_node_check_ar_kvar(self):
        ci = CI.read_text(encoding="utf-8")
        self.assertIn("compileall", ci)
        self.assertIn("node --check frontend/app/app.js", ci)
        self.assertIn("node --check frontend/app/sw.js", ci)


if __name__ == "__main__":
    unittest.main()
