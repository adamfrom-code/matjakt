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
from functools import lru_cache

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
             "kott & fagel", "kott & kyckling", "kott, burgare", "chark",
             "manuell delikatess"],
    "fish": ["fisk & skaldjur", "fisk och skaldjur"],
    "dairy": ["mejeri", "ost & agg", "delikatessen > ost"],
    "produce": ["frukt & gront", "frukt och gront", "potatis & rotsaker",
                "kal & rotsaker"],
    "pantry": ["skafferi", "skafferiet"],
    # City Gross words several of these differently from the Axfood chains,
    # and a wording we do not know maps to NO department - which means the
    # category layer silently steps aside and the name rules decide alone.
    # That is how "Smör Havssalt Majskakor" (rice cakes, in "Bröd & bageri >
    # Kex & tilltugg") got priced as butter: the aisle knew, we just did not
    # speak its dialect. Taken from the real vocabulary of all three chains.
    "bread": ["brod & kakor", "brod och kakor", "brod & bageri", "brod", "bageri",
              "kex & tilltugg"],
    "frozen": ["fryst"],
    "readymeal": ["fardigmat"],
    "vegetarian": ["vegetariskt"],
    "deli": ["delikatessen"],
    # Cold cuts. Their department is "meat", but sliced ham and roast beef
    # are things you put on bread, not things you fry. "Rostbiff Deliskivor"
    # was being priced as a steak.
    "coldcuts": ["palagg", "skivat palagg", "delikatesschark", "charkuterier"],
    "drinks": ["dryck"],
    # Departments a raw recipe ingredient NEVER comes from. This is the
    # single broadest precision win: it rejects the whole class of failures
    # that name rules had to fight one at a time - dog food ("Mini Small
    # Kyckling Ris Active"), sweets ("Chokladagg"), snacks ("Micropop Smor
    # Popcorn").
    # Matched on WORD BOUNDARIES, not as raw substrings - "djur" as a plain
    # substring also matches "skaldjur", which classified every shrimp and
    # shellfish aisle as pet food and took "Räkor" from 13 candidates to 0.
    "pet": ["djur", "hund", "katt", "smadjur", "djurmat", "djurtillbehor", "husdjur"],
    "baby": ["barn", "blojor", "valling & ersattning", "barnmat", "barnsnacks",
             "barnvard"],
    "nonfood": ["hem & stad", "hem & hushall", "halsa & skonhet", "apotek",
                "tobak", "kiosk", "blommor", "gor det sjalv", "media", "klader",
                "koket", "hem & fritid", "skonhet & hygien", "hushall", "halsa"],
    "confectionery": ["godis", "snacks", "chips", "choklad", "tuggummi",
                      "popcorn", "glass"],
}

# Departments that never contain a cooking ingredient, whatever the recipe
# asks for. Applied to every ingredient, so no per-ingredient rule is needed.
NEVER_INGREDIENT_DEPARTMENTS = {"pet", "baby", "nonfood", "confectionery"}

# The one legitimate exception to the snacks veto: nuts, seeds and dried
# fruit really do live in the snacks aisle at every chain. For exactly these
# ingredients "confectionery" is a real pantry shelf - a recipe topping a
# soup with peanuts priced as MISSING because the only peanuts in the store
# sat next to the crisps. Pet/baby/nonfood stay vetoed even for these.
SNACK_AISLE_INGREDIENTS = {
    "jordnotter", "cashewnotter", "mandel", "hasselnotter", "valnotter",
    "pistagenotter", "notter", "solrosfron", "pumpafron", "sesamfron",
    "russin", "jordnotssmor",
    # Tortilla chips for a taco bake are bought exactly where the crisps
    # live; that is not a matching error, it is where the shelf is.
    "tortillachips",
    # Själva tortillabröden står på samma texmex-hylla ("Bröd, chips &
    # skal") - chips-ordet i hyllnamnet är inte ett matchningsfel.
    "tortillabrod", "tortilla", "tortillas", "wraps",
}

