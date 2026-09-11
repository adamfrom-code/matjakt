# -*- coding: utf-8 -*-
"""I2: sökmotorer och delade länkar.

Fyra fel, alla verifierade, alla osynliga för den som bara öppnar sidan:

  * `<title>Matjakt</title>` bar inget budskap.
  * **Sitemapen var tom** - `<urlset>` utan en enda URL - medan robots.txt
    pekade sökmotorerna dit. Det säger "den här domänen har inga sidor".
  * `og-image.svg` fanns men refererades inte, och **SVG fungerar inte som
    og:image hos någon plattform**. Varje delad länk var en tom grå ruta.
  * Tre varumärken i samma domän: grönt Manrope/Bricolage på landningssidan,
    orange DM Sans/Fraunces på 404:an och de juridiska sidorna, en tredje
    orange i reelen.

Det som prövas här är därför det som INTE syns när man tittar på sidan:
markupen, bildens mått i byte, sitemapens innehåll och att strukturerad data
säger samma sak som sidan.
"""

import json
import re
import struct
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
INDEX = FRONTEND / "index.html"
SITEMAP = FRONTEND / "sitemap.xml"
OG_PNG = FRONTEND / "og-image.png"
REEL = ROOT / "backend" / "scripts" / "make_instagram_video.py"

DOMÄN = "https://matjakt.store"
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def index_html() -> str:
    return INDEX.read_text(encoding="utf-8")


def meta(html: str, namn: str) -> str | None:
    """Innehållet i <meta name=...> eller <meta property=...>."""
    träff = re.search(rf'<meta (?:name|property)="{re.escape(namn)}" content="([^"]*)"', html)
    return unescape(träff.group(1)) if träff else None


def normalisera(text: str) -> str:
    """Hårda mellanslag och radbrytningar är inte betydelseskillnader när
    schema jämförs med det sidan visar."""
    return re.sub(r"\s+", " ", unescape(text).replace(" ", " ").replace(" ", " ")).strip()


