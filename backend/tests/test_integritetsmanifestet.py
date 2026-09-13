"""Integritetsmanifestet beskriver det appen faktiskt samlar in.

Apple jämför tre saker mot varandra: PrivacyInfo.xcprivacy, App
Privacy-etiketten på butikssidan, och integritetspolicyn. Säger de olika
saker blir det en fråga från granskaren, och frågan är dyrare att besvara
än manifestet är att hålla rätt.

Manifestet deklarerade exakt plats som insamlad OCH kopplad till
användaren. Den är ingetdera. "Hitta mig" ger koordinater till
`state.position`, som används till avståndsberäkning mot butikerna och
sedan nollställs - den ingår inte i `buildSyncPayload()`, och kontotabellen
har ingen lat/lon-kolumn. Koordinaterna lämnar aldrig telefonen.

Att överdeklarera är inte den säkra sidan. Det ger "Precise Location -
linked to you" på butikssidan, och det motsäger integritetspolicyn som
(korrekt) säger att positionen inte sparas. En policy som överdriver
insamlingen är lika oriktig som en som underdriver den.

Samtidigt saknades två saker som VERKLIGEN samlas in: produktinteraktion
och hälsouppgifter.

Testerna läser koden, inte manifestet mot sig självt. Börjar positionen
synkas, eller slutar allergierna lagras, faller de - och pekar på
manifestet.
"""

import plistlib
import re
import unittest
from pathlib import Path

ROT = Path(__file__).resolve().parents[2]
MANIFEST = ROT / "ios" / "App" / "App" / "PrivacyInfo.xcprivacy"
APP_STATE = ROT / "frontend" / "app" / "src" / "state" / "app-state.js"


def deklarerade():
    with MANIFEST.open("rb") as f:
        data = plistlib.load(f)
    return {
        d["NSPrivacyCollectedDataType"].replace("NSPrivacyCollectedDataType", ""): d
        for d in data.get("NSPrivacyCollectedDataTypes", [])
    }


def sync_nyttolasten() -> str:
    """Kroppen av buildSyncPayload - det som faktiskt lämnar telefonen."""
    källa = APP_STATE.read_text(encoding="utf-8")
    start = källa.index("export function buildSyncPayload")
    # Fram till nästa toppnivådeklaration.
    nästa = re.search(r"\n(?:export )?function ", källa[start + 1 :])
    slut = start + 1 + nästa.start() if nästa else len(källa)
    return källa[start:slut]


class Integritetsmanifestet(unittest.TestCase):
    def test_manifestet_ar_en_giltig_plist(self):
        with MANIFEST.open("rb") as f:
            plistlib.load(f)

    def test_positionen_lamnar_aldrig_telefonen(self):
        """Därför får exakt plats inte deklareras som insamlad."""
        nyttolast = sync_nyttolasten()
        self.assertNotRegex(
            nyttolast,
            r"\bposition\b|\blat\b|\blon\b",
            "positionen har börjat synkas - då SKA PreciseLocation "
            "deklareras i PrivacyInfo.xcprivacy, och policyn skrivas om",
        )
        self.assertNotIn(
            "PreciseLocation",
            deklarerade(),
            "manifestet deklarerar exakt plats som insamlad, men koden "
            "skickar den aldrig från enheten. Överdeklaration ger "
            '"Precise Location - linked to you" på butikssidan och '
            "motsäger integritetspolicyn.",
        )

    def test_allergier_deklareras_som_halsouppgift(self):
        """Allergier lagras på servern och är artikel 9-data."""
        profil = (ROT / "backend" / "services" / "household" / "store.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("allergies", profil, "allergierna lagras inte längre här")
        d = deklarerade()
        self.assertIn(
            "Health",
            d,
            "allergier lagras i hushållsprofilen på servern - det är "
            "hälsouppgifter (GDPR art. 9) och ska deklareras som Health",
        )
        self.assertTrue(d["Health"]["NSPrivacyCollectedDataTypeLinked"])

    def test_produktinteraktion_deklareras(self):
        """Händelser räknas per konto - alltså kopplade till användaren."""
        api = (ROT / "backend" / "api_server.py").read_text(encoding="utf-8")
        self.assertIn("_handle_analytics_event", api)
        self.assertRegex(
            api,
            r"ANALYTICS\.record\(event,\s*user_id=user_id\)",
            "händelserna räknas inte längre per konto - då är de inte "
            "Linked, och manifestet ska ändras",
        )
        d = deklarerade()
        self.assertIn("ProductInteraction", d)
        self.assertTrue(d["ProductInteraction"]["NSPrivacyCollectedDataTypeLinked"])

    def test_inget_deklareras_som_sparning(self):
        """Tracking kräver ATT-dialogen. Appen spårar inte över appgränser."""
        for namn, d in deklarerade().items():
            with self.subTest(typ=namn):
                self.assertFalse(
                    d["NSPrivacyCollectedDataTypeTracking"],
                    f"{namn} deklareras som tracking - då krävs "
                    "App Tracking Transparency, som appen inte har",
                )


if __name__ == "__main__":
    unittest.main()
