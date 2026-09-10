# -*- coding: utf-8 -*-
"""CODEOWNERS är zonkartan, och kartan måste stämma med terrängen.

A2:s acceptanskriterium är "filen finns och matchar zonlistan". Det går att
pröva, och det är tre olika saker som var för sig kan vara fel:

  1. Zonerna. Uppsättningen zoner i CODEOWNERS ska vara EXAKT den i §2 i
     docs/UPPDRAG-MATJAKT.md. Läggs en zon till i dokumentet utan att den
     får en rad här, faller det här testet - annars hade kartan tystnat om
     en hel zon.
  2. Reglerna. Varje mönster ska träffa minst en spårad fil. En rad som inte
     träffar något äger inget; den ser ut som skydd och är det inte.
  3. Skyddet. `.github/**`, `render.yaml` och `backend/Dockerfile` ska ha EN
     enda ägare och får inte krävas av någon zonregel. GitHub låter SISTA
     matchande raden vinna, så testet löser upp ägarskapet med samma regel
     - flyttas skyddsblocket uppåt i filen tappar det sin verkan tyst, och
     ingen syntaxkontroll i världen hade sagt ifrån.

Filen måste dessutom vara spårad: GitHub läser aldrig ett arbetsträd.
"""

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODEOWNERS = ROOT / ".github" / "CODEOWNERS"
UPPDRAG = ROOT / "docs" / "UPPDRAG-MATJAKT.md"

# Zonavsnitten måste skrivas i exakt den här formen för att hittas.
# Att bara leta "Z-NÅGOT" i en kommentar dög inte: brödtexten hänvisar till
# andra zoner ("ligger efter Z-GROCERY med avsikt") och testet hade då bytt
# zon mitt i ett avsnitt.
ZONRUBRIK = re.compile(r"^#\s*─+\s*(Z-[A-Z][A-Z-]*)\s")

# Vägarna till produktion. En ändring här ändrar reglerna paketet självt
# bedöms efter: CI-grinden, deploy-hooken, bilden servern körs i - och
# CODEOWNERS självt, som avgör vem som får släppa igenom de andra tre.
SKYDDADE_FILER = (".github/workflows/ci.yml", ".github/workflows/deploy.yml",
                  ".github/CODEOWNERS", "render.yaml", "backend/Dockerfile")


def _monster_till_regex(monster: str) -> re.Pattern:
    """Samma semantik som gitignore/CODEOWNERS, nog för mönstren i filen."""
    ankrad = monster.startswith("/")
    kropp = monster.lstrip("/")
    if kropp.endswith("/"):          # en katalog äger allt under sig
        kropp += "**"
    ut, i = [], 0
    while i < len(kropp):
        if kropp.startswith("**/", i):
            ut.append("(?:.*/)?"); i += 3
        elif kropp.startswith("**", i):
            ut.append(".*"); i += 2
        elif kropp[i] == "*":
            ut.append("[^/]*"); i += 1
        elif kropp[i] == "?":
            ut.append("[^/]"); i += 1
        else:
            ut.append(re.escape(kropp[i])); i += 1
    prefix = "" if ankrad else "(?:.*/)?"
    return re.compile("^" + prefix + "".join(ut) + "$")


def _las_regler():
    """[(radnummer, zon eller None, mönster, [ägare]), ...] i filordning."""
    regler, zon = [], None
    for nummer, rad in enumerate(CODEOWNERS.read_text(encoding="utf-8").splitlines(), 1):
        rubrik = ZONRUBRIK.match(rad)
        if rubrik:
            zon = rubrik.group(1)
            continue
        if not rad.strip() or rad.lstrip().startswith("#"):
            continue
        delar = rad.split()
        regler.append((nummer, zon, delar[0], delar[1:]))
    return regler


def _zoner_ur_uppdraget() -> set[str]:
    text = UPPDRAG.read_text(encoding="utf-8").splitlines()
    for i, rad in enumerate(text):
        if rad.startswith("**Zoner**"):
            for foljande in text[i:i + 4]:
                funna = re.findall(r"Z-[A-Z][A-Z-]*", foljande)
                if len(funna) > 3:
                    return set(funna)
    raise AssertionError("hittade ingen zonlista i docs/UPPDRAG-MATJAKT.md")


def _sparade_filer() -> list[str]:
    ut = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                        text=True, encoding="utf-8")
    return [rad for rad in ut.stdout.splitlines() if rad]


