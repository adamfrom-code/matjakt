# -*- coding: utf-8 -*-
"""Fyller receptbankens bilder automatiskt.

    set PEXELS_API_KEY=...
    python backend/scripts/backfill_recipe_images.py            # bara de som saknar bild
    python backend/scripts/backfill_recipe_images.py --all      # gör om alla
    python backend/scripts/backfill_recipe_images.py --dry-run  # visa utan att spara

Runs ONCE, here - never while a user is looking at the app. Each recipe gets
a search phrase built from its own name, the best licensed candidate that
clearly shows the dish, and the photographer and source stored alongside it.

A recipe that gets no confident match keeps needs_image rather than being
given a picture of something else. That is the whole point: a photo of the
wrong food is worse than no photo.

The API key is read from PEXELS_API_KEY and never printed, never written to a
file, and never stored in the recipe data.
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from services.recipes import RecipeStore  # noqa: E402
from services.recipes.images import build_query, find_image, pexels_key, placeholder  # noqa: E402

DB_PATH = ROOT / "backend" / "data" / "recipes.db"

# Pexels allows 200 requests an hour on the free tier. A recipe uses one to
# three searches, so a small pause keeps a 200-recipe run inside that without
# anyone having to think about it.
PAUSE_SECONDS = 0.4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Sök om även recept som redan har bild")
    parser.add_argument("--dry-run", action="store_true", help="Visa vad som skulle sparas")
    parser.add_argument("--limit", type=int, help="Max antal recept den här körningen")
    args = parser.parse_args()

    has_pexels = bool(pexels_key())
    print(f"Bildkällor: {'Pexels + ' if has_pexels else ''}Wikimedia Commons")
    if not has_pexels:
        print("  (PEXELS_API_KEY är inte satt - kör med bara Commons, som är hobbyfoto)")

    store = RecipeStore(DB_PATH)
    try:
        recipes = store.search(limit=5000)
        targets = [r for r in recipes if args.all or r.get("imageStatus") != "ok" or not r.get("image")]
        if args.limit:
            targets = targets[:args.limit]
        # Never reuse a picture: the same generic photo across eight recipes
        # reads as stock filler.
        used = {r["image"] for r in recipes if r.get("image") and r not in targets}

        found = missing = 0
        for index, recipe in enumerate(targets, 1):
            image = find_image(recipe, used)
            if image:
                used.add(image["image"])
                found += 1
                source = image["imageSource"]
                print(f"  [{index}/{len(targets)}] {recipe['name'][:40]:40} {source:16} "
                      f"{image['imageTitle'][:36]}")
            else:
                missing += 1
                image = placeholder(recipe)
                print(f"  [{index}/{len(targets)}] {recipe['name'][:40]:40} needs_image      "
                      f"sökte: {', '.join(build_query(recipe)[:2])}")

            if not args.dry_run:
                full = store.get(recipe["id"])
                full.update({k: v for k, v in image.items()
                             if k not in ("imageTitle", "imageScore")})
                # to_dict returns nutrition nested; upsert wants it flat.
                full.update(full.pop("nutrition", {}) or {})
                store.upsert_recipe(full)
            time.sleep(PAUSE_SECONDS)

        stats = store.stats()
        print(f"\n{'=' * 60}")
        print(f"bild hittad {found}, needs_image {missing}")
        print(f"receptbanken: {stats['total']} recept, "
              f"{stats['withLicensedImage']} med licensierad bild, "
              f"{stats['needsImage']} saknar bild")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
