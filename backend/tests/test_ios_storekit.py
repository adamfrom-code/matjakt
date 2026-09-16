# -*- coding: utf-8 -*-
"""P02d: StoreKit-pluginet ska ingå i iOS-projektet - i den form Capacitor
själv skriver, och ingen annan.

`@capgo/native-purchases` är StoreKit 2-vägen appen köper Premium genom
(docs/IAP_COMPLIANCE.md, C4). Det som gör att den faktiskt kompileras in i
appen är två rader i `ios/App/CapApp-SPM/Package.swift` - filen som
`npx cap sync ios` genererar ur package.json och som "DO NOT MODIFY" står
överst i. Saknas paketet i package.json skriver nästa `cap sync` bort det
ur Package.swift; saknas det i Package.swift utan att någon kört sync är
Xcode-projektet ett annat än det package.json beskriver.

Testet vaktar att de två är i takt, och att produkt-id:na appen köper är
exakt de servern annonserar - strängarna i features.PRICING, som P02a band
dokumentet till och P02c band servern till.
"""

import json
import re
import sys
import unittest
from pathlib import Path

HÄR = Path(__file__).resolve().parent
sys.path.insert(0, str(HÄR.parent))

from services.accounts import features  # noqa: E402

ROT = HÄR.parents[1]
PACKAGE_SWIFT = ROT / "ios" / "App" / "CapApp-SPM" / "Package.swift"
PACKAGE_JSON = ROT / "package.json"
PLUGIN = "@capgo/native-purchases"


class StoreKitPluginetArInkopplat(unittest.TestCase):
    def test_pluginet_star_i_package_json_med_capacitor_8(self):
        deps = json.loads(PACKAGE_JSON.read_text(encoding="utf-8")).get("dependencies", {})
        self.assertIn(PLUGIN, deps, f"{PLUGIN} saknas i package.json")
        self.assertRegex(deps[PLUGIN], r"^\^8\.", "pluginets major ska följa Capacitors (8)")
        self.assertRegex(deps.get("@capacitor/core", ""), r"^\^8\.")

    def test_package_swift_bar_pluginet_som_cap_sync_skriver_det(self):
        text = PACKAGE_SWIFT.read_text(encoding="utf-8")
        self.assertIn('.package(name: "CapgoNativePurchases", path: "../../../node_modules/@capgo/native-purchases")',
                      text, "CapgoNativePurchases saknas bland beroendena - kör `npx cap sync ios`")
        self.assertIn('.product(name: "CapgoNativePurchases", package: "CapgoNativePurchases")', text,
                      "CapgoNativePurchases saknas i target-listan")
        self.assertIn("DO NOT MODIFY THIS FILE", text, "filen är inte längre den Capacitor genererar")

    def test_de_tre_gamla_pluginen_star_kvar(self):
        text = PACKAGE_SWIFT.read_text(encoding="utf-8")
        for namn in ("CapacitorApp", "CapacitorBrowser", "CapacitorKeyboard"):
            self.assertIn(f'.product(name: "{namn}"', text, f"{namn} försvann ur Package.swift")

    def test_appen_koper_exakt_serverns_produkter(self):
        # Appen hårdkodar inga produkt-id:n: den läser apple.products ur
        # /api/entitlements. Men ingen sträng som ser ut som ett av våra
        # produkt-id:n får finnas i frontend utan att vara serverns.
        kända = {plan["storekitProductId"] for plan in features.PRICING.values()}
        for fil in (ROT / "frontend" / "app").rglob("*.js"):
            for träff in set(re.findall(r"se\.matjakt\.premium\.[a-z]+", fil.read_text(encoding="utf-8"))):
                self.assertIn(träff, kända, f"{fil.name} bär ett produkt-id som inte finns i features.PRICING")


if __name__ == "__main__":
    unittest.main()
