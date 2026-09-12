# -*- coding: utf-8 -*-
"""I6: Kampanjtorget som publik sida på /fynd/vecka-{n}/.

Sidan är den enda på matjakt.store som får nytt innehåll varje vecka, och den
enda realistiska vägen till organisk sökning på "veckans erbjudanden Willys".

DET HÄR TESTET HANDLAR OM ETT FÄLT SOM INTE FINNS ÄN. C11
(docs/PAKET-C11-fynd.md) lägger till `recipeIds` och `savesOnWeek` på varje
fynd. C11 är inte byggd. Kravet på sidan är därför tvåsidigt, och båda
sidorna prövas här mot samma funktion:

  * UTAN fälten ska sidan rendera, lista butikernas kampanjer som de är, och
    säga rakt ut att receptkopplingen saknas. Den får INTE antyda att fynden
    hör till middagar.
  * MED fälten ska de kopplade fynden lyftas överst med sina recept och sina
    sparade kronor, och den ursäktande texten ska försvinna.

Det som prövas är alltså inte "renderar den" utan "ljuger den inte". En
kampanjsida som påstår en receptkoppling den inte har är värre än ingen sida.
"""

import json
import re
import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from services.site import fynd_page  # noqa: E402

FRONTEND = ROOT / "frontend"
FYND = FRONTEND / "fynd"
SITEMAP = FRONTEND / "sitemap.xml"
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
HÄMTAD = datetime(2026, 9, 11, 22, 15)


def fynd(namn="Fläskfilé", kedja="Willys", **extra) -> dict:
    """Ett fynd med exakt de fält campaign_deals() faktiskt returnerar
    (services/grocery/api.py:167-178). validUntil är alltid None - ingen kedja
    publicerar det, och det får aldrig gissas."""
    bas = {
        "chain": kedja, "name": namn, "brand": "Garant", "productId": 4372,
        "gtin": "07340083485497", "validUntil": None, "size": "600g",
        "imageUrl": "https://assets.axfood.se/bild.jpg",
        "campaignPrice": 49.0, "regularPrice": 89.0, "discountPercent": 45,
        "lowestSeen": 49.0,
    }
    bas.update(extra)
    return bas


UTAN_C11 = {
    "Willys": [fynd("Glasstrut", campaignPrice=16.5, regularPrice=33.0, discountPercent=50),
               fynd("Oreo Sandwich", campaignPrice=12.0, regularPrice=24.0, discountPercent=50)],
    "Hemköp": [fynd("Coca-cola Zero", kedja="Hemköp", campaignPrice=49.95,
                    regularPrice=75.95, discountPercent=34)],
}

MED_C11 = {
    "Willys": [fynd("Fläskfilé", recipeIds=["flaskfilerotmos", "flaskcurrygryta"],
                    savesOnWeek=24.2),
               fynd("Glasstrut", campaignPrice=16.5, regularPrice=33.0, discountPercent=50)],
    "Hemköp": [fynd("Champinjoner", kedja="Hemköp", recipeIds=["svamppasta"],
                    campaignPrice=10.0, regularPrice=15.95, discountPercent=37)],
}


def rendera(deals, **extra) -> str:
    val = {"vecka": 37, "år": 2026, "hämtad": HÄMTAD}
    val.update(extra)
    return fynd_page.render_week(deals, **val)


class UtanC11(unittest.TestCase):
    """Läget i dag. Sidan ska fungera, och framför allt inte låtsas."""

    def setUp(self):
        self.html = rendera(UTAN_C11)

    def test_varje_fynd_star_pa_sidan_med_bada_priserna(self):
        for namn, kampanj, ordinarie in (("Glasstrut", "16,50\u00a0kr", "33,00\u00a0kr"),
                                         ("Oreo Sandwich", "12,00\u00a0kr", "24,00\u00a0kr"),
                                         ("Coca-cola Zero", "49,95\u00a0kr", "75,95\u00a0kr")):
            self.assertIn(namn, self.html)
            self.assertIn(kampanj, self.html)
            self.assertIn(f"ord. {ordinarie}", self.html,
                          "ett kampanjpris utan ordinarie pris är ett tal utan innebörd")

    def test_sidan_sager_rakt_ut_att_receptkopplingen_saknas(self):
        self.assertIn(fynd_page.INGEN_RECEPTKOPPLING, self.html)

    def test_sidan_pastar_ingen_receptkoppling(self):
        """Det dyra felet: en kampanjsida som antyder att fynden hör till
        middagar när ingen sådan koppling finns."""
        for påstående in ("hamnar i en middag", "Används i", "Passar i"):
            self.assertNotIn(påstående, self.html,
                             f"sidan påstår {påstående!r} utan recipeIds")

    def test_sidan_pastar_inga_sparade_kronor(self):
        self.assertNotIn("Du sparar", self.html,
                         "kronor sparade på veckans mängd är vår räkning, "
                         "och den finns inte förrän C11 räknar den")

    def test_kedjorna_far_var_sin_rubrik(self):
        self.assertIn("<h2>Hemköp</h2>", self.html)
        self.assertIn("<h2>Willys</h2>", self.html)


