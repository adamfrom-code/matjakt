# -*- coding: utf-8 -*-
"""Info.plist-nycklarna och privacy-manifestet, prövade mot KÄLLAN.

`ios-prep/` bar sedan september en färdig lista över nycklar och ett
PrivacyInfo.xcprivacy - förberedda på Windows med kommentaren "kan inte
verifieras utan Xcode". De låg alltså rätt men utanför bygget.

N0c applicerade dem. Det här testet ser till att de blir kvar: `npx cap
sync ios` skriver inte över Info.plist, men `npx cap add ios` genererar den
på nytt, och då försvinner varje nyckel som inte står i Capacitors mall.

Två av nycklarna är inte kosmetik:

  NSLocationWhenInUseUsageDescription  - utan den KRASCHAR appen i samma
      stund användaren trycker "Hitta mig". iOS avslutar processen när ett
      behörighetsanrop saknar sin förklaringstext.
  PrivacyInfo.xcprivacy                - App Store avvisar inlämningar utan
      privacy-manifest sedan våren 2024.

Byggkontrollen (att filerna faktiskt hamnar i app-bundlen) görs av
`scripts/ios_pbxproj_add_file.mjs --verify` och av xcodebuild, inte här -
de kräver Xcode och kan inte köras i CI.
"""

import plistlib
import unittest
from pathlib import Path

ROT = Path(__file__).resolve().parents[2]
INFO = ROT / "ios" / "App" / "App" / "Info.plist"
PRIVACY = ROT / "ios" / "App" / "App" / "PrivacyInfo.xcprivacy"
PBXPROJ = ROT / "ios" / "App" / "App.xcodeproj" / "project.pbxproj"


class InfoPlistBarNycklarnaAppenBehover(unittest.TestCase):
    def setUp(self):
        self.info = plistlib.loads(INFO.read_bytes())

    def test_platsforklaringen_finns(self):
        # Utan den kraschar appen vid "Hitta mig" - iOS avslutar processen
        # när ett behörighetsanrop saknar sin text.
        text = self.info.get("NSLocationWhenInUseUsageDescription", "")
        self.assertTrue(text, "NSLocationWhenInUseUsageDescription saknas - appen kraschar vid Hitta mig")
        self.assertIn("plats", text.lower(),
                      "förklaringen ska säga vad platsen används TILL, på svenska")

    def test_visningsnamnet_ar_matjakt(self):
        self.assertEqual(self.info.get("CFBundleDisplayName"), "Matjakt")

    def test_exportfragan_ar_besvarad(self):
        # Appen använder bara systemets TLS. Utan nyckeln måste frågan
        # besvaras för hand vid VARJE uppladdning.
        self.assertIs(self.info.get("ITSAppUsesNonExemptEncryption"), False)

    def test_svenska_ar_utvecklingsspraket(self):
        self.assertEqual(self.info.get("CFBundleDevelopmentRegion"), "sv")

    def test_bara_staende_lage(self):
        self.assertEqual(self.info.get("UISupportedInterfaceOrientations"),
                         ["UIInterfaceOrientationPortrait"],
                         "layouten är byggd för mobil på höjden")

    def test_djuplankschemat_finns(self):
        typer = self.info.get("CFBundleURLTypes") or []
        scheman = [s for t in typer for s in (t.get("CFBundleURLSchemes") or [])]
        self.assertIn("matjakt", scheman,
                      "matjakt:// behövs för att testa djuplänkar utan Team-ID")


class PrivacyManifestet(unittest.TestCase):
    def test_filen_finns_och_ar_giltig(self):
        self.assertTrue(PRIVACY.is_file(),
                        "PrivacyInfo.xcprivacy saknas - App Store avvisar inlämningen")
        plistlib.loads(PRIVACY.read_bytes())

    def test_appen_deklarerar_att_den_inte_sparar(self):
        d = plistlib.loads(PRIVACY.read_bytes())
        self.assertIs(d.get("NSPrivacyTracking"), False)
        self.assertEqual(d.get("NSPrivacyTrackingDomains"), [])

    def test_manifestet_ligger_i_targetets_resources(self):
        # En fil som bara ligger på disk hamnar ALDRIG i app-bundlen.
        self.assertIn("PrivacyInfo.xcprivacy", PBXPROJ.read_text(encoding="utf-8"),
                      "manifestet är inte med i Xcode-targetet - kör "
                      "scripts/ios_pbxproj_add_file.mjs")


class Versionerna(unittest.TestCase):
    def test_marketing_och_build_version(self):
        t = PBXPROJ.read_text(encoding="utf-8")
        self.assertIn("MARKETING_VERSION = 1.0;", t)
        self.assertIn("CURRENT_PROJECT_VERSION = 1;", t)


if __name__ == "__main__":
    unittest.main()
