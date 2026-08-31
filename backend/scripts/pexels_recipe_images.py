# -*- coding: utf-8 -*-
"""Sources appetising recipe photography from Pexels.

    python backend/scripts/pexels_recipe_images.py --check
    python backend/scripts/pexels_recipe_images.py --preview kycklinggryta
    python backend/scripts/pexels_recipe_images.py --fetch kycklinggryta linssoppa
    python backend/scripts/pexels_recipe_images.py --fetch-all

WHY NOT WIKIMEDIA COMMONS, WHICH THE EXISTING IMAGES USE
Commons is an encyclopedia media archive, not a food-photography library.
Reviewing its candidates for these dishes turned up flash-lit home snapshots
on patterned tablecloths, several of them of the wrong dish (the lentil soup
photo is a quinoa soup). Only 5 of the 58 existing images are technically
small - the problem is not resolution, it is that none of them make a person
want to cook the dish. Openverse without a key returns effectively only
Commons, and Flickr is no longer one of its sources.

Pexels photos are free for commercial use and attribution is not required.
We record the photographer in CREDITS.md anyway: it costs nothing, it is the
decent thing to do, and it keeps one honest record of where every image came
from.

The key is read from the environment (PEXELS_API_KEY, via .env) and never
committed.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

RECIPES_JSON = ROOT / "frontend" / "app" / "data" / "recipes.json"
IMAGES_DIR = ROOT / "frontend" / "app" / "assets" / "recipes"
CREDITS = IMAGES_DIR / "CREDITS.md"
API = "https://api.pexels.com/v1/search"

# What to actually search for. The recipe names are Swedish and Pexels is
# indexed in English, so a literal name search returns nothing useful -
# "Korvgratäng med pasta" finds no photos, "sausage pasta bake" finds many.
# Written per dish rather than machine-translated: the point is a photo that
# looks like THIS dish, and only a person reading the ingredients can judge
# which English words get there.
SEARCH_TERMS = {
    "kycklinggryta": "creamy chicken curry rice bowl",
    "pastagratang": "baked pasta gratin cheese dish",
    "linssoppa": "red lentil soup bowl rustic",
    "korvstroganoff": "sausage stroganoff rice creamy",
    "tacobonor": "taco bowl black beans rice",
    "fiskpasta": "creamy salmon pasta plate",
    "lax": "baked salmon fillet potatoes dill",
    "halloumibowl": "grilled halloumi bowl salad",
    "chili": "chili con carne bowl beans",
    "kycklingwok": "chicken noodle stir fry wok",
    "tomatsoppa": "creamy tomato soup bowl bread",
    "pannkakor": "swedish pancakes berries jam",
    "kottbullar": "swedish meatballs mashed potatoes lingonberry",
    "vegetarisklasagne": "vegetable lasagna slice plate",
    "kikartscurry": "chickpea curry rice bowl",
    "flaskfilerotmos": "pork tenderloin root vegetable mash",
    "korvgratang": "sausage pasta bake casserole",
    "fiskgratang": "fish gratin bake creamy",
    "kycklingcouscous": "roast chicken couscous peppers",
    "butterchicken": "butter chicken curry naan",
    "kottfarssas": "bolognese sauce pasta plate",
    "raksallad": "prawn salad bowl fresh",
    "rakcurry": "prawn curry coconut rice",
    "citronkyckling": "lemon chicken roasted",
    "flaskkarre": "pork neck steak plate",
    "halloumipasta": "halloumi pasta tomato",
    "fetapasta": "baked feta pasta tomatoes",
    "kikartssallad": "chickpea salad bowl herbs",
    "bonbowlmatvete": "bean bowl grain salsa",
    "flasktomatpasta": "pork tomato pasta plate",
}

# Everything not listed above falls back to a generic but still useful query
# built from the dish's protein source, so --fetch-all never searches for a
# Swedish word Pexels has never seen.
FALLBACK_BY_PROTEIN = {
    "kyckling": "chicken dinner plate homemade",
    "flask": "pork dinner plate homemade",
    "notkott": "beef dinner plate homemade",
    "kott": "meat dinner plate homemade",
    "fisk": "fish dinner plate homemade",
    "vegetariskt": "vegetarian dinner plate colourful",
    "veganskt": "vegan dinner bowl colourful",
}


def api_key():
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        # .env is how this project already carries local secrets.
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("PEXELS_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
    return key


def search(term, key, per_page=5):
    url = f"{API}?{urllib.parse.urlencode({'query': term, 'per_page': per_page, 'orientation': 'landscape', 'size': 'large'})}"
    request = urllib.request.Request(url, headers={"Authorization": key,
                                                   "User-Agent": "Matjakt/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read()).get("photos", [])


def term_for(recipe):
    return (SEARCH_TERMS.get(recipe["id"])
            or FALLBACK_BY_PROTEIN.get(recipe.get("proteinkalla"))
            or "home cooked dinner plate")


def fetch_one(recipe, key, preview=False):
    term = term_for(recipe)
    photos = search(term, key)
    if not photos:
        print(f"  ❌ {recipe['id']:22} inga träffar för {term!r}")
        return None
    photo = photos[0]
    if preview:
        for index, candidate in enumerate(photos):
            print(f"  {index}: {candidate['photographer']:24} {candidate['width']}x{candidate['height']}"
                  f"  {candidate['url']}")
        return None
    # "large" is 940px wide - plenty for a phone card, and a fraction of the
    # original's weight.
    source = photo["src"].get("large") or photo["src"].get("original")
    request = urllib.request.Request(source, headers={"User-Agent": "Matjakt/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        blob = response.read()
    path = IMAGES_DIR / f"{recipe['id']}.jpg"
    path.write_bytes(blob)
    print(f"  ✅ {recipe['id']:22} {len(blob)//1024:4} kB  {photo['photographer']}")
    return {"file": path.name, "photographer": photo["photographer"],
            "url": photo["url"], "term": term}


def write_credits(entries):
    """Rewrites the Pexels section of CREDITS.md, leaving the Wikimedia rows
    for any image still sourced there."""
    header = ("\n## Pexels\n\n"
              "Fotografier från [Pexels](https://www.pexels.com). Pexels-licensen tillåter "
              "kommersiell användning utan attribution; fotograferna namnges ändå.\n"
              "Ingen bild är AI-genererad.\n\n"
              "| Fil | Fotograf | Källa |\n| --- | --- | --- |\n")
    rows = "".join(f"| {e['file']} | {e['photographer']} | {e['url']} |\n" for e in entries)
    text = CREDITS.read_text(encoding="utf-8")
    marker = "\n## Pexels\n"
    if marker in text:
        text = text[:text.index(marker)]
    CREDITS.write_text(text.rstrip() + "\n" + header + rows, encoding="utf-8")
    print(f"\nCREDITS.md uppdaterad med {len(entries)} rader")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verifiera att nyckeln fungerar")
    parser.add_argument("--preview", help="Visa kandidater för ett recept utan att hämta")
    parser.add_argument("--fetch", nargs="*", help="Hämta bild för angivna recept-id")
    parser.add_argument("--fetch-all", action="store_true")
    args = parser.parse_args()

    key = api_key()
    if not key:
        raise SystemExit(
            "PEXELS_API_KEY saknas.\n"
            "Hämta en gratisnyckel på https://www.pexels.com/api/ och lägg den i .env:\n"
            '  echo "PEXELS_API_KEY=din-nyckel" >> .env')

    if args.check:
        photos = search("chicken curry", key, per_page=1)
        print(f"Nyckeln fungerar. Exempelträff: {photos[0]['photographer'] if photos else 'inga'}")
        return 0

    recipes = json.loads(RECIPES_JSON.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in recipes}

    if args.preview:
        recipe = by_id.get(args.preview)
        if not recipe:
            raise SystemExit(f"Okänt recept: {args.preview}")
        print(f"Söker: {term_for(recipe)!r}")
        fetch_one(recipe, key, preview=True)
        return 0

    targets = recipes if args.fetch_all else [by_id[i] for i in (args.fetch or []) if i in by_id]
    if not targets:
        raise SystemExit("Ange --fetch <id> ... eller --fetch-all")

    entries = []
    for recipe in targets:
        try:
            entry = fetch_one(recipe, key)
            if entry:
                entries.append(entry)
        except urllib.error.HTTPError as error:
            print(f"  ❌ {recipe['id']:22} HTTP {error.code}")
            if error.code == 429:
                print("     Pexels rate limit - vänta och kör igen för resterande.")
                break
    if entries:
        write_credits(entries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
