# -*- coding: utf-8 -*-
"""Avbockningsloopen måste läsa DOM:en EFTER omritningen, inte efter skrivningen.

Prövas HÄR, utan Playwright, för att det är loopen som kan läsa fel - inte
browsern. Samma skäl som `test_e2e_vantan.py` och `test_e2e_matt.py`: en
loop som läser på fel sida av en bildruta faller slumpvis, och en slumpvis
röd svit lär alla att köra om i stället för att läsa loggen.

Sekvensen nedan är inte hittepå. Den är ordningen i `setItemStatus`
(frontend/app/app.js)::

    saveState();          // skrivningen - den T2:s väntan väcks av
    invalidate("basket"); // omritningen - köad på requestAnimationFrame

Skrivningen först, omritningen en bildruta senare. `FramebussensLista`
nedan gör exakt det, och inget annat.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e.avbockning import TAK, Avbockningen, bocka_av_listan  # noqa: E402

E2E_KATALOG = Path(__file__).resolve().parent / "e2e"


class Tidsgräns(Exception):
    """Playwrights TimeoutError, utan Playwright."""


class FramebussensLista:
    """En lista där DOM:en ligger en bildruta efter tillståndet.

    Klicket skriver tillståndet direkt men rör inte DOM:en - raden står
    kvar som obockad tills bildrutan landar. Det är render-bussen i app.js,
    och det är hela glappet den gamla loopen läste i.
    """

    def __init__(self, varor, trilskande=(), atergar=()):
        self.dom = list(varor)          # vad DOM:en visar som OBOCKAT
        self.tillstånd = []             # vad appen SKRIVIT som avbockat
        self.oritad = None              # avbockning som väntar på sin bildruta
        self.trilskande = dict(trilskande)   # varor vars klick inte landar
        self.atergar = set(atergar)     # varor som kommer tillbaka som obockade
        self.inaktuella_läsningar = []  # kvar() medan en bildruta var oritad
        self.svep = 0

    # ---- de fyra stegen ----
    def kvar(self):
        self.svep += 1
        if self.oritad is not None:
            # Det här är felet. Ett svar här beskriver ett läge appen redan
            # lämnat, och loopen fattar sitt beslut på det.
            self.inaktuella_läsningar.append((self.svep, self.oritad))
        return list(self.dom)

    def klicka(self, namn):
        kvar_att_trilska = self.trilskande.get(namn, 0)
        if kvar_att_trilska:
            self.trilskande[namn] = kvar_att_trilska - 1
            return  # noden byttes ut under klicket - ingen skrivning
        if namn not in self.tillstånd:
            self.tillstånd.append(namn)
            self.oritad = namn  # skrivningen är gjord, bildrutan är köad

    def avbockad(self, namn):
        return namn in self.tillstånd

    def ritad(self, namn):
        if self.oritad is None:
            return
        if self.oritad != namn:
            raise AssertionError(f"väntade in {namn} men {self.oritad} var oritad")
        self.dom.remove(self.oritad)
        if self.oritad in self.atergar:
            # Appen ritade avbockningen och tog sedan tillbaka den.
            self.atergar.discard(self.oritad)
            self.tillstånd.remove(self.oritad)
            self.dom.append(self.oritad)
        self.oritad = None

    def stegen(self):
        return self.kvar, self.klicka, self.avbockad, self.ritad


class AvbockningenLaserEfterOmritningen(unittest.TestCase):
    """Kärnan: loopen får aldrig läsa listan medan en bildruta är oritad."""

    def test_hela_listan_bockas_av_i_tur_och_ordning(self):
        lista = FramebussensLista(["Mjölk", "Ägg", "Bröd"])
        avbockade = bocka_av_listan(*lista.stegen())
        self.assertEqual(avbockade, ["Mjölk", "Ägg", "Bröd"])
        self.assertEqual(lista.dom, [])
        self.assertEqual(lista.tillstånd, ["Mjölk", "Ägg", "Bröd"])

    def test_ingen_lasning_sker_medan_en_bildruta_ar_oritad(self):
        """Invarianten. Varje `kvar()` ska svara om ett läge appen ritat."""
        lista = FramebussensLista(["Mjölk", "Ägg", "Bröd", "Smör", "Kaffe"])
        bocka_av_listan(*lista.stegen())
        self.assertEqual(
            lista.inaktuella_läsningar, [],
            "loopen läste listan medan omritningen fortfarande var köad -"
            f" det är precis glappet CI föll i: {lista.inaktuella_läsningar}")

    def test_den_gamla_tvastegslasningen_faller_pa_samma_lista(self):
        """Facit: samma lista, den gamla formen, och tjugosekunderskraschen.

        Den gamla loopen läste i två steg - `count()` och sedan
        `get_attribute()` - med en bildruta emellan. På SISTA varan såg steg
        1 en rad kvar och steg 2 en tom lista, och då väntade Playwright ut
        hela sin tidsgräns på ett element som aldrig kommer tillbaka.
        """
        lista = FramebussensLista(["Mjölk", "Ägg"])

        def gamla_loopen():
            for _ in range(TAK):
                antal = len(lista.dom)          # steg 1: stickprov, svarar direkt
                if antal == 0:
                    return
                # Bildrutan landar mellan de två stegen. På en lastad maskin
                # kan den landa var som helst, och här landar den.
                if lista.oritad is not None:
                    lista.ritad(lista.oritad)
                if not lista.dom:               # steg 2: VÄNTAR in ett element
                    raise Tidsgräns(
                        "Locator.get_attribute: Timeout 20000ms exceeded."
                        ' waiting for locator("#shoppingList [data-bought]")')
                namn = lista.dom[0]
                lista.klicka(namn)
            raise AssertionError("listan tog aldrig slut")

        with self.assertRaises(Tidsgräns) as fångad:
            gamla_loopen()
        self.assertIn("Timeout 20000ms exceeded", str(fångad.exception))

        # Och samma lista, samma bildrutor, genom den nya loopen: i mål.
        pånytt = FramebussensLista(["Mjölk", "Ägg"])
        self.assertEqual(bocka_av_listan(*pånytt.stegen()), ["Mjölk", "Ägg"])


class NagotVerkligtTrasigtFallerFortfarande(unittest.TestCase):
    """En tolerant loop som aldrig faller är lika värdelös som en slumpvis."""

    def test_en_vara_som_inte_gar_att_bocka_av_faller_testet(self):
        lista = FramebussensLista(["Mjölk", "Ägg"], trilskande={"Ägg": 99})
        with self.assertRaises(Avbockningen) as fångad:
            bocka_av_listan(*lista.stegen())
        self.assertIn("Ägg", str(fångad.exception))
        self.assertIn("gick inte att bocka av", str(fångad.exception))
        # Och felet säger hur långt den kom - inte bara att den inte kom fram.
        self.assertIn("Mjölk", str(fångad.exception))

    def test_ett_klick_som_inte_landar_ar_ett_varv_till_inte_ett_fel(self):
        """Noden byts ut under klicket av prishämtningen. Det är inget fel."""
        lista = FramebussensLista(["Mjölk", "Ägg"], trilskande={"Mjölk": 3})
        self.assertEqual(bocka_av_listan(*lista.stegen()), ["Mjölk", "Ägg"])

    def test_en_vara_som_gar_tillbaka_till_obockad_namnger_sig(self):
        """Bokförd, ritad - och strax därpå obockad igen. Ett riktigt fel,
        och det ska heta det i stället för att snurra tills taket tar slut."""
        lista = FramebussensLista(["Mjölk", "Ägg"], atergar={"Mjölk"})
        with self.assertRaises(Avbockningen) as fångad:
            bocka_av_listan(*lista.stegen())
        self.assertIn("Mjölk", str(fångad.exception))
        self.assertIn("stod strax efter kvar som obockad", str(fångad.exception))

    def test_en_lista_som_aldrig_tar_slut_faller_pa_taket(self):
        class Oandlig(FramebussensLista):
            def ritad(self, namn):
                super().ritad(namn)
                self.dom.append(f"{namn}-igen")

        lista = Oandlig(["Mjölk"])
        with self.assertRaises(Avbockningen) as fångad:
            bocka_av_listan(*lista.stegen())
        self.assertIn("listan tog aldrig slut", str(fångad.exception))


class ListanBockasAvPaEttStalle(unittest.TestCase):
    """Regeln har en definition, och det är `e2e/avbockning.py`.

    Grinden failar mot origin/main och pekar då ut de tre ställen i
    test_consumer_journey.py som läste listan på egen hand.
    """

    def test_ingen_annan_e2e_fil_bockar_av_listan_pa_egen_hand(self):
        träffar = []
        for fil in sorted(E2E_KATALOG.glob("*.py")):
            if fil.name == "avbockning.py":
                continue
            for nr, rad in enumerate(fil.read_text(encoding="utf-8").splitlines(), 1):
                if "data-bought" in rad:
                    träffar.append(f"{fil.name}:{nr}: {rad.strip()}")
        self.assertEqual(
            träffar, [],
            "listan bockas av på egen hand här i stället för genom"
            " e2e/avbockning.py, som är det enda stället som vet att"
            " omritningen ligger en bildruta efter skrivningen:\n  "
            + "\n  ".join(träffar))


if __name__ == "__main__":
    unittest.main()
