# -*- coding: utf-8 -*-
"""K6: kontraktstest per kollektor mot sparade svar från kedjorna.

`test_ica_collector.py` var ensam. Willys, Hemköp, City Gross och den
gemensamma Axfood-basen hade ingen egen svit alls — och scraping är det som
faktiskt går sönder i drift, eftersom det går sönder när NÅGON ANNAN ändrar
sig.

DET FARLIGA ÄR INTE ETT UNDANTAG. `normalize_product` läser varje fält med
`.get()`. Döper Willys om `priceValue` till `price` kastas ingenting: varje
produkt får `regular_price=None`, kollektorn sparar den ändå, och
`collectors/axfood.py:run()` rapporterar `status="success"` med
`with_regular_price=0`. En import som tyst slutat bära priser ser exakt
likadan ut i loggen som en frisk. Samma sak en nivå upp: byter kedjan
kuvertets nyckel från `results` till `items` blir listan tom, `found=0`, och
körningen rapporterar `status="empty"`.

Testerna nedan kör kedjornas RIKTIGA parsningskod mot sparade svar i
`fixturer/kollektorer/` — inget nät, inget beroende av att en WAF släpper
igenom just i dag. Varje fält som bär ett pris, ett id eller en bild prövas
med sitt värde, inte bara med "inte None".

Och varje kontrakt prövas BÅDE helt och trasigt: klassen
`EttOmdoptFaltGorProvetRott` döper om fälten i sparade svaren, en i taget,
och kräver att kontraktet faller. Ett kontraktstest som bara körs mot ett
svar man vet stämmer bevisar ingenting.
"""

import json
import sys
import unittest
from pathlib import Path

HÄR = Path(__file__).resolve().parent
sys.path.insert(0, str(HÄR.parent))

from services.grocery.providers.axfood import (  # noqa: E402
    AxfoodProvider, flatten_category_tree, gtin_from_image_url, split_promotions,
)
from services.grocery.providers.citygross import (  # noqa: E402
    CityGrossProvider, extract_prices, normalize_gtin14,
)
from services.grocery.providers.hemkop import HemkopProvider  # noqa: E402
from services.grocery.providers.willys import WillysProvider  # noqa: E402

FIXTURER = HÄR / "fixturer" / "kollektorer"


def svar(namn):
    """Ett sparat svar, färskt varje gång: ett test som muterar sin fixtur
    får aldrig lämna den muterad åt nästa."""
    return json.loads((FIXTURER / f"{namn}.json").read_text(encoding="utf-8"))


def axfood_produkter(leverantör, data, store_id="2132"):
    """Samma väg som get_products tar genom kuvertet, utan nätet.

    Kuvertnyckeln läses här med SAMMA namn som providern använder. Det är
    med flit: byter kedjan `results` mot något annat ska det falla här,
    på en rad som säger vad som hände, och inte visa sig som en tom import.
    """
    resultat = data.get("results") or []
    return [leverantör.normalize_product({**rå, "_store_id": store_id}) for rå in resultat]


def citygross_produkter(leverantör, data, store_id="3209"):
    resultat = (data.get("searchResults") or {}).get("products") or []
    return [leverantör.normalize_product({**rå, "_store_id": store_id}) for rå in resultat]


