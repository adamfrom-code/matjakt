"""Recipe Pricing Engine - turns a week's ingredient needs into a real
checkout cost per chain, using the products actually in grocery.db.

    INGREDIENTS (already summed for the week)
      -> conservative match to a real product per chain
      -> whole-package maths (you buy packages, not grams)
      -> real checkout cost + honest coverage

Two rules shape everything here:

1. NEVER INVENT A PRICE. An ingredient with no confident product match, or a
   matched product with no price, is reported as missing - never estimated,
   never silently skipped from the total in a way that makes a chain look
   cheaper than it is. A total is only comparable when you also know how much
   of the list it actually covers, which is why every result carries coverage.

2. CONSERVATIVE MATCHING. A wrong match is worse than no match: pricing
   "kycklingfilé" against kycklingkorv produces a confidently wrong number,
   which is more damaging than admitting we don't know. Matching therefore
   requires the ingredient to be what the product name LEADS with, matches
   Swedish compounds only on their head (last) element, and rejects
   known-confusable categories outright (see INGREDIENT_RULES).

=== KNOWN LIMITATION - READ BEFORE TRUSTING COVERAGE NUMBERS ===
Name-only matching has a hard precision ceiling, and this module is at it.
Swedish compounds put the head last, so "messmör" (whey spread), "levainrost"
(bread) and "frasrost" (crispbread) are grammatically headed by smör/ost and
cannot be told apart from the real ingredient by name alone. Each one found
in live data has been added to INGREDIENT_RULES, but that is whack-a-mole,
not a general solution.

The real fix is CATEGORY data. City Gross already returns proper categories
(bfCategory: "Mellanmjölk"); Willys and Hemköp expose a category tree
endpoint that the collectors do not yet use (they search by term instead).
Collecting by category would give every product a category and let matching
require "this product is in the dairy category" rather than inferring it
from the name. That is the single highest-value improvement to this engine
and is NOT done yet.

Consequence today: coverage against a term-collected catalog is roughly
50-70%, and the misses are honest misses (reported in missingItems), not
silent wrong prices. Treat coverage as a first-class part of any total.
"""

import math
import re
import unicodedata

# =============================================================================
# CATEGORY (DEPARTMENT) MATCHING
# =============================================================================
# Name-only matching has a hard precision ceiling (see the module docstring).
# Real category data raises it, because the aisle a product sits in is a fact
# the chain asserts - not something inferred from a Swedish compound noun.
#
# The department keywords below are taken from the ACTUAL category vocabulary
# of the live chains (verified 2026-08-31 by walking Willys' 452 and Hemkop's
# 428 leaf categories, plus City Gross' superCategory/category/bfCategory
# triplet), not from a guess at what a Swedish grocery tree looks like.
#
# Matching is on the WHOLE category path ("Mejeri, ost & agg > Mjolk >
# Lattmjolk"), because the department only ever appears in the ancestors.
# Keywords are written folded (accent-stripped, lowercase) because that is
# what they are compared against.
DEPARTMENT_KEYWORDS = {
    "meat": ["kott, chark", "kott, fagel", "chark & fagel", "fagel & chark",
             "kott & fagel", "kott & kyckling", "kott, burgare"],
    "fish": ["fisk & skaldjur", "fisk och skaldjur"],
    "dairy": ["mejeri", "ost & agg", "delikatessen > ost"],
    "produce": ["frukt & gront", "frukt och gront", "potatis & rotsaker",
                "kal & rotsaker"],
    "pantry": ["skafferi"],
    "bread": ["brod & kakor", "brod och kakor"],
    "frozen": ["fryst"],
    "readymeal": ["fardigmat"],
    "vegetarian": ["vegetariskt"],
    "deli": ["delikatessen"],
    "drinks": ["dryck"],
    # Departments a raw recipe ingredient NEVER comes from. This is the
    # single broadest precision win: it rejects the whole class of failures
    # that name rules had to fight one at a time - dog food ("Mini Small
    # Kyckling Ris Active"), sweets ("Chokladagg"), snacks ("Micropop Smor
    # Popcorn").
    # Matched on WORD BOUNDARIES, not as raw substrings - "djur" as a plain
    # substring also matches "skaldjur", which classified every shrimp and
    # shellfish aisle as pet food and took "Räkor" from 13 candidates to 0.
    "pet": ["djur", "hund", "katt", "smadjur", "djurmat", "djurtillbehor"],
    "baby": ["barn", "blojor", "valling & ersattning", "barnmat", "barnsnacks",
             "barnvard"],
    "nonfood": ["hem & stad", "hem & hushall", "halsa & skonhet", "apotek",
                "tobak", "kiosk", "blommor", "gor det sjalv", "media", "klader"],
    "confectionery": ["godis", "snacks", "chips", "choklad", "tuggummi",
                      "popcorn", "glass"],
}

