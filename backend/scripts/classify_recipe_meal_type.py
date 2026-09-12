# -*- coding: utf-8 -*-
"""Sätter `mealType` på varje recept — av regler, inte av en engångskörning.

    python backend/scripts/classify_recipe_meal_type.py              # visa facit
    python backend/scripts/classify_recipe_meal_type.py --skriv      # skriv i källorna
    python backend/scripts/classify_recipe_meal_type.py --kontrollera  # grind
    python backend/scripts/classify_recipe_meal_type.py --db backend/data/recipes.db

VARFÖR SKRIPTET FINNS OCH INTE BARA EN SPALT MED VÄRDEN. 240 recept ska
klassas och en del är genuint tveksamma — är pannkakor middag eller efterrätt?
Ett fält satt av en körning ingen kan upprepa är sämre än inget fält: nästa
gång banken växer vet ingen vilken regel som gällde, och den som tycker att
ett värde är fel har inget att invända mot. Därför: läsbara regler i tur och
ordning, ett svar per recept med namnet på regeln som avgjorde, och en lista
över de recept där svaret är omtvistat.

KÄLLORNA ÄR SANNINGEN, INTE DATABASEN. `services/recipes/api.bootstrap_if_empty`
bygger om banken ur `backend/recipe_sources/*.json` så snart deras fingeravtryck
ändras. Ett `mealType` som bara finns i `recipes.db` överlever alltså inte
nästa gång ett recept redigeras. `--skriv` skriver därför i källorna; `--db`
finns för att kunna stämpla en redan driftsatt databas utan att vänta på en
omimport.

REGLERNA, I ORDNING (första träffen avgör)
--------------------------------------------------------------------------
Ordningen bär hela bedömningen och är därför den enda platsen där den står:

  1  gröt och välling        → frukost    Namnet avgör. Gröt är frukostmat i
                                          Sverige oavsett när den äts, och
                                          "kvällsmat i mysbyxor" i beskriv-
                                          ningen gör den inte till en middag
                                          man planerar en tisdag för.
  2  receptet säger frukost  → frukost    Egen utsago väger tyngre än taggar.
  3  receptet säger efterrätt→ efterratt
  4  receptet säger tillbehör→ tillbehor  "serveras till", "följeslagare till".
  5  receptet säger lunch    → lunch      "kall lunch", "äts till lunch".
  6  middagsbevis            → middag     Egen utsago ("middag", "kvällsmat")
                                          eller en tagg/kategori som bara
                                          sätts på middagar (helgmiddag,
                                          vardagsmat, familj, Familjefavorit,
                                          Helg, Helgmiddag).
  7  lunchmärkt              → lunch      Taggen/kategorin `lunch` när inget
                                          i regel 6 talade emot.
  8  huvudrätt               → middag     Grundfallet. Banken är byggd som en
                                          bank av huvudrätter; ett recept utan
                                          en enda motsatt signal är en middag.

Regel 2–5 har alla samma spärr: de går inte om receptet SAMTIDIGT säger att
det är en middag. "Mättande vardagsmiddag eller helgfrukost" är först och
främst en middag — det är vad receptet själv sätter först.

OSÄKERHETEN RAPPORTERAS, DEN GÖMS INTE
--------------------------------------------------------------------------
Ett recept är osäkert när

  a) bevis för mer än en måltidstyp fanns (regeln valde, men valet är
     omtvistat), eller
  b) namnet hör till en rättfamilj som per definition står mellan två
     stolar — pannkakor och gröt i svenskt kök.

Listan skrivs ut vid varje körning och står i `docs/changelog.d/M1.md`. Den
som inte håller med har ett recept-id och en regel att argumentera mot.
"""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from services.recipes.meal_types import (  # noqa: E402
    BREAKFAST, DESSERT, DINNER, LUNCH, MEAL_TYPES, SIDE)

SOURCE_DIR = ROOT / "backend" / "recipe_sources"
# Den bundlade reservbanken appen faller tillbaka på när backenden inte svarar.
# Utan `mealType` här hade ett backendavbrott gett en veckoplanerare som inte
# kan skilja gröt från gryta — alltså exakt den situation M1 finns för.
FALLBACK_JSON = ROOT / "frontend" / "app" / "data" / "recipes.json"


def _fold(text: str) -> str:
    """Gemener utan diakriter. `Kött` och `kott` är samma ord för en regel."""
    lowered = str(text or "").lower()
    return "".join(c for c in unicodedata.normalize("NFD", lowered)
                   if unicodedata.category(c) != "Mn")


