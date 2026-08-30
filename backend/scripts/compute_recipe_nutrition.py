"""One-off data-prep script: compute kcal/protein/kolhydrater/fett per portion for
every recipe in frontend/app/app.js's RECEPT, from Livsmedelsverkets open food
composition API (CC BY 4.0, https://dataportal.livsmedelsverket.se).

This is NOT wired into the running server - it's run by hand once (and again
whenever recipes/ingredients change), and its output is pasted into RECEPT in
frontend/app/app.js as kcal/protein/kolhydrater/fett fields. Ingredient quantities
below are a hand-kept mirror of RECIPE_QUANTITIES/PACKAGE_INFO in frontend/app/app.js -
keep them in sync when recipes change.

Usage:
    python backend/scripts/compute_recipe_nutrition.py
"""

import json
import urllib.parse
import urllib.request

API_BASE = "https://dataportal.livsmedelsverket.se/livsmedel/api/v1"

# ingredient name -> Livsmedelsverket livsmedelsnummer for the closest raw/as-purchased
# match. A couple of ingredients (Röda linser, Matvete) only exist pre-cooked in the
# database; for those we store a (nummer, cooked_yield_factor) pair and scale the
# per-100g values up by that factor to approximate the dry/as-purchased form our
# recipe quantities are measured in (matches PACKAGE_INFO's "g" units in app.js).
INGREDIENT_MAP = {
    "Pasta": 845, "Purjolök": 354, "Grädde": 1717, "Riven ost": 96,
    "Fryst torsk": 1246, "Crème fraiche": 1719, "Citron": 559,
    "Kycklinglårfilé": 1174, "Ris": 2477, "Kokosmjölk": 7266,
    "Curry & grönsaker": 5973, "Morötter": 289, "Lök & vitlök": 344,
    "Falukorv": 1487, "Tomatpuré": 410, "Svarta bönor": 3817, "Majs": 347,
    "Salsa": 462, "Laxfilé": 1255, "Potatis": 4457, "Dill": 377,
    "Halloumi": 100, "Paprika": 351, "Yoghurt": 124, "Kidneybönor": 3816,
    "Krossade tomater": 422, "Kycklingfilé": 1173, "Äggnudlar": 870,
    "Wokgrönsaker": 424, "Soja": 909, "Lök": 344, "Basilika": 379,
    "Vetemjöl": 1941, "Mjölk": 150, "Ägg": 1225, "Bär": 556,
    "Köttfärs": 2492, "Lingonsylt": 1798, "Lasagneplattor": 845,
    "Zucchini": 362, "Räkor": 1395, "Vitlök": 371, "Kikärtor": 3815,
    "Fläskfilé": 970, "Timjan": 379, "Biff": 946, "Vegofärs": 2068,
    "Tofu": 905, "Sparris": 5861, "Äppelmos": 1809, "Rödkål": 355,
    "Feta": 94, "Kalvschnitzel": 938, "Kapris": 402,
}
COOKED_ONLY = {
    # namn -> (livsmedelsnummer för kokt variant, ungefärlig vikt-ökning vid kokning)
    "Röda linser": (3822, 2.5),
    "Matvete": (6145, 2.2),
}

# Grams per "st" for ingredients that appear with that unit in RECIPE_QUANTITIES.
GRAM_PER_ST = {
    "Purjolök": 250, "Citron": 100, "Dill": 20, "Paprika": 150, "Lök": 110,
    "Basilika": 20, "Ägg": 58, "Zucchini": 250, "Vitlök": 40, "Timjan": 15,
}

