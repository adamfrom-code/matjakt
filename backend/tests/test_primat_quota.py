# -*- coding: utf-8 -*-
"""Primats kvot: läst ur deras eget svar, eller "Ej tillgängligt".

O8 säger att kvoten bara får visas från verklig dokumenterad API-data. Den
här sviten prövar båda riktningarna: att ett svar som BÄR kvoten läses rätt,
och att ett svar som inte gör det ger None i stället för ett gissat tal."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.grocery import alerts  # noqa: E402
from services.grocery.scheduler import DEFAULT_SCHEDULE, PRIMAT_ONLY_CHAINS  # noqa: E402


class KvotenLasesUrSvaret(unittest.TestCase):

    def test_de_vanliga_stavningarna_hittas(self):
        for kropp in ({"rowsUsedToday": 18000, "dailyRowLimit": 100000},
                      {"rows_used_today": 18000, "daily_row_limit": 100000},
                      {"usedToday": 18000, "rowLimit": 100000},
                      {"used": 18000, "limit": 100000}):
            kvot = alerts.quota_from_account_status(kropp)
            self.assertIsNotNone(kvot, kropp)
            self.assertEqual((kvot["rowsUsedToday"], kvot["dailyRowLimit"]), (18000, 100000))

    def test_kvoten_hittas_aven_en_niva_ner(self):
        kvot = alerts.quota_from_account_status(
            {"plan": "app", "usage": {"rowsUsedToday": 5, "dailyRowLimit": 100000}})
        self.assertEqual(kvot["dailyRowLimit"], 100000)
        self.assertEqual(kvot["plan"], "app")

    def test_ett_svar_utan_kvot_ger_none_inte_en_nolla(self):
        # Det här är hela poängen: hellre "Ej tillgängligt" än "0 av 0".
        for kropp in ({}, {"plan": "app"}, {"rowsUsedToday": 100}, {"dailyRowLimit": 0},
                      {"rowsUsedToday": "mycket", "dailyRowLimit": "en del"}, None, "nej", 7):
            self.assertIsNone(alerts.quota_from_account_status(kropp), kropp)

    def test_ingen_kvot_i_koden(self):
        # Siffran ska komma från Primat, inte från oss.
        källa = (Path(__file__).resolve().parents[1] / "services/grocery/alerts.py").read_text(encoding="utf-8")
        for tal in ("20000", "100000", "20_000", "100_000"):
            self.assertNotIn(tal, källa, f"{tal} hårdkodad i alerts.py")


class VarningenNarKvotenTarSlut(unittest.TestCase):

    def test_larmet_gar_vid_85_procent_men_inte_fore(self):
        under = alerts.evaluate([], quota={"rowsUsedToday": 84000, "dailyRowLimit": 100000})
        över = alerts.evaluate([], quota={"rowsUsedToday": 85000, "dailyRowLimit": 100000})
        self.assertNotIn("primat:quota", under)
        self.assertIn("primat:quota", över)
        self.assertIn("85000 av 100000", över["primat:quota"]["body"])

    def test_utan_kvot_larmas_inget(self):
        self.assertNotIn("primat:quota", alerts.evaluate([], quota=None))


class SchematsKedjor(unittest.TestCase):

    def test_lidl_hamtas_och_ligger_sist(self):
        self.assertIn("Lidl", DEFAULT_SCHEDULE)
        self.assertEqual(max(DEFAULT_SCHEDULE, key=lambda k: DEFAULT_SCHEDULE[k]), "Lidl")

    def test_lidl_kravs_nyckel_annars_larmar_den_varje_natt(self):
        # Utan nyckel kastar _provider_for. Står kedjan inte i
        # PRIMAT_ONLY_CHAINS schemaläggs den ändå och faller varje natt.
        self.assertIn("Lidl", PRIMAT_ONLY_CHAINS)

    def test_att_hamta_ar_inte_att_slappa(self):
        # ICA är släppt sedan D11, men på REFERENSNIVÅ och efter ett beslut -
        # inte för att den råkade importeras. Coop och Lidl importeras med
        # samma provider och samma schema, och får inte följa med av misstag.
        from services.grocery.api import RELEASED_CHAINS
        for kedja in ("Coop", "Lidl"):
            self.assertNotIn(kedja, RELEASED_CHAINS, f"{kedja} blev publik av en schemaändring")


if __name__ == "__main__":
    unittest.main()
