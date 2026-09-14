# -*- coding: utf-8 -*-
"""Träffytans 44 px mäts med en tumme - och ingen e2e-fil får mäta med linjal.

L2:s acceptanstest läste tillbaka 43.999969482421875 ur
`getBoundingClientRect()` för en knapp som CSS sätter till `height:44px`,
och fällde bygget på M4 - en PR vars diff inte rör en enda fil appen laddar i
webbläsaren. Samma innehåll passerade vid omkörning.

Två saker prövas här, och den andra är den som gör att det inte händer igen.

**Att toleransen är rätt satt.** Subpixelresten ur den riktiga CI-körningen
ska räcka, och en knapp som verkligen krympt ska fortfarande fällas. En
tolerans som släpper igenom allt är ingen grind.

**Att ingen e2e-fil jämför ett uppmätt mått mot ett naket tal.** Det var inte
en rad som var fel utan ett mönster, och ett mönster som stod på fyra ställen
när det upptäcktes. Källkoden granskas därför här: både Python-sidan (via
`tokenize`, så att prosan i kommentarerna inte råkar räknas) och den JS som
ligger inbäddad i strängarna. Testet kör UTAN Playwright och fäller alltså
mönstret långt innan browserjobbet hinner göra det - samma skäl som
`test_e2e_diagnos.py` och `test_e2e_vantan.py`.
"""

import io
import re
import sys
import tokenize
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e import matt  # noqa: E402

E2E = Path(__file__).resolve().parent / "e2e"

# Det EXAKTA värdet ur den fällda CI-körningen. Skrivet som ett uttryck och
# inte som en decimal för att visa vad det är: 44 minus en enda bit längst ut
# i en double, inte en knapp som är för liten.
CI_VARDET = 44 - 2 ** -15


class ToleransenMaterMedTumme(unittest.TestCase):

    def test_subpixelresten_ur_ci_racker(self):
        """43.999969482421875 är 44 px. Det var den raden som fällde M4."""
        self.assertEqual(CI_VARDET, 43.999969482421875)
        self.assertLess(CI_VARDET, 44, "förutsättningen: värdet ÄR under 44")
        self.assertTrue(matt.minst(CI_VARDET),
                        "subpixelresten ur CI föll igenom - grinden är kvar som lotteri")

    def test_en_knapp_som_verkligen_krympt_falls(self):
        """Grinden har kvar sina tänder: 43,5 räcker inte, och inte 24 heller."""
        for hojd in (43.4, 40.0, 24.0, 0.0):
            self.assertFalse(matt.minst(hojd),
                             f"{hojd} px släpptes igenom som en träffyta på 44 px")

    def test_toleransen_ar_en_halv_pixel_och_inte_mer(self):
        """En halv pixel, inte 'ungefär 44'. Golvet är ett tal som går att läsa."""
        self.assertEqual(matt.golv(), 43.5)
        self.assertEqual(matt.SUBPIXEL_PX, 0.5)
        self.assertEqual(matt.TUMYTA_PX, 44)

    def test_hogst_mater_at_andra_hallet(self):
        """Samma tumme åt andra hållet: ryms blocket innanför vikten?"""
        self.assertTrue(matt.hogst(844 + 2 ** -15, 844), "0,00003 px under vikten ryms")
        self.assertTrue(matt.hogst(844.0, 844))
        self.assertFalse(matt.hogst(845.0, 844), "en hel pixel under vikten ryms inte")

    def test_for_sma_bar_med_sig_de_uppmatta_vardena(self):
        """'knappen är 24 px' går att åtgärda; 'för liten' går att gissa om."""
        self.assertEqual(
            matt.for_sma({"Spara #0": CI_VARDET, "Avbryt #1": 24.0, "Stäng #2": 44.0}),
            {"Avbryt #1": 24.0})


class IngenE2EFilMaterMedLinjal(unittest.TestCase):
    """Mönstret, inte raden: nästa mätning ska ärva toleransen."""

    def _e2e_filer(self):
        filer = sorted(p for p in E2E.glob("*.py") if p.name != "matt.py")
        # En glob som tyst blir tom gör testet till en nickdocka.
        self.assertGreaterEqual(len(filer), 4, f"hittade nästan inga e2e-filer: {filer}")
        return filer

    def test_ingen_pythonrad_jamfor_ett_matt_mot_44(self):
        """Tröskeln kommer ur matt.TUMYTA_PX - aldrig ur en 44:a i koden.

        Läses med tokenize och inte med grep: `44` står i prosan i flera
        kommentarer, och en grind som fäller sin egen förklaring lär den
        som ser den att ta bort förklaringen.
        """
        fel = []
        for fil in self._e2e_filer():
            with io.open(fil, "rb") as fh:
                for tok in tokenize.tokenize(fh.readline):
                    if tok.type == tokenize.NUMBER and tok.string == str(matt.TUMYTA_PX):
                        fel.append(f"{fil.name}:{tok.start[0]}: {tok.line.strip()}")
        self.assertEqual(fel, [], "använd matt.TUMYTA_PX / matt.minst() i stället för 44:\n"
                                  + "\n".join(fel))

    def test_ingen_inbaddad_js_jamfor_ett_matt_mot_ett_tal(self):
        """`.height < 44` i en evaluate() är samma bugg, en våning ned.

        Den inbäddade JS:en ligger i Python-strängar och syns därför inte för
        tokenize-passet ovan. Båda ledden prövas: `r.height < 44` och
        `44 > r.height`.
        """
        matt_ref = r"(?:getBoundingClientRect\(\)|\br)\.(?:height|width|top|bottom|left|right)"
        tal = r"\d+(?:\.\d+)?"
        jmf = r"(?:[<>]=?|={2,3}|!={1,2})"
        mönster = (re.compile(rf"{matt_ref}\s*{jmf}\s*{tal}"),
                   re.compile(rf"{tal}\s*{jmf}\s*{matt_ref}"))
        fel = []
        for fil in self._e2e_filer():
            with io.open(fil, "rb") as fh:
                for tok in tokenize.tokenize(fh.readline):
                    if tok.type != tokenize.STRING:
                        continue
                    for m in mönster:
                        for träff in m.finditer(tok.string):
                            fel.append(f"{fil.name}:{tok.start[0]}: {träff.group(0)!r}")
        self.assertEqual(fel, [], "skicka in matt.golv() i evaluate() i stället:\n"
                                  + "\n".join(fel))