def _words(*parts) -> str:
    return _fold(" ".join(str(p or "") for p in parts))


# --- signalerna reglerna läser -------------------------------------------
# Var och en är ett mönster med ett skäl. Skälet är inte dekoration: det är
# vad någon som tycker att ett recept hamnat fel faktiskt ska bemöta.

# Ändelsematchning, inte helordsmatchning: "risgrynsgröt" och
# "havregrynsgröt" är sammansatta ord och en \b före "gröt" hade missat
# exakt de två recept regeln finns för.
GROT_I_NAMNET = re.compile(r"(gr[öo]t|v[äa]lling|m[üu]sli|granola)(en|ar|arna)?\b")
SAGER_FRUKOST = re.compile(r"\bfrukost")
SAGER_EFTERRATT = re.compile(r"\b(efterr[äa]tt|dessert)")
SAGER_TILLBEHOR = re.compile(r"(tillbeh[öo]r till|serveras till|f[öo]ljeslagare till"
                             r"|passar till|som tillbeh[öo]r)")
SAGER_LUNCH = re.compile(r"\blunch")
SAGER_MIDDAG = re.compile(r"\b(middag|kv[äa]llsmat|fredagsmys)")

# Taggar och kategorier som i den här banken BARA sitter på middagar. Listan
# är kort med flit. `husmanskost` står inte här - risgrynsgröt och pannkakor
# bär den också, och en signal som pekar åt båda hållen är ingen signal.
MIDDAGSTAGGAR = {"helgmiddag", "vardagsmat", "familj", "familjefavorit"}
MIDDAGSKATEGORIER = {"helg", "helgmiddag", "familj", "familjefavorit"}
LUNCHMARKE = {"lunch"}

# Rättfamiljer som står mellan två stolar oavsett vad regeln landar på.
# Rapporteras alltid som osäkra, med frågan skriven ut.
GRANSFALL = [
    (re.compile(r"pannkak"),
     "Pannkakor är både torsdagens huvudrätt och en efterrätt. "
     "Reglerna följer receptets egen inramning."),
    (re.compile(r"gr[öo]t\b"),
     "Gröt är frukost, men risgrynsgröt äts också som kvällsmat."),
]


class Fynd:
    """Ett recept, regeln som avgjorde, och bevisen som fanns."""

    def __init__(self, recipe_id, name, meal_type, rule, evidence, borderline):
        self.recipe_id = recipe_id
        self.name = name
        self.meal_type = meal_type
        self.rule = rule
        self.evidence = evidence          # {meal_type: [skäl, ...]}
        self.borderline = borderline      # [frågan, ...]

    @property
    def uncertain(self) -> bool:
        return len(self.evidence) > 1 or bool(self.borderline)

    def why(self) -> str:
        other = [f"{typ} ({'; '.join(skal)})"
                 for typ, skal in self.evidence.items() if typ != self.meal_type]
        parts = [f"regel {self.rule}"]
        if other:
            parts.append("bevis även för " + ", ".join(other))
        parts.extend(self.borderline)
        return " · ".join(parts)


