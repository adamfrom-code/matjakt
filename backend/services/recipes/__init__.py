"""Matjakts egen receptdatabas - se store.py för designbesluten."""

from .store import RecipeStore, normalize_ingredient_id

__all__ = ["RecipeStore", "normalize_ingredient_id"]