class MedC11(unittest.TestCase):
    """Läget efter C11. Samma funktion, samma sida - fälten bara finns."""

    def setUp(self):
        self.html = rendera(MED_C11, recept_titlar={
            "flaskfilerotmos": "Fläskfilé med rotmos",
            "flaskcurrygryta": "Fläskgryta med curry"})

    def test_de_kopplade_fynden_lyfts_till_en_egen_rubrik(self):
        self.assertIn("<h2>Fynd som hamnar i en middag</h2>", self.html)

    def test_ursakten_forsvinner_nar_kopplingen_finns(self):
        self.assertNotIn(fynd_page.INGEN_RECEPTKOPPLING, self.html)

    def test_recepten_namnges_nar_titlarna_ar_kanda(self):
        self.assertIn("Används i Fläskfilé med rotmos, Fläskgryta med curry.", self.html)

    def test_okant_recept_id_blir_ett_antal_inte_ett_id(self):
        """Ett id ur vår databas på en publik sida upplyser ingen. Går titeln
        inte att slå upp ska sidan räkna i stället för att avslöja."""
        self.assertIn("Passar i 1 rätt i Matjakt.", self.html)
        self.assertNotIn("svamppasta", self.html)

    def test_sparade_kronor_visas_nar_de_ar_raknade(self):
        self.assertIn("Du sparar 24,20\u00a0kr på veckans mängd", self.html)

    def test_fynd_utan_koppling_ligger_kvar_i_kedjans_tabell(self):
        self.assertIn("<h2>Övriga kampanjer hos Willys</h2>", self.html)
        self.assertIn("Glasstrut", self.html)

    def test_det_kopplade_kommer_fore_kedjetabellerna(self):
        """Ordningen ÄR budskapet: det som hör till en middag först, resten
        sedan. Byter de plats är sidan tillbaka till en rabattlista."""
        self.assertLess(self.html.index("Fynd som hamnar i en middag"),
                        self.html.index("Övriga kampanjer hos"))

    def test_hogst_sparade_kronor_star_overst(self):
        with_saves = rendera({"Willys": [
            fynd("Liten", recipeIds=["a"], savesOnWeek=4.0),
            fynd("Stor", recipeIds=["b"], savesOnWeek=44.0)]})
        self.assertLess(with_saves.index("Stor"), with_saves.index("Liten"))


class SkraptalighetOchEscapning(unittest.TestCase):
    """Fälten kommer från en server som kan vara äldre än sidan, och namnen
    kommer ur butikernas egna produktregister."""

    def test_trasiga_recipeids_ger_en_sida_inte_ett_undantag(self):
        for skräp in ("flaskfile", 7, {}, None, [""], [3], True, []):
            html = rendera({"Willys": [fynd("Vara", recipeIds=skräp)]})
            self.assertIn("Vara", html)
            self.assertNotIn("Passar i", html, f"recipeIds={skräp!r} togs för recept")
            self.assertNotIn("Används i", html, f"recipeIds={skräp!r} togs för recept")

    def test_trasigt_savesonweek_ger_en_sida_inte_ett_undantag(self):
        for skräp in ("24,20", "24.20", None, True, False, {}, [], [24.2]):
            html = rendera({"Willys": [fynd("Vara", recipeIds=["a"], savesOnWeek=skräp)]})
            self.assertIn("Vara", html)
            self.assertNotIn("Du sparar", html, f"savesOnWeek={skräp!r} togs för kronor")

    def test_negativt_eller_noll_sparat_ar_inget_att_skylta_med(self):
        for belopp in (0, -5.0):
            html = rendera({"Willys": [fynd("Vara", recipeIds=["a"], savesOnWeek=belopp)]})
            self.assertNotIn("Du sparar", html)

    def test_ett_produktnamn_ur_butiken_escapas(self):
        html = rendera({"Willys": [fynd('Ost <script>alert(1)</script> & co')]})
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp; co", html)

    def test_ett_fynd_utan_namn_hoppas_over_i_stallet_for_att_krascha(self):
        html = rendera({"Willys": [fynd("Riktig"), {"chain": "Willys"}, "skräp"]})
        self.assertIn("Riktig", html)

    def test_tom_vecka_sager_att_vi_inte_kunde_lasa_inte_att_det_saknas_fynd(self):
        html = rendera({})
        self.assertIn("Inga kampanjer kunde läsas in", html)
        self.assertNotIn("<li class=\"fynd-rad\">", html)


