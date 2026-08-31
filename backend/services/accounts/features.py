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
FEATURES = {
    # Veckoplanering
    "standard_week": {"free": True},        # vanlig standardvecka
    "family_week": {"free": False},
    "budget_week": {"free": False},
    "training_week": {"free": False},
    "bulk_week": {"free": False},
    "quick_week": {"free": False},
    "vegetarian_week": {"free": False},
    "balanced_week": {"free": False},
    # Middagar per vecka: Free planerar upp till gränsen, Premium 1-7.
    "seven_dinners": {"free": False},
    # Butiker och priser
    "cheapest_store_price": {"free": True},   # riktigt totalpris, billigaste kvalificerade butiken
    "cheapest_store_basket": {"free": True},  # dess riktiga inköpslista
    "all_store_prices": {"free": False},
    "all_store_baskets": {"free": False},
    "store_comparison": {"free": False},      # exakta skillnader mellan butiker
    # Recept & filter
    "recipe_search": {"free": True},
    "advanced_nutrition": {"free": False},    # kcal-/proteinfilter, näringsmål
    "meal_prep": {"free": False},
    # Skafferi
    "basic_pantry": {"free": True},
    "full_pantry": {"free": False},           # Laga med det jag har m.m.
    "favorites": {"free": True},
}

# Free planerar högst så här många middagar per vecka.
FREE_MAX_DINNERS = 4
PREMIUM_MAX_DINNERS = 7


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
        "features": {name: allowed(plan, name) for name in FEATURES},
        "pricing": PRICING,
    }
