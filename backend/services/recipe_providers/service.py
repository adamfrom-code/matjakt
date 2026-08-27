from .base import RecipeProvider
from .models import Recipe


class RecipeService:
    def __init__(self, providers: list[RecipeProvider]):
        self.providers = {provider.name: provider for provider in providers}

    def search(self, query: str) -> list[Recipe]:
        recipes = []
        for provider in self.providers.values():
            recipes.extend(provider.search(query))
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
