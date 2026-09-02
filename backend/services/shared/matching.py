# -*- coding: utf-8 -*-
"""Matchningsmotorn: vilka recept räcker det som står i kylen till?

Motorn svarar bara på det som är SANT om ett recept och ett skafferi -
hur stor del som finns hemma, vad som saknas, om det går att laga nu. Den
rankar inte efter vad någon vill äta. Det är avsiktligt: bäst-före-datum,
gillamarkeringar och vardagsvänlighet är den KONSUMERANDE appens data, och
en motor som blandar in dem hade tvingat varje app att acceptera Ät Upps
prioriteringar.

TRE UTFALL PER RAD, INTE TVÅ. En receptrad är antingen täckt av något
hemma, täckt av skafferigrunden (salt, peppar, olja), eller saknad. Att
slå ihop de två första gör "du har 7 av 9" till en siffra ingen kan
kontrollera - den som ser raden vill veta om det var kylen eller kryddhyllan
som räddade den.

SKAFFERIGRUNDEN ÄR ANROPARENS. Receptbanken flaggar en del rader som
pantryStaple, och de flaggorna följer med ut som information. Men de
BESTÄMMER inte: banken flaggar ris och vitlök i några recept, och ett
"kan lagas nu" som förutsätter ris man inte har är fel svar. Den som frågar
skickar sin egen uppsättning; DEFAULT_PANTRY_STAPLES gäller när ingen gör
det.
"""

from .canonical import (
    DEFAULT_PANTRY_STAPLES,
    best_match,
    canonical_id,
)

__all__ = ["DEFAULT_PANTRY_STAPLES", "match_recipe", "match_recipes", "resolve_staples"]


def resolve_staples(extra=None, exclude=None) -> frozenset:
    """Anroparens skafferigrund: standarden, plus det egna, minus det egna.

    Två listor och inte en ersättningslista, därför att båda ändringarna är
    vanliga och olika: "jag har alltid vitlök hemma" och "jag har faktiskt
    inget smör". Med bara en ersättningslista hade den andra krävt att appen
    skickade hela standarduppsättningen varje gång."""
    staples = set(DEFAULT_PANTRY_STAPLES)
    for name in extra or []:
        identifier = canonical_id(name)
        if identifier:
            staples.add(identifier)
    for name in exclude or []:
        staples.discard(canonical_id(name))
    return frozenset(staples)


def _ingredient_rows(recipe: dict) -> list:
    """Receptets rader i den form motorn räknar på.

    Både receptbankens fulla form (`ingredients`) och kortformen
    (`ingredientNames`) accepteras. Kortformen saknar mängder och flaggor,
    så en app som bara har kort får ett grövre men inte felaktigt svar."""
    rows = recipe.get("ingredients")
    if rows:
        return [row for row in rows if isinstance(row, dict)]
    return [{"name": name} for name in recipe.get("ingredientNames") or []]


def match_recipe(recipe: dict, have, *, staples=None) -> dict:
    """Ett recept mot ett skafferi.

    `have` är namnen på det som finns hemma, som människor skriver dem
    ("gul lök", "creme fraiche"). Kanoniseringen sker här, inte hos
    anroparen - annars blir varje app tvungen att kunna svenska."""
    staples = DEFAULT_PANTRY_STAPLES if staples is None else staples
    have_names = [str(name).strip() for name in have if str(name or "").strip()]

    available, from_staples, missing = [], [], []
    # Ett recept som råkar lista lök på två rader är EN vara att köpa, inte
    # två. Utan detta blev "du har 7 av 9" fel för att nämnaren räknade
    # samma sak dubbelt, och kompletteringslistan bad någon köpa lök två
    # gånger. Första raden vinner, så mängden som visas är den som stod
    # först i receptet.
    seen_ids = set()
    for row in _ingredient_rows(recipe):
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        # Frivilliga rader räknas aldrig som saknade. "Toppa gärna med
        # persilja" ska inte göra en middag omöjlig.
        if row.get("optional"):
            continue
        identifier = canonical_id(name)
        if identifier in seen_ids:
            continue
        seen_ids.add(identifier)
        entry = {
            "name": name,
            "id": identifier,
            "amount": row.get("amount"),
            "unit": row.get("unit"),
            # Receptets EGEN flagga, som information. Se modulens docstring
            # för varför den inte avgör.
            "recipeStaple": bool(row.get("pantryStaple")),
        }
        matched_name, relation = best_match(have_names, name)
        if relation:
            available.append({**entry, "have": matched_name, "match": relation})
        elif entry["id"] in staples:
            from_staples.append(entry)
        else:
            missing.append(entry)

    required = len(available) + len(from_staples) + len(missing)
    covered = len(available) + len(from_staples)
    return {
        "recipeId": recipe.get("id"),
        # Procent av HELA receptet, skafferigrunden inräknad: det är den
        # siffra "du har 7 av 9 ingredienser" bygger på, och 9 är antalet
        # rader någon behöver ha, inte antalet rader som råkar vara
        # spännande.
        "matchPercent": round(100 * covered / required) if required else 0,
        "requiredCount": required,
        "availableCount": covered,
        "missingCount": len(missing),
        # Saknade råvaror mot saknad skafferigrund. Ett recept som bara
        # saknar salt är en helt annan sak än ett som saknar kycklingen,
        # och en app som bara får ett tal kan inte se skillnaden.
        "missingMainCount": sum(1 for row in missing if not row["recipeStaple"]),
        "missingStapleCount": sum(1 for row in missing if row["recipeStaple"]),
        "canCookNow": not missing,
        "availableIngredients": available,
        "stapleIngredients": from_staples,
        "missingIngredients": missing,
    }


def _sort_key(entry: dict):
    """Ordningen när ingen annan ordning begärts: det som går att laga nu
    först, sedan det som saknar minst, sedan det som täcks bäst.

    Det här är INTE Ät Upps ranking - bäst före-datum och gillamarkeringar
    hör hemma i appen som äger dem. Det är bara en förutsägbar ordning, så
    en app som visar de tio första visar de tio mest användbara."""
    return (
        not entry["match"]["canCookNow"],
        entry["match"]["missingMainCount"],
        entry["match"]["missingCount"],
        -entry["match"]["matchPercent"],
        entry["recipe"].get("name") or "",
    )


def match_recipes(recipes, have, *, staples=None, max_missing=None, limit=None) -> list:
    """Hela receptbanken mot ett skafferi, sorterad och avkortad.

    max_missing filtrerar bort det som ändå inte är intressant: "saknas bara
    1-3 saker" är en skärm i Ät Upp, och att skicka hem 241 recept för att
    appen ska kasta 200 av dem är slöseri på en telefon."""
    scored = []
    for recipe in recipes:
        match = match_recipe(recipe, have, staples=staples)
        # Ett recept där INGENTING finns hemma är inte ett svar på "vad kan
        # jag laga av det jag har" - det är receptbanken. Skafferigrunden
        # ensam räknas inte som en träff: salt och peppar finns i nästan
        # varje recept, och skulle annars göra hela banken till en träff.
        if not match["availableIngredients"]:
            continue
        if max_missing is not None and match["missingCount"] > max_missing:
            continue
        scored.append({"recipe": recipe, "match": match})
    scored.sort(key=_sort_key)
    return scored[:limit] if limit else scored
