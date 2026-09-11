# -*- coding: utf-8 -*-
"""Betalväggen på servern: en grind per skyddad väg, och en lista som inte
går att glömma uppdatera.

Bakgrunden (J1): tretton av sjutton premiumfunktioner var låsta med CSS.
`accounts/features.py` beskrev en affärsmodell som bara frontenden
respekterade - `entitlements.isPremium = true` i devtools räckte för att låsa
upp familjevecka, budgetvecka, sju middagar och näringsfilter, och
`/api/v1/recipes/by-pantry` (hela "Laga med det jag har") hade ingen
entitlement-kontroll alls. Kommentaren som redan stod i koden - *a paywall
that only hides pixels is not a paywall* - gällde alltså två av vägarna.

Det som gör listan svår att glömma är att den inte finns. En grind SKAPAS på
den rad som utför kontrollen, och registrerar sig själv här när modulen
importeras. `unguarded_premium_features()` räknar därför upp exakt de
premiumfunktioner som saknar kontroll i den faktiska serverkoden - och
acceptanstestet (`backend/tests/test_serverside_paywall.py`) är rött så länge
den mängden inte är tom.

Registreringen i sig bevisar ingenting: vem som helst kan skapa ett objekt
utan att någonsin fråga det. Därför bär varje grind en `probe` - en riktig
begäran som testet skickar in i en körande server med ett gratiskonto. En
grind som är registrerad men inte anropad svarar 200, och testet faller.

Två sorters grindar, för att Matjakt säljer två sorters värde:

* DENY - vägen ger ingenting alls till Free (403 med `{"locked": true}`).
* MASK - vägen svarar, men premiumsiffrorna är borta ur svaret. Den formen
  finns för att Free ska få sin RIKTIGA total hos den billigaste
  kvalificerade butiken. Free/Premium ändrar vad som VISAS, aldrig vad som
  är SANT (se features.py).
"""

from ..accounts import features as plan_features

DENY = "deny"
MASK = "mask"

_GATES: list["Gate"] = []


class Gate:
    """En entitlement-kontroll på en väg, deklarerad där kontrollen sker.

    `probe` beskriver en begäran som MÅSTE nekas (DENY) eller maskas (MASK)
    för ett gratiskonto: {"method", "path", "query"|"body"}. Testet kör den
    mot en riktig server. Utan probe går grinden inte att bevisa, och därför
    är den obligatorisk.

    `setup` (J3) är begäranden som körs FÖRE proben, för de grindar som
    vaktar ett TILLSTÅND i stället för en enskild fråga. Hushållsgrinden är
    hela skälet: ett nytt konto har ett hushåll med en medlem, och att bjuda
    in den andra är gratis - det är den TREDJE som möter betalväggen. Utan
    setup går den grinden inte att pröva alls, och en grind som inte går att
    pröva är tillbaka till att vara en åsikt.

    Varje steg är {"method", "path", "body"|"query", "as", "capture"}:

    * `as` är "self" (samma konto som proben) eller "other" (ett andra
      gratiskonto, som behövs för att fylla ett hushåll).
    * `capture` namnger ett fält i svaret att komma ihåg. Ett senare steg
      som skriver "$namn" får värdet insatt - inbjudningstoken finns bara i
      det ena svaret som lämnade ut den.
    """

    __slots__ = ("feature", "route", "kind", "message", "probe", "setup")

    def __init__(self, feature: str, route: str, kind: str, message: str, probe: dict,
                 setup=()):
        if feature not in plan_features.FEATURES:
            raise ValueError(f"Okänd funktion i grinden: {feature}")
        if kind not in (DENY, MASK):
            raise ValueError(f"Okänd grindtyp: {kind}")
        if not isinstance(probe, dict) or not probe.get("path") or not probe.get("method"):
            raise ValueError(f"Grinden för {feature} saknar en prövbar probe")
        self.feature = feature
        self.route = route
        self.kind = kind
        self.message = message
        self.probe = probe
        self.setup = tuple(setup)
        _GATES.append(self)

    def blocks(self, plan: str) -> bool:
        """True när planen INTE får den här funktionen."""
        return not plan_features.allowed(plan, self.feature)

    def denial(self, **extra) -> dict:
        """Kroppen ett nekande svar bär. `locked` och `feature` är kontraktet
        frontenden läser för att veta VILKEN uppgradering som säljs."""
        return {"locked": True, "feature": self.feature, "error": self.message, **extra}

    def __repr__(self):
        return f"<Gate {self.feature} {self.kind} {self.route}>"


def deny(feature: str, route: str, message: str, probe: dict, setup=()) -> Gate:
    return Gate(feature, route, DENY, message, probe, setup)


def mask(feature: str, route: str, message: str, probe: dict, setup=()) -> Gate:
    return Gate(feature, route, MASK, message, probe, setup)


def all_gates() -> list[Gate]:
    return list(_GATES)


def gates_for(feature: str) -> list[Gate]:
    return [gate for gate in _GATES if gate.feature == feature]