# Mirror of frontend/app/app.js RECIPE_QUANTITIES (base 4 portions).
RECIPE_QUANTITIES = {
    "pastagratang": {"Pasta": (250, "g"), "Purjolök": (0.5, "st"), "Grädde": (200, "ml"), "Riven ost": (100, "g")},
    "fiskpasta": {"Fryst torsk": (450, "g"), "Pasta": (250, "g"), "Crème fraiche": (200, "g"), "Citron": (1, "st")},
    "kycklinggryta": {"Kycklinglårfilé": (600, "g"), "Ris": (250, "g"), "Kokosmjölk": (400, "ml"), "Curry & grönsaker": (28, "g")},
    "linssoppa": {"Röda linser": (250, "g"), "Kokosmjölk": (400, "ml"), "Morötter": (300, "g"), "Lök & vitlök": (150, "g")},
    "korvstroganoff": {"Falukorv": (400, "g"), "Grädde": (200, "ml"), "Tomatpuré": (70, "g"), "Ris": (250, "g")},
    "tacobonor": {"Svarta bönor": (380, "g"), "Ris": (250, "g"), "Majs": (150, "g"), "Salsa": (230, "g")},
    "lax": {"Laxfilé": (600, "g"), "Potatis": (800, "g"), "Citron": (1, "st"), "Dill": (1, "st")},
    "halloumibowl": {"Halloumi": (225, "g"), "Matvete": (250, "g"), "Paprika": (1, "st"), "Yoghurt": (200, "g")},
    "chili": {"Kidneybönor": (400, "g"), "Krossade tomater": (400, "g"), "Majs": (150, "g"), "Paprika": (2, "st")},
    "kycklingwok": {"Kycklingfilé": (500, "g"), "Äggnudlar": (250, "g"), "Wokgrönsaker": (400, "g"), "Soja": (30, "ml")},
    "tomatsoppa": {"Krossade tomater": (400, "g"), "Grädde": (200, "ml"), "Lök": (2, "st"), "Basilika": (1, "st")},
    "pannkakor": {"Vetemjöl": (250, "g"), "Mjölk": (600, "ml"), "Ägg": (4, "st"), "Bär": (300, "g")},
    "kottbullar": {"Köttfärs": (500, "g"), "Potatis": (800, "g"), "Grädde": (200, "ml"), "Lingonsylt": (100, "g")},
    "vegetarisklasagne": {"Lasagneplattor": (300, "g"), "Krossade tomater": (400, "g"), "Riven ost": (150, "g"), "Zucchini": (2, "st")},
    "scampi": {"Räkor": (300, "g"), "Pasta": (250, "g"), "Vitlök": (1, "st"), "Citron": (1, "st")},
    "kikartscurry": {"Kikärtor": (380, "g"), "Kokosmjölk": (400, "ml"), "Ris": (250, "g"), "Curry & grönsaker": (28, "g")},
    "flaskfilerotmos": {"Fläskfilé": (600, "g"), "Morötter": (400, "g"), "Potatis": (600, "g"), "Timjan": (1, "st")},
    "biffmedlok": {"Biff": (600, "g"), "Potatis": (800, "g"), "Lök": (2, "st"), "Grädde": (200, "ml")},
    "vegobolognese": {"Vegofärs": (400, "g"), "Pasta": (250, "g"), "Krossade tomater": (400, "g"), "Lök": (1, "st")},
    "kycklingcouscous": {"Kycklingfilé": (500, "g"), "Matvete": (250, "g"), "Paprika": (2, "st"), "Citron": (1, "st")},
    "rotfruktsgratang": {"Falukorv": (400, "g"), "Potatis": (800, "g"), "Morötter": (400, "g"), "Riven ost": (100, "g")},
    "butterchicken": {"Kycklingfilé": (500, "g"), "Krossade tomater": (400, "g"), "Grädde": (200, "ml"), "Curry & grönsaker": (28, "g")},
    "fiskgratang": {"Fryst torsk": (500, "g"), "Räkor": (200, "g"), "Dill": (1, "st"), "Grädde": (200, "g")},
    "tofuwok": {"Tofu": (400, "g"), "Wokgrönsaker": (400, "g"), "Soja": (30, "ml"), "Ris": (250, "g")},
    "ugnstorsk": {"Fryst torsk": (600, "g"), "Citron": (1, "st"), "Sparris": (300, "g"), "Potatis": (600, "g")},
    "flaskkarre": {"Fläskfilé": (600, "g"), "Äppelmos": (200, "g"), "Rödkål": (300, "g"), "Potatis": (600, "g")},
    "fetapasta": {"Pasta": (300, "g"), "Krossade tomater": (400, "g"), "Vitlök": (1, "st"), "Feta": (200, "g")},
    "kalvschnitzel": {"Kalvschnitzel": (600, "g"), "Potatis": (600, "g"), "Citron": (1, "st"), "Kapris": (30, "g")},
    "kycklingmatvete": {"Kycklinglårfilé": (500, "g"), "Matvete": (250, "g"), "Paprika": (2, "st"), "Yoghurt": (200, "g")},
    "citronkyckling": {"Kycklinglårfilé": (600, "g"), "Potatis": (800, "g"), "Timjan": (1, "st"), "Citron": (1, "st")},
    "biffmatvetesallad": {"Biff": (500, "g"), "Matvete": (250, "g"), "Paprika": (1, "st"), "Vitlök": (1, "st")},
    "biffwok": {"Biff": (500, "g"), "Ris": (250, "g"), "Wokgrönsaker": (400, "g"), "Soja": (30, "ml")},
    "flaskcurrygryta": {"Fläskfilé": (500, "g"), "Ris": (250, "g"), "Curry & grönsaker": (28, "g"), "Kokosmjölk": (400, "ml")},
    "flasktomatpasta": {"Fläskfilé": (500, "g"), "Pasta": (250, "g"), "Krossade tomater": (400, "g"), "Basilika": (1, "st")},
    "kalvschnitzelmatvete": {"Kalvschnitzel": (500, "g"), "Matvete": (250, "g"), "Paprika": (1, "st"), "Citron": (1, "st")},
    "teriyakilax": {"Laxfilé": (500, "g"), "Ris": (250, "g"), "Wokgrönsaker": (400, "g"), "Soja": (30, "ml")},
    "laxsallad": {"Laxfilé": (500, "g"), "Matvete": (250, "g"), "Citron": (1, "st"), "Dill": (1, "st")},
    "torskitomatsas": {"Fryst torsk": (500, "g"), "Potatis": (600, "g"), "Krossade tomater": (400, "g"), "Vitlök": (1, "st")},
    "rakcurry": {"Räkor": (300, "g"), "Ris": (250, "g"), "Curry & grönsaker": (28, "g"), "Kokosmjölk": (400, "ml")},
    "raksallad": {"Räkor": (300, "g"), "Matvete": (250, "g"), "Citron": (1, "st"), "Dill": (1, "st")},
    "kikartssallad": {"Kikärtor": (380, "g"), "Matvete": (250, "g"), "Paprika": (1, "st"), "Citron": (1, "st")},
    "bonbowlmatvete": {"Kidneybönor": (400, "g"), "Matvete": (250, "g"), "Paprika": (1, "st"), "Salsa": (230, "g")},
    "svartbonsbowl": {"Svarta bönor": (380, "g"), "Matvete": (250, "g"), "Salsa": (230, "g"), "Majs": (150, "g")},
    "tofucurry": {"Tofu": (400, "g"), "Ris": (250, "g"), "Curry & grönsaker": (28, "g"), "Kokosmjölk": (400, "ml")},
    "teriyakitofu": {"Tofu": (400, "g"), "Matvete": (250, "g"), "Paprika": (1, "st"), "Soja": (30, "ml")},
    "halloumipasta": {"Halloumi": (225, "g"), "Pasta": (250, "g"), "Krossade tomater": (400, "g"), "Basilika": (1, "st")},
    "halloumicurry": {"Halloumi": (225, "g"), "Ris": (250, "g"), "Paprika": (1, "st"), "Curry & grönsaker": (28, "g")},
    "fetagryta": {"Feta": (200, "g"), "Krossade tomater": (400, "g"), "Kikärtor": (380, "g"), "Basilika": (1, "st")},
    "vegofarsgryta": {"Vegofärs": (400, "g"), "Ris": (250, "g"), "Krossade tomater": (400, "g"), "Paprika": (1, "st")},
    "korvgratang": {"Falukorv": (400, "g"), "Pasta": (250, "g"), "Krossade tomater": (400, "g"), "Riven ost": (100, "g")},
    "kottfarssas": {"Köttfärs": (500, "g"), "Pasta": (250, "g"), "Krossade tomater": (400, "g"), "Basilika": (1, "st")},
    "currykottfarsgryta": {"Köttfärs": (500, "g"), "Ris": (250, "g"), "Paprika": (1, "st"), "Curry & grönsaker": (28, "g")},
    "tandoorikyckling": {"Kycklingfilé": (500, "g"), "Ris": (250, "g"), "Curry & grönsaker": (28, "g"), "Yoghurt": (200, "g")},
    "citronflaskfile": {"Fläskfilé": (500, "g"), "Matvete": (250, "g"), "Citron": (1, "st"), "Timjan": (1, "st")},
    "biffgraddtimjan": {"Biff": (500, "g"), "Potatis": (800, "g"), "Grädde": (200, "ml"), "Timjan": (1, "st")},
    "zucchinipastafeta": {"Zucchini": (2, "st"), "Pasta": (250, "g"), "Krossade tomater": (400, "g"), "Feta": (200, "g")},
    "sparrispastacitron": {"Sparris": (300, "g"), "Pasta": (250, "g"), "Citron": (1, "st"), "Vitlök": (1, "st")},
    "morotscurry": {"Morötter": (400, "g"), "Kikärtor": (380, "g"), "Curry & grönsaker": (28, "g"), "Ris": (250, "g")},
}