# Departments that never contain a cooking ingredient, whatever the recipe
# asks for. Applied to every ingredient, so no per-ingredient rule is needed.
NEVER_INGREDIENT_DEPARTMENTS = {"pet", "baby", "nonfood", "confectionery"}

# Which departments an ingredient may legitimately come from. An ingredient
# NOT listed here gets no category constraint beyond the universal one - the
# name rules alone decide, exactly as before. That keeps this additive: it
# can reject a wrong match, never invent a right one.
#
# Frozen is allowed wherever a frozen form is a real product a shopper would
# buy (frozen fish, frozen berries), and left out where it would let a ready
# meal in.
INGREDIENT_DEPARTMENTS = {
    # --- dairy
    "smör": {"dairy"},
    "grädde": {"dairy"},
    "vispgrädde": {"dairy"},
    "matlagningsgrädde": {"dairy"},
    "crème fraiche": {"dairy"},
    "gräddfil": {"dairy"},
    "mjölk": {"dairy"},
    "filmjölk": {"dairy"},
    "yoghurt": {"dairy"},
    "kvarg": {"dairy"},
    "ost": {"dairy", "deli"},
    "riven ost": {"dairy", "deli"},
    "fetaost": {"dairy", "deli"},
    "halloumi": {"dairy", "deli"},
    "parmesan": {"dairy", "deli"},
    "mozzarella": {"dairy", "deli"},
    "ägg": {"dairy"},
    "margarin": {"dairy"},
    # --- meat
    "kycklingfilé": {"meat", "frozen"},
    "kycklinglårfilé": {"meat", "frozen"},
    "kyckling": {"meat", "frozen"},
    "köttfärs": {"meat", "frozen"},
    "blandfärs": {"meat", "frozen"},
    "fläskfilé": {"meat", "frozen"},
    "fläskkarré": {"meat", "frozen"},
    "bacon": {"meat"},
    "korv": {"meat", "frozen"},
    "falukorv": {"meat"},
    "skinka": {"meat", "deli"},
    "biff": {"meat", "frozen"},
    "högrev": {"meat", "frozen"},
    "lammfärs": {"meat", "frozen"},
    # --- fish
    "lax": {"fish", "frozen"},
    "laxfilé": {"fish", "frozen"},
    "torsk": {"fish", "frozen"},
    "torskfilé": {"fish", "frozen"},
    "räkor": {"fish", "frozen"},
    "fiskfilé": {"fish", "frozen"},
    # --- produce
    "lök": {"produce"},
    "gul lök": {"produce"},
    "rödlök": {"produce"},
    "vitlök": {"produce"},
    "potatis": {"produce", "frozen"},
    "morot": {"produce"},
    "morötter": {"produce"},
    "paprika": {"produce"},
    "tomat": {"produce"},
    "tomater": {"produce"},
    "gurka": {"produce"},
    "citron": {"produce"},
    "lime": {"produce"},
    "broccoli": {"produce", "frozen"},
    "blomkål": {"produce", "frozen"},
    "squash": {"produce"},
    "zucchini": {"produce"},
    "champinjoner": {"produce"},
    "spenat": {"produce", "frozen"},
    "salladslök": {"produce"},
    "purjolök": {"produce"},
    "ingefära": {"produce"},
    "avokado": {"produce"},
    "äpple": {"produce"},
    "banan": {"produce"},
    "majs": {"produce", "pantry", "frozen"},
    "ärtor": {"produce", "frozen", "pantry"},
    # --- pantry
    "ris": {"pantry"},
    "pasta": {"pantry"},
    "spaghetti": {"pantry"},
    "makaroner": {"pantry"},
    "nudlar": {"pantry"},
    "couscous": {"pantry"},
    "bulgur": {"pantry"},
    "matvete": {"pantry"},
    "quinoa": {"pantry"},
    "linser": {"pantry"},
    "kikärtor": {"pantry"},
    "svarta bönor": {"pantry"},
    "kidneybönor": {"pantry"},
    "krossade tomater": {"pantry"},
    "tomatpuré": {"pantry"},
    "kokosmjölk": {"pantry"},
    "buljong": {"pantry"},
    "mjöl": {"pantry"},
    "vetemjöl": {"pantry"},
    "socker": {"pantry"},
    "olja": {"pantry"},
    "olivolja": {"pantry"},
    "rapsolja": {"pantry"},
    "vinäger": {"pantry"},
    "soja": {"pantry"},
    "currypasta": {"pantry"},
    "havregryn": {"pantry"},
    # --- bread
    "bröd": {"bread"},
    "tortilla": {"bread", "pantry"},
    # --- vegetarian
    "tofu": {"vegetarian"},
    "quorn": {"vegetarian", "frozen"},
}