def premium_features() -> set:
    """Funktionerna affärsmodellen säger att Free INTE har. Härledd ur
    FEATURES, aldrig skriven för hand - flyttas en funktion mellan nivåerna
    följer den här mängden med i samma sekund."""
    return {name for name in plan_features.FEATURES
            if not plan_features.allowed(plan_features.FREE, name)}


def unguarded_premium_features() -> set:
    """Premiumfunktioner utan en enda serverkontroll. Ska vara tom.

    Det här är hela J1 i en funktion: en funktion som säljs som Premium men
    bara döljs i klienten dyker upp här, och acceptanstestet faller."""
    return premium_features() - {gate.feature for gate in _GATES}


# =============================================================================
# GRINDARNA
# =============================================================================
# En per skyddad väg. api_server frågar dem; de frågar features.py. Ingen väg
# får jämföra plan mot funktionsnamn på egen hand - då kan två ställen svara
# olika om samma köp.
#
# Grindarna byggs BARA för det affärsmodellen säger är Premium just nu
# (`_when_premium`). Flyttas en funktion ner till gratis försvinner både
# grinden och kravet på den i samma sekund, utan att någon rad ändras här.

# Veckans middagar: klienten skickar recipeIds, så antalet är synligt på
# servern. Att neka prissättningen är en RIKTIG spärr - en vecka utan riktiga
# priser är inte produkten.
DINNER_LIMIT_MESSAGE = (f"Fler än {plan_features.FREE_MAX_DINNERS} middagar i veckan "
                        f"ingår i Premium")

# Veckotypens nyckel i klienten -> funktionen i affärsmodellen. Nycklarna är
# PLAN_TYPES i app.js; standardveckan är gratis och har därför ingen grind.
WEEK_TYPE_FEATURES = {
    "standard": "standard_week",
    "familj": "family_week",
    "budget": "budget_week",
    "traning": "training_week",
    "bulk": "bulk_week",
    "snabb": "quick_week",
    "vegetarisk": "vegetarian_week",
    "balanserad": "balanced_week",
}


def _premium(feature: str) -> bool:
    return not plan_features.allowed(plan_features.FREE, feature)


def _optional(builder, feature: str):
    """Bygger grinden bara så länge funktionen faktiskt är Premium."""
    return builder() if _premium(feature) else None


# "Laga med det jag har" - hela funktionen bor på servern (receptkällan söks
# på skafferiets innehåll), så det här är en av de grindar som inte går att
# kringgå från klienten alls.
PANTRY_RECIPES = _optional(lambda: deny(
    "full_pantry", "GET /api/v1/recipes/by-pantry",
    "”Laga med det jag har” ingår i Premium",
    {"method": "GET", "path": "/api/v1/recipes/by-pantry", "query": "items=kyckling,ris"},
), "full_pantry")

# Fritt kcal-/proteinfilter mot hela receptbanken. De kurerade hyllorna
# (/api/recipes/shelves) är och förblir gratis - det är "grundläggande
# näringsfilter" i paketeringen.
NUTRITION_FILTER = _optional(lambda: deny(
    "advanced_nutrition", "GET /api/recipes?minProtein=|maxKcal=",
    "Närings- och proteinmål ingår i Premium",
    {"method": "GET", "path": "/api/recipes", "query": "minProtein=30"},
), "advanced_nutrition")

MEAL_PREP_RECIPES = _optional(lambda: deny(
    "meal_prep", "GET /api/recipes?tag=mealprep",
    "Meal prep ingår i Premium",
    {"method": "GET", "path": "/api/recipes", "query": "tag=mealprep"},
), "meal_prep")

SEVEN_DINNERS = _optional(lambda: deny(
    "seven_dinners", "POST /api/pricing/week + /api/pricing/list (recipeIds)",
    DINNER_LIMIT_MESSAGE,
    {"method": "POST", "path": "/api/pricing/week",
     "body": {"recipeIds": [f"probe-{n}" for n in range(plan_features.PREMIUM_MAX_DINNERS)],
              "people": 2}},
), "seven_dinners")

# En grind per premiumveckotyp, byggd ur affärsmodellen. Svagast av alla:
# veckorna sätts ihop i klienten ur ett lokalt receptregister, så servern kan
# bara neka den som frågar ärligt om priset. Den fångar devtools-vägen
# (klienten skickar sin veckotyp), inte en handskriven begäran.
WEEK_TYPE_GATES = {
    key: deny(feature, f"POST /api/pricing/week (weekType={key})",
              "Den här veckotypen ingår i Premium",
              {"method": "POST", "path": "/api/pricing/week",
               "body": {"weekType": key, "recipeIds": ["probe-1"], "people": 2}})
    for key, feature in WEEK_TYPE_FEATURES.items() if _premium(feature)
}

# Alla butikers riktiga totaler, och den exakta jämförelsen mellan dem. Free
# får sin billigaste kvalificerade butik i FULL sanning; resten maskas.
ALL_STORE_PRICES = _optional(lambda: mask(
    "all_store_prices", "POST /api/pricing/week",
    "Alla butikers priser ingår i Premium",
    {"method": "POST", "path": "/api/pricing/week",
     "body": {"items": [{"name": "mjölk", "amount": 1, "unit": "l"}]}},
), "all_store_prices")

