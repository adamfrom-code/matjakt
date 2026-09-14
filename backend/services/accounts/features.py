# -*- coding: utf-8 -*-
"""Matjakts affärsmodell på ETT ställe: planer, priser och feature-matrisen.

FREE FOREVER / PREMIUM 59 KR/MÅN / PREMIUM 399 KR/ÅR. No automatic trial.

Everything that differs between Free and Premium is a row in FEATURES, and
nothing anywhere else may hardcode the answer - the backend enforces with
`allowed(plan, feature)`, the frontend ASKS via /api/entitlements and renders
locks accordingly. Moving a feature between tiers is editing one line here.

THE ONE RULE THE MODEL MAY NEVER BREAK: Free/Premium changes what is SHOWN,
never what is TRUE. A masked comparison is still computed from real prices;
Premium unlocks the view of it. No tier ever turns an estimate into a price.
"""

FREE = "free"
PREMIUM_MONTHLY = "premium_monthly"
PREMIUM_YEARLY = "premium_yearly"
PLANS = (FREE, PREMIUM_MONTHLY, PREMIUM_YEARLY)
PREMIUM_PLANS = frozenset({PREMIUM_MONTHLY, PREMIUM_YEARLY})

# Central pricing. The numbers 59/399 exist HERE and nowhere else in code;
# the UI reads them from /api/entitlements. The savings line is arithmetic,
# not marketing: 59*12 - 399 = 309.
PRICING = {
    "monthly": {
        "plan": PREMIUM_MONTHLY,
        "label": "Premium",
        "pricePerMonth": 59,
        "priceText": "59 kr/mån",
        # Fylls i när riktiga betalplattformar kopplas på.
        "storekitProductId": "se.matjakt.premium.monthly",
    },
    "yearly": {
        "plan": PREMIUM_YEARLY,
        "label": "Premium År",
        "pricePerYear": 399,
        "priceText": "399 kr/år",
        "perMonthText": "≈ 33 kr/mån",
        "savingsText": "Spara 309 kr jämfört med månadsbetalning",
        "badge": "Bäst värde",
        "storekitProductId": "se.matjakt.premium.yearly",
    },
}

# Feature -> which plans have it. Free is deliberately a GOOD product: the
# whole planning loop works, against real prices, for the cheapest qualified
# store - Premium widens it to every store, every week type and the advanced
# filters. A feature not listed here is free for everyone.
#
# J3 FLYTTADE GRÄNSEN, och principen bakom flytten är värd att skriva ut:
# sälj det som är dyrt för OSS och återkommande värdefullt för kunden -
# färsk prisdata och delning - inte det som är gratis att generera lokalt
# (och därför omöjligt att skydda).
#
# Ner till gratis: alla veckotyper, full_pantry, advanced_nutrition,
# meal_prep. Veckorna sätts ihop i klienten ur ett lokalt receptregister, så
# grinden kunde bara neka den som frågade ärligt om priset - och just de
# funktionerna är vad som gör en ny användare beroende de första två
# veckorna. Att låtsas sälja dem kostade oss vanan och gav ingen intäkt.
#
# Upp till premium: hushåll bortom två personer, och sparhistoriken.
# Hushållet är den överlägset starkaste betalningsanledningen - en familj
# som lagt in skafferi och delar lista byter inte app - och det är omöjligt
# att kringgå från klienten eftersom varje rad går via servern.
FEATURES = {
    # Veckoplanering: varenda veckotyp är gratis sedan J3.
    "standard_week": {"free": True},
    "family_week": {"free": True},
    "budget_week": {"free": True},
    "training_week": {"free": True},
    "bulk_week": {"free": True},
    "quick_week": {"free": True},
    "vegetarian_week": {"free": True},
    "balanced_week": {"free": True},
    # Middagar per vecka: Free planerar upp till gränsen, Premium 1-7.
    "seven_dinners": {"free": False},
    # Byten: obegränsat många sedan G10, och avsikten bakom bytet ingår.
    #
    # G10 sålde de fem avsikterna - "Billigare", "Snabbare", "Barnvänligare",
    # "Mer protein", "Använd det vi har hemma" - som Premium utan att ge dem
    # en rad här. En funktion utan nyckel FINNS inte i modellen: den kunde
    # varken få en serverkontroll (J1 härleder sin mängd ur FEATURES), en rad
    # i premiumtabellerna (J2 och I8 kräver en nyckel per rad) eller ett svar
    # i /api/entitlements. Kvar blev ett lås som bara klienten kände till,
    # och en funktion som inte gick att sälja någonstans.
    #
    # J3:s princip avgör åt vilket håll nyckeln ska sättas, och den pekar hit:
    # rankningen sker i rankSwapOptions() i KLIENTEN, ur samma lokala
    # receptregister som veckorna, och kostar oss ingenting per byte. Fyra av
    # de fem avsikterna är dessutom omskrivningar av det J3 nyss flyttade ner
    # - "Använd det vi har hemma" ÄR full_pantry, "Mer protein" ÄR
    # advanced_nutrition, "Billigare" är portionspriset som redan är gratis.
    # Att låtsas sälja dem hade kostat oss vanan och gett ingen intäkt, precis
    # det J3 skrev. Byte är handlingen som gör veckan till din.
    "swap_intents": {"free": True},
    # Butiker och priser
    "cheapest_store_price": {"free": True},   # riktigt totalpris, billigaste kvalificerade butiken
    "cheapest_store_basket": {"free": True},  # dess riktiga inköpslista
    "all_store_prices": {"free": False},
    "all_store_baskets": {"free": False},
    "store_comparison": {"free": False},      # exakta skillnader mellan butiker
    "live_prices": {"free": False},           # per-vara-priser från butikssajterna (products/batch)
    # Recept & filter
    "recipe_search": {"free": True},
    "advanced_nutrition": {"free": True},     # kcal-/proteinfilter, näringsmål
    "meal_prep": {"free": True},
    # Skafferi
    "basic_pantry": {"free": True},
    "full_pantry": {"free": True},            # "Laga med det jag har"
    "favorites": {"free": True},
    # Hushåll: två personer delar gratis, familjen kostar. Varje rad går via
    # servern, så det här är den enda funktionen i produkten som inte går
    # att låsa upp från klienten.
    "household_sharing": {"free": False},
    # Sparhistorik: Free ser den senaste veckan, Premium hela historiken och
    # månadsrapporten - "Du sparade 1 340 kr i september", den enda siffran
    # som BEVISAR att prenumerationen betalar sig.
    "savings_history": {"free": False},
}

