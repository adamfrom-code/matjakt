# -*- coding: utf-8 -*-
"""N0k: privacy-manifestet ska deklarera det koden faktiskt gör.

Apple läser tre dokument om samma sak och jämför dem med varandra:
`PrivacyInfo.xcprivacy` i bundlen, App Privacy-etiketten i App Store
Connect och integritetspolicyn som `privacy_url.txt` pekar på. En
motsägelse mellan dem är inte ett skrivfel - det är en anledning till
avslag, och den upptäcks efter att arkivet är uppladdat.

DÄRFÖR ÄR DET HÄR ETT TEST OCH INTE EN GRANSKNING. Manifestet är en
fritextfil som ingen kompilator läser; den kan stå kvar och vara osann i
år. Varje deklaration nedan är knuten till den rad i koden som gör
påståendet sant, och varje kodfakta som TVINGAR fram en deklaration
kontrolleras åt andra hållet. Börjar appen spara koordinater, slutar den
fråga efter allergier eller får mätningen en ny tabell failar det här
testet tills manifestet följt med.

APPLES DEFINITION AV "COLLECT" ÄR HELA NYCKELN, och den är snävare än
ordet låter (developer.apple.com/app-store/app-privacy-details/):

    "Collect" refers to transmitting data off the device in a way that
    allows you and/or your third-party partners to access it for a period
    longer than what is necessary to service the transmitted request in
    real time.

Data som aldrig lämnar enheten samlas alltså inte in i Apples mening. Det
är precis vad som gäller koordinaterna från "Hitta mig" - se
`PlatsenDeklarerasSomKodenFaktisktGor` - och det var därför det gamla
manifestet hade fel när det deklarerade exakt plats som kopplad till
användaren.

TVÅ FILER, INTE EN. `scripts/ios_mac_pass.sh` kopierar
`ios-prep/PrivacyInfo.xcprivacy` över `ios/App/App/PrivacyInfo.xcprivacy`
vid varje Mac-pass. Rättas bara den ena är rättelsen borta nästa gång
skriptet körs, tyst. `ManifestenArIdentiska` är grinden mot det.
"""

import plistlib
import re
import unittest
from pathlib import Path

ROT = Path(__file__).resolve().parents[2]
MANIFEST = ROT / "ios" / "App" / "App" / "PrivacyInfo.xcprivacy"
KALLA = ROT / "ios-prep" / "PrivacyInfo.xcprivacy"
ETIKETT = ROT / "ios-prep" / "APP_PRIVACY_LABEL.md"

APP_STATE = ROT / "frontend" / "app" / "src" / "state" / "app-state.js"
KONTOSTORE = ROT / "backend" / "services" / "accounts" / "store.py"
HUSHALLSTORE = ROT / "backend" / "services" / "household" / "store.py"
ANALYSSTORE = ROT / "backend" / "services" / "analytics" / "store.py"


def manifest() -> dict:
    return plistlib.loads(MANIFEST.read_bytes())


def deklarerade() -> dict:
    """Deklarationerna nyckelsatta på datatyp."""
    return {d["NSPrivacyCollectedDataType"]: d
            for d in manifest().get("NSPrivacyCollectedDataTypes", [])}


def sync_payload() -> str:
    """Kroppen av buildSyncPayload() - det ENDA som lämnar enheten.

    persistLocally() skriver den till localStorage och scheduleServerSync()
    POSTar den till /api/account/state, där den landar i users.synced_state.
    Ett fält som inte står här finns inte utanför JS-minnet."""
    källa = APP_STATE.read_text(encoding="utf-8")
    träff = re.search(r"export function buildSyncPayload[^{]*\{(.*?)\n\}", källa, flags=re.S)
    assert träff, "buildSyncPayload() finns inte längre i app-state.js - testet måste skrivas om"
    return träff.group(1)


