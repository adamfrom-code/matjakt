# -*- coding: utf-8 -*-
"""Det Matjakt delar med andra appar - i dag Ät Upp, i morgon vad som helst.

Ett eget lager, inte ett par extra rader i api_server.py, av ett skäl: det
som ligger här är ett KONTRAKT. Matjakts egen frontend får ändras när som
helst, men en endpoint under /api/v1/shared/ har konsumenter vi inte
deployar samtidigt, och den ska därför gå att läsa, testa och versionera för
sig.

Tre regler formar lagret:

BARA LÄSNING. Ingenting här skriver. En delad app kan inte ändra Matjakts
recept, priser eller konton - den kan läsa det Matjakt redan vet.

INGEN PRISDATA I v1. Priser lyder under prisgrindens fail-closed-regler och
Dabas-villkoren, och de reglerna gäller inte automatiskt utanför Matjakt.
Delade priser kräver ett eget beslut, inte en extra endpoint. Se
docs/SHARED_API.md.

EN IMPLEMENTATION AV MATCHNING. Ät Upp bygger inte en egen kopia av
kanoniska ingredienser - den frågar den här modulen. Två implementationer
blir två sanningar första gången någon lägger till ett alias.
"""

from .canonical import canonical_id, canonical_ingredient, satisfies
from .matching import DEFAULT_PANTRY_STAPLES, match_recipes
from .portions import scale_recipe

__all__ = [
    "DEFAULT_PANTRY_STAPLES",
    "canonical_id",
    "canonical_ingredient",
    "match_recipes",
    "scale_recipe",
    "satisfies",
]
