# -*- coding: utf-8 -*-
"""C10: auditens smakordsflagga var delsträngsmatchning.

`any(word in _fold(productName) for word in FLAVOR_SUSPECTS)` frågade bara om
bokstäverna fanns någonstans i strängen. `"te "` finns inuti
`"penne rigaTE Pasta"`, och **75 av 114** `smakords_misstanke` i
produktionsauditen var därför "Pasta -> Penne Rigate Pasta" - rena falsklarm.

Det är exakt den bugg motorn själv övergav när `_exclusion_hit` skrevs:
"läsk" ryms i "fläskfilé", och varje fläskprodukt exkluderades som läsk. Den
regeln finns redan, är genomtänkt och testad, och auditen använder den nu.

Konsekvensen av felet var inte ett fel pris utan LARMTRÖTTHET: 114 flaggor
ingen orkar läsa, och en riktig träff drunknar. Testerna nedan låser båda
halvorna - att falsklarmen är borta OCH att de riktiga träffarna är kvar.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.grocery.audit import (  # noqa: E402
    FLAVOR_MIN_COMPOUND_LENGTH, FLAVOR_SUSPECTS, flavor_suspect)


# Den gamla regeln, ordagrant, så skillnaden är mätbar och inte en åsikt.
def _substring_rule(product_name: str) -> bool:
    from services.grocery.pricing import _fold
    return any(word in _fold(product_name) for word in ["knäcke", "bulle", "kaka", "skorpa",
                                                        "müsli", "godis", "glass", "te ",
                                                        "dryck", "yoghurt", "gröt", "chips"])


class TheAcceptanceCase(unittest.TestCase):
    def test_penne_rigate_pasta_is_not_flagged(self):
        """Acceptanskriteriet, ordagrant ur uppdraget."""
        self.assertFalse(flavor_suspect("Penne Rigate Pasta"))

    def test_the_old_rule_did_flag_it(self):
        """Kontrollen som visar att det ÄR den här buggen som lagas."""
        self.assertTrue(_substring_rule("Penne Rigate Pasta"))


# Riktiga svenska produktnamn. Vänsterkolumnen är namnet, högerkolumnen om
# det SKA flaggas som ett smaksord.
CASES = [
    # Falsklarmen som fyllde produktionsauditen: "te" inuti ett längre ord.
    ("Penne Rigate Pasta", False),
    ("Pasta Penne Rigate 500 g", False),
    ("Rigatoni Durumvete", False),
    ("Tagliatelle Äggpasta", False),
    ("Latte Macchiato", False),
    ("Arrabbiata Pastasås", False),
    # Riktiga träffar - hela ordet.
    ("Grönt Te Citron", True),
    ("Earl Grey Te 20-pack", True),
    # Riktiga träffar - svensk sammansättning, som ordgränsregeln finns för.
    ("Kanelbulle", True),
    ("Havregröt Original", True),
    ("Chokladkaka Mörk 70%", True),
    ("Knäckebröd Råg", True),
    ("Frukostmüsli Nötter", True),
    ("Grekisk Matyoghurt 10%", True),
    ("Potatischips Sourcream", True),
    ("Gräddglass Vanilj", True),
    ("Lakritsgodis Salt", True),
    ("Havredryck Barista", True),
    # Vanliga råvaror som aldrig fick flaggas och inte heller gör det.
    ("Tomat Runda Sverige Klass 1", False),
    ("Kycklingfilé Färsk", False),
    ("Potatis Fast Sverige", False),
    ("Digestive Kex", False),
    # Motorns egen undantagslista gäller också här, och ska göra det:
    # "Tortillachips" är en riktig receptingrediens (tacogratäng) vars EGET
    # huvud är det uteslutna ordet. EXCLUSION_SUFFIX_OVERRIDES säger redan
    # det, och auditen ärver beslutet i stället för att ha en egen åsikt.
    ("Tortillachips Salted", False),
    # Ordlistan är oförändrad i övrigt, och "skorpa" står i singular medan
    # hyllan skriver "Skorpor". Den luckan fanns före C10 och finns kvar -
    # att laga den gör flaggan HÖGLJUDDARE, vilket är ett eget beslut och
    # inte det här paketet.
    ("Skorpor Vetekrans", False),
]


class TheFlavourRule(unittest.TestCase):
    def test_every_case(self):
        for name, expected in CASES:
            with self.subTest(name=name):
                self.assertEqual(flavor_suspect(name), expected)

    def test_it_removes_every_false_alarm(self):
        """Det flaggan fanns för att sluta göra: ingen av de falska får vara
        kvar, och var och en av dem larmade förr."""
        for name, expected in CASES:
            if expected:
                continue
            with self.subTest(name=name):
                self.assertFalse(flavor_suspect(name))
        false_alarms = [name for name, expected in CASES
                        if not expected and _substring_rule(name)]
        self.assertEqual(false_alarms, ["Penne Rigate Pasta", "Pasta Penne Rigate 500 g",
                                        "Latte Macchiato", "Tortillachips Salted"],
                         "fixturen måste innehålla de falsklarm som fanns")

    def test_the_rule_lands_exactly_on_the_truth(self):
        new = {name for name, _ in CASES if flavor_suspect(name)}
        truth = {name for name, expected in CASES if expected}
        self.assertEqual(new, truth)

    def test_an_empty_name_is_not_a_suspect(self):
        self.assertFalse(flavor_suspect(""))
        self.assertFalse(flavor_suspect(None))


class TheDeadWords(unittest.TestCase):
    """Andra halvan av samma bugg, hittad när fixturen ovan kördes mot den
    gamla regeln: den jämförde OFOLDADE sökord mot ett foldat produktnamn.

    "knäcke", "müsli" och "gröt" foldas till "knacke", "musli" och "grot" -
    och kunde därför aldrig finnas i ett namn som redan hade tappat sina
    prickar. Tre av tolv smaksord var döda regler. Flaggan var alltså
    samtidigt för högljudd (te) och helt tyst (de accenttyngda), vilket är
    värsta möjliga kombination för något som ska läsas av en människa.
    Samma accentbugg som en gång tystade varenda namnregel med å/ä/ö."""

    DEAD = ["Knäckebröd Råg", "Frukostmüsli Nötter", "Havregröt Original"]

    def test_the_old_rule_was_silent_on_every_accented_word(self):
        for name in self.DEAD:
            with self.subTest(name=name):
                self.assertFalse(_substring_rule(name))

    def test_the_new_rule_hears_them(self):
        for name in self.DEAD:
            with self.subTest(name=name):
                self.assertTrue(flavor_suspect(name))


class TheShortWordRule(unittest.TestCase):
    """"te" är för kort för att vara ett sammansättningsled. Ordgränsregeln
    ensam räcker alltså inte - dess suffixhalva säger sant om rigaTE."""

    def test_te_is_the_short_word_the_rule_exists_for(self):
        short = [word for word in FLAVOR_SUSPECTS if len(word) < FLAVOR_MIN_COMPOUND_LENGTH]
        self.assertEqual(short, ["te"])

    def test_the_trailing_space_hack_is_gone(self):
        """"te " var en handrullad ordgräns som bara fungerade åt ett håll -
        den stoppade "tepåse" men inte "rigate pasta"."""
        self.assertNotIn("te ", FLAVOR_SUSPECTS)

    def test_a_word_boundary_alone_would_still_flag_rigate(self):
        """Bevis för varför den korta regeln behövs: _exclusion_hit ensam
        säger fortfarande sant om "Penne Rigate Pasta"."""
        from services.grocery.pricing import _exclusion_hit, _fold, _words
        name = "Penne Rigate Pasta"
        self.assertTrue(_exclusion_hit(_fold(name), _words(name), "te"))


if __name__ == "__main__":
    unittest.main()
