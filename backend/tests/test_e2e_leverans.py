# -*- coding: utf-8 -*-
"""Väntan på leveransen måste släppa på omritningen - och säga vad som hände
när den inte kommer.

Prövas HÄR, utan Playwright, för att det är tolkningen som kan släppa fel -
inte browsern. Att glappet finns på riktigt, och att väntan verkligen håller
i det, prövas i en riktig sida av
test_consumer_journey.BrowserJourney.test_leveransen_lases_efter_omritningen_inte_efter_klicket.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e import leverans  # noqa: E402
from e2e.leverans import Leveransen, markera_raderna, tolka, vanta_pa_leveransen  # noqa: E402


class Sida:
    """En sida som svarar det man säger åt den - och minns vad den fick."""

    def __init__(self, svar):
        self.svar = svar
        self.anrop = []

    def evaluate(self, skript, arg=None):
        self.anrop.append((skript, arg))
        return self.svar


PLAN = ["pitepalt", "korvgratang", "kyckling-pesto-pasta", "lax-kall-dillsas"]


class Tolkningen(unittest.TestCase):
    def test_en_ritad_vecka_ger_inget_besked(self):
        self.assertIsNone(tolka({"lista": True, "ritad": True, "gamla": 0,
                                 "ritade": PLAN, "saknas": []}, PLAN))

    def test_en_lista_som_saknas_ar_ett_eget_besked(self):
        besked = tolka({"lista": False}, PLAN)
        self.assertIn("#weekPlanList", besked)
        self.assertIn("finns inte", besked)

    def test_gamla_rader_kvar_betyder_att_omritningen_aldrig_kom(self):
        # CI:s läge: klicket skrev fyra nya recept, men listan visar
        # fortfarande förra bildrutans fyra rader (märkta) - inget nytt
        # ritades på hela tystnadsfönstret.
        gamla = ["blodpudding-lingon", "krogarens-makaroner", "korvgratang", "kycklingwok"]
        besked = tolka({"lista": True, "ritad": False, "tyst": True, "gamla": 7,
                        "ritade": gamla, "saknas": [id for id in PLAN if id not in gamla]},
                       PLAN, tystnad=15.0)
        self.assertIn("ritade den aldrig", besked)
        self.assertIn("7 rad(er) från före klicket", besked)
        self.assertIn("15 s", besked)
        # Både det som skrevs och det som står på skärmen, så läsaren ser
        # att det är TVÅ olika veckor - inte en vecka som saknar en rad.
        self.assertIn("pitepalt", besked)
        self.assertIn("blodpudding-lingon", besked)

    def test_fel_vecka_pa_skarmen_namner_de_saknade_recepten(self):
        # Omritningen landade (inga märkta rader kvar) men två av de fyra
        # skrivna recepten står inte i listan.
        besked = tolka({"lista": True, "ritad": False, "tyst": True, "gamla": 0,
                        "ritade": ["pitepalt", "korvgratang"],
                        "saknas": ["kyckling-pesto-pasta", "lax-kall-dillsas"]}, PLAN)
        self.assertIn("inte den som skrevs", besked)
        self.assertIn("saknas=['kyckling-pesto-pasta', 'lax-kall-dillsas']", besked)
        self.assertNotIn("ritade den aldrig", besked)


class VantanPaSidan(unittest.TestCase):
    def test_slapper_med_lagesbilden_nar_veckan_ar_ritad(self):
        sida = Sida({"lista": True, "ritad": True, "gamla": 0, "ritade": PLAN, "saknas": []})
        svar = vanta_pa_leveransen(sida, PLAN, tystnad=2.0)
        self.assertEqual(svar["ritade"], PLAN)
        # Väntan skickar id:n, märket och tystnaden i millisekunder - inte
        # sekunder: skriptet sover på setTimeout, och 15 ms hade varit en
        # väntan som alltid ger upp innan bildrutan kommer.
        (skript, arg), = sida.anrop
        self.assertIs(skript, leverans.VECKAN_RITAD)
        self.assertEqual(arg, [PLAN, leverans.MARKE, 2000])

    def test_kastar_leveransen_med_beskedet_nar_omritningen_uteblir(self):
        sida = Sida({"lista": True, "ritad": False, "tyst": True, "gamla": 4,
                     "ritade": ["annan"], "saknas": PLAN})
        with self.assertRaises(Leveransen) as fel:
            vanta_pa_leveransen(sida, PLAN)
        self.assertIn("ritade den aldrig", str(fel.exception))
        # AssertionError, så unittest räknar det som ett fel i testet.
        self.assertIsInstance(fel.exception, AssertionError)

    def test_en_tom_leverans_ar_ingen_leverans(self):
        # wait_for_state garanterar en plan; skulle någon ändå skicka en tom
        # ska väntan vägra i stället för att släppa på en oritad lista.
        sida = Sida({"lista": True, "ritad": True, "gamla": 0, "ritade": [], "saknas": []})
        with self.assertRaises(ValueError):
            vanta_pa_leveransen(sida, [])
        self.assertEqual(sida.anrop, [])

    def test_markningen_och_vantan_anvander_samma_marke(self):
        # Märket sätts av den ena och letas upp av den andra. Skulle de
        # glida isär släpper väntan på förra bildrutan igen - tyst.
        sida = Sida(3)
        self.assertEqual(markera_raderna(sida), 3)
        (skript, arg), = sida.anrop
        self.assertIs(skript, leverans.MARKERA_RADERNA)
        self.assertEqual(arg, leverans.MARKE)
        self.assertIn("[data-week-details]", leverans.VECKAN_RITAD)
        self.assertIn("#weekPlanList", leverans.MARKERA_RADERNA)


if __name__ == "__main__":
    unittest.main()


class Prisbilden(unittest.TestCase):
    """Spridningsraden och korten läses i ETT svep - och tolkningen av svaret."""

    def test_en_synlig_rad_ger_korten_ur_samma_bildruta(self):
        svar = {"ritad": True, "spridning": "Priserna skiljer sig med upp till 97 kr",
                "kort": [{"text": "Willys 536 kr", "last": False, "betalvagg": False}]}
        sida = Sida(svar)
        bild = leverans.vanta_pa_prisbilden(sida, tystnad=3.0)
        self.assertEqual(bild["kort"][0]["text"], "Willys 536 kr")
        self.assertIn("skiljer sig", bild["spridning"])
        (skript, arg), = sida.anrop
        self.assertIs(skript, leverans.PRISBILDEN)
        self.assertEqual(arg, 3000)

    def test_en_rad_som_aldrig_syns_namner_korten_som_stod_dar(self):
        # CI:s fallback: två låsta silhuetter och ingen rad, hela tystnaden ut.
        besked = leverans.tolka_prisbilden(
            {"ritad": False, "tyst": True, "rad": True,
             "kort": ["City Gross\nSe pris med Premium", "Hemköp\nSe pris med Premium"]},
            tystnad=15.0)
        self.assertIn("syntes aldrig", besked)
        self.assertIn("15 s", besked)
        self.assertIn("Se pris med Premium", besked)

    def test_en_rad_som_saknas_ar_ett_eget_besked(self):
        besked = leverans.tolka_prisbilden({"ritad": False, "tyst": True, "rad": False, "kort": []})
        self.assertIn("#storeSpreadTeaser", besked)
        self.assertIn("finns inte", besked)

    def test_vantan_kastar_leveransen_nar_raden_uteblir(self):
        sida = Sida({"ritad": False, "tyst": True, "rad": True, "kort": []})
        with self.assertRaises(Leveransen) as fel:
            leverans.vanta_pa_prisbilden(sida)
        self.assertIn("syntes aldrig", str(fel.exception))

    def test_skriptet_laser_raden_och_korten_i_samma_vanda(self):
        # Ett enda skript, en enda funktion `las` som ger både raden och
        # korten - inte två anrop som en omritning kan lägga sig emellan.
        self.assertEqual(leverans.PRISBILDEN.count("const las = () =>"), 1)
        self.assertIn('getElementById("storeSpreadTeaser")', leverans.PRISBILDEN)
        self.assertIn("#storeCards .store-card", leverans.PRISBILDEN)
        self.assertIn("data-store-card-paywall", leverans.PRISBILDEN)