def _keyword_in_path(keyword: str, folded_path: str) -> bool:
    """Whole-word match of a department keyword inside a folded category path.

    A plain `in` test is not safe here: Swedish compounds put the head last,
    so "skaldjur" ends with "djur" and "risdryck" ends with "dryck". Matching
    by substring therefore filed shellfish under pet food and rice drink
    under beverages. Word boundaries mirror the grammar - "skaldjur" is not
    "djur", it is its own word."""
    return re.search(rf"\b{re.escape(keyword)}\b", folded_path) is not None


# Staples where the DEPARTMENT is too coarse to be useful. "Skafferi" holds
# rice, pasta, tinned asparagus, baking supplies and marinades alike, so
# allowing the whole department let real wrong matches through against live
# data: "Ris" -> "Sparris i Bitar" (tinned vegetables), "Pasta" ->
# "Dadelpasta" (date paste, in baking supplies). Both end with the
# ingredient word, so the Swedish compound-head rule accepts them and only
# the aisle can tell them apart.
#
# The chains do carry a specific aisle for each of these ("Skafferi > Pasta,
# ris & matgryn > Ris"), so requiring the aisle to NAME the ingredient is a
# real signal rather than another hand-written exception.
INGREDIENT_CATEGORY_KEYWORDS = {
    "ris": ["ris"],
    "pasta": ["pasta", "spaghetti", "makaroner", "nudlar"],
    "spaghetti": ["pasta", "spaghetti"],
    "makaroner": ["pasta", "makaroner"],
    "nudlar": ["pasta", "nudlar", "asien"],
}


def departments_for_category(category):
    """Which department(s) a category path belongs to.

    Returns an empty set for a product with no category - which is NOT a
    rejection, it just means category data cannot help here (ICA exposes no
    usable tree, and rows collected by term search predate category
    browsing). Those fall back to name matching alone."""
    if not category:
        return set()
    folded = _fold(category)
    return {department for department, keywords in DEPARTMENT_KEYWORDS.items()
            if any(_keyword_in_path(keyword, folded) for keyword in keywords)}