class SidanPastarIngetButikenInteSagt(unittest.TestCase):
    def test_inget_slutdatum_hittas_pa(self):
        """validUntil är alltid None i svaret - ingen kedja publicerar det.
        Ett "gäller t.o.m." är då ett löfte butiken inte gett."""
        html = rendera(UTAN_C11)
        for påstående in ("gäller t.o.m", "Gäller t.o.m", "till och med", "sista dag"):
            self.assertNotIn(påstående, html)

    def test_hamtningsdatumet_star_pa_sidan(self):
        """En kampanjsida utan hämtningsdatum åldras i tysthet."""
        html = rendera(UTAN_C11)
        self.assertIn("fredag 11 september kl. 22.15", html)

    def test_lagsta_sett_pastas_bara_nar_priset_verkligen_ar_det(self):
        lågt = rendera({"Willys": [fynd("Vara", campaignPrice=10.0, lowestSeen=10.0)]})
        högt = rendera({"Willys": [fynd("Vara", campaignPrice=10.0, lowestSeen=8.0)]})
        self.assertIn("Lägsta vi sett", lågt)
        self.assertNotIn("Lägsta vi sett", högt)

    def test_saknad_prishistorik_ger_inget_pastaende(self):
        html = rendera({"Willys": [fynd("Vara", lowestSeen=None)]})
        self.assertNotIn("Lägsta vi sett", html)


class SidansHuvud(unittest.TestCase):
    def setUp(self):
        self.html = rendera(UTAN_C11)

    def test_titel_rubrik_och_kanonisk_adress_bar_veckan(self):
        self.assertIn("<title>Veckans erbjudanden vecka 37", self.html)
        self.assertIn("<h1>Veckans erbjudanden – vecka 37</h1>", self.html)
        self.assertIn('<link rel="canonical" href="https://matjakt.store/fynd/vecka-37/">',
                      self.html)

    def test_delningstaggarna_finns_och_ar_absoluta(self):
        for tagg in ("og:title", "og:description", "og:image", "og:url", "twitter:card"):
            self.assertIn(tagg, self.html, f"{tagg} saknas - en delad länk blir en grå ruta")
        for adress in re.findall(r'property="og:(?:image|url)" content="([^"]+)"', self.html):
            self.assertTrue(adress.startswith("https://"),
                            f"{adress} är relativ och plockas inte upp av någon skrapa")

    def test_strukturerad_data_parsar_och_ar_en_itemlist(self):
        block = re.search(r'<script type="application/ld\+json">(.*?)</script>',
                          self.html, re.S)
        self.assertIsNotNone(block)
        data = json.loads(block.group(1))
        self.assertEqual(data["@type"], "ItemList")
        self.assertEqual(data["numberOfItems"], 3)

    def test_schemat_lovar_inget_erbjudande_utan_giltighetstid(self):
        """Google kräver priceValidUntil eller availability för Offer-schema,
        och båda hade varit påhittade här."""
        self.assertNotIn('"@type": "Offer"', self.html)

    def test_sidan_bar_samma_stilmall_och_typsnitt_som_resten_av_domanen(self):
        self.assertIn('href="/styles.css', self.html)
        self.assertIn("Newsreader", self.html)
        self.assertIn("Archivo", self.html)

    def test_kontaktadressen_ar_domanens(self):
        self.assertIn("mailto:adamfrom@icloud.com", self.html)
        self.assertNotIn("support@matjakt.store", self.html)