class OmritadKnapp:
    """En knapp som omritningen byter ut de `oritade` första svepen.

    Inte hittepå: det är vad `renderBasket` gör med veckolistan::

        $("weekPlanList").innerHTML = veckoDagarMarkup(...)   // alla noder byts

    Svepet svarar None när noden var avhängd - det är vad `matt.SVEP_JS` gör
    med `isConnected` och nollrect:en. Den GAMLA mätningen hade ingen sådan
    vakt: den mätte noden som den låg, och fick nollor.
    """

    def __init__(self, hojd=44.0, oritade=0, alltid_oritad=False):
        self.hojd = hojd
        self.oritade = oritade
        self.alltid_oritad = alltid_oritad
        self.svep = 0

    def _oritad_nu(self):
        self.svep += 1
        return self.alltid_oritad or self.svep <= self.oritade

    def __call__(self):
        return None if self._oritad_nu() else {
            "hojd": self.hojd, "vanster": True, "hoger": True}

    def gamla_matningen(self):
        """Ett enda svep, utan vakt - nollor när omritningen hann emellan."""
        return {"hojd": 0, "vanster": False, "hoger": False} if self._oritad_nu() else {
            "hojd": self.hojd, "vanster": True, "hoger": True}


class MatningenLaserEfterOmritningen(unittest.TestCase):
    """L2c: en rect som är idel nollor är ingen mätning.

    Båda riktningarna prövas. Att den nya mätningen fungerar säger ingenting
    om det inte också visas att den gamla faktiskt gick sönder.
    """

    def test_den_gamla_matningen_laser_nollor_nar_omritningen_hann_emellan(self):
        """Fel-riktningen: utan vakt är CI-felet tillbaka, ordagrant."""
        sjalva_felet = OmritadKnapp(oritade=1).gamla_matningen()
        self.assertEqual(sjalva_felet, {"hojd": 0, "vanster": False, "hoger": False})
        # Och så här fällde det L2:s acceptanstest - toleransen hjälper inte.
        self.assertFalse(matt.minst(sjalva_felet["hojd"]))

    def test_matningen_sveper_forbi_de_oritade_och_mater_den_ritade_noden(self):
        knapp = OmritadKnapp(oritade=5)
        matning = matt.mat(knapp)
        self.assertTrue(matt.minst(matning["hojd"]))
        self.assertEqual(knapp.svep, 6, "svepte inte precis tills noden fanns")

    def test_en_ritad_nod_kostar_ett_enda_svep(self):
        """Det vanliga fallet mäter direkt - omtaget är ett skyddsnät, inte en väntan."""
        knapp = OmritadKnapp()
        matt.mat(knapp)
        self.assertEqual(knapp.svep, 1)

    def test_en_knapp_som_verkligen_ar_for_liten_falls_fortfarande(self):
        """Grinden blev inte slappare. Vakten skiljer 'inte ritad' från
        'ritad, och för liten' - den andra ska fortfarande fälla."""
        matning = matt.mat(OmritadKnapp(hojd=30.0, oritade=2))
        self.assertFalse(matt.minst(matning["hojd"]), f"30 px ska fällas: {matning}")

    def test_en_knapp_som_aldrig_ritas_falls_med_ett_besked_om_appen(self):
        knapp = OmritadKnapp(alltid_oritad=True)
        with self.assertRaises(matt.Oritad) as fel:
            matt.mat(knapp, tak=12)
        self.assertEqual(knapp.svep, 12, "taket hölls inte")
        self.assertIn("aldrig", str(fel.exception))

    def test_taket_maste_vara_minst_ett_svep(self):
        with self.assertRaises(ValueError):
            matt.mat(OmritadKnapp(), tak=0)


class IngenE2EFilMaterPaEnUppslagenNod(unittest.TestCase):
    """Mönstret, inte raden - samma skäl som klassen ovanför.

    Att slå upp ett element i Python och mäta det i en andra CDP-vända är
    glappet en omritning ryms i. Mätningen ska gå genom `matt.sidans_traffyta`,
    som söker upp noden och mäter den i samma svep.
    """

    def test_ingen_matning_gors_pa_en_nod_som_slagits_upp_i_python(self):
        mottagare = re.compile(r"(\w+(?:\.\w+)*)\.evaluate\(")
        fel = []
        for fil in sorted(p for p in E2E.glob("*.py") if p.name != "matt.py"):
            kalla = fil.read_text(encoding="utf-8")
            for m in mottagare.finditer(kalla):
                namn = m.group(1)
                if namn.split(".")[-1] == "page":
                    continue  # page.evaluate söker upp noden inne i JS - ett svep
                kropp = kalla[m.end():m.end() + 1200]
                if "getBoundingClientRect" in kropp:
                    rad = kalla[:m.start()].count("\n") + 1
                    fel.append(f"{fil.name}:{rad}: {namn}.evaluate(...) mäter en uppslagen nod")
        self.assertEqual(fel, [], "mät med matt.sidans_traffyta() i stället:\n" + "\n".join(fel))


if __name__ == "__main__":
    unittest.main()