def allowed_departments_for(ingredient: str) -> set:
    """Which departments this ingredient may come from.

    A shopping line can name more than one thing ("Lök & vitlök" is one line
    covering two vegetables). When the whole line has no entry of its own,
    the union of its known words is used - which is how that line stopped
    matching "Vitlök Marinad" in the Skafferi aisle. If none of the words are
    known the ingredient stays unconstrained, so this can only ever tighten."""
    folded = _fold(ingredient)
    exact = _FOLDED_INGREDIENT_DEPARTMENTS.get(folded)
    if exact:
        return set(exact)
    departments = set()
    for word in _words(ingredient):
        known = _FOLDED_INGREDIENT_DEPARTMENTS.get(word)
        if known:
            departments |= set(known)
    return departments


def category_allows_ingredient(category, ingredient) -> bool:
    """Whether a product in this category can be this ingredient at all.

    Four outcomes, in order:
      1. No category on the product -> True (undecidable, defer to the name).
      2. The category is a department no ingredient comes from (pet food,
         baby food, sweets, non-food) -> False, for every ingredient.
      3. The ingredient names a specific aisle (staples like rice and pasta,
         where the department is too coarse) -> the category path must name
         it too.
      4. The ingredient has an allowed-department list -> the product's
         departments must intersect it.
    An ingredient with neither is unconstrained beyond rule 2."""
    departments = departments_for_category(category)
    if not departments:
        return True
    if departments & NEVER_INGREDIENT_DEPARTMENTS:
        return False

    required_aisle = _FOLDED_CATEGORY_KEYWORDS.get(_fold(ingredient))
    if required_aisle:
        folded_path = _fold(category)
        if not any(_keyword_in_path(_fold(keyword), folded_path) for keyword in required_aisle):
            return False

    allowed = allowed_departments_for(ingredient)
    if not allowed:
        return True
    return bool(departments & allowed)


# Ingredients whose name legitimately appears inside products that are NOT
# that ingredient. Verified against real Swedish grocery data - the classic
# failure is matching a cut of meat against a sausage or a ready meal.
#   require: at least one of these words must also be present
#   exclude: any of these words disqualifies the product outright
INGREDIENT_RULES = {
    "kycklingfilé": {"exclude": ["korv", "bacon", "pastej", "sås", "buljong", "krydda", "nugget", "pannbiff", "färs"]},
    "kycklinglårfilé": {"exclude": ["korv", "bacon", "pastej", "sås", "buljong", "krydda", "nugget", "färs"]},
    "köttfärs": {"exclude": ["sås", "färdig", "buljong", "krydda", "pastej", "biff"]},
    "fläskfilé": {"exclude": ["korv", "pastej", "sås", "krydda", "bacon"]},
    "laxfilé": {"exclude": ["pastej", "sås", "krydda", "soppa", "rom", "gravad", "rökt"]},
    "citron": {"exclude": ["saft", "juice", "dryck", "kräm", "godis", "läsk", "peppar", "gräs", "melis", "syra", "levain", "bröd", "kaka", "paj", "sorbet", "yoghurt"]},
    "paprika": {"exclude": ["pulver", "krydda", "chips", "sås", "flingor", "pasta"]},
    "ris": {"require": ["ris"], "exclude": ["risotto", "grynsallad", "chips", "kaka", "risgryn", "gröt", "risifrutti", "hund", "katt", "active", "foder"]},
    "majs": {"exclude": ["stärkelse", "mjöl", "olja", "chips", "flingor", "sirap"]},
    "smör": {"exclude": ["gräs", "kaka", "deg", "kräm", "jordnöts", "smördeg", "popcorn", "micropop", "sås", "kniv", "form", "papper", "mess"]},
    "grädde": {"exclude": ["glass", "kaka", "bakelse", "tårta", "vaniljsås", "sås", "pulver"]},
    "ost": {"exclude": ["ostbågar", "ostkaka", "dessert", "chips", "snacks", "frasrost", "rostat", "knäcke", "skorpa", "vallmo", "bröd", "kex", "levain", "rost"]},
    # 3-letter ingredients collide in head position too - these are the
    # collisions seen in real Willys/Hemköp data, not hypothetical ones.
    "ägg": {"exclude": ["choklad", "godis", "påsk", "nudel", "kaka"]},
}

