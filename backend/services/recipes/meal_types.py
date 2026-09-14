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

OCH ETT VÄRDE RÄCKER INTE (M5). Två soppor stod som `middag` på sex respektive
sju gram protein per portion. Ett fält som säger "middag" är bara värt något
om det också går att ha fel om, så samma fråga - får den här rätten föreslås
som middag? - har nu ett andra villkor: `MIN_DINNER_PROTEIN_G`. Det står här
och inte i veckoplaneraren, för det är samma beslut som värdeförrådet, prövat
på samma ställe och vid samma tillfälle: vid skrivningen.
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


# M5: GOLVET FÖR VAD SOM FÅR FÖRESLÅS SOM MIDDAG.
#
# Tio gram protein per portion. Gränsen är ett GOLV och inte ett mål: den ska
# fånga rätten som inte är en huvudrätt alls, inte underkänna en vegetarisk
# gryta på tretton gram.
#
# Varför just tio: Livsmedelsverkets intervall för protein är 10-20
# energiprocent, och för en middagsportion på 400-600 kcal börjar det
# intervallet vid 10-15 g. Tio gram är alltså den nedre kanten av den nedre
# kanten. Sätts golvet högre blir det ett näringsråd - och Matjakt säljer
# inte näringsrådgivning, den föreslår vad man ska äta. Sätts det lägre
# släpper det igenom en soppa på sex gram, och en huvudrätt på sex gram
# protein är ingen middag oavsett hur god den är.
#
# Talet står HÄR och ingen annanstans: klassificeringsskriptet, butiken,
# importvalideringen och testet läser alla den här raden.
MIN_DINNER_PROTEIN_G = 10


class UnknownMealType(ValueError):
    """Ett värde utanför det stängda värdeförrådet försökte sparas."""


class DinnerTooLeanError(ValueError):
    """Ett recept under proteingolvet försökte sparas som middag."""


def is_valid(value) -> bool:
    return value in MEAL_TYPES


def protein_of(recipe) -> float | None:
    """Proteinet per portion ur ett recept, oavsett vilken form det har.

    Källorna bär `nutrition.protein`, databasraden och reservbanken bär ett
    platt `protein`. None betyder "vet inte" - och "vet inte" får aldrig
    tolkas som noll, för då hade varje ofullständig delmängdsuppdatering
    plötsligt sett ut som ett brott mot golvet."""
    if not isinstance(recipe, dict):
        return None
    nutrition = recipe.get("nutrition")
    value = (nutrition or {}).get("protein") if isinstance(nutrition, dict) else None
    if value is None:
        value = recipe.get("protein")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def is_dinner_protein_ok(protein) -> bool:
    """Håller det här proteinvärdet för en middag? Okänt protein godtas -
    se `protein_of`."""
    return protein is None or float(protein) >= MIN_DINNER_PROTEIN_G


def require_dinner_protein(meal_type, protein, *, recipe_id: str = "", name: str = ""):
    """Fail closed vid SKRIVNING, precis som värdeförrådet ovan.

    En rätt under golvet får inte ligga kvar som `middag` och upptäckas
    först som en soppa på sex gram i någons middagsvecka. Rör bara
    `middag` - en lunch, en frukost eller en efterrätt under golvet är inte
    ett fel, det är vad de är."""
    if meal_type != DINNER or is_dinner_protein_ok(protein):
        return protein
    vem = " ".join(part for part in (recipe_id, f"({name})" if name else "") if part)
    raise DinnerTooLeanError(
        f"{vem or 'Receptet'} har {float(protein):g} g protein per portion och kan "
        f"inte vara {DINNER!r}: golvet är {MIN_DINNER_PROTEIN_G} g. Höj proteinet i "
        f"receptet och låt compute_recipe_nutrition.py räkna om det, eller klassa "
        f"rätten som {LUNCH!r}.")


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
