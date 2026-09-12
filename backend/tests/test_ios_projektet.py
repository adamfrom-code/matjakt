# -*- coding: utf-8 -*-
"""iOS-projektet ska gå att bygga från en ren klon.

Före N1 fanns ingen app. `ios/App/App/` innehöll `capacitor.config.json`,
`config.xml` och `public/` — alltså exakt de filer `cap sync` KOPIERAR IN,
men ingen `.xcodeproj` som kan bygga dem. Någon hade tagit genvägen att
kopiera webbresurser till en katalog som såg ut som ett iOS-projekt.

Det upptäcktes först när Adam skulle lägga upp appen på TestFlight.

Testet vaktar tre saker som var och en gör projektet obyggbart om de faller:

  1. Projektfilen finns. Utan den finns ingen app, hur mycket webbkod som än
     ligger bredvid.
  2. Bundle-identifieraren är se.matjakt.app. Den är registrerad i App Store
     Connect och går ALDRIG att ändra i efterhand - en felstavning här är ett
     nytt app-id och en ny granskning.
  3. Byggutdata är inte spårad. `App/App/public` är 9,4 MB genererade filer
     som `npm run ios:sync` skapar. Spårades de skulle varje frontend-ändring
     ge en diff på tiotusentals rader i iOS-katalogen.
"""

import plistlib
import unittest
from pathlib import Path

ROT = Path(__file__).resolve().parents[2]
PROJEKT = ROT / "ios" / "App" / "App.xcodeproj" / "project.pbxproj"
BUNDLE_ID = "se.matjakt.app"


class IosProjektetGarAttBygga(unittest.TestCase):
    def test_xcode_projektet_finns(self):
        self.assertTrue(
            PROJEKT.is_file(),
            "ios/App/App.xcodeproj saknas - då finns ingen app att bygga, "
            "bara webbfiler i en katalog. Kör `npx cap add ios`.")

    def test_bundle_identifieraren_ar_den_registrerade(self):
        text = PROJEKT.read_text(encoding="utf-8")
        self.assertIn(
            f"PRODUCT_BUNDLE_IDENTIFIER = {BUNDLE_ID}", text,
            f"bundle-id är inte {BUNDLE_ID}. Det är registrerat i App Store "
            f"Connect och går inte att ändra i efterhand.")

    def test_capacitor_configen_bar_samma_id(self):
        import json
        cfg = json.loads((ROT / "capacitor.config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["appId"], BUNDLE_ID,
                         "capacitor.config.json och Xcode-projektet pekar på olika app-id")
        self.assertEqual(cfg["appName"], "Matjakt")

    def test_visningsnamnet_ar_matjakt(self):
        # Namnet under ikonen på telefonen. Skilt från App Store-titeln, som
        # är "Matjakt: matbudget & veckomeny" (store/appstore/metadata).
        info = plistlib.loads((ROT / "ios" / "App" / "App" / "Info.plist").read_bytes())
        self.assertEqual(info.get("CFBundleDisplayName"), "Matjakt")

    def test_byggutdata_ar_inte_sparad(self):
        import subprocess
        sparade = subprocess.run(
            ["git", "ls-files", "ios/App/App/public"], cwd=ROT,
            capture_output=True, text=True).stdout.strip()
        self.assertEqual(
            sparade, "",
            "ios/App/App/public är spårad. Det är 9,4 MB genererade filer som "
            "npm run ios:sync skapar - varje frontend-ändring skulle ge en "
            "diff på tiotusentals rader.")

    def test_webdir_pekar_pa_native_bygget(self):
        import json
        cfg = json.loads((ROT / "capacitor.config.json").read_text(encoding="utf-8"))
        self.assertEqual(
            cfg["webDir"], "dist/native/app",
            "webDir måste peka på native-bygget - det är det som bär "
            "produktionens API-adress och saknar statistikskriptet")


if __name__ == "__main__":
    unittest.main()