# Apples egen lista över tillåtna värden, hämtad 2026-09-13 ur
# developer.apple.com/documentation/bundleresources/app-privacy-configuration/
# nsprivacycollecteddatatypes/nsprivacycollecteddatatype (och .../purposes).
# Xcode genererar INGEN privacy-rapport om ett egenpåhittat värde smyger in,
# och felet syns först när arkivet redan är byggt.
APPLES_DATATYPER = frozenset({
    "NSPrivacyCollectedDataTypeName", "NSPrivacyCollectedDataTypeEmailAddress",
    "NSPrivacyCollectedDataTypePhoneNumber", "NSPrivacyCollectedDataTypePhysicalAddress",
    "NSPrivacyCollectedDataTypeOtherUserContactInfo", "NSPrivacyCollectedDataTypeHealth",
    "NSPrivacyCollectedDataTypeFitness", "NSPrivacyCollectedDataTypePaymentInfo",
    "NSPrivacyCollectedDataTypeCreditInfo", "NSPrivacyCollectedDataTypeOtherFinancialInfo",
    "NSPrivacyCollectedDataTypePreciseLocation", "NSPrivacyCollectedDataTypeCoarseLocation",
    "NSPrivacyCollectedDataTypeSensitiveInfo", "NSPrivacyCollectedDataTypeContacts",
    "NSPrivacyCollectedDataTypeEmailsOrTextMessages", "NSPrivacyCollectedDataTypePhotosorVideos",
    "NSPrivacyCollectedDataTypeAudioData", "NSPrivacyCollectedDataTypeGameplayContent",
    "NSPrivacyCollectedDataTypeCustomerSupport", "NSPrivacyCollectedDataTypeOtherUserContent",
    "NSPrivacyCollectedDataTypeBrowsingHistory", "NSPrivacyCollectedDataTypeSearchHistory",
    "NSPrivacyCollectedDataTypeUserID", "NSPrivacyCollectedDataTypeDeviceID",
    "NSPrivacyCollectedDataTypePurchaseHistory", "NSPrivacyCollectedDataTypeProductInteraction",
    "NSPrivacyCollectedDataTypeAdvertisingData", "NSPrivacyCollectedDataTypeOtherUsageData",
    "NSPrivacyCollectedDataTypeCrashData", "NSPrivacyCollectedDataTypePerformanceData",
    "NSPrivacyCollectedDataTypeOtherDiagnosticData", "NSPrivacyCollectedDataTypeEnvironmentScanning",
    "NSPrivacyCollectedDataTypeHands", "NSPrivacyCollectedDataTypeHead",
    "NSPrivacyCollectedDataTypeOtherDataTypes",
})
APPLES_ANDAMAL = frozenset({
    "NSPrivacyCollectedDataTypePurposeThirdPartyAdvertising",
    "NSPrivacyCollectedDataTypePurposeDeveloperAdvertising",
    "NSPrivacyCollectedDataTypePurposeAnalytics",
    "NSPrivacyCollectedDataTypePurposeProductPersonalization",
    "NSPrivacyCollectedDataTypePurposeAppFunctionality",
    "NSPrivacyCollectedDataTypePurposeOther",
})


# ── Paketets acceptanskriterium ─────────────────────────────────────────
#
# Deklarerar manifestet att en uppgift samlas in, ska det gå att PEKA UT
# var den lagras. Formatet är (datatyp, fil, textbit som måste finnas där,
# vad raden bevisar). Textbiten är avsiktligt en sträng ur källan och inte
# en omskrivning: byter kolumnen namn eller försvinner fältet ur payloaden
# failar raden, och då är deklarationen inte längre belagd.
#
# Tabellen är UTTÖMMANDE åt båda håll. En deklaration utan rad här är en
# deklaration ingen kan försvara inför Apple; en rad utan deklaration är en
# kvarglömd rad efter att en uppgift slutat samlas in.
BEVIS: tuple[tuple[str, Path, str, str], ...] = (
    ("NSPrivacyCollectedDataTypeEmailAddress", KONTOSTORE, "email TEXT UNIQUE NOT NULL",
     "users.email - kontots inloggning"),
    ("NSPrivacyCollectedDataTypeCoarseLocation", APP_STATE, "postnummer: state.postnummer",
     "postnumret följer med synkpayloaden till users.synced_state"),
    ("NSPrivacyCollectedDataTypeHealth", APP_STATE, "avoidAllergens: [...state.kost.avoidAllergens]",
     "allergier och kosttyp i synkpayloaden - artikel 9 i policyn"),
    ("NSPrivacyCollectedDataTypeHealth", HUSHALLSTORE, '"allergies", "dislikes"',
     "hushållsprofilens allergier, delade med familjen"),
    ("NSPrivacyCollectedDataTypeProductInteraction", ANALYSSTORE, "analytics_user_days",
     "konto x dag x händelse - mätningen är kopplad till kontot"),
    ("NSPrivacyCollectedDataTypePurchaseHistory", KONTOSTORE, '("subscription_plan", "TEXT")',
     "vilken Premium-plan kontot köpt"),
)