# Same rules keyed by their folded name, so lookups by an accent-stripped
# ingredient actually find them (see product_matches_ingredient).
_FOLDED_RULES = None  # built below, after _fold is defined

# Words that disqualify a product for ANY ingredient - a prepared meal or a
# flavouring is never the raw ingredient a recipe asks for.
UNIVERSAL_EXCLUDE = [
    "smaksatt med", "smak av", "chips", "godis", "glass", "läsk", "energidryck",
    # Baby food and pet food both lead with the ingredient word ("Ris & Kyckling
    # Curry Från 6 Månader", "Fullkornspasta Kyckling Från 1-3 År", "Mini Small
    # Kyckling Ris Active"), so they pass every name-shape rule - but they are
    # never the raw ingredient a dinner recipe is asking for. Found in a real
    # run against 800 live Willys products.
    "månader", "1-3 år", "från 1 år", "barnmat", "välling", "modersmjölk",
    "hundfoder", "kattfoder", " hund", " katt", "active tor",
]

# Units we can convert between when comparing "how much the recipe needs"
# against "how much is in a package". Anything outside this stays uncompared
# rather than being guessed at.
_MASS = {"g": 1.0, "gram": 1.0, "hg": 100.0, "kg": 1000.0}
_VOLUME = {"ml": 1.0, "cl": 10.0, "dl": 100.0, "l": 1000.0, "liter": 1000.0, "ltr": 1000.0}


def _fold(text: str) -> str:
    """Lowercase and strip accents, so 'Kycklingfilé' and 'kycklingfile'
    compare equal without any fuzzy distance measure."""
    if not text:
        return ""
    lowered = str(text).lower().strip()
    return "".join(c for c in unicodedata.normalize("NFD", lowered) if unicodedata.category(c) != "Mn")


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _fold(text)))


_FOLDED_RULES = {_fold(key): value for key, value in INGREDIENT_RULES.items()}
# Same folding reason as _FOLDED_RULES: nearly every key here contains
# a/a/o, so an unfolded lookup would find almost none of them.
_FOLDED_INGREDIENT_DEPARTMENTS = {_fold(key): value for key, value in INGREDIENT_DEPARTMENTS.items()}
_FOLDED_CATEGORY_KEYWORDS = {_fold(key): value for key, value in INGREDIENT_CATEGORY_KEYWORDS.items()}


def convert_amount(amount: float | None, from_unit: str | None, to_unit: str | None) -> float | None:
    """Converts between mass units, or between volume units. Returns None when
    the two units aren't comparable (e.g. 'st' vs 'g') rather than assuming a
    density - guessing there would silently produce a wrong package count."""
    if amount is None or not from_unit or not to_unit:
        return None
    source, target = _fold(from_unit), _fold(to_unit)
    if source == target:
        return float(amount)
    for table in (_MASS, _VOLUME):
        if source in table and target in table:
            return float(amount) * table[source] / table[target]
    return None


def packages_needed(required_amount: float, required_unit: str | None,
                    package_amount: float | None, package_unit: str | None) -> int | None:
    """How many whole packages a shopper must actually buy.

    Needing 600 g when the package is 700 g costs one 700 g package - not
    600/700 of one. Needing 1200 g costs two. Returns None when the units
    aren't comparable, so the caller can report the item honestly instead of
    inventing a count."""
    if required_amount is None or required_amount <= 0:
        return 0
    if not package_amount or package_amount <= 0:
        return None
    converted = convert_amount(required_amount, required_unit, package_unit)
    if converted is None:
        return None
    return max(1, math.ceil(converted / package_amount - 1e-9))