STORE_COMPARISON = _optional(lambda: mask(
    "store_comparison", "POST /api/pricing/week",
    "Den exakta butiksjämförelsen ingår i Premium",
    {"method": "POST", "path": "/api/pricing/week",
     "body": {"items": [{"name": "mjölk", "amount": 1, "unit": "l"}]}},
), "store_comparison")

ALL_STORE_BASKETS = _optional(lambda: deny(
    "all_store_baskets", "POST /api/pricing/list",
    "Den här butikens lista ingår i Premium",
    {"method": "POST", "path": "/api/pricing/list",
     "body": {"chain": "Hemköp", "items": [{"name": "mjölk", "amount": 1, "unit": "l"}]}},
), "all_store_baskets")

LIVE_PRICES = _optional(lambda: deny(
    "live_prices", "POST /api/products/batch",
    "Livepriser per vara ingår i Premium",
    {"method": "POST", "path": "/api/products/batch",
     "body": {"butik": "Willys", "zip": "80252", "varor": ["mjölk"]}},
), "live_prices")

# -----------------------------------------------------------------------------
# J3: hushållet och sparhistoriken
# -----------------------------------------------------------------------------

HOUSEHOLD_MESSAGE = (f"Fler än {plan_features.FREE_MAX_HOUSEHOLD_MEMBERS} personer i "
                     f"hushållet ingår i Premium")

# ATT BJUDA IN ÄR DEN HANDLING SOM MÖTER BETALVÄGGEN.
#
# Det här är hela svaret på "vad händer med ett befintligt gratishushåll som
# redan har fler än två medlemmar". Grinden sitter på inbjudan och på
# anslutningen - aldrig på att LÄSA hushållet, aldrig på att synka, aldrig på
# medlemsraderna. Ett gratishushåll med fem personer fortsätter alltså dela
# vecka, lista och skafferi precis som förut, i all evighet. Först när någon
# vill bli den sjätte möter familjen priset.
#
# Alternativet - att kasta ut medlem tre till fem när paketeringen ändras -
# vore att ta tillbaka något folk redan använder. Det säljer inga
# prenumerationer; det säljer avinstallationer.
#
# Proben behöver ett hushåll som redan är fullt, och därför ett andra konto:
# se `setup`.
HOUSEHOLD_SHARING = _optional(lambda: deny(
    "household_sharing", "POST /api/household/invite + /api/household/join",
    HOUSEHOLD_MESSAGE,
    {"method": "POST", "path": "/api/household/invite", "body": {}},
    setup=(
        {"method": "POST", "path": "/api/household/create", "body": {"name": "Probehushållet"}},
        {"method": "POST", "path": "/api/household/invite", "body": {}, "capture": "token"},
        {"method": "POST", "path": "/api/household/join", "body": {"token": "$token"},
         "as": "other"},
    ),
), "household_sharing")

# Sparhistoriken maskas i stället för att nekas: Free ska SE att siffran
# finns - senaste veckan - men inte trenden och inte månadsrapporten. En
# tom historik hade gjort grinden omöjlig att pröva, så proben lägger in
# två veckor först.
SAVINGS_HISTORY = _optional(lambda: mask(
    "savings_history", "GET /api/savings",
    "Full sparhistorik och månadsrapport ingår i Premium",
    {"method": "GET", "path": "/api/savings"},
    setup=(
        {"method": "POST", "path": "/api/savings/week",
         "body": {"weekKey": "2026-W36", "cheapestTotal": 1120.5, "priciestTotal": 1334.0,
                  "chain": "Willys"}},
        {"method": "POST", "path": "/api/savings/week",
         "body": {"weekKey": "2026-W37", "cheapestTotal": 980.0, "priciestTotal": 1194.5,
                  "chain": "Hemköp"}},
    ),
), "savings_history")


def household_member_cap(plan: str) -> int:
    """Hur många medlemmar planen får ha. Samma tal som /api/entitlements."""
    return plan_features.max_household_members(plan)


def household_is_full(plan: str, member_count: int) -> bool:
    """Får det här hushållet ta emot EN till?

    Grandfathering faller ut av jämförelsen i stället för att vara ett
    undantag: ett gratishushåll med fem medlemmar är "fullt" (5 >= 2) och
    får inte bjuda in fler, men ingenting i den här funktionen tar bort en
    enda av de fem."""
    return int(member_count) >= household_member_cap(plan)


def week_type_gate(week_type) -> Gate | None:
    """Grinden för en deklarerad veckotyp, eller None när typen är gratis
    (eller okänd - en okänd nyckel får inte kunna låsa upp något, men den
    får heller inte bli ett fel: den prissätts som en standardvecka)."""
    if not week_type:
        return None
    return WEEK_TYPE_GATES.get(str(week_type).strip().lower())


def dinner_limit(plan: str) -> int:
    """Hur många middagar planen får prissätta. Samma tal som
    /api/entitlements lovar klienten."""
    return (plan_features.PREMIUM_MAX_DINNERS if plan_features.is_premium(plan)
            else plan_features.FREE_MAX_DINNERS)
