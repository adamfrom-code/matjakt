# -*- coding: utf-8 -*-
"""Gör receptbankens skafferiklassning konsekvent - och håller den så.

    backend/venv/bin/python backend/scripts/classify_recipe_pantry.py
    backend/venv/bin/python backend/scripts/classify_recipe_pantry.py --kontrollera
    backend/venv/bin/python backend/scripts/classify_recipe_pantry.py --skriv
    backend/venv/bin/python backend/scripts/classify_recipe_pantry.py --db backend/data/recipes.db

Facit är `services/recipes/pantry.py`: en lista över vilka INGREDIENSER som
antas finnas hemma. Det här skriptet jämför varje receptrad mot den listan.

Utan argument rapporteras avvikelserna. `--kontrollera` gör samma sak men
avslutar med felkod, vilket är vad ett test kör. `--skriv` rättar källorna och
den bundlade reservbanken. `--db` stämplar en redan driftsatt databas.

TVÅ SORTERS RÄTTNING, OCH BARA DEN ENA GÅR ATT AUTOMATISERA. En rad som blir
skafferivara tappar sin mängd - den uppgiften finns i listan. En rad som blir
KÖPVARA behöver en mängd, och en mängd går inte att räkna fram ur en flagga.
Därför står de fyrtio mängderna i MANGDER nedan, var och en med var den är
hämtad ifrån: bankens egna rader för samma ingrediens vid samma portionsantal,
eller receptets egen instruktionstext. Ingen av dem är påhittad, och skriptet
vägrar skriva en köpvarurad det inte har en mängd för.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from services.recipes.pantry import is_pantry_staple, reason  # noqa: E402
from services.recipes.store import normalize_ingredient_id  # noqa: E402

SOURCE_DIR = ROOT / "backend" / "recipe_sources"
# Reservbanken appen faller tillbaka på när backenden inte svarar. Den bär
# samma distinktion i det gamla formatet: `ingredienser` mot `hemma`.
FALLBACK_JSON = ROOT / "frontend" / "app" / "data" / "recipes.json"
DB_PATH = ROOT / "backend" / "data" / "recipes.db"

# (recept-id, ingrediensens normaliserade id) -> (mängd, enhet, varifrån)
#
# Fyrtio rader som var märkta "antas finnas hemma" och som M3 flyttade till
# köpsidan. Trettiotre av dem kommer ur batch00_migrerade.json, där allt som
# inte rymdes i den gamla appens prislista hamnade i `hemma`.
MANGDER = {
    # Vitlök: bankens median och vanligaste mängd vid 4 portioner är 2 klyftor
    # (31 av 64 rader). Enheten är klyfta, inte st - se docs/changelog.d/C3.md:
    # "Vitlök 3 st" lästes som tre hela knoppar, 210 g.
    ("biffwok", "vitlok"): (2, "klyfta", "bankens vanligaste mängd vid 4 port (2 klyfta, 31 av 64)"),
    ("butterchicken", "vitlok"): (2, "klyfta", "bankens vanligaste mängd vid 4 port"),
    ("fetagryta", "vitlok"): (2, "klyfta", "bankens vanligaste mängd vid 4 port"),
    ("flasktomatpasta", "vitlok"): (2, "klyfta", "bankens vanligaste mängd vid 4 port"),
    ("halloumipasta", "vitlok"): (2, "klyfta", "bankens vanligaste mängd vid 4 port"),
    ("tofuwok", "vitlok"): (2, "klyfta", "bankens vanligaste mängd vid 4 port"),
    ("kottfarssas", "vitlok"): (2, "klyfta", "bankens vanligaste mängd vid 4 port"),
    ("tandoorikyckling", "vitlok"): (2, "klyfta", "bankens vanligaste mängd vid 4 port"),
    ("zucchinipastafeta", "vitlok"): (2, "klyfta", "bankens vanligaste mängd vid 4 port"),

    # Ägg, mjöl och ströbröd i de två kalvschnitzlarna är EN panering. Banken
    # panerar tre andra rätter vid 4 portioner: kycklingschnitzel 60 g/2 st/
    # 100 g, panerad-torsk-potatismos 50 g/2 st/80 g, stekt-sej-remoulad
    # 60 g/1 st/80 g. Medianen av de tre är 60 g mjöl, 2 ägg, 80 g ströbröd.
    ("kalvschnitzel", "vetemjol"): (60, "g", "bankens övriga paneringar vid 4 port"),
    ("kalvschnitzel", "agg"): (2, "st", "bankens övriga paneringar vid 4 port"),
    ("kalvschnitzel", "strobrod"): (80, "g", "bankens övriga paneringar vid 4 port"),
    ("kalvschnitzelmatvete", "vetemjol"): (60, "g", "bankens övriga paneringar vid 4 port"),
    ("kalvschnitzelmatvete", "agg"): (2, "st", "bankens övriga paneringar vid 4 port"),
    ("kalvschnitzelmatvete", "strobrod"): (80, "g", "bankens övriga paneringar vid 4 port"),

    # Lök: banken skriver "Gul lök 1 st" i 56 av 68 rader vid 4 portioner.
    ("currykottfarsgryta", "lok"): (1, "st", "bankens lökrader vid 4 port (1 st, 56 av 68)"),
    ("kottfarssas", "lok"): (1, "st", "bankens lökrader vid 4 port (1 st, 56 av 68)"),

    # Ris: syskonen i samma migrerade batch har 250 g vid 4 portioner
    # (currykottfarsgryta, tofuwok, teriyakilax, kikartscurry).
    ("butterchicken", "ris"): (250, "g", "syskonrätterna i batch00 (250 g vid 4 port)"),

    # Färsk ingefära vägs i gram. Banken har 20 g i 9 av 14 rader.
    ("biffwok", "ingefara"): (20, "g", "bankens vanligaste mängd (20 g, 9 av 14)"),
    ("butterchicken", "ingefara"): (20, "g", "bankens vanligaste mängd (20 g, 9 av 14)"),
    ("teriyakilax", "ingefara"): (20, "g", "bankens vanligaste mängd (20 g, 9 av 14)"),
    ("teriyakitofu", "ingefara"): (20, "g", "bankens vanligaste mängd (20 g, 9 av 14)"),

    # Honungen i teriyakiglasyren: receptet säger själv hur mycket. teriyakitofu
    # är samma glasyr på samma 30 ml soja och får samma mängd.
    ("teriyakilax", "honung"): (1, "tsk", "receptets egen text: \"en tesked honung\""),
    ("teriyakitofu", "honung"): (1, "tsk", "samma glasyr som teriyakilax"),

    # Buljong: sopporna i banken. Linssoppan har en tvilling, linssoppa-rod,
    # med 700 ml. Tomatsoppan ligger mellan tomatsoppa-grillost (400 ml) och
    # bonsoppa-tomat (600 ml) och får 500 ml.
    ("tomatsoppa", "buljong"): (500, "ml", "bankens tomatsoppor (400-600 ml vid 4 port)"),
    ("linssoppa", "buljong"): (700, "ml", "linssoppa-rod, samma soppa i banken"),

    # Örter, ost, frön och sirap: bankens egen median för ingrediensen.
    ("flaskkarre", "timjan"): (5, "g", "bankens median (5 g)"),
    ("scampi", "persilja"): (20, "g", "bankens vanligaste mängd (20 g, 9 av 15)"),
    ("sparrispastacitron", "parmesan"): (60, "g", "bankens median (60 g)"),
    ("tofuwok", "sesamfron"): (20, "g", "bankens vanligaste mängd (20 g, 4 av 5)"),
    ("torskitomatsas", "basilika"): (1, "st", "bankens vanligaste mängd (1 st kruka, 5 av 7)"),
    ("fetapasta", "basilika"): (1, "st", "bankens vanligaste mängd (1 st kruka, 5 av 7)"),
    ("vitkalssoppa-fars", "sirap"): (1, "msk", "receptets egen text: \"en matsked sirap\""),

    # Paprikapulver och oregano prissätts i de flesta av bankens rader, och
    # minoriteten utan mängd är felet. 10 g respektive 5 g är vad banken
    # skriver i sina andra rader vid 4 portioner.
    ("kycklingmatvete", "paprikapulver"): (10, "g", "bankens vanligaste mängd vid 4 port"),
    ("tacos-kottfars", "paprikapulver"): (10, "g", "bankens vanligaste mängd vid 4 port"),
    ("korvgryta-potatis", "paprikapulver"): (10, "g", "bankens vanligaste mängd vid 4 port"),
    ("svarta-bonor-tacos", "paprikapulver"): (10, "g", "bankens vanligaste mängd vid 4 port"),
    ("spaghetti-kottfarssas", "oregano"): (5, "g", "bankens oreganorader (5 g i 8 av 9)"),
    ("lasagne-klassisk", "oregano"): (5, "g", "bankens oreganorader (5 g i 8 av 9)"),
    ("linsbolognese-proteinrik", "oregano"): (5, "g", "bankens oreganorader (5 g i 8 av 9)"),
}


def source_files() -> list[Path]:
    return sorted(SOURCE_DIR.glob("*.json"))


def load_sources() -> list[tuple[Path, list]]:
    return [(path, json.loads(path.read_text(encoding="utf-8"))) for path in source_files()]


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def granska_rad(recipe_id: str, ingredient: dict) -> str:
    """Vad som är fel med raden, eller tom sträng om den stämmer med listan."""
    namn = ingredient.get("name") or ""
    skafferi = bool(ingredient.get("pantryStaple"))
    ska_vara = is_pantry_staple(namn)
    har_mangd = ingredient.get("amount") is not None
    if skafferi and not ska_vara:
        return (f"{namn}: märkt skafferivara men står inte i PANTRY_STAPLES - "
                f"ska prissättas och ha en mängd")
    if ska_vara and not skafferi:
        return f"{namn}: ska vara skafferivara ({reason(namn)})"
    if ska_vara and har_mangd:
        return f"{namn}: skafferirad med mängd - skafferiraderna bär ingen mängd"
    if not ska_vara and not har_mangd:
        return f"{namn}: köpvara utan mängd - en rad utan mängd går inte att prissätta"
    return ""


def granska() -> list[str]:
    problem = []
    for path, recipes in load_sources():
        for recipe in recipes:
            for ingredient in recipe.get("ingredients") or []:
                fel = granska_rad(recipe.get("id"), ingredient)
                if fel:
                    problem.append(f"{path.name} / {recipe.get('id')}: {fel}")
    for rad in granska_fallback():
        problem.append(rad)
    return problem


def granska_fallback() -> list[str]:
    """Reservbanken bär samma distinktion som `ingredienser` mot `hemma`."""
    if not FALLBACK_JSON.exists():
        return []
    problem = []
    for recipe in json.loads(FALLBACK_JSON.read_text(encoding="utf-8")):
        for namn in recipe.get("hemma") or []:
            if not is_pantry_staple(namn):
                problem.append(f"reservbanken / {recipe.get('id')}: {namn} ligger i "
                               f"hemma men är en vara man köper")
        for namn in recipe.get("ingredienser") or []:
            if is_pantry_staple(namn):
                problem.append(f"reservbanken / {recipe.get('id')}: {namn} ligger i "
                               f"ingredienser men antas finnas hemma")
    return problem


class SaknadMangd(SystemExit):
    """En rad ska bli köpvara men skriptet har ingen mängd för den."""


def ratta_rad(recipe_id: str, ingredient: dict) -> bool:
    """Rättar en ingrediensrad på plats. True om något ändrades."""
    namn = ingredient.get("name") or ""
    nyckel = (recipe_id, normalize_ingredient_id(namn))
    ska_vara = is_pantry_staple(namn)
    andrad = False

    if ska_vara:
        if not ingredient.get("pantryStaple"):
            ingredient["pantryStaple"] = True
            andrad = True
        # Skafferiraden bär ingen mängd: frontend läser `rows.home` som en
        # ren namnlista (services/assumed-home.js), och prissättningen hoppar
        # över raden ändå. En mängd som ingen visar och ingen räknar på är en
        # uppgift som tyst kan bli fel. Fälten tas BORT, inte nollställs -
        # bankens skafferirader är `{"name": "Salt", "pantryStaple": true}`
        # och en ny sort med `"amount": null` hade varit en tredje form att
        # hålla reda på.
        for falt in ("amount", "unit"):
            if ingredient.pop(falt, None) is not None:
                andrad = True
        return andrad

    if ingredient.get("pantryStaple"):
        ingredient.pop("pantryStaple")
        andrad = True
    if ingredient.get("amount") is None:
        if nyckel not in MANGDER:
            raise SaknadMangd(
                f"{recipe_id}: {namn} ska bli köpvara men saknar mängd, och "
                f"MANGDER i {Path(__file__).name} har ingen rad för "
                f"{nyckel}. Lägg in mängden med var den är hämtad ifrån - "
                f"gissa den inte här.")
        amount, unit, _ = MANGDER[nyckel]
        ingredient["amount"], ingredient["unit"] = amount, unit
        andrad = True
    return andrad


def apply_to_sources() -> int:
    andrade = 0
    for path, recipes in load_sources():
        dirty = False
        for recipe in recipes:
            for ingredient in recipe.get("ingredients") or []:
                if ratta_rad(recipe.get("id"), ingredient):
                    dirty, andrade = True, andrade + 1
        if dirty:
            write_json(path, recipes)
    return andrade


def apply_to_fallback() -> int:
    """Flyttar namn mellan `hemma` och `ingredienser` i reservbanken.

    Reservbanken har inga mängder - ett namn i `ingredienser` är hela
    uppgiften - så här räcker det att namnet hamnar på rätt sida. Utan den
    här halvan skulle ett backendavbrott ge en inköpslista utan ägg för
    precis de recept M3 rättade."""
    if not FALLBACK_JSON.exists():
        return 0
    recipes = json.loads(FALLBACK_JSON.read_text(encoding="utf-8"))
    andrade = 0
    for recipe in recipes:
        hemma = list(recipe.get("hemma") or [])
        kop = list(recipe.get("ingredienser") or [])
        nya_hemma = [n for n in hemma if is_pantry_staple(n)]
        nya_hemma += [n for n in kop if is_pantry_staple(n)]
        nya_kop = [n for n in kop if not is_pantry_staple(n)]
        nya_kop += [n for n in hemma if not is_pantry_staple(n)]
        if nya_hemma != hemma or nya_kop != kop:
            andrade += len(set(hemma) ^ set(nya_hemma))
            if "ingredienser" in recipe:
                recipe["ingredienser"] = nya_kop
            if "hemma" in recipe:
                recipe["hemma"] = nya_hemma
    if andrade:
        write_json(FALLBACK_JSON, recipes)
    return andrade


def apply_to_db(db_path: Path) -> int:
    """Stämplar en redan driftsatt databas utan att vänta på en omimport.

    Flaggan går att sätta här; mängderna gör det inte - de bor i källorna och
    kommer in med nästa import. Raderna som saknar mängd listas därför i
    stället för att gissas."""
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    andrade = 0
    try:
        rader = connection.execute(
            "SELECT recipe_id, position, name, amount, pantry_staple "
            "FROM recipe_ingredients").fetchall()
        saknar_mangd = []
        for rad in rader:
            ska_vara = int(is_pantry_staple(rad["name"]))
            behov = {}
            if rad["pantry_staple"] != ska_vara:
                behov["pantry_staple"] = ska_vara
            if ska_vara and rad["amount"] is not None:
                behov["amount"] = None
                behov["unit"] = None
            if not ska_vara and rad["amount"] is None:
                saknar_mangd.append(f"{rad['recipe_id']}: {rad['name']}")
            if behov:
                satser = ", ".join(f"{k} = ?" for k in behov)
                connection.execute(
                    f"UPDATE recipe_ingredients SET {satser} "
                    f"WHERE recipe_id = ? AND position = ?",
                    (*behov.values(), rad["recipe_id"], rad["position"]))
                andrade += 1
        connection.commit()
        if saknar_mangd:
            print(f"\n{len(saknar_mangd)} köpvarurader saknar mängd i databasen. "
                  f"Mängderna bor i källorna - kör importen:")
            for rad in saknar_mangd[:20]:
                print("   ", rad)
    finally:
        connection.close()
    return andrade


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skriv", action="store_true",
                        help="rätta receptkällorna och reservbanken")
    parser.add_argument("--kontrollera", action="store_true",
                        help="avsluta med felkod om något avviker från listan")
    parser.add_argument("--db", type=Path, nargs="?", const=DB_PATH,
                        help="stämpla flaggan i en redan byggd databas")
    args = parser.parse_args(argv)

    if args.db:
        andrade = apply_to_db(args.db)
        print(f"{args.db}: {andrade} rader stämplade.")
        return 0

    if args.skriv:
        i_kallor = apply_to_sources()
        i_reserv = apply_to_fallback()
        print(f"Källorna: {i_kallor} ingrediensrader rättade.")
        print(f"Reservbanken: {i_reserv} namn flyttade.")
        kvar = granska()
        for rad in kvar:
            print("  KVAR:", rad)
        return 1 if kvar else 0

    problem = granska()
    if not problem:
        print("Varje ingrediens har samma skafferiklassning i alla recept.")
        return 0
    print(f"{len(problem)} rader avviker från services/recipes/pantry.py:\n")
    for rad in problem:
        print("  ", rad)
    print("\nKör med --skriv för att rätta källorna.")
    return 1 if args.kontrollera else 0


if __name__ == "__main__":
    raise SystemExit(main())
