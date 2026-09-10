# -*- coding: utf-8 -*-
"""Normaliserar receptbankens "Vitlök N st" till klyftor.

    backend/venv/bin/python backend/scripts/migrate_vitloksklyftor.py --dry-run
    backend/venv/bin/python backend/scripts/migrate_vitloksklyftor.py
    backend/venv/bin/python backend/scripts/migrate_vitloksklyftor.py --db /sökväg/recipes.db

VARFÖR. Receptbanken skrev "Vitlök 3 st" och menade tre KLYFTOR. Prismotorns
styckvikttabell läste det som tre hela knoppar: 3 × 70 = 210 g. En vecka med
fem vitlöksrecept blev ~840 g vitlök - cirka 125 kr på en veckobudget som
skulle varit 15, och en påse som ruttnar i kylen. Ingen svensk husmansrätt
tar tre hela vitlöksknoppar.

VAD SOM ÄNDRAS. Bara enheten, bara på rader vars namn ÄR vitlök och vars
enhet är st. Mängden rörs inte: "3 st" blir "3 klyftor", inte "15 g" -
klyftan är måttet receptet menar, och prismotorn väger om den (5 g/klyfta,
KLYFT_VIKT_G i services/grocery/pricing.py).

VAD SOM INTE ÄNDRAS. Rader i gram ("Lök & vitlök 150 g"), rader utan enhet
(skafferivaror) och varje annan ingrediens. Skriptet är idempotent: en andra
körning hittar noll rader att ändra.

Receptkällorna i backend/recipe_sources/ bär redan klyftorna, så en ny bank
byggd ur dem är rätt från början. Det här skriptet finns för databaser som
redan är byggda - produktionens disk överlever varje deploy.
"""

import argparse
import sqlite3
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_DB = ROOT / "backend" / "data" / "recipes.db"

# Exakta namn, inte delsträngar: "Lök & vitlök" är en annan rad med en annan
# mängd och ska inte röras. Listan är folded (gemener, utan diakriter).
GARLIC_NAMES = frozenset({"vitlok"})

# Enheterna som betyder "styck" i receptbanken.
PIECE_UNITS = frozenset({"st", "styck"})

CLOVE_UNIT = "klyfta"


def _fold(text: str) -> str:
    """Samma veckning som prismotorn: gemener utan diakriter."""
    if not text:
        return ""
    lowered = str(text).lower().strip()
    return "".join(c for c in unicodedata.normalize("NFD", lowered)
                   if unicodedata.category(c) != "Mn")


def rows_to_migrate(connection) -> list[sqlite3.Row]:
    rows = connection.execute(
        "SELECT recipe_id, position, name, amount, unit FROM recipe_ingredients "
        "WHERE unit IS NOT NULL").fetchall()
    return [row for row in rows
            if _fold(row["name"]) in GARLIC_NAMES and _fold(row["unit"]) in PIECE_UNITS]


def migrate(db_path: Path, dry_run: bool = False) -> dict:
    """Returnerar {"found": n, "changed": n, "recipes": n} för logg och test."""
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        targets = rows_to_migrate(connection)
        recipes = {row["recipe_id"] for row in targets}
        if not targets or dry_run:
            return {"found": len(targets), "changed": 0, "recipes": len(recipes)}
        with connection:
            connection.executemany(
                "UPDATE recipe_ingredients SET unit = ? WHERE recipe_id = ? AND position = ?",
                [(CLOVE_UNIT, row["recipe_id"], row["position"]) for row in targets])
        return {"found": len(targets), "changed": len(targets), "recipes": len(recipes)}
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Sökväg till recipes.db")
    parser.add_argument("--dry-run", action="store_true",
                        help="Visa vad som skulle ändras, skriv ingenting")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"AVBRYTER: hittar ingen receptdatabas på {db_path}")
        return 2

    result = migrate(db_path, dry_run=args.dry_run)
    verb = "skulle ändras" if args.dry_run else "ändrade"
    print(f"vitlöksklyftor: {result['found']} rader i {result['recipes']} recept "
          f"{verb} från st till {CLOVE_UNIT}")
    if not result["found"]:
        print("Inget att göra - banken är redan normaliserad.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
