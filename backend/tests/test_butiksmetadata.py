# -*- coding: utf-8 -*-
"""I5: texterna och bilderna som säljer appen i App Store och Google Play.

Tre fynd:

  * **Titeln slösade 23 tecken.** `name.txt` innehöll bara "Matjakt". Titeln
    är den tyngsta ASO-signalen som finns, och 23 outnyttjade tecken är 23
    sökord appen inte rankar på.
  * **Nyckelorden saknade kedjenamn** - ingen "willys", "hemköp", "city
    gross", "matkasse", "handla", "matkonto" - och upprepade i stället ord
    som redan stod i titeln. Apple indexerar titel och undertitel ändå, så
    varje sådan upprepning är ett bortkastat sökord.
  * **Ingen `store/play/`-katalog** trots att `android/` är byggt.

Gränserna nedan är Apples och Googles, inte våra: en text över gränsen
avvisas vid inlämning, och det upptäcks först när någon står där och ska
lämna in. Därför räknas tecknen här i stället.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPSTORE = ROOT / "store" / "appstore" / "metadata" / "sv-SE"
PLAY = ROOT / "store" / "play" / "metadata" / "sv-SE"
SKRIPT = ROOT / "backend" / "scripts" / "make_store_screenshots.py"

# Samma adress som frontend/index.html och de juridiska sidorna (I3).
# support@matjakt.store har ingen vidarebefordran; en kontaktuppgift som
# inte når fram är sämre än en privat som gör det.
KONTAKT = "adamfrom@icloud.com"

# Fält -> max antal tecken. App Store Connect respektive Play Console.
APPSTORE_GRANSER = {
    "name.txt": 30, "subtitle.txt": 30, "keywords.txt": 100,
    "promotional_text.txt": 170, "description.txt": 4000,
}
PLAY_GRANSER = {"title.txt": 30, "short_description.txt": 80, "full_description.txt": 4000}

# De sex skärmarna uppdraget pekar ut, i butiksordning.
SEX_SKARMAR = ("vecka", "handla", "jamforelse", "recept", "skafferi", "sparat")


def läs(fil: Path) -> str:
    return fil.read_text(encoding="utf-8").rstrip("\n")


def ord_i(text: str) -> set[str]:
    return {o for o in re.findall(r"[\wåäöÅÄÖ]+", text.lower()) if len(o) > 2}


class AppStoreTexterna(unittest.TestCase):
    def test_varje_falt_faller_inom_apples_grans(self):
        for namn, gräns in APPSTORE_GRANSER.items():
            fil = APPSTORE / namn
            self.assertTrue(fil.exists(), f"{namn} saknas")
            längd = len(läs(fil))
            self.assertLessEqual(längd, gräns, f"{namn} är {längd} tecken, max {gräns}")

    def test_titeln_anvander_utrymmet(self):
        """"Matjakt" är 7 av 30 tecken. Resten är sökord vi ger bort."""
        titel = läs(APPSTORE / "name.txt")
        self.assertEqual(titel, "Matjakt: matbudget & veckomeny")
        self.assertGreaterEqual(len(titel), 25, "titeln lämnar ASO-utrymme oanvänt")

    def test_undertiteln_sager_vad_appen_gor(self):
        undertitel = läs(APPSTORE / "subtitle.txt")
        self.assertEqual(undertitel, "Riktiga matpriser, din budget")

    def test_nyckelorden_innehaller_kedjorna(self):
        nyckelord = läs(APPSTORE / "keywords.txt")
        for kedja in ("willys", "hemköp", "city gross"):
            self.assertIn(kedja, nyckelord.lower(),
                          f"{kedja} saknas bland nyckelorden - ingen hittar appen på kedjenamnet")
        for sökord in ("matkasse", "handla", "matkonto"):
            self.assertIn(sökord, nyckelord.lower(), f"{sökord} saknas")

    def test_inget_nyckelord_upprepar_titel_eller_undertitel(self):
        """Apple indexerar titel och undertitel ändå. Ett ord som står där
        och upprepas bland nyckelorden är ett bortkastat sökord."""
        redan = ord_i(läs(APPSTORE / "name.txt")) | ord_i(läs(APPSTORE / "subtitle.txt"))
        for nyckelord in läs(APPSTORE / "keywords.txt").split(","):
            for ord in ord_i(nyckelord):
                self.assertNotIn(ord, redan,
                                 f"nyckelordet {nyckelord.strip()!r} upprepar {ord!r} ur titeln")

    def test_nyckelorden_ar_kommaseparerade_utan_slosade_mellanslag(self):
        """Apple räknar mellanslaget efter kommat som ett tecken."""
        nyckelord = läs(APPSTORE / "keywords.txt")
        self.assertNotIn(", ", nyckelord, "mellanslag efter komma slösar tecken")
        self.assertEqual(len(set(nyckelord.split(","))), len(nyckelord.split(",")),
                         "samma nyckelord står två gånger")

    def test_beskrivningen_sager_priset_och_kallan(self):
        beskrivning = läs(APPSTORE / "description.txt")
        for påstående in ("59 kr/mån", "399 kr/år", "Willys", "Hemköp", "City Gross", "Dabas"):
            self.assertIn(påstående, beskrivning, f"beskrivningen saknar {påstående!r}")
        self.assertIn(KONTAKT, beskrivning)

    def test_beskrivningen_lovar_inget_gratislaget_inte_ger(self):
        """Free planerar upp till FREE_MAX_DINNERS middagar. Står det något
        annat i butiken är det appens första löftesbrott."""
        import sys
        sys.path.insert(0, str(ROOT / "backend"))
        from services.accounts import features
        beskrivning = läs(APPSTORE / "description.txt")
        self.assertIn("fyra middagar", beskrivning.lower())
        self.assertEqual(features.FREE_MAX_DINNERS, 4,
                         "gratisgränsen har ändrats - butikstexten säger fortfarande fyra")
        self.assertIn("sju middagar", beskrivning.lower())
        self.assertEqual(features.PREMIUM_MAX_DINNERS, 7)


class PlayTexterna(unittest.TestCase):
    """Ingen store/play/-katalog fanns, trots att android/ är byggt."""

    def test_katalogen_finns_med_de_falt_play_kraver(self):
        for namn in (*PLAY_GRANSER, "privacy_url.txt", "contact_email.txt"):
            self.assertTrue((PLAY / namn).exists(), f"store/play/.../{namn} saknas")

    def test_varje_falt_faller_inom_googles_grans(self):
        for namn, gräns in PLAY_GRANSER.items():
            längd = len(läs(PLAY / namn))
            self.assertLessEqual(längd, gräns, f"{namn} är {längd} tecken, max {gräns}")

    def test_play_och_app_store_sager_samma_sak(self):
        self.assertEqual(läs(PLAY / "title.txt"), läs(APPSTORE / "name.txt"))
        self.assertEqual(läs(PLAY / "full_description.txt"), läs(APPSTORE / "description.txt"))

    def test_kontaktvagarna_pekar_pa_domanen(self):
        self.assertEqual(läs(PLAY / "contact_email.txt"), KONTAKT)
        self.assertTrue(läs(PLAY / "privacy_url.txt").startswith("https://matjakt.store/"))


class KontaktadressenArSammaOveralltOchGarFram(unittest.TestCase):
    """support@matjakt.store ser bättre ut i en butikslistning, men har ingen
    vidarebefordran - ett mejl dit hamnar ingenstans. Google mejlar
    contact_email vid policybeslut och avslag; en död adress DÄR är den
    dyraste av alla ställen att ha en. Tills brevlådan finns gäller samma
    adress som på matjakt.store (I3).

    Det som testas är inte vilken adress det är, utan att det är EN adress.
    Dagen domänadressen får en mottagare byts alla fem ställena på en gång
    och konstanten här med."""

    def test_butiken_och_webben_sager_samma_adress(self):
        från_sajten = re.findall(r"mailto:([^\"'<>\s]+)",
                                 (ROOT / "frontend" / "index.html").read_text(encoding="utf-8"))
        self.assertTrue(från_sajten, "landningssidan har ingen kontaktadress alls")
        self.assertEqual(set(från_sajten), {KONTAKT},
                         "landningssidan och butikstexterna pekar på olika adresser")

    def test_ingen_butikstext_utlovar_en_brevlada_som_inte_finns(self):
        for katalog in (APPSTORE, PLAY):
            for fil in sorted(katalog.glob("*.txt")):
                self.assertNotIn("support@matjakt.store", läs(fil),
                                 f"{fil.name} pekar på en adress utan mottagare")


class Skarmbilderna(unittest.TestCase):
    """Skärmbilder är det enskilt mest konverterande i en butikslistning, och
    katalogen innehöll bara textfiler. Bilderna byggs av ett skript i stället
    för att ligga i git: de är genererade, väger megabyte och byter innehåll
    varje gång appens utseende ändras.

    Testet prövar generatorns SPECIFIKATION, inte bilderna. Att köra
    Playwright mot en fixturserver hör hemma i e2e-jobbet, inte i den svit
    som ska vara klar på två minuter."""

    def setUp(self):
        self.källa = SKRIPT.read_text(encoding="utf-8")

    def test_generatorn_finns(self):
        self.assertTrue(SKRIPT.exists())

    def test_alla_sex_skarmar_ingar(self):
        träff = re.search(r"SCENER = \(([^)]*)\)", self.källa)
        self.assertIsNotNone(träff, "SCENER saknas i generatorn")
        scener = tuple(re.findall(r'"([a-zå-ö]+)"', träff.group(1)))
        self.assertEqual(scener, SEX_SKARMAR,
                         "generatorn bygger inte precis de sex skärmarna i butiksordning")

    def test_matten_ar_de_butikerna_kraver(self):
        """En skalad skärmdump med fel mått avvisas vid inlämning. Måtten
        räknas som viewport x skalfaktor, så de kontrolleras som produkt."""
        rader = re.findall(r'\("([\w.-]+)", (\w+), (\d+), (\d+), (\d+)\)', self.källa)
        mått = {namn: (int(b) * int(s), int(h) * int(s)) for namn, _, b, h, s in rader}
        self.assertEqual(mått.get("iphone-6.7"), (1290, 2796), "6,7\" måste vara 1290x2796")
        self.assertEqual(mått.get("iphone-6.5"), (1242, 2688), "6,5\" måste vara 1242x2688")
        self.assertEqual(mått.get("telefon"), (1080, 1920), "Play vill ha minst 1080 px bredd")

    def test_bilderna_skrivs_bara_till_gitignorerade_kataloger(self):
        """Arton PNG:er på några megabyte hör inte i ett repo vars .git redan
        är 191 MB. Skriptet får skriva dem, git får inte ta emot dem."""
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for katalog in ("store/appstore/screenshots/", "store/play/screenshots/"):
            self.assertIn(katalog, gitignore, f"{katalog} är inte gitignorerad")
            self.assertIn(katalog.split("/")[1], self.källa)

    def test_skriptet_sager_ifran_nar_en_skarm_inte_gick_att_na(self):
        """En butikslistning med fem av sex bilder är inte klar att lämna in,
        och ett skript som tyst hoppar över en scen döljer just det."""
        self.assertIn("Saknade scener", self.källa)
        self.assertIn("return 1", self.källa)


if __name__ == "__main__":
    unittest.main()