def classify(recipe: dict) -> Fynd:
    """Reglerna, i ordning. Första träffen avgör - och allt som TALADE för
    något annat sparas, så att svaret går att ifrågasätta."""
    name = _fold(recipe.get("name") or recipe.get("namn") or "")
    description = _fold(recipe.get("description") or "")
    said = f"{name} {description}"
    tags = {_fold(t) for t in (recipe.get("tags") or recipe.get("taggar") or [])}
    categories = {_fold(c) for c in (recipe.get("categories") or [])}
    if recipe.get("typ"):
        categories.add(_fold(recipe["typ"]))

    evidence: dict[str, list[str]] = {}

    def note(meal_type, reason):
        evidence.setdefault(meal_type, []).append(reason)
        return True

    # Middagsbeviset räknas fram först, för det är spärren regel 2-5 läser.
    dinner_words = SAGER_MIDDAG.search(said)
    if dinner_words:
        note(DINNER, f'säger "{dinner_words.group(0)}"')
    for tag in sorted(tags & MIDDAGSTAGGAR):
        note(DINNER, f"taggen {tag}")
    for category in sorted(categories & MIDDAGSKATEGORIER):
        note(DINNER, f"kategorin {category}")
    says_dinner = DINNER in evidence

    if GROT_I_NAMNET.search(name):
        note(BREAKFAST, "gröt/välling i namnet")
    if SAGER_FRUKOST.search(said):
        note(BREAKFAST, 'säger "frukost"')
    if SAGER_EFTERRATT.search(said):
        note(DESSERT, 'säger "efterrätt"')
    if SAGER_TILLBEHOR.search(said):
        note(SIDE, "säger att den serveras till något annat")
    if SAGER_LUNCH.search(said):
        note(LUNCH, 'säger "lunch"')
    for mark in sorted((tags | categories) & LUNCHMARKE):
        note(LUNCH, f"märkt {mark}")

    borderline = [reason for pattern, reason in GRANSFALL if pattern.search(name)]

    def fynd(meal_type, rule):
        return Fynd(recipe.get("id"), recipe.get("name") or recipe.get("namn"),
                    meal_type, rule, evidence, borderline)

    # 1. Namnet är starkast: en gröt är en gröt.
    if GROT_I_NAMNET.search(name):
        return fynd(BREAKFAST, "grot-i-namnet")
    # 2-5. Vad receptet säger om sig självt - men inte när det också kallar
    #      sig middag. Då är middagen det receptet sätter först.
    if not says_dinner:
        if SAGER_FRUKOST.search(said):
            return fynd(BREAKFAST, "sager-frukost")
        if SAGER_EFTERRATT.search(said):
            return fynd(DESSERT, "sager-efterratt")
        if SAGER_TILLBEHOR.search(said):
            return fynd(SIDE, "sager-tillbehor")
        if SAGER_LUNCH.search(said):
            return fynd(LUNCH, "sager-lunch")
    # 6. Middagsbeviset.
    if says_dinner:
        return fynd(DINNER, "middagsbevis")
    # 7. Lunchmärkt utan att något talade för middag.
    if (tags | categories) & LUNCHMARKE:
        return fynd(LUNCH, "lunchmarkt")
    # 8. Grundfallet. Banken är en bank av huvudrätter.
    return fynd(DINNER, "huvudratt")


# --- läsa och skriva källorna --------------------------------------------

def source_files() -> list[Path]:
    return sorted(SOURCE_DIR.glob("*.json"))


def load_sources() -> list[tuple[Path, list]]:
    return [(path, json.loads(path.read_text(encoding="utf-8"))) for path in source_files()]


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


# Var i objektet fältet hamnar. INTE sist: M2 arbetar parallellt i samma filer
# och skriver bildfälten, som ligger sist. Ett fält inskjutet direkt efter
# portionsantalet rör en rad inget annat paket rör - och läses dessutom där
# det hör hemma, bredvid "hur många det räcker till".
EFTER = ("servings", "portioner", "description", "namn", "name", "id")


def with_meal_type(recipe: dict, meal_type: str) -> dict:
    """Samma recept med `mealType` inskjutet på en stabil plats."""
    if recipe.get("mealType") == meal_type:
        return recipe
    without = {k: v for k, v in recipe.items() if k != "mealType"}
    anchor = next((key for key in EFTER if key in without), None)
    if anchor is None:
        return {**without, "mealType": meal_type}
    rebuilt = {}
    for key, value in without.items():
        rebuilt[key] = value
        if key == anchor:
            rebuilt["mealType"] = meal_type
    return rebuilt


def classify_all() -> list[Fynd]:
    findings = []
    for _, recipes in load_sources():
        findings.extend(classify(recipe) for recipe in recipes)
    return findings


def apply_to_sources() -> int:
    """Skriver `mealType` i källorna och i den bundlade reservbanken."""
    changed = 0
    by_id = {}
    for path, recipes in load_sources():
        dirty = False
        for index, recipe in enumerate(recipes):
            fynd = classify(recipe)
            by_id[recipe.get("id")] = fynd.meal_type
            if recipe.get("mealType") != fynd.meal_type:
                recipes[index] = with_meal_type(recipe, fynd.meal_type)
                dirty, changed = True, changed + 1
        if dirty:
            write_json(path, recipes)

    # Reservbanken är samma recept i appens egna fältnamn. Samma id ska ha
    # samma svar - annars beror middagsveckan på om backenden råkade svara.
    if FALLBACK_JSON.exists():
        legacy = json.loads(FALLBACK_JSON.read_text(encoding="utf-8"))
        dirty = False
        for index, recipe in enumerate(legacy):
            meal_type = by_id.get(recipe.get("id")) or classify(recipe).meal_type
            if recipe.get("mealType") != meal_type:
                legacy[index] = with_meal_type(recipe, meal_type)
                dirty, changed = True, changed + 1
        if dirty:
            write_json(FALLBACK_JSON, legacy)
    return changed


