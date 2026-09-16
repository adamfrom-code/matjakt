"""Kanoniska ingredienser - P05a.

Kedjan Matjakt lovar: RecipeIngredient -> CanonicalIngredient -> ShoppingItem
-> ProductMatch -> Product -> StorePrice. Det här paketet är länk två, som
saknades: 212 ingrediensnamn gav 212 normaliserade id och ingenting sa att
"tomat" och "tomater" är samma råvara. Se canonical.py.
"""
from .canonical import (  # noqa: F401
    Kanonisk, alla, canonical_id, ladda, resolve, unit_family,
)