def _git_finns() -> bool:
    try:
        subprocess.run(["git", "rev-parse", "--git-dir"], cwd=ROOT,
                       capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


class Zonkartan(unittest.TestCase):
    def setUp(self):
        if not CODEOWNERS.exists():
            self.fail(".github/CODEOWNERS saknas - zonkartan finns bara i prosa")
        self.regler = _las_regler()

    # ── 1. zonerna ──────────────────────────────────────────────────────
    def test_zonerna_i_filen_ar_exakt_zonerna_i_uppdraget(self):
        i_filen = {zon for _, zon, _, _ in self.regler if zon}
        self.assertEqual(i_filen, _zoner_ur_uppdraget(),
                         "CODEOWNERS och §2 i uppdraget är inte överens om zonerna")

    def test_varje_zon_har_minst_en_rad(self):
        for zon in _zoner_ur_uppdraget():
            rader = [m for _, z, m, _ in self.regler if z == zon]
            self.assertTrue(rader, f"zonen {zon} har ingen rad i CODEOWNERS")

    # ── 2. reglerna ─────────────────────────────────────────────────────
    def test_varje_rad_har_en_agare(self):
        for nummer, _, monster, agare in self.regler:
            self.assertTrue(agare, f"CODEOWNERS:{nummer}  {monster} saknar ägare")
            for namn in agare:
                self.assertTrue(namn.startswith("@") or "@" in namn,
                                f"CODEOWNERS:{nummer}  {namn} är ingen giltig ägare")

    def test_det_finns_en_standardagare_for_allt_ovrigt(self):
        # Utan `*` är api_server.py och app.js - de två filer varje våg rör -
        # utan ägare, och en PR som bara rör dem passerar utan granskare.
        self.assertIn("*", [m for _, _, m, _ in self.regler])

    @unittest.skipUnless(_git_finns(), "inget git-arbetsträd att fråga")
    def test_ingen_rad_pekar_pa_nagot_som_inte_finns(self):
        filer = _sparade_filer()
        for nummer, zon, monster, _ in self.regler:
            if monster == "*":
                continue
            regex = _monster_till_regex(monster)
            self.assertTrue(any(regex.match(f) for f in filer),
                            f"CODEOWNERS:{nummer}  {monster} ({zon}) träffar "
                            "ingen spårad fil - raden äger ingenting")

    @unittest.skipUnless(_git_finns(), "inget git-arbetsträd att fråga")
    def test_codeowners_ar_sparad(self):
        # GitHub läser den committade filen, aldrig arbetsträdet.
        self.assertTrue(".github/CODEOWNERS" in _sparade_filer(),
                        "CODEOWNERS är inte spårad - GitHub ser den inte")

    # ── 3. skyddet ──────────────────────────────────────────────────────
    def _agare_for(self, sokvag: str) -> list[str]:
        """GitHubs upplösning: sista matchande raden vinner, inte den första."""
        traff = []
        for _, _, monster, agare in self.regler:
            if _monster_till_regex(monster).match(sokvag):
                traff = agare
        return traff

    def test_vagarna_till_produktion_har_exakt_en_agare(self):
        for sokvag in SKYDDADE_FILER:
            agare = self._agare_for(sokvag)
            self.assertEqual(agare, ["@adamfrom-code"],
                             f"{sokvag} ägs av {agare or 'ingen'}, inte av en enda ägare")

    def test_ingen_zonregel_gor_ansprak_pa_vagarna_till_produktion(self):
        # Poängen med regeln: ett paket i Z-PRICING eller Z-SITE ska inte
        # kunna ändra CI-grinden det självt bedöms av. `*` är standarden och
        # ingen zon - den räknas inte här.
        for nummer, zon, monster, _ in self.regler:
            if zon in (None, "Z-CI"):
                continue
            regex = _monster_till_regex(monster)
            for sokvag in SKYDDADE_FILER:
                self.assertIsNone(regex.match(sokvag),
                                  f"CODEOWNERS:{nummer}  zonen {zon} gör anspråk "
                                  f"på {sokvag} - den vägen rörs aldrig av ett arbetspaket")

    def test_skyddsblocket_ligger_sist(self):
        # Sista matchande raden vinner. Ligger något efter skyddsblocket kan
        # det ta över .github/ utan att en enda syntaxkontroll klagar.
        sista = [(n, m) for n, _, m, _ in self.regler][-3:]
        self.assertEqual([m for _, m in sista],
                         ["/.github/", "/render.yaml", "/backend/Dockerfile"],
                         "skyddsblocket är inte de tre sista raderna i CODEOWNERS")


if __name__ == "__main__":
    unittest.main()