# Which departments an ingredient may legitimately come from. An ingredient
# NOT listed here gets no category constraint beyond the universal one - the
# name rules alone decide, exactly as before. That keeps this additive: it
# can reject a wrong match, never invent a right one.
#
# Frozen is allowed wherever a frozen form is a real product a shopper would
# buy (frozen fish, frozen berries), and left out where it would let a ready
# meal in.
INGREDIENT_DEPARTMENTS = {
    # --- produce that shares its name with drinks and sweets. "Apelsin"
    # matched orange-flavoured sparkling water; fruit comes from the fruit
    # aisle, full stop.
    # Bread, not the Spanish potato omelette in the ready-meal aisle that
    # shares the word.
    "tortillabröd": {"bread", "pantry"},
    "apelsin": {"produce"},
    "päron": {"produce"},
    "mango": {"produce", "frozen"},
    "ananas": {"produce"},
    "hallon": {"produce", "frozen"},
    "blåbär": {"produce", "frozen"},
    "jordgubbar": {"produce", "frozen"},
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
    # Tofu står hos flera kedjor i asiatiska skafferihyllan eller mejerikylen.
    "tofu": {"vegetarian", "pantry", "dairy"},
    # Rostad lök är en skafferiburk, inte färsk lök - suffixet gissar annars
    # grönsakshyllan och kryddhyllans burk avvisas.
    "rostad lök": {"pantry", "produce"},
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


# Words meaning "this meat has been minced, formed, breaded or cured". A
# recipe asking for a steak must not be priced against a patty: "Pannbiff"
# ends with "biff", so Swedish compound-head matching accepts it, and the
# result is a confidently wrong price for a different product entirely.
#
# Found by pricing the real recipe bank against real Willys data - 7 of 22
# matches for "Biff" were wrong, in exactly these two classes.
PROCESSED_MEAT_FORMS = [
    "pannbiff", "farsbiff", "burgare", "bulle", "nugget", "panerad",
    "schnitzel", "sylta", "pastej", "kebab", "fars", "formad", "krossad",
    # Found in the cross-store audit: a whole cut must not become the FAT
    # CAP of one, strips of one, or a different cut entirely. "Biff"
    # simultaneously priced as "Biff med Kappa" (Willys), "Rostbiff i Bit"
    # (Hemköp) and "Grillbiff av Skinka" - PORK - (City Gross): three shops,
    # three different raw materials, one "comparison".
    "kappa", "strimlad", "strimlor", "grillbiff", "rulle",
]

# Ingredients that mean a WHOLE piece of meat or fish. These are the ones a
# processed form can impersonate; a recipe asking for "köttfärs" obviously
# may match minced meat, so it is deliberately not in here.
WHOLE_CUT_INGREDIENTS = {
    "biff", "ryggbiff", "lovbiff", "entrecote", "oxfile", "hogrev",
    "fransyska", "rostbiff", "flaskfile", "flaskkarre", "kotlett", "karre",
    "kycklingfile", "kycklinglarfile", "kycklingbrost", "laxfile", "lax",
    "torskfile", "torsk", "fiskfile", "skinkstek", "lammstek", "kalvfile",
}

# Departments a RAW cut must not come from, on top of the universal ones.
# Cold cuts and ready meals both contain the word, neither is the raw
# ingredient a recipe asks you to cook.
WHOLE_CUT_FORBIDDEN_DEPARTMENTS = {"coldcuts", "readymeal"}


# What a recipe calls something and what the shelf calls it are often two
# different Swedish words for the same thing. A recipe says "Köttfärs"; the
# shelf says "Blandfärs" and "Nötfärs". Neither is wrong, and no amount of
# clever string matching bridges them - it is vocabulary, so it belongs in
# data.
#
# Every alias is matched with the FULL rule set (head position, department,
# processed-form and exclusion rules), so this can only find products the
# matcher would already have accepted under a different name. It widens
# coverage without loosening precision.
#
# Derived from the real misses: six ingredients accounted for all 29 unmatched
# items across the whole recipe bank.
INGREDIENT_ALIASES = {
    "köttfärs": ["blandfärs", "nötfärs"],
    "blandfärs": ["köttfärs", "nötfärs"],
    "soja": ["sojasås"],
    "fryst torsk": ["torskfilé", "torsk"],
    "torsk": ["torskfilé"],
    "lax": ["laxfilé"],
    # "kycklinglår" (ben-i) borttagen: lårfilé är benfri, låret är det inte.
    "kycklinglårfilé": ["kyckling lårfilé", "lårfilé"],
    "kycklingfilé": ["kyckling bröstfilé"],
    "wokgrönsaker": ["wokmix", "wokblandning", "grönsaksblandning"],
    "räkor": ["handskalade räkor"],
    "crème fraiche": ["creme fraiche"],
    "riven ost": ["gratängost", "riven hushållsost"],
    # vispgrädde->grädde borttagen: den släppte in matgrädde 13% som "grädde".
    "matlagningsgrädde": ["matgrädde", "grädde"],
    "tomatpuré": ["tomatpure"],
    "krossade tomater": ["tomater krossade", "krossad tomat"],
    "kikärtor": ["kikärter"],
    "röda linser": ["linser"],
    "svarta bönor": ["bönor svarta"],
    # Generic pantry words almost never appear in product NAMES - ordinary
    # pasta is sold as "Spaghetti" or "Penne", never as "Pasta". Without
    # these, "Pasta" matched exactly one product at Willys: organic chickpea
    # pasta at 118 kr/kg, and a week's realistic 15 kr bag priced as 75 kr.
    # The aliases point at the everyday forms so the cheapest REAL option
    # competes. Each alias still passes the same category guards.
    "pasta": ["spaghetti", "makaroner", "penne", "fusilli", "tagliatelle", "farfalle"],
    "ris": ["jasminris", "basmatiris", "långkornigt ris", "grötris"],
    "matvete": ["vete kärnor", "vetekärnor"],
    "potatis": ["potatis fast", "potatis mjölig"],
    "tomater": ["tomat", "kvisttomater"],
    "körsbärstomater": ["cocktailtomater", "körsbärstomat"],
    "sallad": ["isbergssallad", "romansallad"],
    "lök": ["gul lök"],
    "morötter": ["morot"],
    "vitlök": ["vitlok"],
    "champinjoner": ["champinjon"],
    "paprika": ["paprika röd", "röd paprika"],
    "grädde": ["vispgrädde", "matlagningsgrädde"],
    "yoghurt": ["naturell yoghurt", "yoghurt naturell"],
    "fetaost": ["feta"],
    "mozzarella": ["mozzarella färsk"],
    "bacon": ["bacon skivat"],
    "fläskkarré": ["karré"],
    "högrev": ["högrev benfri"],
    "buljong": ["buljongtärning"],
    "buljongtärning": ["buljong", "fond"],
    # Thai curry pastes are mostly labelled in English on Swedish shelves.
    "röd currypasta": ["currypasta", "red curry paste"],
    "grön currypasta": ["currypasta", "green curry paste"],
    "currypasta": ["red curry paste"],
    "gula ärtor": ["gula ärter", "ärter"],
    # Varumärkesformer: "Coca-Cola" leder med Coca, inte Cola.
    "cola": ["coca-cola", "pepsi"],
    # Samma vara under sitt italienska namn respektive sin vanligaste form -
    # identiteten ändras inte, bara ordet.
    "parmesan": ["parmigiano"],
    # Butikerna säljer varan som "Kebab Grillad"/"Klassisk Kebab" - ordet
    # kebabkött förekommer knappt i produktnamn.
    "kebabkött": ["kebab"],
    # Butikerna kallar kryddan "Taco Spice Mix"; tortillabröd-aliasen
    # fanns redan längre ned.
    "tacokrydda": ["taco spice mix", "taco spice"],
    "buljong": ["buljongtärning", "fond"],
    # Shelf singular/word-order forms found by probing the live catalogue.
    "rödlök": ["lök röd"],
    "kycklingklubbor": ["kycklingklubba", "kyckling klubba"],
    "sardellfilé": ["sardeller"],
    "tortillabröd": ["tortilla", "tortillas", "wraps"],
    "grönsaksbuljong": ["grönsaksbuljongtärning", "buljong grönsak"],
    "kycklingbuljong": ["kycklingbuljongtärning", "buljong kyckling"],
    "sidfläsk": ["rimmat sidfläsk"],
    "rimmat sidfläsk": ["sidfläsk rimmat", "sidfläsk"],
    "nötfärs": ["köttfärs"],
    "fläskfärs": ["färs fläsk"],
    "gröna ärtor": ["ärtor gröna", "frysta ärtor", "ärter"],
    "frysta ärtor": ["gröna ärtor", "ärter"],
    "majs": ["majskorn", "sockermajs"],
}

_FOLDED_ALIASES = None  # built after _fold, below


def aliases_for(ingredient: str) -> list:
    """Alternative shelf names for an ingredient, primary name first."""
    return _FOLDED_ALIASES.get(_fold(ingredient), [])


def is_whole_cut(ingredient: str) -> bool:
    folded = _fold(ingredient)
    if folded in WHOLE_CUT_INGREDIENTS:
        return True
    # "Biff" inside "Biff Strimlad" and similar multi-word shopping lines.
    return any(word in WHOLE_CUT_INGREDIENTS for word in _words(ingredient))


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
    vetoed = NEVER_INGREDIENT_DEPARTMENTS
    if _fold(ingredient) in SNACK_AISLE_INGREDIENTS:
        vetoed = vetoed - {"confectionery"}
    if departments & vetoed:
        return False
    # Sliced ham belongs on bread; a recipe frying a steak must not be
    # priced against the cold-cuts aisle.
    if is_whole_cut(ingredient) and (departments & WHOLE_CUT_FORBIDDEN_DEPARTMENTS):
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
    "köttfärs": {"exclude": ["sås", "färdig", "buljong", "krydda", "pastej", "biff"]},
    "fläskfilé": {"exclude": ["korv", "pastej", "sås", "krydda", "bacon"]},
    "laxfilé": {"exclude": ["pastej", "sås", "krydda", "soppa", "rom", "gravad", "rökt"]},
    "citron": {"exclude": ["saft", "juice", "dryck", "kräm", "godis", "läsk", "peppar", "gräs", "melis", "syra", "levain", "bröd", "kaka", "paj", "sorbet", "yoghurt"]},
    "paprika": {"exclude": ["pulver", "krydda", "chips", "sås", "flingor", "pasta"]},
    "ris": {"require": ["ris"], "exclude": ["risotto", "grynsallad", "chips", "kaka", "risgryn", "gröt", "risifrutti", "hund", "katt", "active", "foder"]},
    "majs": {"exclude": ["stärkelse", "mjöl", "olja", "chips", "flingor", "sirap"]},
    "smör": {"exclude": ["gräs", "kaka", "deg", "kräm", "jordnöts", "smördeg", "popcorn", "micropop", "sås", "kniv", "form", "papper", "mess"]},
    "grädde": {"exclude": ["glass", "kaka", "bakelse", "tårta", "vaniljsås", "sås", "pulver", "havre", "soja", "kokos", "ärt", "vegansk"]},
    # 3-letter ingredients collide in head position too - these are the
    # collisions seen in real Willys/Hemköp data, not hypothetical ones.
    "ägg": {"exclude": ["choklad", "godis", "påsk", "nudel", "kaka"]},
    # ---- CANONICAL CONSTRAINTS (cross-store fairness) -----------------------
    # The same requirement is priced at every chain; these rules make sure a
    # chain can only answer with the SAME raw material. Brand and pack may
    # differ - the food may not. Each entry is a violation actually observed
    # in the cross-store audit 2026-09-01, not a hypothetical.
    #
    # Vispgrädde must whip: 13% matgrädde cannot. Both directions locked.
    "vispgrädde": {"exclude": ["matlagnings", "matgrädde", "kaffe", "havre", "soja", "mellan"]},
    "matlagningsgrädde": {"exclude": ["visp", "kaffe", "havre", "soja", "kokos", "ärt", "vegansk"]},
    # Lårfilé is boneless; "Kycklinglår" and "klubba" are not the same cut.
    # (Also enforced via the alias list: the bone-in aliases are gone.)
    "kycklinglårfilé": {"require": ["lårfilé"],
                        "exclude": ["korv", "bacon", "pastej", "sås", "buljong", "krydda", "nugget", "färs", "klubba", "klubbor", "vinge"]},
    # A generic cooking yoghurt is naturell. Flavoured cups are a different
    # product: "Grekisk Yoghurt CITRON" priced as grekisk yoghurt at two of
    # three chains while the third got plain - incomparable.
    "yoghurt": {"exclude": ["vanilj", "citron", "jordgubb", "hallon", "blåbär", "päron", "honung", "mango", "smultron", "dryck", "drick", "müsli", "musli"]},
    "grekisk yoghurt": {"exclude": ["vanilj", "citron", "jordgubb", "hallon", "blåbär", "päron", "honung", "mango", "dryck", "drick", "müsli", "musli", "granola"]},
    # Fetaost is CHEESE. "Feta Tomat Lätt Crème Fraiche" is a cooking sauce
    # that happens to lead with the word - every chain picked it.
    "fetaost": {"exclude": ["fraiche", "röra", "dressing", "dipp", "sås", "paj", "creme"]},
    "feta": {"exclude": ["fraiche", "röra", "dressing", "dipp", "sås", "paj", "creme"]},
    # Generic pasta requirements mean ordinary wheat pasta. Corn/gluten-free/
    # legume pasta is a legitimate product and an illegitimate SUBSTITUTE -
    # if the recipe wants it, the recipe says so.
    "pasta": {"exclude": ["majs", "glutenfri", "kikärt", "lins", "bön", "proteinpasta"]},
    "spaghetti": {"exclude": ["majs", "glutenfri", "kikärt", "lins", "bön"]},
    "makaroner": {"exclude": ["majs", "glutenfri", "kikärt", "lins", "bön"]},
    # A recipe that wants light dairy says "lätt". Generic crème fraiche is
    # the standard product; one chain answering with Lätt 13% against
    # another's 32% compares two different foods.
    "crème fraiche": {"exclude": ["lätt", "light"]},
    # Lök är lök - purjolök är en annan grönsak som råkar sluta på ordet.
    # Hemköp prissatte "Lök" som Purjolök medan grannkedjan tog gul lök.
    "lök": {"exclude": ["purjo", "sallads", "gräslök", "ringar", "pulver", "friterad", "picklad"]},
    # "Honung Grillkrydda" är en kryddblandning, "Honung Glazer" en glaze -
    # inte honung. Två av tre kedjor svarade med fel vara.
    "honung": {"exclude": ["krydda", "glaze", "glazer", "senap", "marinad", "dressing", "sås", "yoghurt", "rostad"]},
    # "Dill Gräslök Majskakor" är riskakor. Örten är örten.
    "dill": {"exclude": ["majskakor", "kaka", "kakor", "chips", "sås", "dressing", "dipp", "sill", "lax"]},
    "gräslök": {"exclude": ["majskakor", "kaka", "kakor", "chips", "sås", "dressing", "färskost"]},
    "persilja": {"exclude": ["sås", "smör", "dressing"]},
    # Räkor i recept är färska/frysta skalräkor - inte konserv i lake.
    "räkor": {"exclude": ["lake", "konserv", "ost", "röra", "sallad", "smörgås"]},
    # Kaffe är kaffe - inte havredryck som slutar på ordet ("Ikaffe
    # Barista"), inte kaffebröd, inte kaffegrädde.
    "kaffe": {"exclude": ["ikaffe", "iskaffe", "dryck", "grädde", "bröd", "kaka", "filter", "likör", "glass", "iste"]},
    # "Cola" matchade Ruccola och "Läsk" matchade Fläsk Luncheon - svenska
    # suffixsammansättningar åt andra hållet. Extraprodukter går genom samma
    # matchare, så även dryckerna behöver kanoniska krav.
    "cola": {"exclude": ["ruccola", "rucola", "sallad", "choklad", "godis", "mix", "koncentrat", "sodastream", "sirap"]},
    "läsk": {"exclude": ["fläsk", "sidfläsk", "luncheon"]},
    # Generisk "Ost" är en bit ost - inte marinerade salladsostkuber.
    # Generisk "Ost" i ett recept är hård ost i bit eller riven - annars
    # vinner billigaste tub (Baconost, Räkost, Mjukost) varje gång.
    "ost": {"require": ["riven", "block", "bit", "hushållsost", "herrgård", "prästost", "grevé", "cheddar", "gouda", "gratängost"],
            "exclude": ["ostbågar", "ostkaka", "dessert", "chips", "snacks", "frasrost", "rostat", "knäcke", "skorpa", "vallmo", "bröd", "kex", "levain", "rost", "salladsost", "grillost", "stekost", "halloumi", "mjukost", "färskost", "smältost", "cream", "räkost", "tärnad", "kaviar", "feta", "mozzarella", "i olja", "gratinerad", "sås"]},
    # Biff = a beef steak cut. Not roast beef, not the fat-cap trim, not a
    # grill patty, and never another animal.
    "biff": {"exclude": ["rostbiff", "skinka", "fläsk", "kyckling", "kalkon", "vego", "vegansk", "sallad"]},
    # "Tortilla med/utan Lök" är spansk potatisomelett (färdigrätt) och
    # tortillachips är snacks - brödet är brödet.
    "tortillabröd": {"exclude": ["chips", "med lök", "utan lök", "dipp", "corn"]},
    # Bacon är fläsk. Kalkonbacon ligger i samma köttavdelning och vegobacon
    # bredvid - avdelningsspärren hjälper inte, bara namnregeln.
    "bacon": {"exclude": ["kalkon", "vego", "vegansk", "veggie", "tofu", "chips", "snacks", "smak", "krydda", "ost", "dressing"]},
    "halloumi": {"exclude": ["panerad", "sticks", "snacks", "burgare", "krydda"]},
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
_VOLUME = {"ml": 1.0, "cl": 10.0, "dl": 100.0, "l": 1000.0, "liter": 1000.0, "ltr": 1000.0,
           # Kökets vardagsmått. Utan dessa blev varje msk-rad ett gissat
           # "1 paket" som räknades som säkert pris i täckningen.
           "msk": 15.0, "tsk": 5.0, "krm": 1.0}


@lru_cache(maxsize=65536)
def _fold(text: str) -> str:
    """Lowercase and strip accents, so 'Kycklingfilé' and 'kycklingfile'
    compare equal without any fuzzy distance measure."""
    if not text:
        return ""
    lowered = str(text).lower().strip()
    return "".join(c for c in unicodedata.normalize("NFD", lowered) if unicodedata.category(c) != "Mn")


@lru_cache(maxsize=65536)
def _words(text: str) -> frozenset:
    """Cached because the same product name is folded once per ingredient -
    ~40 candidates x 22 ingredients x 4 chains means the same handful of
    strings are re-split thousands of times per week.

    A frozenset, not a set: an lru_cache hands the SAME object to every
    caller, and one of them mutating it would corrupt every later lookup."""
    return frozenset(re.findall(r"[a-z0-9]+", _fold(text)))


_FOLDED_RULES = {_fold(key): value for key, value in INGREDIENT_RULES.items()}
# Same folding reason as _FOLDED_RULES: nearly every key here contains
# a/a/o, so an unfolded lookup would find almost none of them.
_FOLDED_INGREDIENT_DEPARTMENTS = {_fold(key): value for key, value in INGREDIENT_DEPARTMENTS.items()}
_FOLDED_ALIASES = {_fold(key): value for key, value in INGREDIENT_ALIASES.items()}
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


# A suffix exclusion can collide with a compound whose OWN head contains the
# excluded word as its tail. "läsk" (soft drink) folds to "lask", and
# "sidfläsk"/"julfläsk"/every -fläsk compound folds to "...flask" - which
# ENDS with "lask", so pork bellies were universally excluded as soft
# drinks. The suffix rule itself is right (apelsinläsk IS läsk); these name
# the longer heads that override it. Keyed by the folded exclusion term.
# Same idea from the PREFIX end: "färsk" folds to "farsk", which STARTS with
# "fars" (mince) - so the mince-form exclusion rejected every product merely
# labelled fresh. A whole cut marked "Färsk" is the opposite of processed.
EXCLUSION_PREFIX_OVERRIDES = {
    "fars": ("farsk",),
}

EXCLUSION_SUFFIX_OVERRIDES = {
    "lask": ("flask",),
    # "Tortillachips" is a real recipe ingredient (tacogratäng) whose own
    # head IS the excluded word. The head-lead rule still keeps chips
    # products away from every other ingredient.
    "chips": ("tortillachips",),
}


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
    suffix_overrides = EXCLUSION_SUFFIX_OVERRIDES.get(folded_bad, ())
    prefix_overrides = EXCLUSION_PREFIX_OVERRIDES.get(folded_bad, ())
    return any(
        word == folded_bad
        or (word.startswith(folded_bad)
            and not any(word.startswith(longer) for longer in prefix_overrides))
        or (word.endswith(folded_bad)
            and not any(word.endswith(longer) for longer in suffix_overrides))
        for word in words)


def _violates_own_rules(product, ingredient: str) -> bool:
    """Whether a product trips the INGREDIENT'S OWN exclude-rules - used to
    make alias matches inherit the canonical requirement's constraints."""
    haystack = f"{product.name or ''} {product.brand or ''}"
    words = _words(haystack)
    folded = _fold(haystack)
    rules = _FOLDED_RULES.get(_fold(ingredient), {})
    return any(_exclusion_hit(folded, words, bad) for bad in rules.get("exclude", []))


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
    # A whole cut of meat or fish is not a patty, a sausage or a slice of
    # cold cut, however similar the names look.
    if is_whole_cut(ingredient) and any(
            _exclusion_hit(folded_product, product_words, bad) for bad in PROCESSED_MEAT_FORMS):
        return False

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
    # Samma sanering som vid import - hängslen för rader som skrevs innan
    # importvakten fanns. 0 kr vinner annars varje jämförelse.
    def _sane(value):
        return value if value is not None and 0 < value <= 30000 else None
    campaign, regular = _sane(campaign), _sane(regular)
    if campaign is not None and regular is not None:
        return min(campaign, regular)
    return campaign if campaign is not None else regular


# Word indexes by data version. Bounded by the pruning in __init__ - an
# unbounded cache keyed on a changing version is a memory leak with extra
# steps.
_INDEX_CACHE: dict = {}
_PRICE_CACHE: dict = {}


class RecipePricingEngine:
    """Prices a shopping list against the real products in grocery.db."""

    def __init__(self, store):
        self.store = store
        # The word index is shared across ENGINES, not just across the
        # ingredients of one week: a new engine is built for every request,
        # and rebuilding an 18 000-product index each time was most of what
        # was left of the cold cost after the per-ingredient scans went away.
        #
        # Keyed on the data version, so it cannot outlive the data it
        # describes: the moment an import writes a price, the version changes
        # and the next lookup builds a fresh index. No manual invalidation,
        # and no window where a user is priced against a stale index.
        try:
            # The database's own identity is part of the key: the caches are
            # process-global, the databases are not, and two fixtures with
            # the same row counts fingerprint identically.
            self._version = f"{getattr(store, 'db_path', id(store))}#{store.data_version()}"
        except Exception:
            # A store without the fingerprint (an old database, a test
            # double) simply does not share indexes - correctness first.
            self._version = None
        self._word_index = _INDEX_CACHE.setdefault(self._version, {}) if self._version else {}
        self._price_cache = _PRICE_CACHE.setdefault(self._version, {}) if self._version else {}
        if self._version and len(_INDEX_CACHE) > 3:
            # Only the newest few versions are worth keeping; the rest
            # describe data nobody can be reading any more.
            for stale in list(_INDEX_CACHE)[:-3]:
                if stale != self._version:
                    _INDEX_CACHE.pop(stale, None)
                    _PRICE_CACHE.pop(stale, None)

    def _index_for(self, chain: str) -> dict:
        """Maps each word in a chain's product names to the products with it.

        The engine used to run one SQL query PER INGREDIENT, each walking
        every product of the chain (a leading-wildcard LIKE cannot use an
        index) and then running the matcher over all of them in Python. For a
        22-item week across four chains that is 88 full passes over ~11 000
        products - measured at 1.6 seconds, nearly all of it repeated work.

        Reading the chain once and indexing by word turns each ingredient
        into a dict lookup over a few dozen candidates. The index folds words
        exactly as the matcher does (see _words), so the two can never
        disagree about what a word is.

        Suffixes are indexed too, because Swedish puts a compound's head
        last: "jasminris" has to be findable under "ris", which is precisely
        what product_matches_ingredient accepts."""
        cached = self._word_index.get(chain)
        if cached is not None:
            return cached

        index = {}
        rows = self.store.connection.execute(
            """
            SELECT p.* FROM grocery_products p
            JOIN grocery_product_external_ids e ON e.product_id = p.id
            WHERE e.chain = ?
            """,
            (chain,),
        ).fetchall()

        seen = set()
        for row in rows:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            product = self.store._row_to_product(row)
            for word in _words(f"{product.name or ''} {product.brand or ''}"):
                if len(word) <= 2:
                    continue
                index.setdefault(word, []).append(product)
                for cut in range(1, len(word) - 2):
                    index.setdefault(word[cut:], []).append(product)

        self._word_index[chain] = index
        return index

    def _prices_for(self, store_id: int) -> dict:
        """Every current price in one store, by product id.

        price_item() asked the database for one product's price at a time.
        With ~40 candidates per ingredient, 22 ingredients and four chains
        that is thousands of single-row queries per week - each cheap, all of
        them together not. One query per store answers all of them.

        Shared across engines on the same data version, like the word index,
        because prices only change when an import writes them."""
        cached = self._price_cache.get(store_id)
        if cached is not None:
            return cached
        prices = {}
        for row in self.store.connection.execute(
                "SELECT * FROM grocery_current_prices WHERE store_id = ?", (store_id,)):
            prices[row["product_id"]] = self.store._row_to_current_price(row)
        self._price_cache[store_id] = prices
        return prices

    def _candidates(self, ingredient: str, chain: str) -> list:
        """Products of one chain whose name plausibly is this ingredient.

        The word index is only a cheap prefilter; product_matches_ingredient()
        remains the authority on whether a product IS the ingredient. Both
        sides fold the same way (see _words), so an accented ingredient and an
        unaccented product name still meet - which the old two-LIKE approach
        needed a second query to achieve."""
        words = sorted((w for w in _words(ingredient) if len(w) > 2), key=len, reverse=True)
        if not words:
            return []
        # Longest word first: it is the most specific, so it yields the
        # smallest candidate set for the matcher to judge.
        index = self._index_for(chain)
        candidates, seen = [], set()
        for product in index.get(words[0], ()):
            if product.id in seen:
                continue
            seen.add(product.id)
            candidates.append(product)
        matched = [p for p in candidates
                   if product_matches_ingredient(p.name, ingredient, p.brand, p.category)]
        # The shelf's own names COMPETE with the recipe's word - they do not
        # merely stand in when it finds nothing. "Pasta" literally matched
        # exactly one product (organic chickpea pasta, 118 kr/kg), so the
        # cheapest "real" pasta became a specialty product while every
        # ordinary spaghetti sat unconsidered under its own name. An alias is
        # a curated statement that the two names mean the same thing, and
        # each alias candidate still passes the same matcher and category
        # guards under the alias's name.
        matched_ids = {p.id for p in matched}
        for alias in aliases_for(ingredient):
            alias_words = sorted((w for w in _words(alias) if len(w) > 2), key=len, reverse=True)
            if not alias_words:
                continue
            for product in index.get(alias_words[0], ()):
                if product.id in matched_ids:
                    continue
                if not product_matches_ingredient(product.name, alias, product.brand, product.category):
                    continue
                # THE ORIGINAL'S canonical exclusions apply to alias matches
                # too. "Cola" -> alias "pepsi" found "Pepsi Max SODA MIX"
                # (a concentrate): the alias's own rules knew nothing about
                # the requirement's forbidden forms. An alias may widen the
                # NAME, never the requirement.
                if _violates_own_rules(product, ingredient):
                    continue
                matched_ids.add(product.id)
                matched.append(product)
        return matched

    def price_item(self, ingredient: str, amount: float, unit: str, chain: str, store_id: int) -> dict:
        """Picks the cheapest real checkout option for one ingredient at one
        chain: for each candidate product, work out how many packages are
        needed and what that costs, then take the lowest total. Buying one
        big package can beat three small ones, so the comparison has to be on
        total cost, not unit price."""
        best = None
        prices = self._prices_for(store_id)
        for product in self._candidates(ingredient, chain):
            price = prices.get(product.id)
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

            # Skafferiet lagras i basenheter (ml/vikt-g/st) medan radens
            # mängd står i receptets enhet (dl, l, msk...). Avdraget görs i
            # radens enhet via riktig konvertering - 50 ml grädde hemma
            # nollade annars en hel literrad ("1 - 50 = köps inte"), och
            # skräpvärden (icke-tal) 500:ade hela prissättningen.
            # Veckat uppslag: {"ris": 500} ska träffa varan "Ris" - exakt
            # skiftlägeskänslig likhet lät skafferiet tyst sluta dra av.
            pantry_value = pantry.get(name)
            if pantry_value is None and pantry:
                folded_name = _fold(name)
                for pantry_key, value in pantry.items():
                    if _fold(str(pantry_key)) == folded_name:
                        pantry_value = value
                        break
            try:
                raw_at_home = float(pantry_value or 0)
            except (TypeError, ValueError):
                raw_at_home = 0.0
            at_home = 0.0
            if raw_at_home > 0:
                pantry_unit = "ml" if _fold(unit) in _VOLUME else ("g" if _fold(unit) in _MASS else "st")
                converted = convert_amount(raw_at_home, pantry_unit, unit)
                # Ojämförbara enheter (st hemma mot gram-rad): inget avdrag -
                # hellre att varan står kvar än att den försvinner på en
                # gissning.
                at_home = converted if converted is not None else 0.0
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
            # Ett paketantal som GISSADES till 1 (enheterna gick inte att
            # jämföra) är inte ett säkert pris: det räknas som estimat och
            # hålls utanför täckningen och Billigast-underlaget. Hellre en
            # kedja som ärligt inte kan jämföras än en som vinner på en
            # underskattad gissning.
            "realPriceItems": sum(1 for item in matched if item.get("exactPackaging", True)),
            "estimatedItems": sum(1 for item in matched if not item.get("exactPackaging", True)),
            "totalItems": requested,
            "coveragePercent": (round(100 * sum(1 for item in matched if item.get("exactPackaging", True)) / requested)
                                if requested else 0),
        }