class VarjeInsamladUppgiftGarAttPekaUt(unittest.TestCase):
    """N0k:s acceptanskriterium. Se BEVIS ovan."""

    def test_varje_deklaration_har_ett_bevis_i_koden(self):
        belagda = {rad[0] for rad in BEVIS}
        for datatyp in deklarerade():
            self.assertIn(
                datatyp, belagda,
                f"{datatyp} deklareras i manifestet men har ingen rad i BEVIS - "
                "gå inte vidare förrän du kan peka ut var uppgiften lagras")

    def test_varje_bevis_pekar_pa_en_deklaration(self):
        deklarationer = set(deklarerade())
        for datatyp, _, _, varfor in BEVIS:
            self.assertIn(
                datatyp, deklarationer,
                f"BEVIS bär {datatyp} ({varfor}) men manifestet deklarerar den inte - "
                "antingen ska deklarationen tillbaka eller raden bort")

    def test_varje_bevis_finns_kvar_i_sin_kalla(self):
        for datatyp, fil, nal, varfor in BEVIS:
            with self.subTest(datatyp=datatyp, fil=fil.name):
                self.assertIn(
                    nal, fil.read_text(encoding="utf-8"),
                    f"{fil.relative_to(ROT)} innehåller inte längre {nal!r}. Det var beviset "
                    f"för att {datatyp} samlas in ({varfor}). Ändrades lagringen ska "
                    "manifestet ändras med den.")


class ManifestenArIdentiska(unittest.TestCase):
    """`ios_mac_pass.sh` kopierar ios-prep över ios/App/App vid varje pass.

    Rättas bara en av filerna försvinner rättelsen nästa gång någon kör
    skriptet - utan ett felmeddelande, för kopieringen lyckas."""

    def test_bundlens_manifest_ar_samma_fil_som_kallan(self):
        self.assertEqual(
            KALLA.read_text(encoding="utf-8"), MANIFEST.read_text(encoding="utf-8"),
            "ios-prep/PrivacyInfo.xcprivacy och ios/App/App/PrivacyInfo.xcprivacy skiljer sig. "
            "scripts/ios_mac_pass.sh kopierar den första över den andra - ändra båda.")


class ManifestetTalarApplesSprak(unittest.TestCase):
    """Egenpåhittade värden gör att Xcode inte kan generera någon
    privacy-rapport alls, och det märks först när arkivet är byggt."""

    def test_datatyperna_finns_hos_apple(self):
        for datatyp in deklarerade():
            self.assertIn(datatyp, APPLES_DATATYPER,
                          f"{datatyp} är inget värde Apple känner igen")

    def test_andamalen_finns_hos_apple(self):
        for datatyp, d in deklarerade().items():
            ändamål = d.get("NSPrivacyCollectedDataTypePurposes") or []
            self.assertTrue(ändamål, f"{datatyp} saknar ändamål")
            for syfte in ändamål:
                self.assertIn(syfte, APPLES_ANDAMAL, f"{syfte} är inget värde Apple känner igen")

    def test_varje_deklaration_har_bada_boolerna(self):
        for datatyp, d in deklarerade().items():
            for nyckel in ("NSPrivacyCollectedDataTypeLinked", "NSPrivacyCollectedDataTypeTracking"):
                self.assertIsInstance(d.get(nyckel), bool, f"{datatyp} saknar {nyckel}")

    def test_ingenting_deklareras_som_sparning(self):
        # Appen har inga tredjeparts-SDK:er, ingen reklam och inget
        # annonsnätverk. Sätts någon av flaggorna nedan krävs ATT-dialog
        # (AppTrackingTransparency) innan en enda rad får skickas.
        d = manifest()
        self.assertIs(d.get("NSPrivacyTracking"), False)
        self.assertEqual(d.get("NSPrivacyTrackingDomains"), [])
        for datatyp, rad in deklarerade().items():
            self.assertIs(rad.get("NSPrivacyCollectedDataTypeTracking"), False,
                          f"{datatyp} deklareras som spårning - då krävs ATT-dialogen")


