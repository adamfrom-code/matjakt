# -*- coding: utf-8 -*-
"""Portionsskalning - ett recept för fyra, lagat för två.

Ligger här och inte i varje app av samma skäl som kanoniseringen: det är
tre rader aritmetik med fyra fällor i, och två appar som skriver dem var för
sig skriver dem olika.

FÄLLORNA:

SKAFFERIRADER SKALAS INTE. "Salt" har ingen mängd, och en rad utan mängd
ska förbli utan mängd - inte bli 0,5. Samma sak för "1 kruka basilika"
skriven som en not.

NÄRING ÄR PER PORTION. kcal och protein i banken är redan per portion, så
de ska ALDRIG multipliceras med skalfaktorn. Det är den fällan som gör att
ett halverat recept plötsligt ser ut att innehålla 270 kcal per portion i
stället för 540.

AVRUNDNING SKA GÅ ATT LAGA MAT EFTER. 600 g kyckling delat på tre blir 200,
inte 200,00000000003, och 1 st lök delat på två blir 0,5 och inte 0,5 st
avrundat till noll.
"""

__all__ = ["scale_recipe", "scaled_amount"]

# Under så här många portioner blir skalningen meningslös (ett halvt ägg),
# och över blir den ett cateringuppdrag receptet inte är skrivet för.
MIN_SERVINGS = 1
MAX_SERVINGS = 24


def scaled_amount(amount, factor: float):
    """En mängd i en annan skala, avrundad till något ett kök kan mäta.

    None in, None ut: en rad utan mängd har ingen mängd att skala."""
    if amount is None:
        return None
    try:
        value = float(amount) * factor
    except (TypeError, ValueError):
        return None
    # Två decimaler under 10 (0,25 tsk betyder något), en över (351 g mjöl
    # vägs som 350). Heltal skrivs som heltal, så "2 st ägg" inte blir
    # "2.0 st".
    value = round(value, 2) if value < 10 else round(value, 1)
    return int(value) if value == int(value) else value


def scale_recipe(recipe: dict, servings) -> dict:
    """Receptet skrivet för ett annat antal portioner.

    Returnerar en KOPIA. Receptet som skickas in är delat med resten av
    processen - receptlagrets cache lämnar ut samma dict till varje läsare,
    och att skala den på plats hade ändrat banken för alla."""
    base = recipe.get("servings") or 0
    try:
        wanted = int(servings)
    except (TypeError, ValueError):
        return dict(recipe)
    # Noll och negativa portioner är inte en begäran, det är skräp - och de
    # ska lämna receptet i fred i stället för att klämmas upp till en
    # portion. Ett ÖNSKEMÅL utanför intervallet (1000 portioner) är däremot
    # menat, och kläms till taket.
    if wanted < MIN_SERVINGS:
        return dict(recipe)
    wanted = min(wanted, MAX_SERVINGS)
    if not base or wanted == base:
        return dict(recipe)

    factor = wanted / base
    scaled = dict(recipe)
    scaled["servings"] = wanted
    scaled["baseServings"] = base
    scaled["ingredients"] = [
        {**row, "amount": scaled_amount(row.get("amount"), factor)}
        for row in recipe.get("ingredients") or []
    ]
    # Näringen rörs INTE - se modulens docstring. Att skriva ut det här är
    # billigare än att någon "fixar" det om ett halvår.
    return scaled
