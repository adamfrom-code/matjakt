# -*- coding: utf-8 -*-
"""Hittar och verifierar receptbilder automatiskt.

The image is a large part of how a recipe feels, and choosing 200 of them by
hand is not work worth doing. So this searches, checks the licence, judges
whether the picture actually shows the dish, and writes the reference into
the recipe. Nothing here ever runs while a user is looking at the app.

THREE RULES, IN THIS ORDER

1. LICENCE FIRST. Only licences that permit commercial use are accepted, and
   the specific licence of the specific file is checked - "it came from
   Wikimedia Commons" proves nothing on its own, because Commons also hosts
   non-commercial and fair-use files. Anything we cannot state a licence for
   is rejected.

2. THE PICTURE MUST SHOW THE DISH. A photo of the wrong food is worse than no
   photo: it makes the app look careless in the one place a food app cannot
   afford to. Candidates are scored on how well the file's own title matches
   the dish, and a weak best candidate loses to a placeholder.

3. NO REUSE. The same generic picture on eight recipes reads as stock
   filler. A file already used by another recipe is skipped.

TWO SOURCES, NOT RANKED TOGETHER. Pexels is curated food photography whose
alt text describes the food; Wikimedia Commons is an encyclopedia archive
whose titles are whatever the uploader typed, full of hobby snapshots and
species pictures. Scoring them against each other let a Commons file beat a
better Pexels photo, so Commons is a FALLBACK - used only when Pexels finds
nothing, or when there is no key.

Each source returns the same candidate shape, so adding Unsplash later is
adding a function.
"""

import json
import re
import unicodedata
import urllib.parse
import urllib.request

import os
from pathlib import Path

USER_AGENT = "Matjakt/1.0 (receptbilder; https://matjakt.store)"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
PEXELS_API = "https://api.pexels.com/v1/search"

# The key is read from the environment or .env and never written anywhere -
# not to a file, not to a log line, not into the recipe data. Nothing here
# prints it, and the only thing that leaves this module is photo metadata.
def pexels_key() -> str:
    """The Pexels key, from the environment or from .env.

    CLI scripts do not go through api_server, which is what normally loads
    .env - so without this the key would have to be exported by hand every
    time, and the obvious next step would be pasting it into a file that gets
    committed. Reading .env here removes that temptation."""
    # An env var that is SET, even to empty, is an explicit answer: no key.
    # Falling through to .env in that case made the test suite reach the live
    # Pexels API - a unit test that needs the network is not a unit test, and
    # there would be no way to exercise the no-key path on a machine that has
    # one.
    if "PEXELS_API_KEY" in os.environ:
        return os.environ["PEXELS_API_KEY"].strip()
    env_file = Path(__file__).resolve().parents[3] / ".env"
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "PEXELS_API_KEY":
                return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


# The Pexels License permits commercial use without attribution. We store the
# photographer and the photo page anyway: crediting a photographer who did
# not demand it costs nothing, and a photo whose origin we cannot show is a
# photo we cannot defend later.
PEXELS_LICENCE = "Pexels License"

# Licences that allow commercial use. Anything not on this list is refused,
# including "no licence stated" - an unstated licence is not a permissive
# one, and Commons hosts plenty of files we may not use.
# NC/ND refused explicitly and the whole string checked, not just its start.
# An earlier version only anchored the beginning, so "CC BY-NC 4.0" matched
# on its "CC BY" prefix - it would have accepted non-commercial images for a
# commercial product. Caught by a test, which is the only reason to write one.
_NON_COMMERCIAL = re.compile(r"n[cd]|noncommercial|no[- ]derivat", re.IGNORECASE)
_PERMISSIVE = re.compile(
    r"^\s*(cc0.*|cc[- ]by([- ]sa)?([- ]?\d(\.\d)?)?\s*"
    r"|public domain.*|pd[- ].*|no restrictions\s*"
    # The Pexels License permits commercial use without attribution. Named
    # explicitly rather than pattern-matched: a licence we allow should be a
    # licence someone decided to allow.
    r"|pexels license\s*|unsplash license\s*)$",
    re.IGNORECASE)


