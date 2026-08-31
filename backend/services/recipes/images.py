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

WHY WIKIMEDIA COMMONS: it needs no API key. Pexels and Unsplash have better
food photography but require a secret we do not have, so this is built so the
source is swappable - each source returns the same candidate shape, and
adding one is adding a function.
"""

import json
import re
import unicodedata
import urllib.parse
import urllib.request

USER_AGENT = "Matjakt/1.0 (receptbilder; https://matjakt.store)"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

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
    r"|public domain.*|pd[- ].*|no restrictions\s*)$",
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
    "raw ", "ingredient", "uncooked", "illustration", "drawing", "painting",
    "cartoon", "icon", "stamp", "coin", "book", "cover",
]

MIN_WIDTH = 640
MIN_SCORE = 2.0


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
    "pyttipanna": "hash", "raggmunk": "potato pancake",
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
    return score


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
            "title": page.get("title", "").removeprefix("File:"),
            "url": info.get("thumburl") or info.get("url"),
            "descriptionUrl": info.get("descriptionurl"),
            "license": licence,
            "credit": credit or "Wikimedia Commons",
            "width": info.get("width"), "source": "Wikimedia Commons",
        })
    return candidates


def find_image(recipe: dict, used_titles: set | None = None) -> dict | None:
    """The best licensed image that clearly shows this dish, or None.

    None is a real answer, not a failure: the recipe is still created, marked
    needs_image, and a placeholder is shown. A picture of the wrong food
    would be worse."""
    used_titles = used_titles if used_titles is not None else set()
    best = None
    for query in build_query(recipe):
        for candidate in search_commons(query):
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