# Free planerar högst så här många middagar per vecka. J3: 4 -> 5. En
# arbetsvecka är den naturliga enheten; fyra känns som en stympning.
FREE_MAX_DINNERS = 5
PREMIUM_MAX_DINNERS = 7

# Hushållets storlek per plan. Två personer är "vi delar lista"; tre är en
# familj, och det är familjen som är produkten.
FREE_MAX_HOUSEHOLD_MEMBERS = 2
PREMIUM_MAX_HOUSEHOLD_MEMBERS = 12

# Så många veckor bakåt sparhistoriken visar. Free ser den senaste veckan -
# nog för att veta att siffran finns, för lite för att se en trend.
FREE_SAVINGS_WEEKS = 1
PREMIUM_SAVINGS_WEEKS = 52


def max_household_members(plan: str) -> int:
    """Hur många som får dela hushåll på den här planen.

    ETT ställe. Både grinden i billing/gate.py, hushållslagret och
    /api/entitlements läser den här funktionen, så de kan aldrig svara
    olika på samma fråga."""
    return (PREMIUM_MAX_HOUSEHOLD_MEMBERS if is_premium(plan)
            else FREE_MAX_HOUSEHOLD_MEMBERS)


def max_savings_weeks(plan: str) -> int:
    return PREMIUM_SAVINGS_WEEKS if is_premium(plan) else FREE_SAVINGS_WEEKS


def plan_for_user(user: dict | None) -> str:
    """Which plan a user payload (accounts.store._to_public) is on.

    Grandfathering: the boolean premium flag (redeem codes, legacy trials,
    an active subscription without a recorded plan) counts as monthly - a
    paying or comped user must never wake up demoted by a refactor."""
    if not user:
        return FREE
    subscription_plan = (user.get("subscriptionPlan") or "").lower()
    if user.get("premium"):
        if "year" in subscription_plan or subscription_plan == PREMIUM_YEARLY:
            return PREMIUM_YEARLY
        return PREMIUM_MONTHLY
    return FREE


def is_premium(plan: str) -> bool:
    return plan in PREMIUM_PLANS


def allowed(plan: str, feature: str) -> bool:
    rule = FEATURES.get(feature)
    if rule is None:
        return True  # oallokerad funktion är fri
    return True if is_premium(plan) else bool(rule.get("free"))


def entitlements(plan: str) -> dict:
    """What /api/entitlements hands the frontend: the whole contract."""
    return {
        "plan": plan,
        "isPremium": is_premium(plan),
        "maxDinners": PREMIUM_MAX_DINNERS if is_premium(plan) else FREE_MAX_DINNERS,
        # J3: klienten ska kunna säga "ni är två av två" utan att gissa, och
        # utan att först få ett 403 i ansiktet.
        "maxHouseholdMembers": max_household_members(plan),
        "maxSavingsWeeks": max_savings_weeks(plan),
        "features": {name: allowed(plan, name) for name in FEATURES},
        "pricing": PRICING,
    }
