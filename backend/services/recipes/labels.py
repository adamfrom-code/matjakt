# -*- coding: utf-8 -*-
"""ETT etikettfält, ett format - nyckeln normaliserad, namnet läsbart.

Fram till M4 bar receptbanken TVÅ fält med överlappande innehåll: `categories`
och `tags`. Nio etiketter fanns i båda, i var sin versalisering - `Kött` i det
ena, `kott` i det andra - och filtret i `RecipeStore.search` jämförde med
likhet mot strängen. Alltså:

    filter "kott"            gav 39 recept     filter "Kött"   gav 18
    filter "husmanskost"     gav 74            "Husmanskost"   gav 69
    filter "familjefavorit"  gav 0             "Familjefavorit" gav 54

Den sista raden är felets hela form. `Familjefavorit` stavas likadant i båda
fälten - med versal - så hyllan "Familjemiddag" i `api.SHELVES` var tvungen
att skrivas `"tags": ["Familjefavorit"]` för att hitta något alls. Den som i
stället skrev den normaliserade formen fick noll träffar, och ingenting sa
ifrån: en tom lista ser ut som "vi har inga sådana recept".

DÄRFÖR: en etikett har en NYCKEL och ett NAMN.

* **Nyckeln** är det datorn jämför med - gemen, utan diakriter, härledd med
  samma slug-regel som `normalize_ingredient_id` använder för ingredienser.
  `Kött`, `kott` och `KÖTT ` är samma etikett, för de blir samma nyckel.
* **Namnet** är det människan läser - `Kött`, med sitt versala K och sitt ö.
  Det är en FUNKTION AV NYCKELN (`display`), inte en kolumn: två rader kan
  därmed inte bära olika namn för samma etikett, vilket är precis den sortens
  drift som M4 städar bort.

Nyckeln lagras i `recipe_labels.value`; namnet räknas fram vid läsning.

VÄRDEFÖRRÅDET ÄR ÖPPET, TILL SKILLNAD FRÅN `meal_types`. En etikett beskriver
maten och nya sorter ska kunna tillkomma utan ett kodsläpp. Det som är stängt
är FORMATET: varje etikett passerar `normalize_label_id` på väg in, så en ny
etikett kan aldrig komma in i två versaliseringar. Saknar en nyckel sitt namn
i `DISPLAY_NAMES` härleds ett läsbart namn ur nyckeln - ett hyggligt namn är
bättre än ett tomt fält, och den som vill ha "Snabbt & enkelt" i stället för
"Snabbt enkelt" skriver in raden.
"""

# nyckel -> namnet som visas. Namnen är bankens egna: den versaliserade formen
# där en sådan fanns, annars etikettens egen form med versal begynnelse.
# `snabbt-enkelt` är skälet till att tabellen inte kan ersättas av `.title()`:
# nyckeln har tappat sitt "&", och bara en uppslagning kan ge tillbaka det.
DISPLAY_NAMES = {
    # Vad rätten är gjord av.
    "kott": "Kött",
    "fisk": "Fisk",
    "kyckling": "Kyckling",
    "vegetariskt": "Vegetariskt",
    "veganskt": "Veganskt",
    # Vad det är för sorts rätt.
    "husmanskost": "Husmanskost",
    "pasta": "Pasta",
    "grytor": "Grytor",
    "soppor": "Soppor",
    "soppa": "Soppa",
    "ris": "Ris",
    # När den äts.
    "vardagsmat": "Vardagsmat",
    "helgmiddag": "Helgmiddag",
    "helg": "Helg",
    "lunch": "Lunch",
    # Vem den är för, och hur den lagas.
    "familj": "Familj",
    "familjefavorit": "Familjefavorit",
    "barn": "Barn",
    "billigt": "Billigt",
    "snabbt": "Snabbt",
    "snabbt-enkelt": "Snabbt & enkelt",
    "proteinrikt": "Proteinrikt",
    # Ett ord, inte "Meal prep": namnet måste normalisera tillbaka till sin
    # egen nyckel, annars är det visade namnet ett tredje sätt att skriva
    # etiketten. "Meal prep" ger nyckeln `meal-prep`, som är en ANNAN etikett
    # än `mealprep` - och två nycklar för samma sak är exakt det fel M4
    # städar bort. Ett test håller kvar den rundgången för varje namn här.
    # (Hyllans rubrik på receptsidan heter fortfarande "Meal prep"; en rubrik
    # är en mening till en människa, inte en etikett.)
    "mealprep": "Mealprep",
    "bulk": "Bulk",
}

# Kinden i `recipe_labels` som bär det sammanslagna fältet. `allergens` och
# `dietFlags` ligger kvar som egna kinder: de svarar på andra frågor ("vad
# finns i rätten", "vilken kosthållning passar den") och har aldrig varit
# klassade åt två håll - varje värde i dem är redan i nyckelform.
LABELS = "labels"

# De två fälten som slogs ihop, i den ordning de vävdes: kategorierna först.
# Ordningen är inte kosmetik. Appen visar `categories[0]` som badge på
# receptkortet (`typ` i frontendens receptmodell), och den badgen ska inte
# ändras av en datastädning. Se `scripts/normalize_recipe_labels.py`.
LEGACY_KINDS = ("categories", "tags")


def normalize_label_id(value) -> str:
    """Etikettens nyckel: gemen, utan diakriter, ett bindestreck per glapp.

    Härledd genom `normalize_ingredient_id` i stället för att kopiera regeln,
    för uppdraget säger uttryckligen "samma form som `normalize_ingredient_id`
    redan använder" - och två kopior av en regel driver isär. Importen ligger
    inne i funktionen för att bryta cirkeln: `store` importerar den här
    modulen för att kunna normalisera vid skrivning."""
    from .store import normalize_ingredient_id
    return normalize_ingredient_id(value or "")


def display(value) -> str:
    """Etikettens läsbara namn. Tar både en nyckel och en obearbetad sträng.

    Fallbacken gör en nyckel läsbar i stället för att lämna ett tomt fält:
    `nyttig-vardag` blir "Nyttig vardag". Den som vill ha ett annat namn
    skriver in raden i DISPLAY_NAMES - fallbacken är en rimlig gissning, inte
    ett facit."""
    key = normalize_label_id(value)
    if not key:
        return ""
    if key in DISPLAY_NAMES:
        return DISPLAY_NAMES[key]
    ord_ = key.replace("-", " ")
    return ord_[:1].upper() + ord_[1:]


def label(value) -> dict:
    """Etiketten som appen och testerna ser den: nyckel plus namn."""
    return {"key": normalize_label_id(value), "name": display(value)}


def merge(*groups) -> list[str]:
    """Väver ihop flera etikettlistor till EN, i ordning och utan dubbletter.

    Ordningen bevaras från första förekomsten, och det är hela poängen med
    argumentordningen: `merge(categories, tags)` lägger kategorierna först,
    så att den etikett som låg först före sammanslagningen ligger först efter
    den också. `Husmanskost` och `husmanskost` möts i samma nyckel och blir en
    enda etikett - den dubbletten ÄR felet M4 rättar."""
    ordning = []
    for group in groups:
        for value in group or []:
            # En etikett som kommer tillbaka ur `_to_dict` är {"key", "name"}.
            # Att ta emot den formen här gör en recept-dict rundgångbar: läs
            # ut ett recept, skriv tillbaka det, få samma etiketter.
            if isinstance(value, dict):
                value = value.get("key") or value.get("name") or ""
            key = normalize_label_id(value)
            if key and key not in ordning:
                ordning.append(key)
    return ordning
