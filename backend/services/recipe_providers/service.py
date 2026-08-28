import logging

from .base import RecipeProvider
from .models import Recipe

logger = logging.getLogger("matjakt.api")


class RecipeService:
    def __init__(self, providers: list[RecipeProvider]):
        self.providers = {provider.name: provider for provider in providers}

    def search(self, query: str) -> list[Recipe]:
        recipes = []
        for provider in self.providers.values():
            try:
                recipes.extend(provider.search(query))
            except Exception:
                logger.exception("Recipe provider %r failed for query %r", provider.name, query)
                continue
        return recipes

    def get(self, recipe_id: str) -> Recipe | None:
        provider_name, separator, provider_recipe_id = recipe_id.partition(":")
        provider = self.providers.get(provider_name)
        if not separator or not provider or not provider_recipe_id:
            return None
        recipe = provider.get(provider_recipe_id)
        if recipe and recipe.id != recipe_id:
            raise ValueError("Provider returned a recipe with a mismatched id")
        return recipe

    def search_by_pantry(self, swedish_ingredients: list[str], limit: int = 8) -> list[tuple[Recipe, list[str]]]:
        """Ask every provider that supports pantry-based search (currently just
        TheMealDB) for recipes matching the given Swedish ingredient names."""
        results: list[tuple[Recipe, list[str]]] = []
        for provider in self.providers.values():
            method = getattr(provider, "search_by_pantry", None)
            if not callable(method):
                continue
            try:
                results.extend(method(swedish_ingredients, limit=limit))
            except Exception:
                logger.exception("Pantry-based search failed for provider %r", provider.name)
        results.sort(key=lambda pair: len(pair[1]), reverse=True)
        return results[:limit]
