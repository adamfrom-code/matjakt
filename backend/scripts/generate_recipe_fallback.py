# -*- coding: utf-8 -*-
"""Bygger reservbanken ur samma kod som backenden.

    python backend/scripts/generate_recipe_fallback.py          # skriver
    python backend/scripts/generate_recipe_fallback.py --check  # jämför

P03a. `frontend/app/data/recipes.json` är vad appen visar när backenden
inte svarar - eller svarar med en tom lista. Den bar 58 recept i appens
egen svenska form (`namn`, `bild`, `tid`), redigerade för hand, och alla 58
skilde sig från källorna i backend/recipe_sources/: kcal upp till 271 fel,
en ugnstemperatur på 200 °C där källan säger 175, en fläskkarré som i
källan är en fläskfilé. Samma recept-id, två sanningar - och den som
visades vid ett avbrott var den felaktiga.

Det här skriptet tar bort den andra sanningen genom att aldrig skapa den.
Reservbanken byggs av:

  1. samma importslinga som servern kör vid start (api.import_sources),
  2. in i en riktig RecipeStore (tillfällig fil, samma schema, samma
     migreringar),
  3. och dumpas med samma _to_dict som /api/recipes svarar med.

Filen är alltså API-FORMEN, inte appens. Appen översätter den med samma
fromApi() som den översätter serversvaret med. Det finns därmed en enda
översättning, och den kan inte glida.

Volatila fält tas bort så att två körningar av samma källor ger samma
bytes: tidsstämplar (created/updated) och prisfälten, som i en färsk bank
alltid är None och i produktion sätts av en prissättningskörning - de hör
inte hemma i en fil som ska vara deterministisk.

Testet test_receptsanningen kör --check i CI. Ändras källorna utan att
filen genereras om blir bygget rött med kommandot i felmeddelandet.
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UT = ROOT / "frontend" / "app" / "data" / "recipes.json"

# Fält som varierar mellan körningar eller sätts av drift, inte av källorna.
VOLATILA = ("createdAt", "updatedAt", "pricedAt", "pricePerPortion",
            "priceChain", "priceCovered", "priceTotal")


def bygg() -> list[dict]:
    """Källorna -> RecipeStore -> _to_dict, i den ordningen och ingen annan.

    Rör ALDRIG miljön. Första versionen satte MATJAKT_DATA_DIR till en ny
    tempkatalog här inne - och testsviten kör alla tester i en process, så
    varje test efter det här såg en annan datakatalog än den sviten ställt
    in. Fyra orelaterade tester föll. Katalogen LÄSES; den som anropar
    (main() eller sviten) ansvarar för att den är säker.
    """
    sys.path.insert(0, str(ROOT / "backend"))
    from services.recipes import api as recipes_api  # noqa: E402
    from services.recipes.store import RecipeStore  # noqa: E402

    katalog = Path(os.environ["MATJAKT_DATA_DIR"])
    # Egen fil per anrop, så två körningar i samma process (determinism-
    # testet) inte läser varandras rader. Städas i finally, inklusive WAL.
    db = katalog / f"reservbank-{os.getpid()}-{id(katalog)}.db"
    store = RecipeStore(db)
    try:
        recipes_api.import_sources(store)
        ids = [row["id"] for row in store.connection.execute("SELECT id FROM recipes ORDER BY id")]
        recept = []
        for recipe_id in ids:
            r = store.get(recipe_id)
            for fält in VOLATILA:
                r.pop(fält, None)
            recept.append(r)
        return recept
    finally:
        store.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                (db.parent / (db.name + suffix)).unlink()
            except FileNotFoundError:
                pass


def rendera(recept: list[dict]) -> str:
    # sort_keys + fast indrag: en ändring i ett recept ger en diff på det
    # receptet, inte på hela filen.
    return json.dumps(recept, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def main(argv=None) -> int:
    tolk = argparse.ArgumentParser(description="Bygg reservbanken ur källorna.")
    tolk.add_argument("--check", action="store_true",
                      help="skriv ingenting - avsluta med 1 om filen inte stämmer")
    arg = tolk.parse_args(argv)
    # Samma spärr som testsviten: pekar MATJAKT_DATA_DIR på en tempkatalog om
    # den inte redan är test-säker. Idempotent - inne i sviten återanvänds
    # svitens katalog och ingenting ändras. Importen får aldrig råka öppna
    # den riktiga databasen.
    sys.path.insert(0, str(ROOT / "backend"))
    from services.data_guard import isolated_test_data_dir  # noqa: E402
    isolated_test_data_dir()
    text = rendera(bygg())
    if arg.check:
        befintlig = UT.read_text(encoding="utf-8") if UT.exists() else ""
        if befintlig == text:
            print(f"reservbanken stämmer med källorna ({text.count(chr(10))} rader)")
            return 0
        print("reservbanken är INTE genererad ur dagens källor. Kör:\n"
              "  python backend/scripts/generate_recipe_fallback.py", file=sys.stderr)
        return 1
    UT.write_text(text, encoding="utf-8")
    antal = len(json.loads(text))
    print(f"skrev {UT.relative_to(ROOT)}: {antal} recept, {len(text.encode()) // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