class WillysKontrakt(unittest.TestCase):
    """Willys söksvar -> RawProduct. Fältvärden, inte bara fältnärvaro."""

    def setUp(self):
        self.leverantör = WillysProvider()
        self.produkter = axfood_produkter(self.leverantör, svar("willys_sok"))

    def test_kuvertet_ger_alla_produkter(self):
        # Byter kedjan `results` mot `items` blir listan tom och importen
        # rapporterar "empty" i stället för att någon får veta.
        self.assertEqual(len(self.produkter), 3)
        self.assertEqual([p.external_product_id for p in self.produkter],
                         ["101150", "202320", "303011"])

    def test_mjolken_bar_varje_falt_den_ska(self):
        mjölk = self.produkter[0]
        self.assertEqual(mjölk.chain, "Willys")
        self.assertEqual(mjölk.name, "Mellanmjölk 1,5% 1,5l Arla Ko")
        self.assertEqual(mjölk.brand, "Arla Ko")
        self.assertEqual(mjölk.regular_price, 16.50)
        self.assertEqual(mjölk.unit_price, 11.00)       # ur "11,00 kr/l"
        self.assertEqual(mjölk.size, "1,5l")
        self.assertEqual(mjölk.quantity, 1.5)
        self.assertEqual(mjölk.unit, "l")
        self.assertEqual(mjölk.currency, "SEK")
        self.assertEqual(mjölk.store_id, "2132")
        # GTIN finns inte som eget fält hos Axfood - det läses ur bildens URL
        # och bara om GS1-siffran stämmer.
        self.assertEqual(mjölk.gtin, "07340083443893")
        self.assertEqual(mjölk.source_url, "https://www.willys.se/produkt/101150")

    def test_de_tre_kampanjslagen_hamnar_inte_i_samma_falt(self):
        # Kycklingen har både ett erbjudande alla får (69) och ett
        # medlemspris (59). Blandas de ihop visas ett pris ingen kan få.
        kyckling = self.produkter[1]
        self.assertEqual(kyckling.regular_price, 89.90)
        self.assertEqual(kyckling.campaign_price, 69.00)
        self.assertEqual(kyckling.member_price, 59.00)
        self.assertIsNone(kyckling.multibuy_price)

    def test_flerkopet_ar_ett_flerkop_och_inte_en_kampanj(self):
        # "4 för 50 kr" är 12,50 styck NÄR man köper fyra. Som campaign_price
        # hade den överdrivit rabatten för den som köper en burk - precis den
        # sorts fel som gör att appen lovar ett pris kunden inte får.
        tomater = self.produkter[2]
        self.assertEqual(tomater.multibuy_price, 12.50)
        self.assertIsNone(tomater.campaign_price)
        self.assertEqual(tomater.regular_price, 16.95)


class HemkopKontrakt(unittest.TestCase):
    def setUp(self):
        self.leverantör = HemkopProvider()
        self.produkter = axfood_produkter(self.leverantör, svar("hemkop_sok"), store_id="4256")

    def test_samma_vara_prissatts_pa_kedjans_egen_niva(self):
        # 07340083443893 kostade 16,50 hos Willys och 17,70 hos Hemköp vid
        # importen 2026-08-30. Att skillnaden överlever parsningen är hela
        # produkten: kollapsar den till ett pris finns ingen jämförelse.
        mjölk = self.produkter[0]
        self.assertEqual(mjölk.chain, "Hemköp")
        self.assertEqual(mjölk.regular_price, 17.70)
        self.assertEqual(mjölk.gtin, "07340083443893")
        self.assertEqual(mjölk.source_url, "https://www.hemkop.se/produkt/101150")

    def test_flerkop_utan_villkorsetikett_ar_anda_ett_flerkop(self):
        # Hemköp lämnar conditionLabelFormatted TOM på flerköp där Willys
        # fyller i den. En tidigare version läste just det fältet och hade
        # bokfört 64,50 som ett pris alla får - det gör den inte längre, och
        # det här testet är det som håller fast att den inte gör det igen.
        lax = self.produkter[1]
        self.assertEqual(lax.regular_price, 66.20)
        self.assertEqual(lax.multibuy_price, 64.50)
        self.assertIsNone(lax.campaign_price)


