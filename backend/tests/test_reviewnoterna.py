# -*- coding: utf-8 -*-
"""P02e: reviewnoterna beskriver det bygge som lämnas in - inte v1-planen.

`store/appstore/metadata/review_notes.txt` är texten Adam klistrar in i
App Store Connect > App Review Information. Den sa "Premium säljs inte i
iOS-appen i v1 ... Inga köpknappar" om ett bygge som har knappen
"Prenumerera" (`#subscribeBtn` i `frontend/app/index.html`). Efter P02c och
P02d säljs Premium i appen via In-App Purchase, och en granskare som läser
att det inte finns några köpknappar och sedan hittar en har ett skäl att
avvisa (2.3, "accurate metadata") innan hon ens prövat köpet.

Testet läser noterna mot koden, som `test_iap_compliance.py` läser
`docs/IAP_COMPLIANCE.md`: produkt-id:na är strängarna i `features.PRICING`
(de Adam skriver in i App Store Connect, och ett produkt-id går inte att
byta i efterhand), ingen gratisperiod får påstås (J3b, 2026-09-19: ingen
automatisk trial), och det gamla styckets tre påståenden får aldrig komma
tillbaka. Belopp hör
inte hit: Apples prispunkt väljs i App Store Connect och appen visar
StoreKits pris, så en siffra i kronor vore antingen webbens pris (fel för
Apple) eller en avskrift ur ASC som tyst blir gammal.

Påståendena prövas med assertTrue/assertFalse i stället för assertIn, så
att ett fel visar frasen som saknas - inte hela noterna som container.
"""

import re
import sys
import unittest
from pathlib import Path

HÄR = Path(__file__).resolve().parent
sys.path.insert(0, str(HÄR.parent))

from services.accounts import features  # noqa: E402

ROT = HÄR.parents[1]
NOTER = ROT / "store" / "appstore" / "metadata" / "review_notes.txt"

# Det gamla styckets påståenden, ord för ord. Vart och ett beskriver ett bygge
# utan köp i appen - och det bygget lämnas inte in.
FÖRLEGAT = (
    "Inga köpknappar",
    "säljs inte i iOS-appen",
    "Om köp i appen läggs till senare",
)


def _text() -> str:
    return NOTER.read_text(encoding="utf-8")


def _platt() -> str:
    """Radbrytningarna bortsmälta: en fras ska hittas oavsett var raden bröts."""
    return re.sub(r"\s+", " ", _text())


class NoternaBeskriverKopetIAppen(unittest.TestCase):
    def _kräver(self, fras: str, varför: str, *, text: str | None = None):
        platt = _platt() if text is None else text
        self.assertTrue(fras in platt, f"{fras!r} saknas i reviewnoterna - {varför}")

    def test_filen_finns(self):
        self.assertTrue(NOTER.is_file(), "store/appstore/metadata/review_notes.txt saknas")

    def test_det_gamla_pastaendet_lever_inte_kvar(self):
        platt = _platt().lower()
        for fras in FÖRLEGAT:
            with self.subTest(fras=fras):
                self.assertFalse(fras.lower() in platt,
                                 f"reviewnoterna påstår fortfarande {fras!r} - appen har knappen "
                                 f"Prenumerera och säljer Premium via In-App Purchase (P02d)")

    def test_premium_saljs_via_in_app_purchase(self):
        self._kräver("In-App Purchase", "noterna säger inte att Premium köps i appen")
        self._kräver('"Prenumerera"', "köpknappens namn ska stå så granskaren hittar den")
        self._kräver("samma subscription group",
                     "att månad och år ligger i samma grupp är det som gör bytet Apples (3.1.2(b))")

    def test_bada_produkt_idna_ar_kodens(self):
        text = _text()
        for nyckel, plan in features.PRICING.items():
            with self.subTest(plan=nyckel):
                self._kräver(plan["storekitProductId"],
                             f"produkt-id:t för {nyckel} ur features.PRICING är det Adam skriver in i ASC",
                             text=text)

    def test_noterna_hittar_inte_pa_egna_produkt_id(self):
        kända = {plan["storekitProductId"] for plan in features.PRICING.values()}
        for träff in set(re.findall(r"se\.matjakt\.premium\.[a-z]+", _text())):
            self.assertIn(träff, kända, f"{träff} finns inte i features.PRICING")

    def test_webbkop_lases_upp_enligt_3_1_3_b(self):
        self._kräver("3.1.3(b)", "riktlinjen som tillåter upplåsning av webbköp ska vara namngiven")
        self._kräver("matjakt.store", "var Premium också säljs (webben) ska stå")

    def test_aterstall_kop_finns(self):
        self._kräver('"Återställ köp"', "återställningsvägen krävs av 3.1.1")

    def test_granskaren_far_en_testvag_i_sandbox(self):
        self._kräver("sandbox", "hur granskaren testar köpet (Sandbox-konto) ska stå",
                     text=_platt().lower())
        self._kräver("Så testar ni köpet", "ett stycke ska leda granskaren genom köpet")

    def test_inga_belopp_ur_app_store_connect(self):
        träff = re.search(r"(?i)\b\d+([.,]\d+)?\s*(kr|kronor|sek)\b", _platt())
        self.assertIsNone(träff, "ett belopp står i noterna - Apples prispunkt hör hemma i "
                                 "App Store Connect, och appen visar StoreKits pris")

    def test_ingen_gratisperiod_pastas(self):
        # J3b (2026-09-19): ingen automatisk trial. En granskare som läser
        # om sju gratisdagar och inte hittar dem har ett skäl att avvisa
        # (2.3, accurate metadata) - och en introductory offer som inte är
        # konfigurerad får inte utlovas.
        text = _platt().lower()
        for fras in ("gratis period", "gratisperiod", "provperiod", "free trial", "trial",
                     "introductory offer", "7 dagar", "sju dagar", "7 days", "seven days"):
            self.assertNotIn(fras, text, f"noterna påstår en gratisperiod: {fras!r}")

    def test_granskningskontots_platshallare_star_kvar(self):
        # Kontot hör hemma i App Store Connect, inte i repot (N0h); men
        # raderna ska finnas, så att Adam ser var de fylls i. Tillåtet är
        # exakt det secret_scan.granskningskontot tillåter: hakparentes,
        # streck eller tomt.
        text = _text()
        for fält in ("E-post", "Lösenord"):
            with self.subTest(fält=fält):
                self.assertIsNotNone(re.search(rf"(?m)^\s*{fält}:\s*(\[.*\]|-*)\s*$", text),
                                     f"raden för granskningskontots {fält.lower()} saknas eller är ifylld")


if __name__ == "__main__":
    unittest.main()