class DenPubliceradeVeckan(unittest.TestCase):
    """GitHub Pages kopierar frontend/ rakt av - en vecka finns bara om dess
    HTML är committad. Testet nedan gäller de sidor som faktiskt ligger där."""

    def sidor(self):
        return sorted(FYND.glob("vecka-*/index.html"))

    def test_minst_en_vecka_ar_publicerad(self):
        self.assertTrue(self.sidor(), "frontend/fynd/ innehåller ingen vecka")

    def test_arkivsidan_finns_och_listar_varje_vecka(self):
        arkiv = (FYND / "index.html").read_text(encoding="utf-8")
        for sida in self.sidor():
            vecka = sida.parent.name.split("-", 1)[1]
            self.assertIn(f'href="/fynd/vecka-{vecka}/"', arkiv,
                          f"vecka {vecka} finns men står inte i arkivet")

    def test_varje_veckas_kanoniska_adress_ar_dess_egen_sokvag(self):
        """En kanonisk adress som pekar på en annan vecka slår ihop två sidor
        till en i sökindexet, och den nya veckan försvinner."""
        for sida in self.sidor():
            html = sida.read_text(encoding="utf-8")
            vecka = sida.parent.name.split("-", 1)[1]
            self.assertIn(f'href="https://matjakt.store/fynd/vecka-{vecka}/">', html)

    def test_varje_vecka_star_i_sitemapen(self):
        adresser = {url.findtext(f"{SITEMAP_NS}loc")
                    for url in ET.parse(SITEMAP).getroot().findall(f"{SITEMAP_NS}url")}
        self.assertIn("https://matjakt.store/fynd/", adresser, "arkivet saknas i sitemapen")
        for sida in self.sidor():
            vecka = sida.parent.name.split("-", 1)[1]
            self.assertIn(f"https://matjakt.store/fynd/vecka-{vecka}/", adresser)

    def test_de_gamla_sidorna_star_kvar_i_sitemapen(self):
        """Generatorn skriver om sitemapen. Skriver den över de tre sidor som
        redan stod där är I2 ogjort utan att någon märker det."""
        adresser = {url.findtext(f"{SITEMAP_NS}loc")
                    for url in ET.parse(SITEMAP).getroot().findall(f"{SITEMAP_NS}url")}
        for sida in ("https://matjakt.store/",
                     "https://matjakt.store/integritetspolicy.html",
                     "https://matjakt.store/anvandarvillkor.html"):
            self.assertIn(sida, adresser)

    def test_landningssidan_lankar_till_fyndsidan(self):
        """En sida som bara sitemapen känner till crawlas sent och rankas
        lågt. Den enda interna länken dit är den här - försvinner den blir
        veckosidan en ö."""
        index = (FRONTEND / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="fynd/"', index,
                      "landningssidan länkar inte till Kampanjtorget")

    def test_varje_vecka_lankar_tillbaka_till_arkivet_och_till_appen(self):
        for sida in self.sidor():
            html = sida.read_text(encoding="utf-8")
            self.assertIn('href="/fynd/"', html, f"{sida.parent.name} saknar väg till arkivet")
            self.assertIn('href="/app/"', html, f"{sida.parent.name} saknar väg in i appen")

    def test_varje_fyndadress_har_lastmod_som_inte_ligger_i_framtiden(self):
        for url in ET.parse(SITEMAP).getroot().findall(f"{SITEMAP_NS}url"):
            loc = url.findtext(f"{SITEMAP_NS}loc")
            if "/fynd/" not in loc:
                continue
            self.assertLessEqual(date.fromisoformat(url.findtext(f"{SITEMAP_NS}lastmod")),
                                 date.today(), f"{loc} har lastmod i framtiden")


class Generatorn(unittest.TestCase):
    """backend/scripts/make_fynd_page.py. Specifikationen prövas, inte ett
    nätanrop - skriptet hämtar från en riktig server och hör inte hemma i en
    svit som ska vara klar på två minuter."""

    def setUp(self):
        self.källa = (ROOT / "backend" / "scripts" / "make_fynd_page.py").read_text(
            encoding="utf-8")

    def test_generatorn_finns(self):
        self.assertTrue((ROOT / "backend" / "scripts" / "make_fynd_page.py").exists())

    def test_den_ror_inte_campaign_deals(self):
        """Rankningen ligger i Z-GROCERY (C11). Sidan läser, den rättar inte."""
        self.assertNotIn("ORDER BY", self.källa)
        self.assertNotIn("def campaign_deals", self.källa)

    def test_den_vagrar_publicera_en_tom_vecka(self):
        """En kampanjsida med veckans nummer i rubriken och noll fynd ser ut
        som en produkt som slutat fungera."""
        self.assertIn("Inga fynd att publicera", self.källa)
        self.assertIn("return 1", self.källa)

    def test_den_anvander_samma_veckonummer_som_mejlet(self):
        """Kampanjtorget-mejlet använder ISO-vecka i svensk tid
        (services/mailings.py). Två nummer på samma vecka är ett fel ingen
        upptäcker förrän någon jämför ett mejl med en sida."""
        self.assertIn("isocalendar()", self.källa)
        self.assertIn("Europe/Stockholm", self.källa)


if __name__ == "__main__":
    unittest.main()