def json_ld(html: str) -> list[dict]:
    return [json.loads(block) for block in
            re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


class TitelOchBeskrivning(unittest.TestCase):
    def setUp(self):
        self.html = index_html()

    def test_titeln_bar_ett_budskap(self):
        titel = re.search(r"<title>(.*?)</title>", self.html, re.S).group(1)
        self.assertEqual(titel,
                         "Matjakt – veckans middagar efter din budget, till riktiga butikspriser")
        # Under ~60 tecken klipps inte titeln i träfflistan.
        self.assertLessEqual(len(titel), 70, f"titeln är {len(titel)} tecken och klipps")

    def test_beskrivningen_finns_och_ar_en_mening_vard_att_klicka_pa(self):
        beskrivning = meta(self.html, "description")
        self.assertIsNotNone(beskrivning)
        self.assertLessEqual(len(beskrivning), 165, "beskrivningen klipps i träfflistan")
        for ord in ("budget", "Willys", "Hemköp", "City Gross"):
            self.assertIn(ord, beskrivning)

    def test_kanonisk_adress(self):
        self.assertIn(f'<link rel="canonical" href="{DOMÄN}/">', self.html)


class DeladLank(unittest.TestCase):
    """En delad länk är den enda marknadsföring som kostar noll. I dag är
    varje sådan länk en tom grå ruta."""

    def setUp(self):
        self.html = index_html()

    def test_og_bilden_ar_en_png_som_finns(self):
        bild = meta(self.html, "og:image")
        self.assertEqual(bild, f"{DOMÄN}/og-image.png")
        self.assertTrue(OG_PNG.exists(), "og-image.png saknas i frontend/")

    def test_ingen_svg_pekas_ut_som_delningsbild(self):
        """Facebook, LinkedIn, Slack, iMessage och X renderar inte SVG. En
        og:image som pekar på en .svg är samma sak som ingen bild alls."""
        for nyckel in ("og:image", "twitter:image"):
            self.assertNotIn(".svg", meta(self.html, nyckel) or "",
                             f"{nyckel} pekar på en SVG")

    def test_bilden_ar_exakt_1200x630(self):
        """Måtten står i IHDR - ingen Pillow behövs för att läsa dem. Fel
        mått blir beskuret hos hälften av mottagarna."""
        data = OG_PNG.read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n", "og-image.png är inte en PNG")
        self.assertEqual(data[12:16], b"IHDR")
        self.assertEqual(struct.unpack(">II", data[16:24]), (1200, 630))
        self.assertEqual(meta(self.html, "og:image:width"), "1200")
        self.assertEqual(meta(self.html, "og:image:height"), "630")

    def test_bilden_ar_liten_nog_att_hamtas(self):
        self.assertLess(OG_PNG.stat().st_size, 1_000_000,
                        "delningsbilden väger över 1 MB")

    def test_alla_delningstaggar_finns_och_ar_absoluta(self):
        for nyckel in ("og:type", "og:site_name", "og:url", "og:title", "og:description",
                       "og:image", "og:image:alt", "twitter:card", "twitter:title",
                       "twitter:description", "twitter:image"):
            värde = meta(self.html, nyckel)
            self.assertTrue(värde, f"{nyckel} saknas")
        self.assertEqual(meta(self.html, "twitter:card"), "summary_large_image")
        for nyckel in ("og:url", "og:image", "twitter:image"):
            self.assertTrue(meta(self.html, nyckel).startswith("https://"),
                            f"{nyckel} är relativ - ingen skrapa löser upp den")


class Sitemapen(unittest.TestCase):
    """robots.txt:3 pekar sökmotorerna hit. Filen låg tom."""

    def setUp(self):
        self.träd = ET.parse(SITEMAP).getroot()
        self.urler = self.träd.findall(f"{SITEMAP_NS}url")

    def _fil_för(self, loc: str) -> Path:
        self.assertTrue(loc.startswith(f"{DOMÄN}/"), f"{loc} ligger utanför domänen")
        stig = loc[len(DOMÄN) + 1:]
        return FRONTEND / (stig or "index.html")

    def test_sitemapen_ar_inte_tom(self):
        self.assertGreaterEqual(len(self.urler), 3,
                                "sitemapen listar färre än tre sidor")

    def test_varje_url_har_loc_och_lastmod_och_pekar_pa_en_sida_som_finns(self):
        for url in self.urler:
            loc = url.findtext(f"{SITEMAP_NS}loc")
            lastmod = url.findtext(f"{SITEMAP_NS}lastmod")
            self.assertTrue(loc, "en <url> saknar <loc>")
            self.assertTrue(lastmod, f"{loc} saknar <lastmod>")
            dag = date.fromisoformat(lastmod)          # kastar på fel format
            self.assertLessEqual(dag, date.today(), f"{loc} har lastmod i framtiden")
            self.assertTrue(self._fil_för(loc).exists(), f"{loc} finns inte i frontend/")

    def test_varje_publik_sida_star_med(self):
        """Den grind som faktiskt betyder något: en ny publik sida som inte
        hamnar i sitemapen indexeras inte, och ingen märker det."""
        listade = {self._fil_för(url.findtext(f"{SITEMAP_NS}loc")).name for url in self.urler}
        for sida in sorted(FRONTEND.glob("*.html")):
            html = sida.read_text(encoding="utf-8")
            if 'name="robots" content="noindex"' in html:
                continue
            self.assertIn(sida.name, listade, f"{sida.name} är indexerbar men saknas i sitemapen")

    def test_robots_pekar_hit_och_slapper_in(self):
        robots = (FRONTEND / "robots.txt").read_text(encoding="utf-8")
        self.assertIn(f"Sitemap: {DOMÄN}/sitemap.xml", robots)
        self.assertNotIn("Disallow: /", robots)


class StruktureradData(unittest.TestCase):
    def setUp(self):
        self.html = index_html()
        self.block = json_ld(self.html)                # json.loads kastar på trasig JSON
        self.typer = {b["@type"]: b for b in self.block}

    def test_bada_blocken_parsar_och_har_ratt_typ(self):
        self.assertIn("SoftwareApplication", self.typer)
        self.assertIn("FAQPage", self.typer)
        for block in self.block:
            self.assertEqual(block["@context"], "https://schema.org")

    def test_priserna_i_schemat_ar_de_priser_sidan_visar(self):
        erbjudanden = self.typer["SoftwareApplication"]["offers"]
        priser = {o["price"] for o in erbjudanden["offers"]}
        self.assertEqual(priser, {"0", "59", "399"})
        self.assertEqual(erbjudanden["lowPrice"], "0")
        self.assertEqual(erbjudanden["highPrice"], "399")
        for erbjudande in erbjudanden["offers"]:
            self.assertEqual(erbjudande["priceCurrency"], "SEK")

    def test_faq_schemat_ar_ordagrant_det_sidan_sager(self):
        """Google underkänner - och kan straffa - ett FAQPage-schema som
        lovar svar sidan inte innehåller. Därför jämförs de, inte bara
        räknas."""
        på_sidan = {}
        for block in re.findall(r"<details>(.*?)</details>", self.html, re.S):
            fråga = re.search(r"<summary>(.*?)</summary>", block, re.S).group(1)
            svar = " ".join(re.findall(r"<p>(.*?)</p>", block, re.S))
            på_sidan[normalisera(fråga)] = normalisera(re.sub(r"<[^>]+>", "", svar))

        i_schemat = {normalisera(f["name"]): normalisera(f["acceptedAnswer"]["text"])
                     for f in self.typer["FAQPage"]["mainEntity"]}

        self.assertEqual(sorted(i_schemat), sorted(på_sidan),
                         "FAQ-schemat och sidans frågor är inte samma uppsättning")
        for fråga, svar in i_schemat.items():
            self.assertEqual(svar, på_sidan[fråga], f"svaret på {fråga!r} skiljer sig")
        self.assertEqual(len(i_schemat), 6)


class Webbanalys(unittest.TestCase):
    def test_trafikmatningen_ar_paslagen_och_kakfri(self):
        html = index_html()
        self.assertEqual(meta(html, "matjakt-traffic"), "plausible:matjakt.store")
        self.assertIn('<script src="traffic.js" defer></script>', html)

    def test_varden_far_passera_appens_csp(self):
        """traffic.js laddar ett externt skript. Står värden inte i CSP:n
        blockeras det tyst i appen - och siffrorna uteblir utan felmeddelande."""
        app_html = (FRONTEND / "app" / "index.html").read_text(encoding="utf-8")
        csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', app_html).group(1)
        self.assertIn("https://plausible.io", csp)


class EttVarumarkeIHelaDomanen(unittest.TestCase):
    """Fem ytor bär varumärket: landningssidan, appen, 404:an, de juridiska
    sidorna och reelen. Tre paletter i samma domän läser som tre produkter."""

    GAMLA_TYPSNITT = ("DM Sans", "Fraunces", "Manrope", "Bricolage")
    GAMLA_FARGER = ("#146c43", "#0f5233", "#f6f3ea", "#f6f7f4", "#f28c28",
                    "#d96a1c", "#173b2a", "#162019")

    def sidor(self):
        """Varje publik sida, med den CSS den faktiskt laddar. En sida med
        extern stilmall bär inga hex själv - att bara läsa HTML:en hade
        friat den utan att ha tittat."""
        for sida in sorted(FRONTEND.glob("*.html")):
            html = sida.read_text(encoding="utf-8")
            text = html
            for stilmall in re.findall(r'<link rel="stylesheet" href="([^":?]+)', html):
                fil = FRONTEND / stilmall
                if fil.exists():
                    text += fil.read_text(encoding="utf-8")
            yield sida.name, html, text

    def test_ingen_sida_pa_domanen_bar_ett_gammalt_typsnitt(self):
        for namn, _, text in self.sidor():
            for typsnitt in self.GAMLA_TYPSNITT:
                self.assertTrue(typsnitt not in text, f"{namn} bär fortfarande {typsnitt}")
            self.assertTrue("Newsreader" in text, f"{namn} saknar designsystemets antikva")
            self.assertTrue("Archivo" in text, f"{namn} saknar designsystemets grotesk")

    def test_ingen_sida_pa_domanen_bar_en_gammal_varumarkesfarg(self):
        for namn, _, text in self.sidor():
            liten = text.lower()
            for färg in self.GAMLA_FARGER:
                self.assertTrue(färg not in liten, f"{namn} använder {färg}")

    def test_varje_sida_bar_riktning_d(self):
        for namn, _, text in self.sidor():
            self.assertTrue("#ECEEEF" in text, f"{namn} har inte pappersviten")
            self.assertTrue("#8A1F42" in text, f"{namn} har inte oxblodsaccenten")

    def test_reelen_bar_samma_tokens(self):
        källa = REEL.read_text(encoding="utf-8")
        for död in ("BRAND_GREEN", "BRAND_ORANGE"):
            self.assertNotIn(död, källa, f"{död} lever kvar i reelen")
        for token in ("PAPER = (236, 238, 239)", "INK = (22, 25, 27)",
                      "ACCENT = (138, 31, 66)"):
            self.assertIn(token, källa, f"reelen saknar {token}")


class KontaktadressenGarFram(unittest.TestCase):
    """Paketet skrev först support@matjakt.store överallt. Den adressen har
    ingen vidarebefordran - ett mejl dit hamnar ingenstans, och det är värre
    än en privat adress som läses. I3 avgjorde: adamfrom@icloud.com på hela
    domänen tills brevlådan finns. Byts den, byts den på alla sidor samtidigt
    och det här testet med."""

    SIDOR = ("index.html", "integritetspolicy.html", "anvandarvillkor.html")

    def test_varje_publik_sida_bar_en_adress_som_nar_nagon(self):
        for namn in self.SIDOR:
            html = (FRONTEND / namn).read_text(encoding="utf-8")
            self.assertIn("mailto:adamfrom@icloud.com", html,
                          f"{namn} saknar en kontaktadress som går fram")

    def test_ingen_sida_utlovar_en_brevlada_som_inte_finns(self):
        for sida in sorted(FRONTEND.glob("*.html")):
            html = sida.read_text(encoding="utf-8")
            self.assertNotIn("support@matjakt.store", html,
                             f"{sida.name} ber om support till en adress utan mottagare")


class SlappgrindenArPasserad(unittest.TestCase):
    """Beslutet är fattat (I3) och platshållarna ifyllda. CI:s steg
    "Juridiska platshållare" är fortfarande en VARNING och inte ett byggfel -
    det ska stå kvar, för nästa platshållare någon skriver ska hittas på
    samma sätt. Men på de sidor som finns i dag ska den inte ha något att
    varna om."""

    def test_inga_platshallare_kvar_pa_nagon_publik_sida(self):
        for sida in sorted(FRONTEND.glob("*.html")):
            html = sida.read_text(encoding="utf-8")
            self.assertNotIn('class="placeholder"', html,
                             f"{sida.name} har kvar en juridisk platshållare")
            self.assertNotIn("[FÖRETAGSNAMN", html, f"{sida.name}: platshållartext kvar")
            self.assertNotIn("[ORGANISATIONSNUMMER", html, f"{sida.name}: platshållartext kvar")

    def test_ci_steget_ar_en_varning_inte_ett_byggfel(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        steg = ci.split("Juridiska platshållare")[1].split("- name:")[0]
        self.assertIn("::warning::", steg)
        self.assertNotIn("exit 1", steg, "platshållarna har blivit ett byggfel")


if __name__ == "__main__":
    unittest.main()
