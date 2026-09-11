# -*- coding: utf-8 -*-
"""E2E:ns väntan måste väckas av skrivningen, inte av klockan.

Prövas HÄR, utan Playwright, för att det är loopen som kan vänta fel - inte
browsern. En väntan som tyst väntar på fel sak upptäcks annars först den
gång den behövs, och då är CI-körningen redan förbi.

Varje test nedan motsvarar ett sätt den gamla, stickprovande väntan gick
sönder på. Sekvenserna är inte hittepå: de är skrivordningen ur en riktig
körning av test_premium_paywall_and_stripe_testmode, mätt med en
instrumenterad Storage.prototype.setItem.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e.vantan import Vantan, sidans_skrivbok, vanta_pa_tillstand  # noqa: E402


class Skrivbok:
    """En bokförd skrivsekvens - samma seam som sidans, utan sida.

    Räknar dessutom avläsningarna. Det är den mätbara skillnaden mellan att
    vakna på en skrivning och att stickprova: en stickprovande väntan läser
    om och om igen MELLAN skrivningarna, en väckt väntan läser exakt en
    gång per skrivning.
    """

    def __init__(self, start=None, skrivningar=(), tyst_efter=True):
        self.start = start if start is not None else {}
        self.kvar = list(skrivningar)
        self.tyst_efter = tyst_efter
        self.nulage_anrop = 0
        self.nasta_anrop = 0
        self.levererade = 0

    def nulage(self):
        self.nulage_anrop += 1
        return self.levererade, self.start if not self.levererade else self.senast

    def nasta(self, efter, tystnad):
        self.nasta_anrop += 1
        if not self.kvar:
            if self.tyst_efter:
                return efter, []
            raise AssertionError("väntan frågade efter fler skrivningar än sekvensen har")
        # En skrivning i taget om inget annat sägs; en lista betyder att de
        # kom så tätt att samma skörd fick med båda.
        nasta = self.kvar.pop(0)
        lagen = list(nasta) if isinstance(nasta, list) else [nasta]
        self.levererade += len(lagen)
        self.senast = lagen[-1]
        return self.levererade, lagen


# Skrivordningen efter återkomsten från Stripe, mätt i en riktig körning:
# en tom vecka, den nygenererade veckan (chooseMenu på ?billing=success),
# och sist kontots egen vecka tillbaka via pullAccountState.
VECKAN_FORE = ["tonfiskpasta-citron", "linssoppa-rod", "kycklingsoppa-nudlar", "kottfarssas"]
EFTER_CHECKOUT = [
    {"onboardingComplete": True, "weekPlan": []},
    {"onboardingComplete": True, "weekPlan": ["kottfarssas", "broccolisoppa"]},
    {"onboardingComplete": True, "weekPlan": VECKAN_FORE},
]


class VantanVaknarPaSkrivningen(unittest.TestCase):

    def test_returnerar_skrivningen_som_uppfyller_villkoret(self):
        bok = Skrivbok(start={"weekPlan": []}, skrivningar=EFTER_CHECKOUT)
        lage = vanta_pa_tillstand(bok.nulage, bok.nasta,
                                  lambda s: s.get("weekPlan") == VECKAN_FORE,
                                  vad="veckan efter checkout")
        self.assertEqual(lage["weekPlan"], VECKAN_FORE)

    def test_laser_en_gang_per_skrivning_och_inte_daremellan(self):
        """Acceptanskriteriet. En stickprovande väntan läser på en timer och
        gör alltså fler avläsningar än det finns skrivningar - hur många
        beror på hur långsam maskinen råkade vara. Den här läser exakt en
        gång i början och en gång per skörd, oavsett hur lång tid det tog."""
        bok = Skrivbok(start={"weekPlan": []}, skrivningar=EFTER_CHECKOUT)
        vanta_pa_tillstand(bok.nulage, bok.nasta,
                           lambda s: s.get("weekPlan") == VECKAN_FORE)
        self.assertEqual(bok.nulage_anrop, 1, "läste nuläget mer än en gång")
        self.assertEqual(bok.nasta_anrop, len(EFTER_CHECKOUT),
                         "väntade på något annat än skrivningarna")

    def test_tiden_mellan_skrivningarna_spelar_ingen_roll(self):
        """Det som fällde CI: svaret kom senare än tidsgränsen. Väntan har
        ingen total tidsgräns kvar att gå över - bara tystnad räknas, och
        appen var aldrig tyst."""
        langsam = [{"weekPlan": []}] * 40 + [{"weekPlan": VECKAN_FORE}]
        bok = Skrivbok(skrivningar=langsam)
        lage = vanta_pa_tillstand(bok.nulage, bok.nasta,
                                  lambda s: s.get("weekPlan") == VECKAN_FORE,
                                  tystnad=0.001)
        self.assertEqual(lage["weekPlan"], VECKAN_FORE)

    def test_ett_varde_som_skrivs_over_direkt_missas_inte(self):
        """Den andra halvan av felet: appen skriver extravaran och
        pullAccountState skriver över den med kontots äldre blob några
        millisekunder senare. Ett stickprov däremellan ser ingenting -
        värdet fanns, men ingen tittade. Här prövas VARJE skrivning, också
        de två som kom i samma skörd."""
        bok = Skrivbok(skrivningar=[[{"extraItems": [{"name": "Olivolja"}]},
                                     {"extraItems": []}]])
        lage = vanta_pa_tillstand(
            bok.nulage, bok.nasta,
            lambda s: any(e.get("name") == "Olivolja" for e in s.get("extraItems") or []),
            vad="Olivolja som extravara")
        self.assertEqual(lage["extraItems"], [{"name": "Olivolja"}])

    def test_villkoret_som_redan_ar_sant_vantar_inte(self):
        bok = Skrivbok(start={"weekPlan": VECKAN_FORE})
        lage = vanta_pa_tillstand(bok.nulage, bok.nasta,
                                  lambda s: s.get("weekPlan") == VECKAN_FORE)
        self.assertEqual(lage["weekPlan"], VECKAN_FORE)
        self.assertEqual(bok.nasta_anrop, 0, "väntade fast svaret redan stod där")

    def test_tystnad_sager_att_appen_slutade_skriva(self):
        """Beskedet måste gå att skilja från 'maskinen är långsam'. Antalet
        skrivningar och den sista av dem är hela skillnaden mellan 'klicket
        nådde aldrig fram' och 'appen skrev något annat'."""
        bok = Skrivbok(skrivningar=[{"weekPlan": ["fel-recept"]}])
        with self.assertRaises(Vantan) as fangat:
            vanta_pa_tillstand(bok.nulage, bok.nasta,
                               lambda s: s.get("weekPlan") == VECKAN_FORE,
                               vad="veckan efter checkout", tystnad=0.001)
        text = str(fangat.exception)
        self.assertIn("veckan efter checkout", text)
        self.assertIn("skrev 1 gånger", text)
        self.assertIn("tyst", text)
        self.assertIn("fel-recept", text, "sista skrivningen måste stå i beskedet")

    def test_ingen_skrivning_alls_sager_just_det(self):
        bok = Skrivbok(start={"extraItems": []})
        with self.assertRaises(Vantan) as fangat:
            vanta_pa_tillstand(bok.nulage, bok.nasta, lambda s: s.get("extraItems"),
                               vad="Olivolja som extravara", tystnad=0.001)
        self.assertIn("skrev aldrig", str(fangat.exception))

    def test_taket_haller_en_evig_skrivloop_kort(self):
        bok = Skrivbok(skrivningar=[{"n": n} for n in range(50)], tyst_efter=False)
        with self.assertRaises(Vantan) as fangat:
            vanta_pa_tillstand(bok.nulage, bok.nasta, lambda s: False, tak=10)
        self.assertIn("taket 10", str(fangat.exception))
        self.assertEqual(bok.nasta_anrop, 10)