class _LicenceCheck:
    """Matches only licences that genuinely permit commercial use."""

    @staticmethod
    def match(licence):
        text = (licence or "").strip()
        if not text or _NON_COMMERCIAL.search(text):
            return None
        return _PERMISSIVE.match(text)


COMMERCIAL_LICENCES = _LicenceCheck

# Words in a file title that mean it is not a plain photograph of a dish.
NOT_A_DISH_PHOTO = [
    "logo", "sign", "menu", "poster", "diagram", "map", "chart", "label",
    "packaging", "package", "box", "tin", "can ", "advert", "banner",
    "portrait", "chef", "cook", "restaurant", "kitchen", "market", "shop",
    "illustration", "drawing", "painting", "cartoon", "icon", "stamp",
    "coin", "book", "cover",
    # RAW INGREDIENTS. A recipe card wants the finished dish; "Frozen cod
    # fillet" is a photograph of a raw piece of fish in a freezer bag and was
    # picked for an oven-baked cod recipe.
    "raw ", "uncooked", "frozen", "fresh ", "ingredient", "fillets on",
    "in packaging", "defrost", "thawed",
    # SUBSTITUTE DISHES. These are different dishes that borrow the name of
    # the one we want: "Courgetti Spaghetti" is courgette noodles, and it was
    # picked for spaghetti with meat sauce. The word after the substitute is
    # ours, which is exactly why title matching alone accepts it.
    "courgetti", "zoodles", "zucchini noodle", "cauliflower rice",
    "konjac", "shirataki", "low carb", "keto ", "gluten-free ", "protein ",
]

MIN_WIDTH = 640
MIN_SCORE = 2.0

# Ingredient words that are ALSO the name of an animal or plant. Wikimedia
# Commons is full of species photography, so "Pacific cod - cropped" was
# picked for an oven-baked cod recipe - a photograph of a fish, not a meal.
#
# A blocklist cannot win this: there is no end to the ways a species photo can
# be titled. So for these dishes the requirement is POSITIVE - the title must
# say something was DONE to the food.
AMBIGUOUS_WITH_SPECIES = {
    "torsk", "lax", "cod", "salmon", "fisk", "fish", "kyckling", "chicken",
    "rakor", "shrimp", "prawn", "biff", "beef", "flask", "pork", "lamm", "lamb",
}

PREPARATION_WORDS = [
    "baked", "fried", "grilled", "roast", "stew", "soup", "gratin", "casserole",
    "curry", "sauce", "served", "plate", "dish", "dinner", "meal", "recipe",
    "cooked", "smoked", "poached", "steamed", "burger", "sandwich", "salad",
    "pasta", "rice", "potato", "with ", "and ",
    "gratang", "gryta", "soppa", "sas", "stekt", "ugnsbakad", "kokt", "grillad",
    "med ", "och ", "pa tallrik", "middag",
]


def needs_preparation_word(dish: str) -> bool:
    """True when a bare photo of this food would be a species picture."""
    return any(word in AMBIGUOUS_WITH_SPECIES for word in re.findall(r"[a-z0-9]+", _fold(dish)))


def has_preparation_word(title: str) -> bool:
    folded = _fold(title)
    return any(word in folded for word in PREPARATION_WORDS)


def _fold(text: str) -> str:
    lowered = str(text or "").lower()
    return "".join(c for c in unicodedata.normalize("NFD", lowered)
                   if unicodedata.category(c) != "Mn")


def _get(url: str, params: dict) -> dict:
    request = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)


