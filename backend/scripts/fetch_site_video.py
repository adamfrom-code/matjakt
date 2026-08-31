# -*- coding: utf-8 -*-
"""Hämtar klippen till landningssidans presentation.

Run once when the presentation changes, never while a visitor is on the site.
The landing page reads the manifest this writes; it never talks to Pexels.

    python backend/scripts/fetch_site_video.py

Nothing here prints the API key, and no clip is kept unless the manifest can
record where it came from.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from services.site import video  # noqa: E402


def main() -> int:
    if not video.pexels_key():
        print("PEXELS_API_KEY saknas. Sätt den i miljön eller .env och kör igen.")
        return 1

    video.CLIP_DIR.mkdir(parents=True, exist_ok=True)
    manifest, used_ids, used_slugs, total_bytes = {}, set(), [], 0

    for scene in video.SCENES:
        found = video.find_clip(scene, used_ids, used_slugs=used_slugs)
        if not found:
            # Said out loud rather than filled with something else. A scene
            # without a fitting clip falls back to a still on the page.
            print(f"  {scene['key']:<10} INGET KLIPP - scenen faller tillbaka på stillbild")
            manifest[scene["key"]] = {"sceneKey": scene["key"], "status": "needs_clip",
                                      "headline": scene["headline"],
                                      "caption": scene.get("caption", "")}
            continue

        used_ids.add(found["pexelsId"])
        used_slugs.append(set(video._slug_words(found["sourceUrl"])))
        stem = f"matjakt-{scene['key']}"
        clip_path = video.CLIP_DIR / f"{stem}.mp4"
        poster_path = video.CLIP_DIR / f"{stem}.jpg"

        size = video.download(found["downloadUrl"], clip_path)
        total_bytes += size
        if found.get("posterUrl"):
            total_bytes += video.download(found["posterUrl"], poster_path)

        entry = {k: v for k, v in found.items() if k != "downloadUrl"}
        entry.update({
            "status": "ok",
            "src": f"{video.WEB_PREFIX}/{stem}.mp4",
            "poster": f"{video.WEB_PREFIX}/{stem}.jpg",
            "bytes": size,
            "headline": scene["headline"],
            "caption": scene.get("caption", ""),
        })
        manifest[scene["key"]] = entry
        print(f"  {scene['key']:<10} {size/1e6:5.1f} MB  {found['duration']:>2}s  "
              f"poäng {found['score']:<4} {found['credit']}")
        print(f"             {found['sourceUrl']}")

    video.MANIFEST.write_text(
        json.dumps({"closing": video.CLOSING, "clips": manifest},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    ok = sum(1 for c in manifest.values() if c.get("status") == "ok")
    print(f"\n{ok}/{len(video.SCENES)} scener har klipp. Totalt {total_bytes/1e6:.1f} MB.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
