# -*- coding: utf-8 -*-
"""Tests for the automatic recipe-image pipeline.

Every case here is a real failure the pipeline produced against live
Wikimedia Commons before it was fixed. Nothing here touches the network:
scoring and licence checking are pure functions, which is most of the risk.

The rule these protect: a photo of the WRONG dish is worse than no photo. It
makes the app look careless in the one place a food app cannot afford to.
"""

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.recipes import RecipeStore, images  # noqa: E402
from services.recipes.api import RECIPE_SOURCE_DIR  # noqa: E402
from services.recipes.images import (  # noqa: E402
    COMMERCIAL_LICENCES, build_query, english_terms, placeholder, score_candidate,
)


def recipe(name, *ingredients):
    return {"name": name, "ingredients": [{"name": i} for i in ingredients]}


class LicenceTest(unittest.TestCase):
    def test_accepts_licences_that_allow_commercial_use(self):
        for licence in ["CC0", "CC BY 2.0", "CC BY-SA 4.0", "Public domain",
                        "PD-old", "No restrictions"]:
            self.assertTrue(COMMERCIAL_LICENCES.match(licence), licence)

    def test_refuses_non_commercial_and_unstated_licences(self):
        """Commons hosts plenty of files we may not use. "It came from
        Commons" proves nothing on its own."""
        for licence in ["CC BY-NC 4.0", "CC BY-NC-SA 3.0", "Fair use",
                        "All rights reserved", "", "Unknown"]:
            self.assertFalse(COMMERCIAL_LICENCES.match(licence), licence)


class QueryTest(unittest.TestCase):
    def test_searches_for_the_dish_not_the_whole_sentence(self):
        """"lasagne med spenat och ricotta" finds nothing; "lasagne" finds
        lasagne."""
        self.assertEqual(build_query(recipe("Lasagne med spenat", "Spenat"))[0], "Lasagne")

    def test_adds_the_english_term_for_swedish_dishes(self):
        """Commons is titled overwhelmingly in English - a Swedish dish name
        misses thousands of perfectly good photos."""
        self.assertIn("pancakes", build_query(recipe("Pannkakor", "Ägg")))

    def test_english_term_follows_compound_heads(self):
        self.assertIn("chicken stew", english_terms("Kycklinggryta"))
        self.assertIn("soup", english_terms("Rotfruktssoppa"))


class ScoringTest(unittest.TestCase):
    def test_a_matching_dish_scores(self):
        self.assertGreaterEqual(
            score_candidate("Meaty Lasagna 8of8.jpg", recipe("Lasagne", "Köttfärs")), 2.0)

    def test_potato_pancakes_are_not_pancakes(self):
        """The English layer's own failure: "Potato pancakes" contains
        "pancakes", but it is raggmunk. The longest matching dish term wins,
        which settles it without a list of special cases."""
        self.assertEqual(
            score_candidate("Potato pancakes with meat.jpg", recipe("Pannkakor", "Ägg")), 0.0)

    def test_and_raggmunk_still_gets_them(self):
        self.assertGreaterEqual(
            score_candidate("Potato pancakes with meat.jpg", recipe("Raggmunk", "Potatis")), 2.0)

    def test_a_short_generic_dish_word_is_not_evidence(self):
        """"Fisk" is four letters and also a surname - it matched
        "Fisk, Joel H - 1st Cavalry", a photograph of a man."""
        self.assertEqual(
            score_candidate("(Vermont) Fisk, Joel H - 1st Cavalry.jpg",
                            recipe("Fisk med potatis", "Torskfilé")), 0.0)

    def test_a_specific_fish_dish_still_scores(self):
        self.assertGreater(
            score_candidate("Torskfilé med potatismos.jpg",
                            recipe("Torskfilé med potatismos", "Torskfilé")), 0.0)

    def test_non_photographs_are_rejected(self):
        for title in ["Lasagne restaurant menu.jpg", "Lasagne logo.png",
                      "Lasagne packaging box.jpg", "Lasagne illustration.svg"]:
            self.assertEqual(score_candidate(title, recipe("Lasagne", "Köttfärs")), 0.0, title)

    def test_raw_ingredient_photos_are_rejected(self):
        """A recipe card wants the finished dish, not the raw mince."""
        self.assertEqual(
            score_candidate("Raw minced beef.jpg", recipe("Köttfärssås", "Köttfärs")), 0.0)


class PlaceholderTest(unittest.TestCase):
    def test_a_recipe_without_an_image_says_so(self):
        """Explicit, so the gap can be found and filled later rather than
        discovered by a user."""
        gap = placeholder(recipe("Köttfärslimpa", "Köttfärs"))
        self.assertEqual(gap["imageStatus"], "needs_image")
        self.assertIsNone(gap["image"])
        self.assertIsNone(gap["imageLicense"])

    def test_it_still_carries_alt_text(self):
        self.assertTrue(placeholder(recipe("Köttfärslimpa", "Köttfärs"))["imageAlt"])