# Wikimedia Commons is titled overwhelmingly in English, so a Swedish dish
# name finds nothing for perfectly common food: "Pannkakor" misses every one
# of the thousands of pancake photos. Searching the English term as well is
# the difference between a recipe having a picture and not.
#
# Only dishes are translated, not ingredients - "pancake" finds pancakes,
# while translating "grädde" would drag in unrelated cream photography.
DISH_TERMS_EN = {
    "pannkakor": "pancakes", "ugnspannkaka": "oven pancake",
    "kottbullar": "swedish meatballs", "kottfarssas": "bolognese sauce",
    "kottfarslimpa": "meatloaf", "lasagne": "lasagna", "tacos": "tacos",
    "hamburgare": "hamburger", "korvstroganoff": "sausage stroganoff",
    "pyttipanna": "swedish hash", "raggmunk": "potato pancake",
    "fisksoppa": "fish soup", "fiskgratang": "fish gratin",
    "kycklinggryta": "chicken stew", "kycklingwok": "chicken stir fry",
    "kottgryta": "beef stew", "gulaschsoppa": "goulash soup",
    "tomatsoppa": "tomato soup", "linssoppa": "lentil soup",
    "artsoppa": "pea soup", "chili": "chili con carne",
    "risotto": "risotto", "paella": "paella", "curry": "curry",
    "omelett": "omelette", "aggrora": "scrambled eggs",
    "potatisgratang": "potato gratin", "gratang": "gratin",
    "pastasallad": "pasta salad", "sallad": "salad",
    "wok": "stir fry", "biff": "steak", "schnitzel": "schnitzel",
    "laxfile": "salmon fillet", "lax": "salmon", "torsk": "cod",
    "rakor": "shrimp", "kyckling": "chicken", "flaskfile": "pork tenderloin",
    "falukorv": "sausage", "korv": "sausage", "pasta": "pasta",
    "soppa": "soup", "gryta": "stew", "bowl": "grain bowl",
    "smorgastarta": "sandwich cake", "paj": "savoury pie",
    "pizza": "pizza", "burrito": "burrito", "wrap": "wrap",
    "couscous": "couscous", "bulgur": "bulgur", "quinoa": "quinoa",
    # Added after a backfill left 23 recipes without a picture: Swedish
    # compound dish names that Pexels has plenty of photos of, under an
    # English word we had not given it.
    "gratang": "casserole", "pastagratang": "baked pasta",
    "potatisgratang": "potato gratin", "fiskgratang": "fish casserole",
    "korvgratang": "sausage casserole", "rotfruktsgratang": "root vegetable gratin",
    "bolognese": "bolognese", "vegobolognese": "vegetarian bolognese",
    "linsbolognese": "lentil bolognese", "kottfarslimpa": "meatloaf",
    "tofuwok": "tofu stir fry", "biffwok": "beef stir fry",
    "teriyakilax": "teriyaki salmon", "teriyakitofu": "teriyaki tofu",
    "flaskkarre": "pork roast", "flaskfile": "pork tenderloin",
    "makaroner": "macaroni", "ugnspannkaka": "baked pancake",
    "aggrora": "scrambled eggs", "lax": "salmon dish",
    "torsk": "cod dish", "biff": "beef steak",
    # Added when 59 of 205 recipes sat imageless: dishes Pexels has plenty
    # of, under words the map did not know yet.
    "fajitas": "chicken fajitas", "kycklingfajitas": "chicken fajitas",
    "tikka": "tikka masala", "minestrone": "minestrone",
    "burgare": "burger", "halloumiburgare": "halloumi burger",
    "bonburgare": "veggie burger", "quesadillas": "quesadilla",
    "spett": "skewers", "kycklingspett": "chicken skewers",
    "klubbor": "chicken drumsticks", "kycklingklubbor": "baked chicken drumsticks",
    "fiskpinnar": "fish sticks", "nudelwok": "noodle stir fry",
    "gravadlax": "cured salmon", "kalops": "beef stew",
    "kalpudding": "cabbage casserole", "dillkott": "beef stew dill",
    "wallenbergare": "veal patty", "pannbiff": "beef patty",
    "farsbiffar": "meat patties", "biffar": "patties",
    "risgrynsgrot": "rice pudding", "grot": "porridge",
    "daal": "dal curry", "falafel": "falafel", "paj": "quiche",
    "gronsakspaj": "vegetable quiche", "poke": "poke bowl",
    "pokebowl": "poke bowl", "carbonara": "pasta carbonara",
    "caesarsallad": "caesar salad", "shakshuka": "shakshuka",
    "gulasch": "goulash", "stroganoff": "stroganoff",
    "potatissoppa": "potato soup", "morotssoppa": "carrot soup",
    "sotpotatissoppa": "sweet potato soup", "broccolisoppa": "broccoli soup",
    "spenatsoppa": "spinach soup", "vitkalssoppa": "cabbage soup",
    "kottfarssoppa": "minestrone", "sill": "pickled herring",
    "pyttipanna": "swedish hash", "pytt": "swedish hash",
    "tzatziki": "tzatziki", "gnocchipanna": "gnocchi",
    "gnocchi": "gnocchi", "toast": "toast skagen",
}

