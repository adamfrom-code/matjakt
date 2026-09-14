# -*- coding: utf-8 -*-
"""Slår ihop `categories` och `tags` till ETT etikettfält - och håller det så.

    backend/venv/bin/python backend/scripts/normalize_recipe_labels.py
    backend/venv/bin/python backend/scripts/normalize_recipe_labels.py --kontrollera
    backend/venv/bin/python backend/scripts/normalize_recipe_labels.py --skriv
    backend/venv/bin/python backend/scripts/normalize_recipe_labels.py --db

Facit är `services/recipes/labels.py`: en etikett har en NYCKEL (gemen, utan
diakriter) och ett NAMN (läsbart, härlett ur nyckeln). Det här skriptet skriver
om receptkällorna till det ena fältet `labels`, och kan stämpla en redan byggd
databas.

ORDNINGEN ÄR DATA, INTE PYNT. Före M4 lästes etiketterna med `ORDER BY kind,
value`, och 'categories' < 'tags', så kategorierna kom först - i den ordningen
har appen visat sin badge (`categories[0]` blir `typ` i frontendens
receptmodell). Sammanslagningen väver därför `sorted(categories)` före
`sorted(tags)`, exakt samma ordning som databasen gav, och ett test håller kvar
att varje recept har samma första namn efter migreringen som före. En
etikettstädning får inte byta text på ett receptkort.

INGENTING KASTAS. En etikett som bara fanns i det ena fältet följer med; en som
fanns i båda blir en. `granska()` räknar upp båda halvorna av det, och
`--kontrollera` är vad testet kör.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from services.recipes.labels import (  # noqa: E402
    LABELS, LEGACY_KINDS, display, merge, normalize_label_id)

SOURCE_DIR = ROOT / "backend" / "recipe_sources"
DB_PATH = ROOT / "backend" / "data" / "recipes.db"


def source_files() -> list[Path]:
    return sorted(SOURCE_DIR.glob("*.json"))


def load_sources() -> list[tuple[Path, list]]:
    return [(path, json.loads(path.read_text(encoding="utf-8"))) for path in source_files()]


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def sammanslagna(recipe: dict) -> list[str]:
    """Receptets etiketter som EN lista nycklar, i den ordning banken gav dem.

    `sorted()` på varje halva för sig återskapar `ORDER BY kind, value`:
    SQLite jämför strängar byte för byte i UTF-8, vilket är samma ordning som
    Pythons kodpunktsordning."""
    return merge(recipe.get(LABELS),
                 sorted(recipe.get("categories") or []),
                 sorted(recipe.get("tags") or []))


def granska_recept(recipe: dict) -> list[str]:
    """Vad som avviker från det ena fältet. Tom lista när receptet är i mål."""
    fel = []
    rid = recipe.get("id")
    for gammalt in LEGACY_KINDS:
        if recipe.get(gammalt):
            fel.append(f"{rid}: har kvar fältet `{gammalt}` - "
                       f"{len(recipe[gammalt])} etiketter som hör hemma i `labels`")
    etiketter = recipe.get(LABELS)
    if not etiketter:
        if not any(recipe.get(k) for k in LEGACY_KINDS):
            fel.append(f"{rid}: saknar etiketter helt")
        return fel
    for value in etiketter:
        if not isinstance(value, str):
            fel.append(f"{rid}: etiketten {value!r} är inte en sträng")
        elif normalize_label_id(value) != value:
            fel.append(f"{rid}: etiketten {value!r} är inte i nyckelform "
                       f"(ska vara {normalize_label_id(value)!r})")
    if len(set(etiketter)) != len(etiketter):
        fel.append(f"{rid}: samma etikett förekommer två gånger i `labels`")
    return fel


def granska() -> list[str]:
    problem = []
    for path, recipes in load_sources():
        for recipe in recipes:
            problem.extend(f"{path.name} / {rad}" for rad in granska_recept(recipe))
    return problem


def forsta_namnet(recipe: dict) -> str:
    """Badgen appen visar på kortet: `categories[0]` före, `labels[0]` efter."""
    if recipe.get("categories"):
        return sorted(recipe["categories"])[0]
    etiketter = sammanslagna(recipe)
    return display(etiketter[0]) if etiketter else ""


def apply_to_sources() -> tuple[int, int]:
    """Skriver om källorna till det ena fältet. (ändrade recept, borttagna dubbletter)"""
    andrade = sparade = 0
    for path, recipes in load_sources():
        dirty = False
        for recipe in recipes:
            fore = len(recipe.get("categories") or []) + len(recipe.get("tags") or [])
            etiketter = sammanslagna(recipe)
            if recipe.get(LABELS) == etiketter and not any(
                    recipe.get(k) for k in LEGACY_KINDS):
                continue
            for gammalt in LEGACY_KINDS:
                recipe.pop(gammalt, None)
            recipe[LABELS] = etiketter
            sparade += max(fore - len(etiketter), 0)
            andrade += 1
            dirty = True
        if dirty:
            write_json(path, recipes)
    return andrade, sparade


def apply_to_db(db_path: Path) -> int:
    """Stämplar en redan byggd bank utan att vänta på en omimport.

    `RecipeStore` gör samma sak när den öppnar databasen (`_merge_legacy_labels`),
    så det här är en genväg för den som vill se resultatet direkt - inte den
    enda vägen."""
    sys.path.insert(0, str(ROOT / "backend"))
    from services.recipes.store import RecipeStore
    store = RecipeStore(db_path)
    try:
        return store.connection.execute(
            f"SELECT COUNT(*) FROM recipe_labels WHERE kind = '{LABELS}'").fetchone()[0]
    finally:
        store.close()


def rapport() -> None:
    """Vad sammanslagningen gör med filtren - siffror, inte påståenden."""
    per_nyckel: dict[str, set] = {}
    per_strang: dict[str, set] = {}
    for _, recipes in load_sources():
        for recipe in recipes:
            for gammalt in LEGACY_KINDS:
                for value in recipe.get(gammalt) or []:
                    per_strang.setdefault(value, set()).add(recipe["id"])
                    per_nyckel.setdefault(normalize_label_id(value), set()).add(recipe["id"])
            for value in recipe.get(LABELS) or []:
                per_strang.setdefault(value, set()).add(recipe["id"])
                per_nyckel.setdefault(normalize_label_id(value), set()).add(recipe["id"])
    print(f"{len(per_nyckel)} etiketter, {len(per_strang)} skrivningar av dem.\n")
    print(f"{'etikett':>18}  {'recept':>6}   skrivningar (och vad var och en gav)")
    for key in sorted(per_nyckel, key=lambda k: -len(per_nyckel[k])):
        former = sorted(s for s in per_strang if normalize_label_id(s) == key)
        delar = ", ".join(f"{s!r}={len(per_strang[s])}" for s in former)
        marke = "  <-- två skrivningar" if len(former) > 1 else ""
        print(f"{display(key):>18}  {len(per_nyckel[key]):>6}   {delar}{marke}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skriv", action="store_true", help="skriv om receptkällorna")
    parser.add_argument("--kontrollera", action="store_true",
                        help="avsluta med felkod om något avviker")
    parser.add_argument("--rapport", action="store_true",
                        help="visa varje etikett, dess skrivningar och vad de ger")
    parser.add_argument("--db", type=Path, nargs="?", const=DB_PATH,
                        help="slå ihop etiketterna i en redan byggd databas")
    args = parser.parse_args(argv)

    if args.rapport:
        rapport()
        return 0

    if args.db:
        print(f"{args.db}: {apply_to_db(args.db)} etikettrader i det ena fältet.")
        return 0

    if args.skriv:
        andrade, sparade = apply_to_sources()
        print(f"Källorna: {andrade} recept skrivna till ett fält, "
              f"{sparade} dubbletter sammanslagna.")
        kvar = granska()
        for rad in kvar:
            print("  KVAR:", rad)
        return 1 if kvar else 0

    problem = granska()
    if not problem:
        print("Varje recept har ETT etikettfält, och varje etikett är i nyckelform.")
        return 0
    print(f"{len(problem)} avvikelser från services/recipes/labels.py:\n")
    for rad in problem[:40]:
        print("  ", rad)
    if len(problem) > 40:
        print(f"   ... och {len(problem) - 40} till")
    print("\nKör med --skriv för att slå ihop fälten.")
    return 1 if args.kontrollera else 0


if __name__ == "__main__":
    raise SystemExit(main())
