# -*- coding: utf-8 -*-
"""Vad en rätt är TILL FÖR - receptbankens minsta, mest saknade fält.

Fram till M1 sa ingenting i `recipes` vad ett recept var till för. Kolumnen
fanns inte; `PRAGMA table_info(recipes)` hade varken `mealType` eller
`meal_type`. Veckoplaneraren valde alltså bland allt banken hade, och att
risgrynsgröt inte hamnade i middagsveckan oftare var tur, inte konstruktion.

VÄRDEFÖRRÅDET ÄR STÄNGT. Fem värden, inga fler, och ingen `NULL`. Ett öppet
fält hade blivit en synonymsoppa inom en månad ("dinner", "Middag",
"huvudrätt") och `NULL` betyder i praktiken "kanske middag" - vilket gör
fältet värdelöst för det enda det finns för: att kunna säga NEJ till ett
recept i veckoplaneringen. Butiken avvisar därför ett okänt värde vid
skrivning i stället för att spara det och låta felet upptäckas av en
veckoplan hos en användare.

FEM VÄRDEN, INTE FYRTIO. Kategorierna ska svara på frågan "får den här rätten
föreslås som middag?" - inte beskriva maten. `tags` och `categories` gör redan
det jobbet (M4 städar dem). Därför inget "förrätt", inget "mellanmål": en
förrätt som faktiskt äts som lättmiddag är `middag`, och den som inte gör det
är `tillbehor`.
"""

DINNER = "middag"
BREAKFAST = "frukost"
LUNCH = "lunch"
DESSERT = "efterratt"
SIDE = "tillbehor"

# Ordningen är den man läser dem i, inte en rangordning.
MEAL_TYPES = (DINNER, BREAKFAST, LUNCH, DESSERT, SIDE)

# Vad varje värde betyder, i en mening. Står här och inte i en README för att
# den som lägger till ett recept läser koden, inte dokumentationen.
MEAL_TYPE_MEANING = {
    DINNER: "Huvudrätt som får föreslås i veckoplaneringen.",
    BREAKFAST: "Frukostmat - gröt, välling, frukostpannkakor.",
    LUNCH: "Lätt måltid eller matlåda som inte är tänkt som kvällens middag.",
    DESSERT: "Efterrätt, äts efter en annan rätt.",
    SIDE: "Tillbehör som serveras till en annan rätt och inte är en måltid.",
}


class UnknownMealType(ValueError):
    """Ett värde utanför det stängda värdeförrådet försökte sparas."""


def is_valid(value) -> bool:
    return value in MEAL_TYPES


def require(value, *, recipe_id: str = "") -> str:
    """Släpper igenom ett giltigt värde och kastar på allt annat.

    Fail closed vid SKRIVNING, inte vid läsning: ett felstavat `meal_type`
    som hinner ner i databasen upptäcks annars först när en användare får
    frukost i sin middagsvecka - eller aldrig, om felstavningen råkar bli
    filtrerad bort tyst."""
    if is_valid(value):
        return value
    vem = f" ({recipe_id})" if recipe_id else ""
    raise UnknownMealType(
        f"Okänd meal_type {value!r}{vem}. Värdeförrådet är stängt: "
        f"{', '.join(MEAL_TYPES)}. Saknas ett recept sin klassificering, kör "
        f"backend/scripts/classify_recipe_meal_type.py - gissa inte här.")