# Swedish food words -> the English word a Pexels photographer would use.
# This is what lets an ENGLISH title score at all: the queries are Swedish
# and Pexels' search understands them fine, but the scorer judges the title
# text - and "Delicious grilled salmon with broccoli and rice" contains not
# one Swedish word. Compound-aware: "kycklinglada" hits "kyckling".
INGREDIENT_EN = {
    "kyckling": "chicken", "lax": "salmon", "torsk": "cod", "sej": "fish",
    "fisk": "fish", "rakor": "shrimp", "tonfisk": "tuna", "sill": "herring",
    "biff": "steak", "notfars": "beef", "blandfars": "beef", "kottfars": "beef",
    "hogrev": "beef", "lovbiff": "beef", "rostbiff": "roast beef",
    "flask": "pork", "karre": "pork", "kassler": "pork", "bacon": "bacon",
    "korv": "sausage", "chorizo": "chorizo", "kalv": "veal",
    "halloumi": "halloumi", "feta": "feta", "mozzarella": "mozzarella",
    "chevre": "goat cheese", "ost": "cheese", "tofu": "tofu", "agg": "egg",
    "kikartor": "chickpeas", "linser": "lentil", "bonor": "beans",
    "potatis": "potato", "sotpotatis": "sweet potato", "ris": "rice",
    "pasta": "pasta", "spaghetti": "spaghetti", "makaroner": "macaroni",
    "nudlar": "noodle", "bulgur": "bulgur", "quinoa": "quinoa",
    "broccoli": "broccoli", "blomkal": "cauliflower", "morot": "carrot",
    "morotter": "carrot", "paprika": "pepper", "tomat": "tomato",
    "champinjoner": "mushroom", "svamp": "mushroom", "spenat": "spinach",
    "majs": "corn", "vitkal": "cabbage", "rodbetor": "beetroot",
    "artor": "peas", "artsoppa": "pea soup", "dill": "dill",
    "citron": "lemon", "lime": "lime", "kokos": "coconut", "curry": "curry",
    "teriyaki": "teriyaki", "pesto": "pesto", "apple": "apple",
    "avokado": "avocado", "banan": "banana", "purjolok": "leek",
    "zucchini": "zucchini", "sparris": "asparagus", "mos": "mashed",
}


def english_terms(dish: str) -> list[str]:
    """English search terms for a Swedish dish name, best first."""
    folded = _fold(dish)
    terms = []
    if folded in DISH_TERMS_EN:
        terms.append(DISH_TERMS_EN[folded])
    # Compound heads: "kycklinggryta" is a gryta, "fisksoppa" is a soppa.
    for swedish, english in DISH_TERMS_EN.items():
        if folded != swedish and folded.endswith(swedish) and len(swedish) > 3:
            terms.append(f"{english}")
    return list(dict.fromkeys(terms))


