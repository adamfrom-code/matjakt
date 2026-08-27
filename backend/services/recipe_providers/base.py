from abc import ABC, abstractmethod

from .models import Recipe


class RecipeProvider(ABC):
    name: str

    @abstractmethod
    def search(self, query: str) -> list[Recipe]:
        """Return normalized recipes matching query."""

    @abstractmethod
    def get(self, provider_recipe_id: str) -> Recipe | None:
        """Return one normalized recipe owned by this provider."""
