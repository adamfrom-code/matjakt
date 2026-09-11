# -*- coding: utf-8 -*-
"""I1: landningssidan är återkopplad, inte bara närvarande.

matjakt.store var 52 rader - en rubrik, en mening och en knapp - medan en
komplett landningssidas CSS och en filmad presentation på sju klipp låg
obrukade i repot. `e70a9a8` gjorde sajten till en låsskärm, `9c1898d`
öppnade appen igen, men landningssidan återställdes aldrig.

Det som prövas här är därför INKOPPLINGEN, inte utseendet:

  1. sidan refererar faktiskt styles.css och site-video.js,
  2. varje klipp och stillbild den pekar på finns på disk,
  3. de element site-video.js letar efter finns i markupen,
  4. copyn står ordagrant som den är skriven,
  5. sajten och appen delar designsystem (docs/DESIGNSYSTEM-D.md).

En sida som "ser klar ut" men laddar en CSS som inte finns, eller pekar på
en mp4 som 404:ar, är exakt det fel som inte syns i en kodgranskning och
alltid syns för en besökare.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "frontend" / "index.html"
STYLES = ROOT / "frontend" / "styles.css"
VIDEO_JS = ROOT / "frontend" / "site-video.js"
CLIPS = ROOT / "frontend" / "site" / "video" / "clips.json"


def index_html() -> str:
    return INDEX.read_text(encoding="utf-8")


class MaterialetArInkopplat(unittest.TestCase):
    """Fyndet i I1, ordagrant: "refererar varken styles.css eller
    site-video.js (verifierat: noll träffar)"."""

    def test_sidan_laddar_landningssidans_css(self):
        html = index_html()
        self.assertRegex(html, r'<link rel="stylesheet" href="styles\.css(\?v=\d+)?">',
                         "index.html laddar inte frontend/styles.css")
        self.assertTrue(STYLES.exists())

    def test_sidan_laddar_filmskriptet(self):
        html = index_html()
        self.assertRegex(html, r'<script src="site-video\.js(\?v=\d+)?" defer></script>',
                         "index.html laddar inte site-video.js")
        self.assertTrue(VIDEO_JS.exists())

    def test_varje_klipp_och_stillbild_sidan_pekar_pa_finns(self):
        """En scen vars mp4 404:ar renderas som en tom platta. Det är det
        enda felet i den här filen som besökaren garanterat ser."""
        referenser = set(re.findall(r'(?:data-film-src|poster)="(site/video/[^"]+)"', index_html()))
        self.assertGreaterEqual(len(referenser), 8, "hittade nästan inga klipp i markupen")
        for relativ in sorted(referenser):
            self.assertTrue((ROOT / "frontend" / relativ).exists(), f"{relativ} saknas på disk")

    def test_elementen_site_video_js_letar_efter_finns(self):
        """Skriptet frågar efter [data-hero-clip] och [data-film-src]. Byter
        markupen namn laddas ingenting, helt tyst."""
        html = index_html()
        skript = VIDEO_JS.read_text(encoding="utf-8")
        for väljare in ("data-hero-clip", "data-film-src"):
            self.assertIn(väljare, skript, f"site-video.js letar inte längre efter {väljare}")
            self.assertIn(väljare, html, f"index.html har inga element med {väljare}")
        # Hjälten korsbleknar mellan TVÅ klipp - skriptet laddar det andra
        # först när det första spelar.
        self.assertEqual(html.count("data-hero-clip"), 2)
        self.assertIn("is-active", html, "inget hjälteklipp är markerat som det synliga")

    def test_stillbilden_star_i_markupen_sa_sidan_haller_utan_video(self):
        """Data Saver och prefers-reduced-motion ger stillbilder - och då
        gör site-video.js ingenting alls. Postern måste därför finnas i
        HTML:en, inte sättas av skriptet."""
        for video in re.findall(r"<video[^>]*>", index_html()):
            self.assertIn('poster="site/video/', video, f"video utan poster: {video[:80]}")
            self.assertIn('preload="none"', video, "ett klipp laddas innan det behövs")