def build_query(recipe: dict) -> list[str]:
    """Search terms for a recipe, most specific first.

    Built from the DISH, not from a random word: the recipe's own name
    without its trailing garnish clause, then the name of the main
    ingredient with the dish type. Searching for "lasagne" finds lasagne;
    searching for "lasagne med spenat och ricotta" finds nothing."""
    name = recipe.get("name") or ""
    # Swedish recipe names are "<dish> med <sides>" - the dish is the part
    # before "med", and that is what a photo is of.
    dish = re.split(r"\s+med\s+|\s+och\s+|,", name, maxsplit=1)[0].strip()
    queries = [dish]
    if dish.lower() != name.lower():
        queries.append(name)
    # A main ingredient plus the dish type widens the net without drifting
    # to a different food.
    mains = [i["name"] for i in (recipe.get("ingredients") or [])
             if not i.get("pantryStaple")][:1]
    for main in mains:
        queries.append(f"{main} {dish}")
    # English last: a Swedish title is stronger evidence that the photo is of
    # the Swedish dish, so it gets first refusal.
    queries.extend(english_terms(dish))
    return [q for q in dict.fromkeys(queries) if len(q) > 2]


def score_candidate(title: str, recipe: dict) -> float:
    """How well a file title matches the dish. Higher is better.

    Deliberately blunt: this cannot see the picture, so it judges the words
    the uploader chose. A blunt score that refuses when unsure is better than
    a clever one that guesses."""
    folded_title = _fold(title)
    if any(bad in folded_title for bad in NOT_A_DISH_PHOTO):
        return 0.0

    name_words = [w for w in re.findall(r"[a-z0-9]+", _fold(recipe.get("name", "")))
                  if len(w) > 3]
    if not name_words:
        return 0.0
    dish = re.split(r"\s+med\s+|\s+och\s+|,", recipe.get("name", ""), maxsplit=1)[0].strip()

    # For food that shares its name with an animal or plant, the title has to
    # say something was DONE to it. Otherwise we are looking at the species.
    if needs_preparation_word(recipe.get("name", "")) and not has_preparation_word(title):
        return 0.0

    # A short, generic dish word is not evidence of anything. "Fisk" is four
    # letters and also a surname - it matched "Fisk, Joel H - 1st Cavalry",
    # a photograph of a man. Generic words only count as part of a longer
    # phrase, never on their own.
    if len(_fold(dish)) < 5 and _fold(dish) not in {"lax", "ris"}:
        return 0.0

    # An English title scores on the translated dish word, since the Swedish
    # one will not appear in it - but only if no OTHER known dish matches the
    # title better. "Potato pancakes" contains "pancakes", yet it is
    # raggmunk, not pannkakor: a different dish that happens to contain our
    # word. Letting the longest matching dish term win settles that without
    # a list of special cases.
    for term in english_terms(dish):
        if not all(word in folded_title for word in term.split()):
            continue
        competing = [other for other in DISH_TERMS_EN.values()
                     if other != term and len(other) > len(term)
                     and all(word in folded_title for word in other.split())]
        if competing:
            return 0.0
        return 2.6
    # The dish word carries most of the weight - "lasagne" appearing in the
    # title is far stronger evidence than "spenat" doing so.
    score = 0.0
    for index, word in enumerate(name_words):
        if word in folded_title:
            score += 2.0 if index == 0 else 0.6

    # English titles: translate the recipe's own food words and score hits.
    # Pexels' search understands the Swedish queries and returns the right
    # dishes - "Delicious grilled chicken fajitas with bell peppers" for
    # "Kycklingfajitas" - but not one Swedish word appears in that title, so
    # 59 recipes sat imageless while their perfect photos scored 0.0. The
    # first (head) signal is the main ingredient and carries the most; a
    # title that names the main ingredient plus one more of the recipe's own
    # foods clears the bar, one incidental word alone does not.
    # THE PROTEIN GATE, on the English contribution only. When the recipe's
    # main food is a protein, an ENGLISH title must name it (or an accepted
    # stand-in) before any English word may add points - "teriyaki" plus
    # "rice" must not carry a picture whose salmon is nowhere to be seen.
    # A SWEDISH title that already matched the recipe's own words is not
    # touched by this: it named the dish itself, which is stronger evidence
    # than any translated ingredient list.
    signals = _english_signals(recipe)
    gate_open = bool(signals) and (
        signals[0] not in PROTEIN_ACCEPT
        or any(word in folded_title for word in PROTEIN_ACCEPT[signals[0]]))
    if gate_open:
        for position, english in enumerate(signals):
            if all(word in folded_title for word in english.split()):
                score += 1.4 if position == 0 else 0.7
    return score