class Sidhalvan(unittest.TestCase):
    """Seamen mot sidan, prövad med en sidattrapp.

    Det som kan gå sönder här går sönder TYST: ett init-skript som inte kör
    ger en väntan som inte ser något, och det ser ut precis som en app som
    inte skriver. Därför måste den saknade boken bli ett högljutt fel med
    en åtgärd i sig, inte en tystnad som råkar likna ett riktigt besked.
    """

    class Sidattrapp:
        def __init__(self, svar):
            self.svar = list(svar)
            self.laddningar = 0

        def evaluate(self, uttryck, arg=None):
            nasta = self.svar.pop(0)
            if isinstance(nasta, Exception):
                raise nasta
            return nasta

        def wait_for_load_state(self, *a, **kw):
            self.laddningar += 1

    def test_saknad_skrivbok_ar_ett_hogljutt_fel(self):
        sida = self.Sidattrapp([{"nummer": None, "text": None}])
        nulage, _ = sidans_skrivbok(sida)
        with self.assertRaises(Vantan) as fangat:
            nulage()
        self.assertIn("skrivboken saknas", str(fangat.exception))
        self.assertIn("SKRIVBOKEN", str(fangat.exception), "beskedet måste säga vad som fattas")

    def test_navigering_mitt_i_vantan_laser_om_nya_dokumentet(self):
        """Dokumentet - och boken med det - försvinner vid en navigering.
        Det nya dokumentets lagring är ett nytt läge att pröva villkoret
        mot, inte tystnad."""
        sida = self.Sidattrapp([
            RuntimeError("Execution context was destroyed, most likely because of a navigation"),
            {"nummer": 0, "text": '{"weekPlan": ["efter-navigering"]}'},
        ])
        _, nasta = sidans_skrivbok(sida)
        nummer, lagen = nasta(7, 1.0)
        self.assertEqual(nummer, 0)
        self.assertEqual(lagen, [{"weekPlan": ["efter-navigering"]}])
        self.assertEqual(sida.laddningar, 1)

    def test_tappade_skrivningar_ar_ett_fel_och_ingen_tystnad(self):
        """Slår boken i sitt tak har den kastat bort lägen som väntan aldrig
        fick pröva. Att då svara "villkoret blev aldrig sant" vore att påstå
        något om skrivningar ingen har sett."""
        sida = self.Sidattrapp([{"nummer": 3, "tappade": 4, "text": "{}"},
                                 {"nummer": 300, "tappade": 16, "nya": []}])
        nulage, nasta = sidans_skrivbok(sida)
        nulage()                     # bortfall som redan skett angår inte väntan
        with self.assertRaises(Vantan) as fangat:
            nasta(3, 1.0)
        self.assertIn("tappade 12 skrivningar", str(fangat.exception))

    def test_andra_fel_fran_sidan_slas_inte_ihop_med_en_navigering(self):
        sida = self.Sidattrapp([RuntimeError("protocol error: allt brann")])
        _, nasta = sidans_skrivbok(sida)
        with self.assertRaises(RuntimeError):
            nasta(0, 1.0)


if __name__ == "__main__":
    unittest.main()