class Presentationen(unittest.TestCase):
    def setUp(self):
        self.clips = json.loads(CLIPS.read_text(encoding="utf-8"))
        self.html = index_html()

    def test_sju_scener_med_rubrikerna_ur_clips_json(self):
        scener = re.findall(r'<article class="site-film-scene">', self.html)
        self.assertEqual(len(scener), 7, "presentationen är sju scener")
        for nyckel, klipp in self.clips["clips"].items():
            if klipp.get("status") != "ok":
                continue
            self.assertIn(klipp["headline"], self.html, f"rubriken för {nyckel} saknas på sidan")

    def test_avslutningsraden_star_dar(self):
        self.assertIn(self.clips["closing"], self.html)
        self.assertIn("Matjakt gör jobbet åt dig.", self.html)

    def test_varje_scen_redovisar_sin_fotograf(self):
        """Pexels-licensen kräver inget, men ett klipp vi inte kan visa
        ursprunget för är ett klipp vi inte kan försvara."""
        krediteringar = re.findall(r'<p class="site-film-credit">', self.html)
        self.assertEqual(len(krediteringar), 7)
        for klipp in self.clips["clips"].values():
            if klipp.get("status") == "ok":
                self.assertIn(klipp["sourceUrl"], self.html)


class TioSektionerMedSinCopy(unittest.TestCase):
    """Copyn i UPPDRAG-MATJAKT.md I1 är skriven, inte utkastad. Den står
    ordagrant, och det här testet är vad som håller den kvar när nästa agent
    ska "putsa lite"."""

    def setUp(self):
        self.html = index_html()

    def test_topprad_med_ordmarke_meny_och_knapp(self):
        topp = self.html.split("</header>")[0]
        self.assertIn('class="site-topbar"', topp)
        for post in ("Så funkar det", "Pris", "Vanliga frågor"):
            self.assertIn(f">{post}</a>", topp, f"toppradens meny saknar {post!r}")
        self.assertIn("Öppna appen", topp)

    def test_hjaltens_copy(self):
        for text in (
            "Riktiga butikspriser, inte uppskattningar",
            "Säg vad maten får kosta. Matjakt planerar veckan och visar var den blir billigast.",
            "Sju middagar, en inköpslista och ett verkligt pris hos Willys, Hemköp och City Gross. "
            "Du bestämmer budgeten – vi räknar.",
            "Kom igång gratis",
            "Se hur det fungerar",
            "Gratis att använda. Inget kort. Inget konto krävs för att prova.",
        ):
            self.assertIn(text, self.html, f"hjältens copy saknar: {text[:48]}…")

    def test_h1_ar_loftet_och_star_en_gang(self):
        rubriker = re.findall(r"<h1[^>]*>(.*?)</h1>", self.html, re.S)
        self.assertEqual(len(rubriker), 1, "en sida har exakt en h1")
        self.assertIn("Säg vad maten får kosta", rubriker[0])
        # Ordmärket är inte längre rubriken - det flyttade till toppraden.
        self.assertNotIn("Matjakt.", rubriker[0])

    def test_beviset_star_direkt_under_hjalten(self):
        self.assertIn("Priserna kommer från butikerna, inte från en gissning.", self.html)
        self.assertIn(
            "Matjakt läser in Willys, Hemköps och City Gross priser varje natt. Kan vi inte "
            "prissätta en vara säger appen det rakt ut – hellre inget pris än ett fel pris. "
            "Och en butik som inte går att jämföra rättvist märks aldrig som billigast.",
            self.html)
        self.assertLess(self.html.index("Priserna kommer från butikerna"),
                        self.html.index("Så fungerar det"),
                        "beviset ska stå före hur-det-funkar, inte efter")

    def test_de_tre_stegen(self):
        for rubrik, text in (
            ("Sätt ramarna", "Hur många ni är, vad veckan får kosta, var ni handlar."),
            ("Få veckan", "Middagar som håller budgeten, byt de du inte gillar."),
            ("Handla", "Listan är sorterad som hyllorna och räknar bort det du har hemma."),
        ):
            self.assertIn(f"<h3>{rubrik}</h3>", self.html)
            self.assertIn(text, self.html)

    def test_skillnaden_mot_att_handla_som_vanligt(self):
        """Sektionen saknades helt på den gamla sidan."""
        for rubrik in ("Du planerar inte i butiken",
                       "Du vet vad veckan kostar innan du går",
                       "Kampanjerna hamnar i maten du faktiskt lagar"):
            self.assertIn(f"<h3>{rubrik}</h3>", self.html)
        self.assertIn("Impulsköpen är det dyra.", self.html)
        self.assertIn("Ett fynd du inte använder är inget fynd.", self.html)

    def test_priset_star_pa_sidan(self):
        """Fyndet i I1: "Inget pris". Nu står båda planerna och beloppen."""
        self.assertIn("Gratis för alltid", self.html)
        self.assertIn("Premium", self.html)
        # Hårt mellanslag mellan siffra och kr (DESIGNSYSTEM-D 3.4) - ett
        # belopp får aldrig brytas över raden.
        self.assertIn("59&nbsp;kr/mån", self.html)
        self.assertIn("399&nbsp;kr/år", self.html)
        self.assertIn("Börja gratis, uppgradera sen", self.html)

    def test_de_sex_vanliga_fragorna(self):
        """Frågorna är också underlaget för FAQPage-schemat i I2."""
        for fråga in ("Var kommer priserna ifrån?", "Behöver jag konto?", "Vad kostar det?",
                      "Vilka butiker stöds?", "Kan familjen dela samma vecka?",
                      "Hur raderar jag mitt konto?"):
            self.assertIn(f"<summary>{fråga}</summary>", self.html, f"FAQ saknar {fråga!r}")
        # Varje fråga har ett svar - en tom <details> är sämre än ingen.
        for block in re.findall(r"<details>(.*?)</details>", self.html, re.S):
            self.assertRegex(block, r"<p>\s*\S", "en FAQ-fråga saknar svar")

    def test_avslutningen(self):
        self.assertIn("Nästa vecka kan vara planerad om fem minuter.", self.html)

    def test_footern(self):
        fot = self.html.split('<footer')[1]
        self.assertIn("integritetspolicy.html", fot)
        self.assertIn("anvandarvillkor.html", fot)
        self.assertIn("Produktinformation delvis från Dabas. Klipp från Pexels.", fot)

    def test_supporten_ar_en_adress_pa_domanen_inte_en_privat_inkorg(self):
        """En betaltjänst som ber om support via någons privata iCloud-adress
        ser ut som ett hobbyprojekt, och adressen går inte att lämna över."""
        self.assertIn("mailto:support@matjakt.store", self.html)
        self.assertNotIn("adamfrom@icloud.com", self.html)

    def test_varje_sektion_i_strukturen_finns(self):
        for ankare in ("sa-fungerar-det", "filmen", "skillnaden", "pris", "vanliga-fragor"):
            self.assertIn(f'id="{ankare}"', self.html, f"sektionen #{ankare} saknas")
        for länk in ("#sa-fungerar-det", "#pris", "#vanliga-fragor", "#filmen"):
            self.assertIn(f'href="{länk}"', self.html, f"ingen länk pekar på {länk}")


