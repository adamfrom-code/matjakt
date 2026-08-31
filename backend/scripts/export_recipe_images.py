# -*- coding: utf-8 -*-
"""Skriver tillbaka bildmetadata från recipes.db till källfilerna.

The backfill finds images and stores them in the DATABASE - but production
BUILDS its database from the committed source JSON. An image that only lives
in a local recipes.db is an image that quietly disappears on the next
rebuild, which is exactly what happened: 126 recipes with licensed photos
locally, 73 after a re-import. This script closes that loop; run it after
every backfill, before committing.

    python backend/scripts/export_recipe_images.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from services.recipes.api import DB_PATH, RECIPE_SOURCE_DIR  # noqa: E402
from services.recipes.store import RecipeStore  # noqa: E402

IMAGE_FIELDS = ("image", "imageSource", "imageSourceUrl", "imageCredit",
                "imageLicense", "imageAlt", "imageStatus")


def main() -> int:
    store = RecipeStore(DB_PATH)
    updated = files = 0
    try:
        for path in sorted(RECIPE_SOURCE_DIR.glob("*.json")):
            recipes = json.loads(path.read_text(encoding="utf-8"))
            dirty = False
            for recipe in recipes:
                stored = store.get(recipe["id"])
                # Only a real, licensed find is worth exporting - a
                # placeholder would overwrite nothing with nothing.
                if not stored or stored.get("imageStatus") != "ok" or not stored.get("image"):
                    continue
                for field in IMAGE_FIELDS:
                    if recipe.get(field) != stored.get(field):
                        recipe[field] = stored.get(field)
                        dirty = True
                if dirty:
                    updated += 1
            if dirty:
                path.write_text(json.dumps(recipes, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")
                files += 1
    finally:
        store.close()
    print(f"{updated} recept uppdaterade i {files} källfiler")
    return 0


if __name__ == "__main__":
    sys.exit(main())
