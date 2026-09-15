# -*- coding: utf-8 -*-
"""P02a: IAP-analysen får inte glida ifrån affärsmodellen den beskriver.

`docs/IAP_COMPLIANCE.md` är beslutsunderlaget för StoreKit i iOS-appen. Det
namnger produkt-id:n Adam ska skriva in i App Store Connect, priserna
webben tar, flaggan servern läser och de sektioner briefen kräver. Var och
en av dem har en sanningskälla i kod, och ett dokument som säger något
annat än koden är farligare än inget dokument: det är det Adam klickar
efter i App Store Connect, och ett produkt-id går inte att ändra i
efterhand.

Testet läser därför dokumentet mot `services.accounts.features.PRICING` -
inte tvärtom. Ändras ett produkt-id eller ett pris i koden ska dokumentet
bli rött tills någon läst igenom vad det betyder för App Store Connect.

Två saker prövas som INTE får finnas: det gamla priset 499 kr och en
fjorton dagars provperiod. Affärsbeslutet 2026-08-31 (features.py: "No
automatic trial") tog bort båda, och briefen för P02 säger uttryckligen att
ingen av dem får leva kvar i det som beskriver Apple-flödet.
"""

import re
import sys
import unittest
from pathlib import Path

HÄR = Path(__file__).resolve().parent
sys.path.insert(0, str(HÄR.parent))

from services.accounts import features  # noqa: E402

ROT = HÄR.parents[1]
DOKUMENT = ROT / "docs" / "IAP_COMPLIANCE.md"

# Sektionerna briefen kräver, i den ordning de ska stå.
SEKTIONER = ("## (a)", "## (b)", "## (c)", "## (d)", "## (e) BLOCKED – ADAM")


def _text() -> str:
    return DOKUMENT.read_text(encoding="utf-8")


def _platt() -> str:
    """Dokumentet med radbrytningar och citatprefix ihopsmälta till ett
    blanksteg. Citaten ur Apple radbryts på 72 tecken med `> ` framför varje
    rad, och en fras som "must use in-app purchase" ska hittas oavsett var
    brytningen råkade hamna."""
    return re.sub(r"\s+", " ", _text().replace("\n> ", " "))


class DokumentetFinnsOchArKomplett(unittest.TestCase):
    def test_dokumentet_finns(self):
        self.assertTrue(DOKUMENT.is_file(), "docs/IAP_COMPLIANCE.md saknas")

    def test_alla_fem_sektionerna_star_i_ordning(self):
        text = _text()
        positioner = []
        for rubrik in SEKTIONER:
            self.assertIn(rubrik, text, f"sektionen {rubrik!r} saknas")
            positioner.append(text.index(rubrik))
        self.assertEqual(positioner, sorted(positioner),
                         "sektionerna (a)-(e) står inte i briefens ordning")

    def test_apples_regler_citeras_med_avsnitt_och_datum(self):
        # Analysen ska stå på citat ur Apples text, inte på minne. De tre
        # avsnitten som avgör frågan måste vara namngivna, och läsdatumet
        # ska stå så att nästa läsare vet hur färsk texten är.
        text = _platt()
        for avsnitt in ("3.1.1", "3.1.1(a)", "3.1.3(b)"):
            self.assertIn(avsnitt, text, f"avsnitt {avsnitt} nämns inte")
        self.assertIn("must use in-app purchase", text,
                      "huvudregelns ordalydelse citeras inte")
        self.assertIn("provided those items are also available as in-app purchases", text,
                      "3.1.3(b):s villkor - det som hela korsplattformsdesignen vilar på - citeras inte")
        self.assertRegex(text, r"\b2026-\d{2}-\d{2}\b", "inget läsdatum i dokumentet")

    def test_slutsatsen_om_dagens_flode_ar_uttalad(self):
        # Ett dokument som beskriver reglerna men inte fäller domen är inte
        # ett beslutsunderlag. Meningen ska stå där, rakt ut.
        self.assertIn("får inte skickas till App Review", _platt())