# For each protein, the title words that count as showing it. Deliberately
# narrow: "meat" is accepted for the red meats (a cutlet caption often says
# just "meat"), never for fish or chicken - a photo captioned "meat" is not
# a salmon dinner.
PROTEIN_ACCEPT = {
    "chicken": ("chicken",),
    "salmon": ("salmon",),
    "cod": ("cod", "white fish", "fish fillet"),
    "fish": ("fish", "cod", "salmon"),
    "shrimp": ("shrimp", "prawn"),
    "tuna": ("tuna",),
    "herring": ("herring",),
    "steak": ("steak", "beef"),
    "beef": ("beef", "steak", "meat", "mince"),
    "roast beef": ("roast beef", "beef"),
    "pork": ("pork",),
    "veal": ("veal", "cutlet", "patty", "schnitzel", "meat"),
    "sausage": ("sausage", "hot dog"),
    "bacon": ("bacon",),
    "chorizo": ("chorizo", "sausage"),
    "halloumi": ("halloumi",),
    "tofu": ("tofu",),
    "egg": ("egg",),
}


def _english_signals(recipe: dict) -> list[str]:
    """The recipe's food words in English, main ingredient first."""
    seen, ordered = set(), []
    def add(text):
        for token in re.findall(r"[a-z]+", _fold(text or "")):
            for swedish, english in INGREDIENT_EN.items():
                if (token == swedish or (len(swedish) > 3 and
                        (token.endswith(swedish) or token.startswith(swedish)))):
                    if english not in seen:
                        seen.add(english)
                        ordered.append(english)
    add(recipe.get("name"))
    for ingredient in (recipe.get("ingredients") or [])[:6]:
        if isinstance(ingredient, dict) and not ingredient.get("pantryStaple"):
            add(ingredient.get("name"))
    return ordered


