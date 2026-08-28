import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .base import RecipeProvider
from .ingredient_map import SWEDISH_TO_MEALDB_INGREDIENT
from .models import Recipe, RecipeIngredient


class TheMealDbProvider(RecipeProvider):
    name = "themealdb"
    base_url = "https://www.themealdb.com/api/json/v1/1"

    def _request(self, endpoint: str, params: dict) -> dict:
        request = Request(f"{self.base_url}/{endpoint}?{urlencode(params)}", headers={"User-Agent": "Matjakt/1.0"})
        with urlopen(request, timeout=8) as response:
            return json.load(response)

    def search(self, query: str) -> list[Recipe]:
        return [self.normalize(meal) for meal in self._request("search.php", {"s": query}).get("meals") or []]

    def get(self, provider_recipe_id: str) -> Recipe | None:
        meals = self._request("lookup.php", {"i": provider_recipe_id}).get("meals") or []
        return self.normalize(meals[0]) if meals else None

    def search_by_pantry(self, swedish_ingredients: list[str], limit: int = 8) -> list[tuple[Recipe, list[str]]]:
        """Find recipes that use ingredients the user already has, via TheMealDB's
        filter-by-ingredient endpoint (one ingredient per call - there is no
        multi-ingredient filter). Ranked by how many pantry ingredients match."""
        terms_to_swedish: dict[str, list[str]] = {}
        for name in swedish_ingredients:
            term = SWEDISH_TO_MEALDB_INGREDIENT.get(name)
            if term:
                terms_to_swedish.setdefault(term, []).append(name)
        if not terms_to_swedish:
            return []
        matched_swedish: dict[str, set[str]] = {}
        for term, names in terms_to_swedish.items():
            meals = self._request("filter.php", {"i": term}).get("meals") or []
            for meal in meals:
                meal_id = meal.get("idMeal")
                if meal_id:
                    matched_swedish.setdefault(meal_id, set()).update(names)
        ranked_ids = sorted(matched_swedish, key=lambda meal_id: len(matched_swedish[meal_id]), reverse=True)[:limit]
        results = []
        for meal_id in ranked_ids:
            recipe = self.get(meal_id)
            if recipe:
                results.append((recipe, sorted(matched_swedish[meal_id])))
        return results

    @classmethod
    def normalize(cls, meal: dict) -> Recipe:
        provider_id = str(meal.get("idMeal") or "").strip()
        if not provider_id:
            raise ValueError("TheMealDB recipe is missing idMeal")
        ingredients = []
        for index in range(1, 21):
            name = str(meal.get(f"strIngredient{index}") or "").strip()
            measure = str(meal.get(f"strMeasure{index}") or "").strip() or None
            if name:
                ingredients.append(RecipeIngredient(name=name, measure=measure))
        image_url = str(meal.get("strMealThumb") or "").strip() or None
        instructions = [part.strip() for part in str(meal.get("strInstructions") or "").replace("\r", "").split("\n") if part.strip()]
        return Recipe(
            id=f"{cls.name}:{provider_id}", provider=cls.name, provider_recipe_id=provider_id,
            title=str(meal.get("strMeal") or "Namnlöst recept").strip(),
            image_url=image_url, image_source=cls.name if image_url else None,
            servings=None, prep_minutes=None, ingredients=ingredients, instructions=instructions,
            source_url=str(meal.get("strSource") or "").strip() or None, language="en",
        )
