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


if __name__ == "__main__":
    unittest.main()
