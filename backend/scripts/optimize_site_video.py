# -*- coding: utf-8 -*-
"""Bantar klippen till något en mobil faktiskt orkar ladda.

Pexels ships broadcast-quality files - 8 MB for fifteen seconds. A landing
page that makes a phone on mobile data pay for that is a landing page people
leave before it loads, so every clip is re-encoded here: trimmed to the few
seconds that carry the scene, stripped of its audio track, and capped at a
width no phone screen exceeds.

Removing the audio is not only about size. A background video that could make
sound is a background video that will, on some browser, some day.

    python backend/scripts/optimize_site_video.py
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from services.site import video  # noqa: E402

# Long enough to read as a scene, short enough that the loop feels intentional.
MAX_SECONDS = 8
TARGET_WIDTH = 1280
# 30 is visibly compressed on a still, invisible on moving footage behind text.
CRF = 30
# The poster is the ONE asset the browser fetches eagerly for every clip on
# the page, loaded or not - seven of them at clip resolution was 433 kB spent
# before a visitor had scrolled anywhere. It is only ever seen for a moment,
# behind text, or as the still fallback, so it does not need clip resolution.
POSTER_WIDTH = 800
POSTER_QUALITY = 7


def ffmpeg_binary() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    # winget installs into a versioned package directory that is on PATH only
    # after a new shell. Looking for it directly means the script works in the
    # session that installed it.
    packages = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    for candidate in packages.glob("Gyan.FFmpeg*/ffmpeg*/bin/ffmpeg.exe"):
        return str(candidate)
    return None


def run(args: list[str]) -> bool:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"    ffmpeg misslyckades: {result.stderr.strip().splitlines()[-1:]}")
    return result.returncode == 0


def main() -> int:
    ffmpeg = ffmpeg_binary()
    if not ffmpeg:
        print("ffmpeg saknas - kan inte optimera klippen.")
        return 1

    manifest = video.load_manifest()
    clips = manifest.get("clips", {})
    if not clips:
        print("Ingen clips.json. Kör fetch_site_video.py först.")
        return 1

    before = after = 0
    for key, clip in clips.items():
        if clip.get("status") != "ok":
            continue
        source = video.CLIP_DIR / Path(clip["src"]).name
        if not source.exists():
            continue
        before += source.stat().st_size
        optimised = source.with_suffix(".opt.mp4")

        if not run([
            ffmpeg, "-y", "-loglevel", "error", "-t", str(MAX_SECONDS), "-i", str(source),
            # Even width: h264 refuses odd dimensions.
            "-vf", f"scale={TARGET_WIDTH}:-2",
            "-c:v", "libx264", "-preset", "slow", "-crf", str(CRF),
            "-profile:v", "main", "-pix_fmt", "yuv420p",
            # Playable while still downloading, instead of only once complete.
            "-movflags", "+faststart",
            "-an", str(optimised),
        ]):
            optimised.unlink(missing_ok=True)
            continue

        # The poster is the clip's own first frame, so there is no jump when
        # the video takes over from the still.
        poster = video.CLIP_DIR / Path(clip["poster"]).name
        run([ffmpeg, "-y", "-loglevel", "error", "-i", str(optimised),
             "-frames:v", "1", "-vf", f"scale={POSTER_WIDTH}:-2",
             "-q:v", str(POSTER_QUALITY), str(poster)])

        optimised.replace(source)
        size = source.stat().st_size
        after += size
        clip["bytes"] = size
        clip["seconds"] = min(MAX_SECONDS, clip.get("duration") or MAX_SECONDS)
        print(f"  {key:<10} {before and ''}{size/1e6:5.2f} MB")

    video.MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{before/1e6:.1f} MB -> {after/1e6:.1f} MB "
          f"({100 - after * 100 // max(before, 1)}% mindre)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