class PlatsenDeklarerasSomKodenFaktisktGor(unittest.TestCase):
    """Manifestet deklarerade exakt plats, kopplad till användaren. Appen
    lagrar ingen plats alls - bara postnumret.

    `state.position` sätts av "Hitta mig" (app.js) och av geokodningen av
    postnumret, men ingår inte i `buildSyncPayload()`. Koordinaterna lever i
    JS-minnet under sessionen och tar aldrig vägen till localStorage, till
    /api/account/state eller till en kolumn i `users`. Avståndsräkningen
    sker i klienten: servern skickar butikernas koordinater till enheten,
    aldrig tvärtom.

    Enligt Apples definition av "collect" - se modulens docstring - samlas
    de alltså inte in, och NSPrivacyCollectedDataTypePreciseLocation ska
    inte stå i manifestet.

    Postnumret är en annan sak. Det ligger i synkpayloaden, det landar i
    users.synced_state och det stannar där. Ett femsiffrigt postnummer
    beskriver var någon bor med LÄGRE upplösning än lat/lon med tre
    decimaler, vilket är exakt Apples gräns mellan Precise och Coarse
    Location. Det är alltså insamlat, och det är grovt."""

    def test_koordinaterna_lamnar_inte_enheten(self):
        self.assertNotIn(
            "position", sync_payload(),
            "position ingår nu i synkpayloaden - då LÄMNAR koordinaterna enheten, "
            "och de ska deklareras som NSPrivacyCollectedDataTypePreciseLocation igen")
        konto = KONTOSTORE.read_text(encoding="utf-8")
        for kolumn in ('"latitude"', '"longitude"', '("lat"', '("lon"'):
            self.assertNotIn(kolumn, konto,
                             f"users bär nu {kolumn} - manifestet måste skrivas om")

    def test_exakt_plats_deklareras_inte(self):
        self.assertNotIn(
            "NSPrivacyCollectedDataTypePreciseLocation", deklarerade(),
            "manifestet deklarerar exakt plats, men koordinaterna lämnar aldrig enheten. "
            "En etikett som ÖVERDRIVER insamlingen är lika oriktig som en som underdriver.")

    def test_postnumret_deklareras_som_grov_plats(self):
        self.assertIn("postnummer: state.postnummer", sync_payload(),
                      "postnumret ingår inte längre i synken - då ska grov plats bort")
        d = deklarerade().get("NSPrivacyCollectedDataTypeCoarseLocation")
        self.assertIsNotNone(
            d, "postnumret följer med till users.synced_state och stannar där. Det är "
               "grov plats i Apples mening och ska deklareras.")
        self.assertIs(d["NSPrivacyCollectedDataTypeLinked"], True,
                      "postnumret ligger på kontoraden - det är kopplat till användaren")

    def test_kommentaren_pastar_inte_att_positionen_sparas(self):
        for fil in (MANIFEST, KALLA):
            with self.subTest(fil=fil.name):
                text = fil.read_text(encoding="utf-8")
                self.assertNotRegex(
                    text, r"sparas i profilen som\s+lat/lon",
                    f"{fil.name}: kommentaren säger att positionen sparas i profilen. "
                    "Den sparas inte alls - och kommentaren är det första en granskare läser.")
                # Och den ska säga det åt rätt håll. Kommentaren är den enda
                # förklaringen en granskare får till varför exakt plats SAKNAS
                # i en app som ber om platsbehörighet.
                self.assertIn(
                    "KOORDINATERNA LÄMNAR ALDRIG ENHETEN", text,
                    f"{fil.name}: kommentaren förklarar inte varför exakt plats inte "
                    "deklareras, trots att appen har NSLocationWhenInUseUsageDescription")