def check_sources() -> list[str]:
    """Vad som skiljer källornas `mealType` från vad reglerna säger idag."""
    problems = []
    by_id = {}
    for path, recipes in load_sources():
        for recipe in recipes:
            fynd = classify(recipe)
            by_id[recipe.get("id")] = fynd.meal_type
            stored = recipe.get("mealType")
            if stored is None:
                problems.append(f"{path.name}: {recipe.get('id')} saknar mealType")
            elif stored not in MEAL_TYPES:
                problems.append(f"{path.name}: {recipe.get('id')} har okänt mealType {stored!r}")
            elif stored != fynd.meal_type:
                problems.append(
                    f"{path.name}: {recipe.get('id')} står som {stored!r} men regel "
                    f"{fynd.rule} ger {fynd.meal_type!r}")
    if FALLBACK_JSON.exists():
        for recipe in json.loads(FALLBACK_JSON.read_text(encoding="utf-8")):
            want = by_id.get(recipe.get("id")) or classify(recipe).meal_type
            if recipe.get("mealType") != want:
                problems.append(
                    f"{FALLBACK_JSON.name}: {recipe.get('id')} står som "
                    f"{recipe.get('mealType')!r}, källorna säger {want!r}")
    return problems


def apply_to_db(db_path: Path) -> int:
    """Stämplar en redan driftsatt databas utan att vänta på en omimport."""
    from services.recipes.store import RecipeStore
    store = RecipeStore(db_path)
    try:
        by_id = {}
        for _, recipes in load_sources():
            for recipe in recipes:
                by_id[recipe.get("id")] = classify(recipe).meal_type
        written = 0
        with store.connection:
            for row in store.connection.execute("SELECT id, name FROM recipes"):
                meal_type = by_id.get(row["id"])
                if meal_type is None:
                    # Ett recept som finns i databasen men inte i källorna.
                    # Klassa det på namnet hellre än att lämna det oklassat -
                    # ett NULL hade ändå bara betytt "aldrig middag".
                    meal_type = classify({"id": row["id"], "name": row["name"]}).meal_type
                written += store.connection.execute(
                    "UPDATE recipes SET meal_type = ? WHERE id = ? AND meal_type IS NOT ?",
                    (meal_type, row["id"], meal_type)).rowcount
        return written
    finally:
        store.close()


def report(findings: list[Fynd]) -> None:
    counts = {}
    for fynd in findings:
        counts[fynd.meal_type] = counts.get(fynd.meal_type, 0) + 1
    print(f"{len(findings)} recept klassificerade")
    for meal_type in MEAL_TYPES:
        print(f"  {meal_type:10s} {counts.get(meal_type, 0):4d}")
    # Två listor, för de svarar på två frågor. Den första: var valde regeln
    # mellan två rimliga svar? Den andra: vilka recept tog klassificeringen
    # BORT ur veckoplaneringen? Den andra är den med konsekvenser - varje rad
    # där är en middag användaren inte längre kan få föreslagen.
    uncertain = [f for f in findings if f.uncertain]
    print(f"\nOsäkra klassificeringar ({len(uncertain)}) — regeln valde, men valet går att ifrågasätta:")
    for fynd in sorted(uncertain, key=lambda f: (f.meal_type, f.recipe_id or "")):
        print(f"  {fynd.recipe_id:34s} {fynd.meal_type:10s} {fynd.name}")
        print(f"      {fynd.why()}")
    excluded = [f for f in findings if f.meal_type != DINNER]
    print(f"\nUteslutna ur middagsveckan ({len(excluded)}) — allt som inte är {DINNER!r}:")
    for fynd in sorted(excluded, key=lambda f: (f.meal_type, f.recipe_id or "")):
        print(f"  {fynd.recipe_id:34s} {fynd.meal_type:10s} {fynd.name}")
        print(f"      {fynd.why()}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skriv", action="store_true",
                        help="skriv mealType i recipe_sources/ och reservbanken")
    parser.add_argument("--kontrollera", action="store_true",
                        help="avsluta med 1 om källorna inte stämmer med reglerna")
    parser.add_argument("--db", type=Path,
                        help="stämpla en befintlig recipes.db med reglernas svar")
    args = parser.parse_args(argv)

    findings = classify_all()
    if args.kontrollera:
        problems = check_sources()
        for problem in problems:
            print(problem)
        print(f"{len(problems)} avvikelser mot reglerna")
        return 1 if problems else 0
    if args.skriv:
        print(f"{apply_to_sources()} fält skrivna")
    if args.db:
        print(f"{apply_to_db(args.db)} rader stämplade i {args.db}")
    report(findings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