def _exclusion_hit(text: str, words: set[str], bad: str) -> bool:
    """Whether an exclusion term actually applies to this product name.

    A raw substring test is WRONG here, and cost real matches: "läsk" folds
    to "lask", which sits inside "flaskfile" (fläskfilé), so every pork
    product in the catalogue was universally excluded as a soft drink. The
    same shape of bug had already been found twice in this codebase (accent
    folding, and "djur" inside "skaldjur").

    An exclusion must therefore sit at a WORD BOUNDARY: the whole word, the
    compound head (suffix), or the compound's first element (prefix). Both
    ends are needed and neither is optional:
        "kycklingkorv" ends with "korv"      -> a sausage, excluded
        "vaniljsås"    ends with "sås"       -> a sauce, excluded
        "messmör"      starts with "mess"    -> whey spread, excluded
        "chokladägg"   starts with "choklad" -> confectionery, excluded
        "fläskfilé"    has "läsk" in the MIDDLE only -> NOT a soft drink
    Multi-word terms ("smaksatt med", " hund") are matched as plain
    substrings, since they already carry their own boundaries."""
    folded_bad = _fold(bad)
    if not folded_bad:
        return False
    if " " in folded_bad or "-" in folded_bad:
        return folded_bad in text
    return any(word == folded_bad or word.startswith(folded_bad) or word.endswith(folded_bad)
               for word in words)


def product_matches_ingredient(product_name: str, ingredient: str, brand: str | None = None,
                               category: str | None = None) -> bool:
    """Conservative check - see this module's docstring for why. Requires the
    ingredient's head word as a WHOLE word in the product name, then applies
    that ingredient's require/exclude rules.

    category is optional and defaults to None so every existing caller keeps
    working: a product without one is judged on its name exactly as before.
    When a category IS present it is checked FIRST, because it is the one
    piece of evidence the chain asserts rather than something we infer."""
    if not category_allows_ingredient(category, ingredient):
        return False

    haystack = f"{product_name or ''} {brand or ''}"
    product_words = _words(haystack)
    folded_product = _fold(haystack)
    folded_ingredient = _fold(ingredient)

    # Needles must be folded to match the folded haystack. Comparing raw
    # "sås"/"gräs"/"färs"/"månader" against accent-stripped product text meant
    # every rule containing å/ä/ö silently never fired - found when baby-food
    # exclusions had no effect on a real Willys run.
    if any(_exclusion_hit(folded_product, product_words, bad) for bad in UNIVERSAL_EXCLUDE):
        return False

    # The ingredient's own words must appear - all of them for a multi-word
    # ingredient ("fryst torsk").
    #
    # Matching is by whole word OR by compound HEAD: in Swedish the head of a
    # compound is its last element, so "jasminris" and "basmatiris" really
    # are ris, while "risotto"/"risifrutti" (where ris is a prefix) are not.
    # Allowing a plain substring would wrongly match those; requiring a bare
    # whole word would wrongly reject jasminris. Suffix matching is what
    # actually mirrors the grammar.
    ingredient_words = {w for w in _words(ingredient) if len(w) > 2}
    if not ingredient_words:
        return False

    def word_hit(candidate: str, word: str) -> bool:
        """Compound matching is only safe for reasonably long ingredient
        words. A 3-letter word is a substring of far too many unrelated
        products: allowing suffixes let "ost" match "frasrost" (crispbread)
        and "ägg" match "chokladägg" - both confidently wrong. Short words
        therefore require an exact whole-word hit, longer ones may sit at
        either end of a compound ("jasminris", "smörstav")."""
        if candidate == word:
            return True
        # Swedish compound head is the LAST element, so "jasminris" is rice.
        # A prefix compound ("smörstav") is also usually the ingredient, but
        # only for longer words - allowing 3-letter prefixes matched far too
        # much. Known head-position collisions that survive this (frasrost
        # for "ost", chokladägg for "ägg") are handled by INGREDIENT_RULES.
        # ONLY suffix (head) matching. A prefix compound names something the
        # ingredient goes ON or WITH, not the ingredient: "smörgåsrån" is
        # crispbread, "smörpapper" is baking paper. Allowing prefixes matched
        # both. The cost is losing genuine prefix cases like "smörstav" -
        # accepted deliberately, since a wrong price is worse than a missing
        # one.
        return candidate.endswith(word)

    for word in ingredient_words:
        if not any(word_hit(candidate, word) for candidate in product_words):
            return False

    # HEAD-POSITION RULE - the single biggest precision win, added after a
    # real run against 800 live Willys products produced confidently wrong
    # matches: "Ris" -> "Mini Small Kyckling Ris Active Tor" (dog food),
    # "Smör" -> "Micropop Smör Popcorn 3-pack", "Grädde" -> "Kyld Vaniljsås
    # Grädde & Mjölk". Every one of those contains the ingredient as a real
    # whole word, so word matching alone cannot reject them.
    #
    # Swedish grocery names lead with what the product IS ("Kokosmjölk 7%",
    # "Kycklingfilé Naturell") and put qualifiers after. When the ingredient
    # word is NOT first, the name is usually describing something else that
    # merely contains or is flavoured by it. So: accept it as the leading
    # word, or accept a very short name where there is no room for the real
    # head to be something else - and reject the long descriptive names that
    # produced the failures above.
    name_words = [w for w in re.findall(r"[^\W\d_]+", _fold(product_name or "")) if len(w) > 1]
    if name_words:
        leads = any(word_hit(name_words[0], w) for w in ingredient_words)
        # No short-name exemption: a two-word name like "Kycklingcurry Ris"
        # (a ready meal) or "Chokladägg Lol" is exactly the case that slipped
        # through when short names were trusted. If the ingredient isn't what
        # the product leads with, we don't claim to know what it is.
        if not leads:
            return False

    # Look up by FOLDED key. The rule dict is written with natural Swedish
    # spelling ("ägg", "smör", "köttfärs") while folded_ingredient has its
    # accents stripped ("agg", "smor", "kottfars"), so a raw .get() silently
    # missed every rule containing å/ä/ö - which is why chokladägg and
    # smörkniv were still being matched despite having exclusions.
    rules = _FOLDED_RULES.get(folded_ingredient, {})
    if any(_exclusion_hit(folded_product, product_words, bad) for bad in rules.get("exclude", [])):
        return False
    required = rules.get("require")
    # Same compound-head rule as above, so "jasminris" satisfies require:["ris"].
    if required and not any(
        candidate == _fold(word) or candidate.endswith(_fold(word))
        for word in required for candidate in product_words
    ):
        return False
    return True


