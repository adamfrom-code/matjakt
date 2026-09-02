# -*- coding: utf-8 -*-
"""Tester för matchningsmotorn.

Recepten här är påhittade och små, med avsikt. Ett test som matchar mot
receptbankens riktiga innehåll går sönder varje gång någon publicerar ett
recept, och säger då ingenting om motorn - bara att banken ändrats.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.shared.canonical import canonical_id  # noqa: E402
from services.shared.matching import (  # noqa: E402
    match_recipe,
    match_recipes,
    resolve_staples,
)
from services.shared.portions import scale_recipe, scaled_amount  # noqa: E402


def recipe(*ingredients, name="Testrätt", recipe_id="test", servings=4):
    """Ett recept med bara det motorn läser."""
    return {
        "id": recipe_id, "name": name, "servings": servings,
        "ingredients": [row if isinstance(row, dict) else {"name": row}
                        for row in ingredients],
    }


GRYTA = recipe(
    {"name": "Kycklingfilé", "amount": 600, "unit": "g"},
    {"name": "Ris", "amount": 250, "unit": "g"},
    {"name": "Paprika", "amount": 2, "unit": "st"},
    {"name": "Crème fraiche", "amount": 2, "unit": "dl"},
    {"name": "Gul lök", "amount": 1, "unit": "st"},
    {"name": "Salt", "pantryStaple": True},
    {"name": "Peppar", "pantryStaple": True},
    name="Kycklinggryta", recipe_id="gryta",
)


class FullMatchTest(unittest.TestCase):
    def test_everything_at_home_can_be_cooked_now(self):
        result = match_recipe(GRYTA, ["Kycklingfilé", "Ris", "Paprika",
                                      "Crème fraiche", "Gul lök"])
        self.assertTrue(result["canCookNow"])
        self.assertEqual(result["missingCount"], 0)
        self.assertEqual(result["matchPercent"], 100)
        self.assertEqual(result["requiredCount"], 7)
        self.assertEqual(result["availableCount"], 7)

    def test_the_milestone_pantry_is_understood(self):
        """Uppgiftens första milstolpe, ordagrant: kyckling, ris, paprika och
        crème fraiche ska matcha ett recept som säger "Kycklingfilé" och
        "Gul lök", och SAKNA gul lök."""
        result = match_recipe(GRYTA, ["kyckling", "ris", "paprika", "creme fraiche"])
        self.assertEqual([row["name"] for row in result["missingIngredients"]], ["Gul lök"])
        self.assertEqual(result["missingCount"], 1)
        self.assertFalse(result["canCookNow"])
        matched = {row["name"]: row["match"] for row in result["availableIngredients"]}
        self.assertEqual(matched["Kycklingfilé"], "generic")
        self.assertEqual(matched["Crème fraiche"], "exact")


class MissingCountTest(unittest.TestCase):
    def test_missing_one(self):
        result = match_recipe(GRYTA, ["Kycklingfilé", "Ris", "Paprika", "Crème fraiche"])
        self.assertEqual(result["missingCount"], 1)
        self.assertEqual(result["missingMainCount"], 1)
        self.assertEqual([row["name"] for row in result["missingIngredients"]], ["Gul lök"])

    def test_missing_three(self):
        result = match_recipe(GRYTA, ["Kycklingfilé", "Ris"])
        self.assertEqual(result["missingCount"], 3)
        self.assertEqual(
            sorted(row["name"] for row in result["missingIngredients"]),
            ["Crème fraiche", "Gul lök", "Paprika"])
        # 4 av 7 täckta (två råvaror + salt och peppar ur skafferigrunden).
        self.assertEqual(result["matchPercent"], 57)

    def test_a_missing_ingredient_keeps_its_amount_and_unit(self):
        """Kompletteringslistan ska kunna säga "600 g kycklingfilé", inte
        bara "kycklingfilé"."""
        missing = match_recipe(GRYTA, ["Ris"])["missingIngredients"]
        chicken = next(row for row in missing if row["name"] == "Kycklingfilé")
        self.assertEqual((chicken["amount"], chicken["unit"]), (600, "g"))
        self.assertEqual(chicken["id"], canonical_id("Kycklingfilé"))


class PantryStapleTest(unittest.TestCase):
    def test_staples_are_covered_without_being_in_the_fridge(self):
        """Ett recept ska inte rankas ned för att salt saknas i en
        registrerad kyl."""
        result = match_recipe(GRYTA, ["Kycklingfilé", "Ris", "Paprika",
                                      "Crème fraiche", "Gul lök"])
        self.assertEqual(sorted(row["name"] for row in result["stapleIngredients"]),
                         ["Peppar", "Salt"])
        self.assertEqual(result["missingCount"], 0)

    def test_the_user_can_declare_they_have_no_salt(self):
        """§6: användaren ska kunna ändra vad som räknas som skafferivara."""
        staples = resolve_staples(exclude=["Salt"])
        result = match_recipe(GRYTA, ["Kycklingfilé", "Ris", "Paprika",
                                      "Crème fraiche", "Gul lök"], staples=staples)
        self.assertEqual([row["name"] for row in result["missingIngredients"]], ["Salt"])
        # Saknad SKAFFERIVARA, inte saknad råvara - skillnaden är hela
        # skälet till att de räknas var för sig.
        self.assertEqual(result["missingStapleCount"], 1)
        self.assertEqual(result["missingMainCount"], 0)
        self.assertFalse(result["canCookNow"])

    def test_the_user_can_declare_they_always_have_garlic(self):
        with_garlic = recipe("Vitlök", "Ris")
        default = match_recipe(with_garlic, ["Ris"])
        self.assertEqual(default["missingCount"], 1)
        extended = match_recipe(with_garlic, ["Ris"], staples=resolve_staples(extra=["Vitlök"]))
        self.assertEqual(extended["missingCount"], 0)
        self.assertTrue(extended["canCookNow"])


class RecipeShapeTest(unittest.TestCase):
    def test_optional_ingredients_are_never_missing(self):
        garnished = recipe("Ris", {"name": "Persilja", "optional": True})
        result = match_recipe(garnished, ["Ris"])
        self.assertEqual(result["requiredCount"], 1)
        self.assertTrue(result["canCookNow"])

    def test_a_duplicated_ingredient_counts_once(self):
        """Ett recept som listar lök på två rader är EN vara att köpa."""
        doubled = recipe("Gul lök", "Gul lök", "Ris")
        result = match_recipe(doubled, ["Ris"])
        self.assertEqual(result["requiredCount"], 2)
        self.assertEqual([row["name"] for row in result["missingIngredients"]], ["Gul lök"])

    def test_differently_spelled_duplicates_also_count_once(self):
        doubled = recipe("Tomater", "tomat", "Ris")
        self.assertEqual(match_recipe(doubled, ["Ris"])["requiredCount"], 2)

    def test_a_malformed_recipe_does_not_crash(self):
        for broken in [
            {"id": "x"},
            {"id": "x", "ingredients": None},
            {"id": "x", "ingredients": []},
            {"id": "x", "ingredients": [{}, {"name": ""}, {"name": None}]},
            {"id": "x", "ingredients": ["inte ett objekt", 42, None]},
        ]:
            result = match_recipe(broken, ["Ris"])
            self.assertEqual(result["missingCount"], 0)
            self.assertEqual(result["matchPercent"], 0)
            self.assertEqual(result["requiredCount"], 0)

    def test_a_card_without_amounts_still_matches(self):
        """Kortformen bär bara namn. Svaret blir grövre, inte felaktigt."""
        card = {"id": "kort", "name": "Kort", "ingredientNames": ["Ris", "Gul lök"]}
        result = match_recipe(card, ["ris"])
        self.assertEqual(result["missingCount"], 1)
        self.assertIsNone(result["missingIngredients"][0]["amount"])

    def test_an_empty_pantry_matches_nothing(self):
        result = match_recipe(GRYTA, [])
        self.assertEqual(result["availableIngredients"], [])
        self.assertFalse(result["canCookNow"])

    def test_blank_pantry_entries_are_ignored(self):
        self.assertEqual(match_recipe(GRYTA, ["", "   ", None])["availableIngredients"], [])


class RankingTest(unittest.TestCase):
    BANK = [
        recipe("Ris", "Gul lök", name="Allt hemma", recipe_id="allt"),
        recipe("Ris", "Gul lök", "Lax", name="Saknar en", recipe_id="en"),
        recipe("Ris", "Lax", "Torsk", "Räkor", name="Saknar tre", recipe_id="tre"),
        recipe("Lax", "Torsk", name="Inget hemma", recipe_id="inget"),
    ]
    PANTRY = ["Ris", "Lök"]

    def test_cookable_recipes_come_first(self):
        order = [entry["recipe"]["id"] for entry in match_recipes(self.BANK, self.PANTRY)]
        self.assertEqual(order, ["allt", "en", "tre"])

    def test_a_recipe_with_nothing_at_home_is_not_an_answer(self):
        """Ett recept där ingenting finns hemma är receptbanken, inte ett
        svar på "vad kan jag laga av det jag har"."""
        self.assertNotIn("inget", [entry["recipe"]["id"]
                                   for entry in match_recipes(self.BANK, self.PANTRY)])

    def test_staples_alone_are_not_a_hit(self):
        """Salt finns i nästan varje recept. Om skafferigrunden räknades som
        en träff hade hela banken varit en träff."""
        salty = [recipe({"name": "Salt", "pantryStaple": True}, "Lax", recipe_id="salt")]
        self.assertEqual(match_recipes(salty, ["Ris"]), [])

    def test_max_missing_filters_the_long_tail(self):
        ids = [entry["recipe"]["id"] for entry in match_recipes(self.BANK, self.PANTRY, max_missing=1)]
        self.assertEqual(ids, ["allt", "en"])

    def test_limit_truncates_after_sorting(self):
        ids = [entry["recipe"]["id"] for entry in match_recipes(self.BANK, self.PANTRY, limit=1)]
        self.assertEqual(ids, ["allt"])

    def test_the_order_of_the_bank_never_changes_the_result(self):
        forward = [e["recipe"]["id"] for e in match_recipes(self.BANK, self.PANTRY)]
        backward = [e["recipe"]["id"] for e in match_recipes(list(reversed(self.BANK)), self.PANTRY)]
        self.assertEqual(forward, backward)


class AllergenTest(unittest.TestCase):
    """Allergener filtreras av appen som vet vem användaren är - men den kan
    bara göra det om etiketterna följer med receptet oförändrade."""

    def test_labels_survive_matching(self):
        nutty = {**recipe("Ris", "Jordnötter", recipe_id="nöt"),
                 "allergens": ["nötter"], "dietFlags": ["vegetariskt"]}
        entry = match_recipes([nutty], ["Ris"])[0]
        self.assertEqual(entry["recipe"]["allergens"], ["nötter"])
        self.assertEqual(entry["recipe"]["dietFlags"], ["vegetariskt"])

    def test_matching_never_mutates_the_recipe_it_was_given(self):
        original = recipe("Ris", "Lax")
        before = {key: value for key, value in original.items()}
        match_recipe(original, ["Ris"])
        self.assertEqual(original, before)


class PortionsTest(unittest.TestCase):
    def test_halving_a_recipe_halves_the_amounts(self):
        scaled = scale_recipe(
            {"servings": 4, "ingredients": [{"name": "Kycklingfilé", "amount": 600, "unit": "g"}]}, 2)
        self.assertEqual(scaled["servings"], 2)
        self.assertEqual(scaled["baseServings"], 4)
        self.assertEqual(scaled["ingredients"][0]["amount"], 300)

    def test_a_row_without_an_amount_keeps_having_none(self):
        """"Salt" har ingen mängd, och ska inte få 0,5."""
        scaled = scale_recipe(
            {"servings": 4, "ingredients": [{"name": "Salt", "amount": None}]}, 2)
        self.assertIsNone(scaled["ingredients"][0]["amount"])

    def test_nutrition_is_per_portion_and_is_never_scaled(self):
        base = {"servings": 4, "nutrition": {"kcal": 540, "protein": 38}, "ingredients": []}
        self.assertEqual(scale_recipe(base, 2)["nutrition"], {"kcal": 540, "protein": 38})

    def test_scaling_returns_a_copy(self):
        base = {"servings": 4, "ingredients": [{"name": "Ris", "amount": 250}]}
        scale_recipe(base, 2)
        self.assertEqual(base["servings"], 4)
        self.assertEqual(base["ingredients"][0]["amount"], 250)

    def test_amounts_are_rounded_to_something_a_kitchen_can_measure(self):
        self.assertEqual(scaled_amount(600, 1 / 3), 200)
        self.assertEqual(scaled_amount(1, 0.5), 0.5)
        self.assertEqual(scaled_amount(2, 1), 2)

    def test_a_nonsense_serving_count_leaves_the_recipe_alone(self):
        base = {"servings": 4, "ingredients": [{"name": "Ris", "amount": 250}]}
        for bad in (None, "två", 0, -3):
            self.assertEqual(scale_recipe(base, bad)["ingredients"][0]["amount"], 250, bad)

    def test_scaling_is_clamped_to_a_sane_range(self):
        base = {"servings": 4, "ingredients": [{"name": "Ris", "amount": 100}]}
        self.assertEqual(scale_recipe(base, 1000)["servings"], 24)

    def test_a_recipe_without_a_serving_count_is_not_scaled(self):
        base = {"servings": None, "ingredients": [{"name": "Ris", "amount": 250}]}
        self.assertEqual(scale_recipe(base, 2)["ingredients"][0]["amount"], 250)


if __name__ == "__main__":
    unittest.main()