class ProvenanceInTheBankTest(unittest.TestCase):
    """M2: varje rad i `recipes` som bär en bild bär också sin licens.

    Repot är publikt och landningssidan krediterar redan Pexels. En bild vi
    inte kan namnge licensen på är en juridisk skuld, inte en bild - och den
    sortens rad kommer aldrig in med buller. Den kommer in för att någon
    klistrade in en URL som såg bra ut.

    Testet byggs mot den SPÅRADE källan (backend/recipe_sources/) och prövas
    på den riktiga tabellen, inte på JSON-dictarna: det är `recipes` som
    servern svarar ur, och kolumnen som ska vara ifylld är image_license.
    backend/data/recipes.db är gitignorerad och finns inte i CI, så den
    byggs här i en tempkatalog ur exakt de filer som ligger i git.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.store = RecipeStore(Path(cls._tmp.name) / "recipes.db")
        for path in sorted(RECIPE_SOURCE_DIR.glob("*.json")):
            for recipe_row in json.loads(path.read_text(encoding="utf-8")):
                cls.store.upsert_recipe(recipe_row)

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        cls._tmp.cleanup()

    def _rows(self, where=""):
        return list(self.store._connection.execute(
            f"SELECT id, name, image, image_source, image_source_url, image_credit, "
            f"image_license, image_status FROM recipes {where}"))

    def test_the_bank_is_actually_loaded(self):
        """Skyddar kraven nedan från att bli tomma och därmed meningslösa."""
        self.assertGreater(len(self._rows()), 200)
        self.assertGreater(
            len(self._rows("WHERE image IS NOT NULL AND image <> ''")), 200)

    def test_every_row_with_an_image_states_its_licence(self):
        missing = [(row["id"], row["image"]) for row
                   in self._rows("WHERE image IS NOT NULL AND TRIM(image) <> ''")
                   if not (row["image_license"] or "").strip()]
        self.assertEqual(missing, [],
                         "recept med bild men utan image_license: "
                         + ", ".join(rid for rid, _ in missing))

    def test_a_licence_is_useless_without_a_source_to_check_it_against(self):
        """CC BY och CC BY-SA kräver namngivning. Står bara licensen kvar är
        raden ett påstående ingen kan kontrollera."""
        thin = [row["id"] for row
                in self._rows("WHERE image IS NOT NULL AND TRIM(image) <> ''")
                if not (row["image_source_url"] or "").strip()
                or not (row["image_credit"] or "").strip()]
        self.assertEqual(thin, [])

    def test_a_stated_licence_is_one_we_may_actually_ship(self):
        refused = [(row["id"], row["image_license"]) for row
                   in self._rows("WHERE image IS NOT NULL AND TRIM(image) <> ''")
                   if not COMMERCIAL_LICENCES.match(row["image_license"] or "")]
        self.assertEqual(refused, [])

    def test_a_row_without_an_image_is_marked_so_the_gap_can_be_found(self):
        for row in self._rows("WHERE image IS NULL OR TRIM(image) = ''"):
            self.assertEqual(row["image_status"], "needs_image", row["id"])

    def test_the_bundled_photos_exist_where_the_app_looks_for_them(self):
        """Bilder vi själva laddat ner ligger i frontend/app/assets/recipes/.
        En rad som pekar på en fil som inte är med i bygget är samma tomma
        bildyta som ingen bild alls - bara svårare att upptäcka."""
        assets = Path(__file__).resolve().parents[2] / "frontend" / "app"
        own = [row for row in self._rows("WHERE image LIKE 'assets/%'")]
        self.assertGreater(len(own), 0)
        for row in own:
            self.assertTrue((assets / row["image"]).is_file(),
                            f"{row['id']} pekar på {row['image']} som inte finns")


class PexelsSourceTest(unittest.TestCase):
    """Pexels is the good source - stock food photography rather than the
    hobby snapshots and species pictures Commons is full of. It needs a key,
    so everything here has to degrade cleanly when there is not one.
    """

    def setUp(self):
        self._original = os.environ.get("PEXELS_API_KEY")
        self.addCleanup(self._restore)

    def _restore(self):
        if self._original is None:
            os.environ.pop("PEXELS_API_KEY", None)
        else:
            os.environ["PEXELS_API_KEY"] = self._original

    def test_no_key_means_no_pexels_search_not_a_crash(self):
        """A missing key must leave the app importing recipes from Commons,
        not fail the whole run - and this must be testable on a machine that
        HAS a key, without touching the network."""
        os.environ["PEXELS_API_KEY"] = ""
        self.assertEqual(images.pexels_key(), "")
        self.assertEqual(images.search_pexels("lasagna"), [])

    def test_the_pexels_licence_is_accepted(self):
        """Without this every Pexels photo would be rejected by the licence
        check and the key would appear not to work."""
        self.assertTrue(COMMERCIAL_LICENCES.match("Pexels License"))

    def test_the_key_is_never_part_of_the_stored_image_data(self):
        """A key that reaches the recipe data reaches the frontend."""
        source = (Path(__file__).resolve().parents[1] /
                  "services" / "recipes" / "images.py").read_text(encoding="utf-8")
        stored = source[source.index("def find_image"):]
        self.assertNotIn("pexels_key()", stored,
                         "bildmetadatan får aldrig innehålla nyckeln")

    def test_key_is_read_only_from_the_environment_or_dotenv(self):
        source = (Path(__file__).resolve().parents[1] /
                  "services" / "recipes" / "images.py").read_text(encoding="utf-8")
        self.assertIn('os.environ["PEXELS_API_KEY"]', source)
        # No hardcoded key-shaped literal anywhere.
        self.assertIsNone(re.search(r'["\'][A-Za-z0-9]{40,}["\']', source))


if __name__ == "__main__":
    unittest.main()