def search_commons(query: str, limit: int = 12) -> list[dict]:
    """Candidate images from Wikimedia Commons, with their licences."""
    try:
        data = _get(COMMONS_API, {
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6,
            "gsrlimit": limit, "prop": "imageinfo",
            "iiprop": "url|size|extmetadata", "iiurlwidth": 1024,
        })
    except Exception:
        return []

    candidates = []
    for page in (data.get("query", {}).get("pages") or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        licence = (meta.get("LicenseShortName", {}).get("value") or "").strip()
        if not COMMERCIAL_LICENCES.match(licence):
            continue
        if (info.get("width") or 0) < MIN_WIDTH:
            continue
        credit = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value") or "").strip()
        candidates.append({
            "creditUrl": info.get("descriptionurl"), "photoId": "",
            "title": page.get("title", "").removeprefix("File:"),
            "url": info.get("thumburl") or info.get("url"),
            "descriptionUrl": info.get("descriptionurl"),
            "license": licence,
            "credit": credit or "Wikimedia Commons",
            "width": info.get("width"), "source": "Wikimedia Commons",
        })
    return candidates


def search_pexels(query: str, limit: int = 15) -> list[dict]:
    """Candidate photos from Pexels, in the same shape as the Commons search.

    Pexels is stock food photography: brighter, better composed and far more
    likely to show a plated dish than Wikimedia Commons, which is mostly
    hobby snapshots and species pictures. It needs a key, so it is used when
    one exists and skipped silently when it does not."""
    key = pexels_key()
    if not key:
        return []
    request = urllib.request.Request(
        f"{PEXELS_API}?{urllib.parse.urlencode({'query': query, 'per_page': limit, 'orientation': 'landscape'})}",
        headers={"Authorization": key, "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            data = json.load(response)
    except Exception:
        # A failing image source must never stop a recipe from being created.
        return []

    candidates = []
    for photo in data.get("photos") or []:
        source = photo.get("src") or {}
        url = source.get("large") or source.get("original")
        if not url or (photo.get("width") or 0) < MIN_WIDTH:
            continue
        candidates.append({
            # Pexels' own alt text describes the photo's CONTENT, which is a
            # far better relevance signal than a filename - Commons titles
            # are whatever the uploader felt like typing.
            # No alt text means no evidence of what the photo shows. An
            # earlier fallback used the QUERY as the title - which then
            # matched itself perfectly, so any altless photo Pexels returned
            # scored as ideal. That is how "Teriyakilax" got a rice bowl
            # whose own slug said "meat". Empty title = candidate skipped.
            "title": (photo.get("alt") or "").strip(),
            "url": url,
            "descriptionUrl": photo.get("url"),
            "license": PEXELS_LICENCE,
            "credit": photo.get("photographer") or "Pexels",
            "creditUrl": photo.get("photographer_url"),
            "photoId": str(photo.get("id") or ""),
            "width": photo.get("width"),
            "source": "Pexels",
        })
    return candidates


def search_sources(query: str) -> list[dict]:
    """Pexels first, and Commons ONLY when Pexels found nothing.

    They are not comparable sources. Pexels is curated food photography whose
    alt text describes the food; Commons is an encyclopedia archive whose
    titles are whatever the uploader typed. Ranking them together let a
    Commons file outscore a genuinely better Pexels photo - that is how
    pyttipanna ended up with "War Department. The Adjutant General's Office",
    a US military archive photograph that matched the English word "hash".

    So Commons is a fallback, not a competitor."""
    from_pexels = search_pexels(query)
    return from_pexels if from_pexels else search_commons(query)


def find_image(recipe: dict, used_titles: set | None = None) -> dict | None:
    """The best licensed image that clearly shows this dish, or None.

    None is a real answer, not a failure: the recipe is still created, marked
    needs_image, and a placeholder is shown. A picture of the wrong food
    would be worse."""
    used_titles = used_titles if used_titles is not None else set()
    best = None
    for query in build_query(recipe):
        for candidate in search_sources(query):
            if not candidate["title"]:
                continue
            if candidate["title"] in used_titles:
                continue
            score = score_candidate(candidate["title"], recipe)
            if score >= MIN_SCORE and (best is None or score > best[0]):
                best = (score, candidate)
        if best and best[0] >= 2.6:
            break  # good enough; stop hitting the API
    if not best:
        return None
    score, candidate = best
    return {
        "image": candidate["url"],
        "imageSource": candidate["source"],
        "imageSourceUrl": candidate["descriptionUrl"],
        "imageCredit": candidate["credit"],
        "imageCreditUrl": candidate.get("creditUrl"),
        "imagePhotoId": candidate.get("photoId"),
        "imageLicense": candidate["license"],
        "imageAlt": f"{recipe['name']} upplagd på tallrik",
        "imageTitle": candidate["title"],
        "imageScore": round(score, 2),
        "imageStatus": "ok",
    }


def placeholder(recipe: dict) -> dict:
    """What a recipe gets when no image passes. Explicit, so the gap can be
    found and filled later rather than discovered by a user."""
    return {
        "image": None, "imageSource": None, "imageSourceUrl": None,
        "imageCredit": None, "imageLicense": None,
        "imageAlt": recipe.get("name"), "imageStatus": "needs_image",
    }