class CityGrossKontrakt(unittest.TestCase):
    def setUp(self):
        self.leverantör = CityGrossProvider()
        self.produkter = citygross_produkter(self.leverantör, svar("citygross_sok"))

    def test_kuvertet_ar_tva_nivaer_djupt(self):
        # searchResults.products, inte results. Ett annat kuvert än Axfoods.
        self.assertEqual(len(self.produkter), 2)

    def test_gtin_nollutfylls_till_fjorton_sa_kedjorna_motts(self):
        # City Gross svarar EAN-13, Axfood-kedjorna GTIN-14. Utan utfyllnad
        # blir samma vara två rader och jämförelsen tappar en kedja.
        self.assertEqual(self.produkter[0].gtin, "07340083443893")
        self.assertEqual(self.produkter[1].gtin, "07310865005168")

    def test_kategoristigen_byggs_av_tre_niver(self):
        self.assertEqual(self.produkter[0].category,
                         "Mejeri, ost & ägg > Mjölk & dryck > Mellanmjölk")

    def test_ordinariepriset_ar_ordinarie_aven_nar_det_ar_samma(self):
        # currentPrice == ordinaryPrice betyder INGEN kampanj. Skrivs
        # "current" ändå som kampanjpris visar appen en rabatt på noll kronor
        # som en rabatt.
        mjölk = self.produkter[0]
        self.assertEqual(mjölk.regular_price, 16.90)
        self.assertIsNone(mjölk.campaign_price)
        self.assertEqual(mjölk.unit_price, 11.27)

    def test_de_tre_prisniverna_halls_isar(self):
        kyckling = self.produkter[1]
        self.assertEqual(kyckling.regular_price, 94.90)   # ordinaryPrice
        self.assertEqual(kyckling.campaign_price, 74.90)  # currentPrice, lägre
        self.assertEqual(kyckling.member_price, 69.90)    # memberPrice
        self.assertEqual(kyckling.unit_price, 107.00)
        self.assertEqual(
            kyckling.image_url,
            "https://www.citygross.se/images/products/VI_7310865005168_C1L1.jpeg")
        self.assertEqual(
            kyckling.source_url,
            "https://www.citygross.se/produkter/kott-chark-fagel/fagel/kycklingfile-101487002_ST")


class AxfoodButikslistan(unittest.TestCase):
    """Butikslistan är inte kosmetik: matchar inte storeId det kollektorn
    ombads importera avbryts hela körningen med SystemExit."""

    def test_butikerna_lases_ur_kedjans_egen_lista(self):
        butiker = _axfood_butiker(svar("axfood_butiker"))
        # Butiken utan storeId hoppas över, inte sparas som en butik med tomt id.
        self.assertEqual([b["external_store_id"] for b in butiker], ["2132", "2140"])
        först = butiker[0]
        self.assertEqual(först["name"], "Willys Gävle Gestrike")
        self.assertEqual(först["city"], "Gävle")
        self.assertEqual(först["postal_code"], "80281")
        self.assertEqual(först["address"], "Gestrikegatan 11")
        self.assertEqual(först["latitude"], 60.6749)
        self.assertTrue(först["active"])

    def test_nollkoordinater_ar_okand_position_inte_atlanten(self):
        butiker = _axfood_butiker(svar("axfood_butiker"))
        self.assertIsNone(butiker[1]["latitude"])
        self.assertIsNone(butiker[1]["longitude"])
        self.assertFalse(butiker[1]["active"])


class AxfoodKategoritradet(unittest.TestCase):
    def setUp(self):
        self.löv = flatten_category_tree(svar("axfood_kategoritrad"))

    def test_bara_lov_och_bara_giltiga(self):
        # En förälders listning är unionen av barnens - båda nivåerna hade
        # hämtat varje produkt två gånger. valid=false hämtas inte alls.
        self.assertEqual([löv["slug"] for löv in self.löv],
                         ["c/kott-chark-fagel/fagel/farsk-fagel", "c/mejeri-ost-agg/mjolk"])

    def test_stigen_bar_hela_vagen_men_inte_rotnoden(self):
        # Roten är "Alla varor"-behållaren. Hamnar den först i varje stig blir
        # ingen kategori jämförbar med någon annan kedjas - och kategoristigen
        # är det ENDA som är jämförbart mellan kedjorna: koderna är inte det
        # ("Färsk fågel" är N010101 hos Willys och N010403 hos Hemköp).
        self.assertEqual(self.löv[0]["path"], "Kött, chark & fågel > Fågel > Färsk fågel")
        self.assertEqual(self.löv[1]["path"], "Mejeri, ost & ägg > Mjölk")
        self.assertEqual(self.löv[0]["code"], "N010101")
        self.assertNotIn("Alla varor", self.löv[0]["path"])