BASE_PORTIONS = 4
_cache = {}


def fetch_nutrition_per_100g(nummer):
    if nummer in _cache:
        return _cache[nummer]
    url = f"{API_BASE}/livsmedel/{nummer}/naringsvarden?{urllib.parse.urlencode({'sprak': 1})}"
    with urllib.request.urlopen(url, timeout=20) as response:
        data = json.load(response)
    values = {"kcal": 0.0, "protein": 0.0, "kolhydrater": 0.0, "fett": 0.0}
    for item in data:
        code, unit, value = item["euroFIRkod"], item["enhet"], item["varde"]
        if code == "ENERC" and unit == "kcal":
            values["kcal"] = value
        elif code == "PROT":
            values["protein"] = value
        elif code == "CHO":
            values["kolhydrater"] = value
        elif code == "FAT":
            values["fett"] = value
    _cache[nummer] = values
    return values


def ingredient_grams(namn, amount, unit):
    if unit == "st":
        return amount * GRAM_PER_ST[namn]
    return amount  # "g" och "ml" behandlas som 1:1 (rimligt för vätskorna i receptet)


def nutrition_per_100g(namn):
    if namn in COOKED_ONLY:
        nummer, yield_factor = COOKED_ONLY[namn]
        cooked = fetch_nutrition_per_100g(nummer)
        return {key: value * yield_factor for key, value in cooked.items()}
    return fetch_nutrition_per_100g(INGREDIENT_MAP[namn])


def compute_recipe(quantities):
    totals = {"kcal": 0.0, "protein": 0.0, "kolhydrater": 0.0, "fett": 0.0}
    for namn, (amount, unit) in quantities.items():
        grams = ingredient_grams(namn, amount, unit)
        per_100g = nutrition_per_100g(namn)
        for key in totals:
            totals[key] += per_100g[key] * grams / 100
    return {key: round(value / BASE_PORTIONS) for key, value in totals.items()}


if __name__ == "__main__":
    for recipe_id, quantities in RECIPE_QUANTITIES.items():
        macros = compute_recipe(quantities)
        print(f"{recipe_id}: kcal={macros['kcal']} protein={macros['protein']}g "
              f"kolhydrater={macros['kolhydrater']}g fett={macros['fett']}g")
