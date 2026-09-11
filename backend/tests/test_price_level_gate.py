# -*- coding: utf-8 -*-
"""D2 - en kedja vars priser råkar delas med tio får inte kröna Billigast.

Kvalitetsgaten kontrollerade två saker: att varje RAD var ett rimligt pris
(0 < pris <= 30 000) och att körningen levererade tillräckligt MÅNGA rader
(>= 30 % av föregående). Ingenstans jämfördes nytt pris mot gammalt för
samma produkt.

Det gör en decimalbugg osynlig. Öre tolkat som kronor, eller en källa som
byter fältform så att 12,90 kommer in som 1,29: varje rad är sund var för
sig, antalet rader är exakt som i går, gaten ger 100 % och 30 %-regeln ser
en komplett katalog. Kedjan publiceras med en tiondel av sina riktiga
priser, kröns Billigast, och ingenting larmar. Matjakts hela
värdeerbjudande är den frågan.

Testerna nedan låser båda halvorna av det nya måttet - att det fäller det
som ska fällas, och att det INTE fäller vanliga nätter, en första import
eller ett urval som är för litet för att bedöma.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.grocery import api as grocery_api  # noqa: E402
from services.grocery import register  # noqa: E402
from services.grocery.models import RawProduct  # noqa: E402
from services.grocery.publish import (  # noqa: E402
    PRICE_LEVEL_MIN_SAMPLE, price_level_reason, price_level_shift, publish_run)
from services.grocery.store import GroceryStore  # noqa: E402


def _raw(index: int, price: float) -> RawProduct:
    return RawProduct(
        chain="Willys", external_product_id=f"w-{index}", name=f"Vara {index}",
        store_id="2132", store_name="Willys Gävle", gtin=None,
        size="1 kg", quantity=1000.0, unit="g", category="Skafferi",
        regular_price=price)


# Ett riktigt sortiment har inte ett enda pris. Priserna nedan spänner
# 7,50-249 kr så medianen mäter en NIVÅ och inte ett tal.
def _sortiment(antal: int) -> list[float]:
    return [round(7.5 + (index * 4.7) % 242, 2) for index in range(antal)]


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "grocery.db"
        self._real_path = grocery_api.DB_PATH
        grocery_api.DB_PATH = self.db_path
        self.addCleanup(lambda: setattr(grocery_api, "DB_PATH", self._real_path))
        self.db = GroceryStore(self.db_path)
        self.addCleanup(self.db.close)
        register.ensure_chains(self.db)
        self.butik = self.db.upsert_store(
            chain="Willys", external_store_id="2132", name="Willys Gävle",
            pricing_scope=register.CHAIN_PRICING_SCOPE["Willys"])
        self.produkter = []

    def gällande_priser(self, priser: list[float]):
        """Det dataset kunderna ser just nu."""
        for index, pris in enumerate(priser):
            produkt = self.db.find_or_create_product(_raw(index, pris))
            self.produkter.append(produkt)
            self.db.upsert_current_price(product_id=produkt.id, store_id=self.butik.id,
                                         regular_price=pris, source="axfood:2132")

    def kör(self, priser: list[float], **kwargs):
        """Stagear en ny körning med exakt de priserna, i produktordning."""
        run = self.db.start_collector_run(chain="Willys", store_id=self.butik.id)
        for produkt, pris in zip(self.produkter, priser):
            self.db.stage_price(run_id=run.id, store_id=self.butik.id,
                                product_id=produkt.id, regular_price=pris,
                                source="axfood:2132")
        return publish_run(self.db, run.id, self.butik.id, "Willys",
                           source="axfood:2132", **kwargs)


class ADatasetDividedByTenIsNeverPublished(_Base):
    """ACCEPTANSEN, ordagrant: ett dataset där alla priser dividerats med
    tio ska stoppa publiceringen."""

    def test_every_price_divided_by_ten_stops_the_publish(self):
        priser = _sortiment(60)
        self.gällande_priser(priser)

        utfall = self.kör([round(pris / 10, 2) for pris in priser])

        self.assertFalse(utfall["published_ok"], utfall.get("message"))
        # Varje RAD var sund och ALLA rader kom fram: det är precis därför
        # de två gamla gaterna inte kunde se det här.
        self.assertEqual(utfall["gatePercent"], 100.0)
        self.assertEqual(utfall["staged"], 60)
        self.assertIn("prisnivån", utfall["message"])
        self.assertEqual(utfall["priceLevel"]["compared"], 60)
        self.assertAlmostEqual(utfall["priceLevel"]["medianRatio"], 0.1, places=2)

    def test_the_customers_keep_yesterdays_dataset(self):
        """Att neka publicering är bara halva jobbet - det gamla datasetet
        måste stå kvar orört, annars är botemedlet värre än sjukdomen."""
        priser = _sortiment(60)
        self.gällande_priser(priser)
        self.kör([round(pris / 10, 2) for pris in priser])

        for produkt, pris in zip(self.produkter, priser):
            self.assertEqual(
                self.db.get_current_price(produkt.id, self.butik.id).regular_price, pris)

    def test_a_blocked_partial_run_is_checked_too(self):
        """En källa som avbröt sig själv ger förväntat FÅ rader - men en
        tiondel av rätt pris är lika fel på sextio rader som på tolvtusen.
        Nivågaten gäller därför även blocked, till skillnad från
        30 %-regeln."""
        priser = _sortiment(60)
        self.gällande_priser(priser)

        utfall = self.kör([round(pris / 10, 2) for pris in priser], blocked=True)

        self.assertFalse(utfall["published_ok"], utfall.get("message"))
        self.assertIn("prisnivån", utfall["message"])

    def test_a_tenfold_increase_is_refused_the_same_way(self):
        """Felet har ingen favoritriktning: kronor lästa som öre är samma
        bugg spegelvänd, och en kedja som plötsligt ser tio gånger dyrare ut
        får inte heller publiceras."""
        priser = _sortiment(60)
        self.gällande_priser(priser)

        utfall = self.kör([round(pris * 10, 2) for pris in priser])

        self.assertFalse(utfall["published_ok"], utfall.get("message"))
        self.assertAlmostEqual(utfall["priceLevel"]["medianRatio"], 10.0, places=1)


class HalfTheCatalogueMovingTogetherIsAlsoRefused(_Base):
    """Medianen ensam räcker inte. Rör sig knappt hälften av raderna kraftigt
    åt samma håll medan resten står still ligger medianen kvar på 1,0 - och
    det är ändå inte en normal natt."""

    def test_more_than_forty_percent_moving_the_same_way_stops_the_publish(self):
        priser = _sortiment(100)
        self.gällande_priser(priser)

        # 45 varor ner 30 %, 55 orörda -> medianen är exakt 1,0.
        nya = [round(pris * 0.7, 2) if index < 45 else pris
               for index, pris in enumerate(priser)]
        utfall = self.kör(nya)

        self.assertEqual(utfall["priceLevel"]["medianRatio"], 1.0)
        self.assertFalse(utfall["published_ok"], utfall.get("message"))
        self.assertIn("åt samma håll", utfall["message"])
        self.assertEqual(utfall["priceLevel"]["movedDownShare"], 0.45)

    def test_a_normal_campaign_week_still_publishes(self):
        """Motpolen, och den som avgör om gaten går att ha på: en vanlig
        natt där en fjärdedel av sortimentet sänks och resten rör sig några
        ören ska publiceras precis som förut."""
        priser = _sortiment(100)
        self.gällande_priser(priser)

        nya = [round(pris * 0.75, 2) if index < 25 else round(pris * 1.01, 2)
               for index, pris in enumerate(priser)]
        utfall = self.kör(nya)

        self.assertTrue(utfall["published_ok"], utfall.get("message"))
        self.assertEqual(utfall["published"], 100)


class TheGateNeverFiresWhenTheLevelCannotBeJudged(_Base):
    """"Vet inte" är inte "allt är fel". En gate som fäller på avsaknad av
    underlag hade gjort en första import omöjlig."""

    def test_a_first_import_into_an_empty_store_publishes(self):
        priser = _sortiment(60)
        for index, pris in enumerate(priser):
            self.produkter.append(self.db.find_or_create_product(_raw(index, pris)))

        utfall = self.kör(priser)

        self.assertTrue(utfall["published_ok"], utfall.get("message"))
        self.assertIsNone(utfall["priceLevel"])
        self.assertEqual(utfall["published"], 60)

    def test_too_few_shared_products_is_not_judged(self):
        """Under minimiurvalet säger måttet ingenting, och då fäller det
        ingenting - inte ens ett dataset delat med tio. Hellre det än en
        gate som slår slumpmässigt på en handfull rader."""
        antal = PRICE_LEVEL_MIN_SAMPLE - 1
        priser = _sortiment(antal)
        self.gällande_priser(priser)

        utfall = self.kör([round(pris / 10, 2) for pris in priser])

        self.assertIsNone(utfall["priceLevel"])
        self.assertTrue(utfall["published_ok"], utfall.get("message"))

    def test_the_sample_is_the_shared_products_not_the_row_count(self):
        """En körning med gott om rader men nästan ingen överlappning mot
        det gällande datasetet kan inte heller bedömas."""
        self.gällande_priser(_sortiment(60))
        färska = []
        for index in range(200, 260):
            färska.append(self.db.find_or_create_product(_raw(index, 20.0)))
        self.produkter = färska

        utfall = self.kör([2.0] * 60, blocked=True)

        self.assertIsNone(utfall["priceLevel"])
        self.assertTrue(utfall["published_ok"], utfall.get("message"))


class TheMeasureItself(_Base):
    """Måttets kanter, direkt mot funktionen - lättare att läsa än via en
    hel publicering, och de säger vad tröskeln faktiskt betyder."""

    def test_an_unchanged_catalogue_measures_as_unchanged(self):
        priser = _sortiment(60)
        self.gällande_priser(priser)
        rader = [({"product_id": produkt.id}, {"regular_price": pris})
                 for produkt, pris in zip(self.produkter, priser)]

        skift = price_level_shift(self.db, self.butik.id, rader)

        self.assertEqual(skift["medianRatio"], 1.0)
        self.assertEqual(skift["movedUpShare"], 0.0)
        self.assertEqual(skift["movedDownShare"], 0.0)
        self.assertIsNone(price_level_reason(skift))

    def test_no_verdict_without_a_measurement(self):
        self.assertIsNone(price_level_reason(None))

    def test_a_campaign_only_row_is_not_compared_as_a_regular_price(self):
        """Kampanjer utelämnas med flit: de flyttar enskilda varor 30-50 %
        helt lagligt. En rad utan ordinarie pris får därför inte smyga in i
        nivåmåttet som om den vore ett hyllpris."""
        priser = _sortiment(60)
        self.gällande_priser(priser)
        rader = [({"product_id": produkt.id}, {"regular_price": None})
                 for produkt in self.produkter]

        self.assertIsNone(price_level_shift(self.db, self.butik.id, rader))


if __name__ == "__main__":
    unittest.main()
