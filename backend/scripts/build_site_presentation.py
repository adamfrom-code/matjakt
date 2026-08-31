# -*- coding: utf-8 -*-
"""Skriver presentationsblocket i index.html från clips.json.

Generated rather than hand-written for one reason: the markup carries each
clip's photographer and source URL, and hand-copied credits go stale the
first time a clip is replaced. Re-run this after fetching or swapping clips.

    python backend/scripts/build_site_presentation.py
"""

import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from services.site import video  # noqa: E402

INDEX = ROOT / "frontend" / "index.html"
START = "<!-- PRESENTATION:START - genererad av backend/scripts/build_site_presentation.py -->"
END = "<!-- PRESENTATION:END -->"


def scene_markup(index: int, clip: dict) -> str:
    headline = html.escape(clip.get("headline", ""))
    caption = html.escape(clip.get("caption", ""))
    number = f'<span class="site-film-step">{index}</span>'

    if clip.get("status") != "ok":
        # No clip for this scene: the panel still plays its part in the story,
        # it simply does it without footage. Better a clean typographic panel
        # than a clip that shows the wrong thing.
        return (f'        <article class="site-film-scene site-film-scene-plain">\n'
                f'          <div class="site-film-copy">{number}'
                f'<h3>{headline}</h3><p>{caption}</p></div>\n'
                f'        </article>')

    credit = html.escape(clip.get("credit", ""))
    credit_url = html.escape(clip.get("sourceUrl", ""))
    return (
        f'        <article class="site-film-scene">\n'
        f'          <div class="site-film-media">\n'
        # No src attribute: site-video.js fills it in when the scene comes
        # near the viewport, so opening the page never downloads six clips.
        f'            <video class="site-film-video" data-film-src="{html.escape(clip["src"])}"\n'
        f'                   poster="{html.escape(clip["poster"])}"\n'
        f'                   muted playsinline loop preload="none" disablepictureinpicture\n'
        f'                   aria-hidden="true"></video>\n'
        f'            <span class="site-film-scrim"></span>\n'
        f'            <div class="site-film-copy">{number}'
        f'<h3>{headline}</h3><p>{caption}</p></div>\n'
        f'          </div>\n'
        f'          <p class="site-film-credit">Film: '
        f'<a href="{credit_url}" rel="noopener nofollow" target="_blank">{credit}</a> · Pexels</p>\n'
        f'        </article>')


def main() -> int:
    manifest = video.load_manifest()
    clips = manifest.get("clips", {})
    if not clips:
        print("Ingen clips.json. Kör fetch_site_video.py först.")
        return 1

    # Hero-klippet spelar redan högst upp; presentationen börjar efter det.
    scenes = [s for s in video.SCENES if s["key"] != "hero"]
    parts = ['      <div class="site-film-track">']
    for index, scene in enumerate(scenes, start=1):
        clip = clips.get(scene["key"])
        if clip:
            parts.append(scene_markup(index, clip))
    parts.append('      </div>')
    parts.append(
        f'      <div class="site-film-closing">\n'
        f'        <p class="site-film-closing-line">{html.escape(manifest.get("closing", ""))}</p>\n'
        f'        <a class="site-btn site-btn-primary site-btn-lg" href="app/" '
        f'data-track="cta_testa_gratis">Testa Matjakt gratis →</a>\n'
        f'      </div>')

    source = INDEX.read_text(encoding="utf-8")
    before, _, rest = source.partition(START)
    _, _, after = rest.partition(END)
    if not rest or not after:
        print("Hittade inte PRESENTATION-markörerna i index.html.")
        return 1

    INDEX.write_text(before + START + "\n" + "\n".join(parts) + "\n      " + END + after,
                     encoding="utf-8")
    usable = sum(1 for s in scenes if (clips.get(s["key"]) or {}).get("status") == "ok")
    print(f"Presentationen skriven: {usable}/{len(scenes)} scener med film.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