class HalsouppgifterDeklareras(unittest.TestCase):
    """Allergier och kosttyp lämnar enheten på TVÅ vägar, och ingen av dem
    stod i manifestet.

    Den ena är kontots egen synk: `kost.kosttyp` och `kost.avoidAllergens`
    ligger i `buildSyncPayload()` och landar i `users.synced_state`. Den
    andra är hushållsprofilen, där `allergies` delas med varje medlem i
    hushållet.

    Integritetspolicyn säger att allergier och kosttyp "säger något om din
    hälsa" och behandlar dem som artikel 9-uppgifter med uttryckligt
    samtycke. Etiketten som säger att appen inte samlar in hälsodata
    motsäger alltså appens egen policy, och det är den sortens motsägelse
    Apple letar efter."""

    def test_kosten_ligger_i_synkpayloaden(self):
        kropp = sync_payload()
        self.assertIn("kosttyp: state.kost.kosttyp", kropp)
        self.assertIn("avoidAllergens: [...state.kost.avoidAllergens]", kropp)

    def test_halsa_deklareras_och_ar_kopplad_till_kontot(self):
        d = deklarerade().get("NSPrivacyCollectedDataTypeHealth")
        self.assertIsNotNone(
            d, "allergier och kosttyp lagras på kontot och i hushållsprofilen, men "
               "manifestet deklarerar ingen hälsodata")
        self.assertIs(d["NSPrivacyCollectedDataTypeLinked"], True,
                      "uppgifterna ligger på kontoraden respektive hushållsmedlemmen")


class ProduktinteraktionDeklareras(unittest.TestCase):
    """Mätningen räknar namngivna händelser PER KONTO och dag.

    `analytics_user_days` är konto x dag x händelse, och `trackEvent()` i
    app.js skickar sessionens token med varje händelse när någon är
    inloggad. Det är "Product Interaction" i Apples mening - "app launches,
    taps, clicks (...) or other information about how the user interacts
    with the app" - och det är kopplat till användaren.

    Ändamålet är Analytics, inte App Functionality: tabellen finns för att
    besvara om någon kommer tillbaka vecka två, inte för att appen ska
    fungera."""

    def test_handelserna_rakas_per_konto(self):
        källa = ANALYSSTORE.read_text(encoding="utf-8")
        self.assertIn("analytics_user_days", källa)
        self.assertIn("ANALYTICS_EVENTS = frozenset({", källa)
        self.assertRegex(källa, r"INSERT INTO analytics_user_days \(user_id, day, event",
                         "mätningen skriver inte längre per konto - då kan deklarationen omprövas")

    def test_produktinteraktion_deklareras_med_ratt_andamal(self):
        d = deklarerade().get("NSPrivacyCollectedDataTypeProductInteraction")
        self.assertIsNotNone(
            d, "analytics_user_days räknar namngivna händelser per konto och dag, men "
               "manifestet deklarerar ingen produktinteraktion")
        self.assertIs(d["NSPrivacyCollectedDataTypeLinked"], True,
                      "raderna bär user_id - de är kopplade till användaren")
        self.assertIn("NSPrivacyCollectedDataTypePurposeAnalytics",
                      d["NSPrivacyCollectedDataTypePurposes"],
                      "tabellen finns för att mäta beteende, inte för att appen ska fungera")


class EtikettenSpeglarManifestet(unittest.TestCase):
    """App Privacy-etiketten fylls i för hand i App Store Connect och finns
    inte i repot. `ios-prep/APP_PRIVACY_LABEL.md` är svaren som ska skrivas
    in, och det här testet håller dem mot manifestet - annars driver de isär
    i samma sekund som någon ändrar det ena."""

    def test_etikettfilen_listar_exakt_manifestets_datatyper(self):
        self.assertTrue(ETIKETT.is_file(),
                        "ios-prep/APP_PRIVACY_LABEL.md saknas - då finns etikettsvaren "
                        "bara i huvudet på den som fyller i dem")
        text = ETIKETT.read_text(encoding="utf-8")
        nämnda = set(re.findall(r"NSPrivacyCollectedDataType[A-Za-z]+", text))
        nämnda &= APPLES_DATATYPER
        self.assertEqual(
            nämnda, set(deklarerade()),
            "etikettfilen och manifestet räknar upp olika uppgifter - "
            "Apple jämför dem med varandra")


if __name__ == "__main__":
    unittest.main()