def effective_price(price) -> float | None:
    """What a normal shopper actually pays today: the campaign price when one
    is running, otherwise the ordinary price. Member and multibuy prices are
    deliberately NOT used - a member price isn't available to everyone, and a
    multibuy price only applies if you buy the qualifying quantity, so
    counting either as the plain price would understate the real checkout
    total."""
    if price is None:
        return None
    campaign = getattr(price, "campaign_price", None)
    regular = getattr(price, "regular_price", None)
    if campaign is not None and regular is not None:
        return min(campaign, regular)
    return campaign if campaign is not None else regular


class RecipePricingEngine:
    """Prices a shopping list against the real products in grocery.db."""

    def __init__(self, store):
        self.store = store

    def _candidates(self, ingredient: str, chain: str) -> list:
        """Products of one chain whose name plausibly is this ingredient.

        The SQL step is only a cheap prefilter; product_matches_ingredient()
        below is the authority. Two LIKE patterns are used because
        grocery_products.normalized_key keeps Swedish accents
        ("kycklingfilé") while the matcher folds them away
        ("kycklingfile") - searching with only the folded form silently
        matched nothing at all, and only the unfolded form would miss an
        ingredient typed without its accents."""
        raw_head = sorted((w for w in re.findall(r"[^\W\d_]+", str(ingredient).lower()) if len(w) > 2),
                          key=len, reverse=True)
        folded_head = sorted((w for w in _words(ingredient) if len(w) > 2), key=len, reverse=True)
        if not raw_head and not folded_head:
            return []
        patterns = {f"%{w}%" for w in (raw_head[:1] + folded_head[:1])}
        rows = []
        for pattern in patterns:
            rows.extend(self.store.connection.execute(
                """
                SELECT p.* FROM grocery_products p
                JOIN grocery_product_external_ids e ON e.product_id = p.id
                WHERE e.chain = ? AND p.normalized_key LIKE ?
                """,
                (chain, pattern),
            ).fetchall())
        seen, products = set(), []
        for row in rows:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            products.append(self.store._row_to_product(row))
        return [p for p in products if product_matches_ingredient(p.name, ingredient, p.brand, p.category)]

    def price_item(self, ingredient: str, amount: float, unit: str, chain: str, store_id: int) -> dict:
        """Picks the cheapest real checkout option for one ingredient at one
        chain: for each candidate product, work out how many packages are
        needed and what that costs, then take the lowest total. Buying one
        big package can beat three small ones, so the comparison has to be on
        total cost, not unit price."""
        best = None
        for product in self._candidates(ingredient, chain):
            price = self.store.get_current_price(product.id, store_id)
            unit_cost = effective_price(price)
            if unit_cost is None:
                continue
            count = packages_needed(amount, unit, product.quantity, product.unit)
            if count is None:
                # Units not comparable (e.g. recipe in "st", package in "g").
                # Fall back to one package - honest, and flagged below.
                count, exact = 1, False
            else:
                exact = True
            total = count * unit_cost
            if best is None or total < best["totalCost"]:
                best = {
                    "productId": product.id,
                    "productName": product.name,
                    "brand": product.brand,
                    # Carried through so a caller can see WHY this product was
                    # accepted for this ingredient - the aisle is the evidence.
                    "category": product.category,
                    "imageUrl": product.image_url,
                    "packageSize": product.size,
                    "packageAmount": product.quantity,
                    "packageUnit": product.unit,
                    "packages": count,
                    "unitPrice": unit_cost,
                    "totalCost": round(total, 2),
                    "regularPrice": getattr(price, "regular_price", None),
                    "campaignPrice": getattr(price, "campaign_price", None),
                    "memberPrice": getattr(price, "member_price", None),
                    "comparisonPrice": getattr(price, "unit_price", None),
                    "fetchedAt": getattr(price, "fetched_at", None),
                    "exactPackaging": exact,
                }
        return best

    def price_list(self, items: list[dict], chain: str, store_id: int, pantry: dict | None = None) -> dict:
        """Prices a whole (already week-aggregated) shopping list.

        items: [{"name": "Kycklingfilé", "amount": 600, "unit": "g"}, ...]

        The returned coverage is the honest part: a total covering 12 of 20
        items is NOT comparable with one covering 20 of 20, and the caller
        must be able to see that rather than comparing the bare numbers."""
        pantry = pantry or {}
        matched, missing = [], []
        total = 0.0

        for item in items:
            name = item.get("name") or item.get("namn") or ""
            amount = float(item.get("amount") or item.get("total") or 0)
            unit = item.get("unit") or "st"

            at_home = float(pantry.get(name) or 0)
            needed = max(0.0, amount - at_home)
            if needed <= 0:
                continue  # already in the pantry - costs nothing, isn't missing

            best = self.price_item(name, needed, unit, chain, store_id)
            if best is None:
                missing.append({"name": name, "amount": needed, "unit": unit})
                continue
            matched.append({"name": name, "neededAmount": needed, "neededUnit": unit, **best})
            total += best["totalCost"]

        requested = len(matched) + len(missing)
        return {
            "chain": chain,
            "storeId": store_id,
            "totalCheckoutCost": round(total, 2),
            "matchedItems": matched,
            "missingItems": missing,
            "realPriceItems": len(matched),
            "totalItems": requested,
            "coveragePercent": round(100 * len(matched) / requested) if requested else 0,
        }
