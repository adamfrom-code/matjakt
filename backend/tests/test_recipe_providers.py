import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.recipe_providers.base import RecipeProvider  # noqa: E402
from services.recipe_providers.service import RecipeService  # noqa: E402
from services.recipe_providers.themealdb import TheMealDbProvider  # noqa: E402


MEAL = {
    "idMeal": "52772",
    "strMeal": "Teriyaki Chicken Casserole",
    "strMealThumb": "https://www.themealdb.com/images/media/meals/wvpsxx1468256321.jpg",
    "strIngredient1": "soy sauce",
    "strMeasure1": "3/4 cup",
    "strIngredient2": "chicken breasts",
    "strMeasure2": "4",
    "strInstructions": "Heat the oven.\r\nBake the chicken.",
    "strSource": "https://example.com/teriyaki",
}


class FakeProvider(RecipeProvider):
    name = "themealdb"

    def search(self, query):
        return [TheMealDbProvider.normalize(MEAL)]

    def get(self, provider_recipe_id):
        return TheMealDbProvider.normalize(MEAL) if provider_recipe_id == "52772" else None


class RecipeProviderTest(unittest.TestCase):
    def test_recipe_and_image_keep_the_same_provider_id(self):
        recipe = TheMealDbProvider.normalize(MEAL)
        self.assertEqual(recipe.id, "themealdb:52772")
        self.assertEqual(recipe.provider_recipe_id, "52772")
        self.assertEqual(recipe.image_source, recipe.provider)
        self.assertIn("themealdb.com", recipe.image_url)

    def test_recipe_without_image_uses_null_for_frontend_fallback(self):
        recipe = TheMealDbProvider.normalize({**MEAL, "strMealThumb": ""})
        self.assertIsNone(recipe.image_url)
        self.assertIsNone(recipe.image_source)

    def test_search_result_can_be_opened_by_the_same_detail_id(self):
        service = RecipeService([FakeProvider()])
        search_result = service.search("chicken")[0]
        detail = service.get(search_result.id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.id, search_result.id)
        self.assertEqual(detail.image_url, search_result.image_url)

    def test_external_provider_data_is_normalized(self):
        value = TheMealDbProvider.normalize(MEAL).to_dict()
        self.assertEqual(value["provider"], "themealdb")
        self.assertEqual(value["title"], MEAL["strMeal"])
        self.assertEqual(value["ingredients"][0], {"name": "soy sauce", "measure": "3/4 cup"})
        self.assertEqual(value["instructions"], ["Heat the oven.", "Bake the chicken."])
        self.assertIn("providerRecipeId", value)
        self.assertEqual(value["sourceUrl"], MEAL["strSource"])
        self.assertEqual(value["language"], "en")

    def test_one_broken_provider_does_not_break_search(self):
        class BrokenProvider(FakeProvider):
            name = "broken"

            def search(self, query):
                raise RuntimeError("provider unavailable")

        recipes = RecipeService([BrokenProvider(), FakeProvider()]).search("chicken")
        self.assertEqual(len(recipes), 1)


if __name__ == "__main__":
    unittest.main()
