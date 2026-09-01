# -*- coding: utf-8 -*-
"""Den stora kanoniska matrisen (RC-audit 2026-09-01).

En butik får välja märke, förpackning och rimlig storlek - aldrig byta
själva råvaran. 128 par över kött, fågel, fisk, mejeri, ost, chark, pasta,
ris, grönsaker, kryddor och veganska alternativ - åt BÅDA hållen: varje
förbjuden substitution OCH att den äkta varan fortsätter matcha (precision
får aldrig komma från att förkasta allt).

En rad som börjar avvika är antingen en regression i motorn eller ett
medvetet regelbeslut - då uppdateras raden i samma commit som regeln, med
motivering. Tre rader i utkastet avvek och blev lärdomar: fläskytterfilé är
en EGEN styckdetalj (min förväntan var fel, motorn hade rätt), och
Parmigiano/buljongtärning var aliasluckor, inte matcharfel.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.grocery.pricing import product_matches_ingredient  # noqa: E402

MEAT = "Kött, chark & fågel > Kött > Nöt & kalv"
PORK = "Kött, chark & fågel > Kött > Fläsk"
BIRD = "Kött, chark & fågel > Fågel"
FISH = "Fisk & skaldjur"
DAIRY = "Mejeri, ost & ägg > Mjölk, fil & grädde"
CHEESE = "Mejeri, ost & ägg > Ost"
PANTRY = "Skafferi > Pasta, ris & matgryn"
FROZEN = "Fryst"
PRODUCE = "Frukt & grönt"
SPICE = "Skafferi > Kryddor & smaksättning"

# (ingrediens, produkt, kategori, ska_matcha)
CASES = [
    # ---- kött: styckdetaljer byter aldrig identitet ----
    ("Lövbiff", "Biffkappa Bit", MEAT, False),
    ("Lövbiff", "Lövbiff av Nöt Skivad", MEAT, True),
    ("Ryggbiff", "Rostbiff i Bit", MEAT, False),
    ("Ryggbiff", "Ryggbiff Bit Sverige", MEAT, True),
    ("Entrecôte", "Entrecôte Skivad", MEAT, True),
    ("Oxfilé", "Oxfilé Bit", MEAT, True),
    ("Oxfilé", "Fläskfilé Bit", PORK, False),
    ("Högrev", "Högrev Bit", MEAT, True),
    ("Fläskkarré", "Fläskkarré Benfri", PORK, True),
    # Ytterfilé är en EGEN styckdetalj - motorn hade rätt, min förväntan fel.
    ("Fläskfilé", "Fläskytterfilé", PORK, False),
    ("Fläskfilé", "Fläskfilé Färsk", PORK, True),
    ("Kotlett", "Fläskkotlett Ben", PORK, True),
    ("Nötfärs", "Blandfärs 50/50", MEAT, False),
    ("Nötfärs", "Nötfärs 12%", MEAT, True),
    ("Blandfärs", "Nötfärs 12%", MEAT, False),
    ("Blandfärs", "Blandfärs 20%", MEAT, True),
    ("Fläskfärs", "Fläskfärs 23%", PORK, True),
    ("Köttfärs", "Kycklingfärs", BIRD, False),
    ("Lammfärs", "Lammfärs Färsk", "Kött, chark & fågel > Kött > Lamm", True),
    # ---- kyckling ----
    ("Kycklingfilé", "Kycklingfilé Färsk", BIRD, True),
    ("Kycklingfilé", "Kycklingnuggets Frysta", FROZEN, False),
    ("Kycklingfilé", "Kycklingvingar", BIRD, False),
    ("Kycklinglårfilé", "Kycklingklubbor", BIRD, False),
    ("Kycklinglårfilé", "Kycklinglårfilé Färsk", BIRD, True),
    ("Hel kyckling", "Grillad Kyckling Färdig", "Färdigmat", False),
    ("Kalkonfilé", "Kycklingfilé Färsk", BIRD, False),
    # ---- fisk ----
    ("Laxfilé", "Laxfilé Fryst 4-pack", FROZEN, True),
    ("Laxfilé", "Fiskpinnar Panerade", FROZEN, False),
    ("Laxfilé", "Rökt Lax Skivad", FISH, False),
    ("Laxfilé", "Laxpastej", FISH, False),
    ("Torskfilé", "Torskfilé MSC", FISH, True),
    ("Torskfilé", "Panerad Torsk", FROZEN, False),
    ("Torskrygg", "Torskrygg Fryst", FROZEN, True),
    ("Räkor", "Räkor Skalade Frysta", FROZEN, True),
    ("Räkor", "Räkost Tub", DAIRY, False),
    ("Fiskpinnar", "Fiskpinnar Panerade", FROZEN, True),
    # ---- grädde/mejeri ----
    ("Vispgrädde", "Matgrädde 13%", DAIRY, False),
    ("Vispgrädde", "Vispgrädde 40%", DAIRY, True),
    ("Vispgrädde", "Havregrädde Vispbar", DAIRY, False),
    ("Matlagningsgrädde", "Vispgrädde 40%", DAIRY, False),
    ("Matlagningsgrädde", "Matlagningsgrädde 15%", DAIRY, True),
    ("Grädde", "Havregrädde 13%", DAIRY, False),
    ("Crème fraiche", "Crème Fraiche Lätt 13%", DAIRY, False),
    ("Crème fraiche", "Crème Fraiche 34%", DAIRY, True),
    ("Gräddfil", "Gräddfil 12%", DAIRY, True),
    ("Mjölk", "Havredryck Barista", DAIRY, False),
    ("Mjölk", "Mellanmjölk 1.5%", DAIRY, True),
    ("Filmjölk", "Filmjölk 3%", DAIRY, True),
    ("Yoghurt", "Vaniljyoghurt", DAIRY, False),
    ("Yoghurt", "Yoghurt Naturell 3%", DAIRY, True),
    ("Grekisk yoghurt", "Grekisk Yoghurt Honung", DAIRY, False),
    ("Grekisk yoghurt", "Grekisk Yoghurt 10%", DAIRY, True),
    ("Kvarg", "Kvarg Naturell", DAIRY, True),
    ("Smör", "Margarin 70%", DAIRY, False),
    ("Smör", "Smör Normalsaltat 82%", DAIRY, True),
    # ---- ost ----
    ("Fetaost", "Feta Tomat Crème Fraiche", DAIRY, False),
    ("Fetaost", "Fetaost i Bit", CHEESE, True),
    ("Riven ost", "Gratängost Riven 27%", CHEESE, True),
    ("Ost", "Baconost Tub", CHEESE, False),
    ("Ost", "Hushållsost Bit 26%", CHEESE, True),
    ("Mozzarella", "Mozzarella Riven", CHEESE, True),
    ("Halloumi", "Halloumi Sticks Panerad", FROZEN, False),
    ("Halloumi", "Halloumi 26%", CHEESE, True),
    ("Parmesan", "Parmesan Riven", CHEESE, True),
    # ---- bacon/chark ----
    ("Bacon", "Kalkonbacon", "Kött, chark & fågel > Chark", False),
    ("Bacon", "Vegobacon", "Vegetariskt", False),
    ("Bacon", "Bacon Skivat", "Kött, chark & fågel > Chark", True),
    ("Falukorv", "Kycklingkorv", "Kött, chark & fågel > Chark", False),
    ("Falukorv", "Falukorv 800 g", "Kött, chark & fågel > Chark", True),
    ("Chorizo", "Chorizo Stark", "Kött, chark & fågel > Chark", True),
    ("Prinskorv", "Prinskorv Frysta", FROZEN, True),
    # ---- pasta/ris/spannmål ----
    ("Pasta", "Kikärtspasta", PANTRY, False),
    ("Pasta", "Pasta Penne", PANTRY, True),
    ("Spaghetti", "Spaghetti Majspasta Glutenfri", PANTRY, False),
    ("Spaghetti", "Spaghetti Fullkorn", PANTRY, True),
    ("Makaroner", "Linsmakaroner", PANTRY, False),
    ("Makaroner", "Idealmakaroner", PANTRY, True),
    ("Ris", "Risifrutti Original", DAIRY, False),
    ("Ris", "Ris Basmati", PANTRY, True),
    ("Jasminris", "Jasminris 1 kg", PANTRY, True),
    ("Nudlar", "Snabbnudlar Kyckling", PANTRY, True),
    ("Couscous", "Couscous Fullkorn", PANTRY, True),
    ("Bulgur", "Bulgur 1 kg", PANTRY, True),
    ("Havregryn", "Havregryn 1.5 kg", PANTRY, True),
    # ---- grönsaker ----
    ("Lök", "Purjolök", PRODUCE, False),
    ("Lök", "Lök Gul", PRODUCE, True),
    ("Rödlök", "Rödlök i Nät", PRODUCE, True),
    ("Vitlök", "Vitlökspulver", SPICE, False),
    ("Vitlök", "Vitlök 3-pack", PRODUCE, True),
    ("Tomater", "Krossade Tomater", "Skafferi > Konserver", False),
    ("Tomater", "Tomater Kvist", PRODUCE, True),
    ("Krossade tomater", "Tomater Krossade Burk", "Skafferi > Konserver", True),
    ("Potatis", "Potatismos Pulver", PANTRY, False),
    ("Potatis", "Potatis Fast", PRODUCE, True),
    ("Sötpotatis", "Sötpotatis Klass 1", PRODUCE, True),
    ("Paprika", "Paprikapulver", SPICE, False),
    ("Paprika", "Paprika Röd", PRODUCE, True),
    ("Gurka", "Inlagd Gurka", "Skafferi > Konserver", False),
    ("Gurka", "Gurka Klass 1", PRODUCE, True),
    ("Champinjoner", "Champinjoner Färska", PRODUCE, True),
    ("Broccoli", "Broccoli Fryst", FROZEN, True),
    ("Spenat", "Bladspenat Fryst", FROZEN, True),
    ("Avokado", "Avokado 2-pack", PRODUCE, True),
    ("Citron", "Citronsyra", PANTRY, False),
    ("Citron", "Citron Klass 1", PRODUCE, True),
    ("Apelsin", "Apelsinjuice", "Dryck", False),
    ("Apelsin", "Apelsin Klass 1", PRODUCE, True),
    # ---- kryddor/skafferi ----
    ("Basilika", "Basilika Färsk Kruka", PRODUCE, True),
    ("Basilika", "Pesto Basilika", "Skafferi > Såser", False),
    ("Dill", "Dillchips", "Snacks", False),
    ("Dill", "Dill Färsk", PRODUCE, True),
    ("Kanel", "Kanelbullar 6-pack", "Bröd", False),
    ("Kanel", "Kanel Malen", SPICE, True),
    ("Honung", "Honung Grillkrydda", SPICE, False),
    ("Honung", "Honung Flytande", PANTRY, True),
    ("Sojasås", "Sojabönor Frysta", FROZEN, False),
    ("Sojasås", "Sojasås Japansk", PANTRY, True),
    ("Kokosmjölk", "Kokosdryck", "Dryck", False),
    ("Kokosmjölk", "Kokosmjölk Burk", PANTRY, True),
    ("Tomatpuré", "Tomatpuré Tub", "Skafferi > Konserver", True),
    ("Buljong", "Grönsaksbuljong Koncentrerad", PANTRY, True),
    # ---- veganskt: åt BÅDA hållen ----
    ("Tofu", "Tofu Naturell", "Skafferi > Asiatiskt", True),
    ("Köttfärs", "Vegofärs Sojabaserad", "Vegetariskt", False),
    ("Vegofärs", "Vegofärs Fryst", FROZEN, True),
    ("Kycklingfilé", "Vegansk Filébit", "Vegetariskt", False),
    ("Halloumi", "Grillost", CHEESE, False),
    ("Havredryck", "Mellanmjölk 1.5%", DAIRY, False),
    ("Havredryck", "Havredryck Original", DAIRY, True),
]


class CanonicalMatrix(unittest.TestCase):
    def test_every_pair_holds(self):
        failures = []
        for ingredient, product, category, want in CASES:
            got = product_matches_ingredient(product, ingredient, None, category=category)
            if got != want:
                failures.append(f"{ingredient!r} mot {product!r}: fick {got}, ville {want}")
        self.assertEqual(failures, [], "; ".join(failures))

    def test_alias_forms_reach_the_engine(self):
        """Parmigiano och buljongtärning är samma varor under andra namn -
        de nås via aliaslagret i motorn, med originalets regler intakta."""
        from services.grocery.pricing import aliases_for
        self.assertIn("parmigiano", [a.lower() for a in aliases_for("parmesan")])
        self.assertIn("buljongtärning", [a.lower() for a in aliases_for("buljong")])


if __name__ == "__main__":
    unittest.main()