class DokumentetFoljerKoden(unittest.TestCase):
    def test_varje_storekit_produkt_id_ur_pricing_star_i_dokumentet(self):
        text = _text()
        for nyckel, plan in features.PRICING.items():
            produkt = plan["storekitProductId"]
            self.assertIn(produkt, text,
                          f"produkt-id:t {produkt} ({nyckel}) ur features.PRICING saknas i dokumentet - "
                          f"det är strängen Adam skriver in i App Store Connect")

    def test_dokumentet_hittar_inte_pa_egna_produkt_id(self):
        # Alla strängar som ser ut som våra produkt-id måste finnas i koden.
        # Ett påhittat id i klickvägen blir ett påhittat id i App Store
        # Connect, och det går inte att ändra i efterhand.
        kända = {plan["storekitProductId"] for plan in features.PRICING.values()}
        for träff in set(re.findall(r"se\.matjakt\.premium\.[a-z]+", _text())):
            self.assertIn(träff, kända, f"{träff} finns inte i features.PRICING")

    def test_priserna_i_dokumentet_ar_affarsmodellens(self):
        text = _text()
        månad = features.PRICING["monthly"]["pricePerMonth"]
        år = features.PRICING["yearly"]["pricePerYear"]
        self.assertIn(f"{månad} kr", text, "månadspriset ur features.PRICING saknas")
        self.assertIn(f"{år} kr", text, "årspriset ur features.PRICING saknas")

    def test_inga_apple_belopp_ar_hardkodade(self):
        # Apples prispunkter läses i App Store Connect och visas av StoreKit.
        # Dokumentet ska säga det - och får inte själv innehålla en tabell
        # med Apple-belopp som tyst börjar ljuga när Apple ändrar listan.
        text = _platt()
        self.assertIn("displayPrice", text,
                      "dokumentet säger inte att appen visar StoreKits pris")
        self.assertIn("Hårdkoda inga belopp", text)
        self.assertNotRegex(text, r"\d+\s*SEK\b",
                            "ett belopp i SEK står i dokumentet - Apples prispunkter hör hemma i ASC")

    def test_det_gamla_priset_och_provperioden_lever_inte_kvar(self):
        text = _text()
        self.assertNotRegex(text, r"\b499\b", "det gamla priset 499 lever kvar i dokumentet")
        self.assertNotRegex(text, r"\b14[ -]dagars?\b", "en fjorton dagars provperiod lever kvar i dokumentet")
        # Och koden själv: affärsmodellen bär inget prov och inget 499.
        källa = (ROT / "backend" / "services" / "accounts" / "features.py").read_text(encoding="utf-8")
        self.assertNotRegex(källa, r"\b499\b")
        for plan in features.PRICING.values():
            self.assertFalse(any("trial" in nyckel.lower() for nyckel in plan),
                             f"features.PRICING bär en provperiod: {sorted(plan)}")

    def test_flaggan_servern_laser_ar_namngiven(self):
        # P02c och P02d ligger bakom samma flagga. Namnet bestäms här, en
        # gång, så att servern, appen och Render-konfigurationen inte kan
        # stava den olika.
        self.assertIn("MATJAKT_APPLE_IAP", _text())


class BlockeratForAdamHarKlickvagar(unittest.TestCase):
    """Varje punkt Adam måste göra själv ska ha en exakt klickväg - annars är
    listan en önskan, inte en instruktion."""

    def _punkter(self):
        text = _text()
        start = text.index("## (e) BLOCKED – ADAM")
        slut = text.index("## Paketen och det som återstår")
        del_ = text[start:slut]
        delar = re.split(r"\n### BLOCKED – ADAM \d+ · ", del_)
        return delar[1:]      # första biten är sektionsingressen

    def test_det_finns_flera_punkter(self):
        self.assertGreaterEqual(len(self._punkter()), 5)

    def test_varje_punkt_bar_en_klickvag(self):
        for punkt in self._punkter():
            rubrik = punkt.splitlines()[0]
            with self.subTest(punkt=rubrik):
                self.assertIn("Klickväg:", punkt, f"BLOCKED – ADAM-punkten {rubrik!r} saknar klickväg")

    def test_paid_apps_avtalet_och_notis_urlen_finns_med(self):
        # De två som blockerar allt annat: utan avtalet finns inga produkter,
        # utan URL:en når ingen notis servern.
        text = _platt()
        self.assertIn("Paid Apps", text)
        self.assertIn("/api/billing/apple/notifications", text)
        self.assertIn("Version 2", text)


if __name__ == "__main__":
    unittest.main()
