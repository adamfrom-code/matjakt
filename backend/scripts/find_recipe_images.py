# -*- coding: utf-8 -*-
"""Finds freely licensed recipe photos on Wikimedia Commons.

    python backend/scripts/find_recipe_images.py --search "lentil soup" --limit 6
    python backend/scripts/find_recipe_images.py --download File:Foo.jpg --as linssoppa

Keeps the sourcing rule the recipe images already follow (see
frontend/app/assets/recipes/CREDITS.md): Wikimedia Commons, a free licence,
credited by name, nothing AI-generated. This just makes finding and crediting
them repeatable instead of manual.

Candidates are ranked by pixel size, because the failure mode with the
existing photos is not licensing - it is that several are small, flash-lit
home snapshots. A large, well-exposed photo is not guaranteed to be
appetising, so the picking is still done by eye; this only narrows the field.
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

API = "https://commons.wikimedia.org/w/api.php"
UA = "Matjakt/1.0 (recipe image sourcing; adamfrom@icloud.com)"
RECIPES_DIR = Path(__file__).resolve().parents[2] / "frontend" / "app" / "assets" / "recipes"

# Licences we will actually ship. Everything else is skipped rather than
# used and apologised for later.
ALLOWED = ("cc0", "public domain", "cc by", "cc-by")
FORBIDDEN = ("nc", "nd", "fair use", "non-free")


def _get(params):
    url = f"{API}?{urllib.parse.urlencode({**params, 'format': 'json'})}"
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def _clean(html):
    return re.sub(r"<[^>]+>", "", html or "").strip()


def licence_ok(name):
    lowered = (name or "").lower()
    if any(bad in lowered for bad in FORBIDDEN):
        return False
    return any(good in lowered for good in ALLOWED)


def search(term, limit=8):
    data = _get({
        "action": "query", "generator": "search", "gsrsearch": f"filetype:bitmap {term}",
        "gsrnamespace": "6", "gsrlimit": str(limit * 3),
        "prop": "imageinfo", "iiprop": "url|size|extmetadata",
    })
    pages = (data.get("query") or {}).get("pages") or {}
    results = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        licence = _clean((meta.get("LicenseShortName") or {}).get("value"))
        if not licence_ok(licence):
            continue
        width, height = info.get("width", 0), info.get("height", 0)
        if width < 900 or height < 600:
            continue  # too small to look good on a phone card
        results.append({
            "title": page.get("title"),
            "url": info.get("url"),
            "descriptionUrl": info.get("descriptionurl"),
            "width": width, "height": height,
            "licence": licence,
            "author": _clean((meta.get("Artist") or {}).get("value"))[:60],
        })
    results.sort(key=lambda r: r["width"] * r["height"], reverse=True)
    return results[:limit]


def download(title, target_name):
    data = _get({"action": "query", "titles": title, "prop": "imageinfo",
                 "iiprop": "url|size|extmetadata", "iiurlwidth": "1200"})
    page = next(iter((data.get("query") or {}).get("pages", {}).values()), {})
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata") or {}
    licence = _clean((meta.get("LicenseShortName") or {}).get("value"))
    if not licence_ok(licence):
        raise SystemExit(f"Vägrar: licensen {licence!r} är inte fri nog att skeppa")
    # The 1200px thumbnail, not the original: a 6 MB source photo on a phone
    # card is bandwidth nobody asked for.
    source = info.get("thumburl") or info.get("url")
    request = urllib.request.Request(source, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=60) as response:
        blob = response.read()
    path = RECIPES_DIR / f"{target_name}.jpg"
    path.write_bytes(blob)
    print(f"{path.name}: {len(blob) // 1024} kB, {licence}, {_clean((meta.get('Artist') or {}).get('value'))[:50]}")
    print(f"CREDITS-rad: | {path.name} | {_clean((meta.get('Artist') or {}).get('value'))[:50]} | "
          f"{licence} | {info.get('descriptionurl')} |")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--search")
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--download")
    parser.add_argument("--as", dest="target")
    args = parser.parse_args()

    if args.download:
        if not args.target:
            raise SystemExit("--download kräver --as <receptid>")
        download(args.download, args.target)
    elif args.search:
        for hit in search(args.search, args.limit):
            print(f"\n{hit['title']}")
            print(f"  {hit['width']}x{hit['height']}  {hit['licence']}  {hit['author']}")
            print(f"  {hit['url']}")
    else:
        parser.error("ange --search eller --download")