class AppenOchSajtenArSammaProdukt(unittest.TestCase):
    """Tre varumärken låg i samma domän. Landningssidan går över till
    designsystemet i docs/DESIGNSYSTEM-D.md - samma tokens som appen."""

    def setUp(self):
        self.css = STYLES.read_text(encoding="utf-8")

    def test_paletten_ar_riktning_d(self):
        for token, värde in (("--paper", "#ECEEEF"), ("--ink", "#16191B"),
                             ("--accent", "#8A1F42"), ("--on-accent", "#FFFFFF")):
            self.assertIn(f"{token}:{värde}", self.css, f"{token} är inte riktning D")

    def test_de_gamla_grona_varumarkesfargerna_ar_borta(self):
        for död in ("#146c43", "#0f5233", "#f6f7f4", "#f28c28", "#d96a1c"):
            self.assertNotIn(död, self.css.lower(), f"{död} lever kvar i landningssidans CSS")

    def test_typsnitten_ar_newsreader_mot_archivo(self):
        self.assertIn('"Newsreader"', self.css)
        self.assertIn('"Archivo"', self.css)
        for gammalt in ("Bricolage", "Manrope", "DM Sans", "Fraunces"):
            self.assertNotIn(gammalt, self.css, f"{gammalt} lever kvar i landningssidans CSS")
        # Typsnitten måste också hämtas, annars faller sidan till Georgia.
        self.assertIn("family=Archivo", index_html())
        self.assertIn("Newsreader", index_html())

    def test_body_har_en_explicit_bakgrund(self):
        """En genomskinlig body lånar värdens tema och gör mörkt läge
        trasigt (DESIGNSYSTEM-D 2.1)."""
        self.assertRegex(self.css, r"body\{[^}]*background:var\(--paper\)")

    def test_morkt_lage_finns_i_bada_riktningarna(self):
        self.assertIn("@media (prefers-color-scheme:dark)", self.css)
        self.assertIn(':root[data-theme="dark"]', self.css)
        # Ingen färg får ha sin ENDA definition i ett mörkt block.
        ljust = self.css.split("@media (prefers-color-scheme:dark)")[0]
        for token in ("--paper", "--ink", "--accent", "--rule", "--shot"):
            self.assertIn(f"{token}:", ljust, f"{token} definieras bara i mörkt läge")

    def test_traffytorna_haller_44_px(self):
        """G5: allt som går att trycka på är minst 44x44 CSS-px."""
        höjder = [int(m) for m in re.findall(r"min-height:(\d+)px", self.css)]
        self.assertTrue(höjder)
        self.assertTrue(all(h >= 44 for h in höjder), f"träffytor under 44 px: {höjder}")


if __name__ == "__main__":
    unittest.main()