class EttOmdoptFaltGorProvetRott(unittest.TestCase):
    """Kontraktet prövas trasigt, inte bara helt.

    Varje fall döper om ETT fält i det sparade svaret - precis det en kedja
    gör den dag den byter plattform - och kräver att kontraktet faller.
    Utan de här fallen hade sviten kunnat vara grön mot ett svar där varenda
    produkt bär `regular_price=None`.
    """

    def _willys(self, data):
        return axfood_produkter(WillysProvider(), data)

    def test_omdopt_prisfalt_ger_inget_pris_alls(self):
        data = svar("willys_sok")
        for produkt in data["results"]:
            produkt["price"] = produkt.pop("priceValue")
        produkter = self._willys(data)
        # Inget undantag. Ingen tom lista. Bara priser som inte finns - och
        # det är därför kontraktet måste vara ett påstående om VÄRDET.
        self.assertEqual([p.regular_price for p in produkter], [None, None, None])
        with self.assertRaises(AssertionError):
            self.assertEqual(produkter[0].regular_price, 16.50)

    def test_omdopt_kuvert_ger_noll_produkter(self):
        data = svar("willys_sok")
        data["items"] = data.pop("results")
        self.assertEqual(self._willys(data), [])

    def test_omdopt_kampanjfalt_gor_varje_kampanj_osynlig(self):
        data = svar("willys_sok")
        for produkt in data["results"]:
            produkt["promotions"] = produkt.pop("potentialPromotions")
        kyckling = self._willys(data)[1]
        self.assertIsNone(kyckling.campaign_price)
        self.assertIsNone(kyckling.member_price)

    def test_flyttad_bild_url_tar_med_sig_gtin(self):
        # GTIN läses ur bildens URL. Byter Axfood bildvärd tappas varje
        # kopplingsnyckel mellan kedjorna - och jämförelsen blir tyst tunnare.
        data = svar("willys_sok")
        for produkt in data["results"]:
            produkt["image"] = {"href": produkt["image"]["url"]}
            produkt.pop("thumbnail", None)
        self.assertEqual([p.gtin for p in self._willys(data)], [None, None, None])

    def test_omdopt_prisblock_hos_citygross(self):
        data = svar("citygross_sok")
        for produkt in data["searchResults"]["products"]:
            produkt["storeDetails"] = produkt.pop("productStoreDetails")
        produkter = citygross_produkter(CityGrossProvider(), data)
        self.assertEqual([p.regular_price for p in produkter], [None, None])

    def test_omdopt_kuvert_hos_citygross(self):
        data = svar("citygross_sok")
        data["results"] = data.pop("searchResults")
        self.assertEqual(citygross_produkter(CityGrossProvider(), data), [])

    def test_ogiltig_gtin_lagras_aldrig_som_gissning(self):
        # En felaktig GTIN slår ihop två olika varor under tier-1-matchningen.
        # Hellre ingen nyckel än fel nyckel.
        self.assertIsNone(gtin_from_image_url(
            "https://assets.axfood.se/image/upload/f_auto,t_200/07340083443891_C1L1_s01"))
        self.assertIsNone(normalize_gtin14("7340083443891"))

    def test_kampanj_utan_prisvarde_raknas_inte_som_kampanj(self):
        self.assertEqual(split_promotions([{"campaignType": "OFFER", "price": {}}]),
                         (None, None, None))
        self.assertEqual(extract_prices({"prices": {}}),
                         {"regular_price": None, "campaign_price": None, "member_price": None,
                          "multibuy_price": None, "unit_price": None})


def _axfood_butiker(data):
    """Butikskartläggningen ur AxfoodProvider.get_stores, utan nätanropet.

    Koden är kopierad hit MEDVETET INTE - den anropas. `get_stores` börjar
    med `self._request(...)`, så vägen in är en leverantör vars `_request`
    svarar med det sparade svaret i stället för med Willys.
    """
    class UtanNat(AxfoodProvider):
        name = "Willys"
        base_url = "https://www.willys.se/axfood/rest/v1"

        def _request(self, url):
            return data

    return [{"external_store_id": b.external_store_id, "name": b.name, "city": b.city,
             "postal_code": b.postal_code, "address": b.address, "latitude": b.latitude,
             "longitude": b.longitude, "active": b.active}
            for b in UtanNat().get_stores()]


if __name__ == "__main__":
    unittest.main()
