# -*- coding: utf-8 -*-
"""Bygger Matjakts presentation som en färdig Reel-fil.

Same story as the landing page, cut for a phone held upright: 1080x1920,
around half a minute, silent, ready to upload.

TWO DECISIONS WORTH KNOWING ABOUT.

Portrait clips are fetched fresh rather than cropping the landscape ones the
website uses. Cropping 16:9 to 9:16 throws away two thirds of the frame and
usually the subject with it - the cart, the hands, the shelf.

The text is drawn with Pillow into transparent PNGs instead of ffmpeg's
drawtext. drawtext cannot wrap a line, and Swedish headlines wrap; doing it
here also means the scrim behind the text is part of the same image, so a
headline is never left sitting on a pale frame it cannot be read against.

    python backend/scripts/make_instagram_video.py

Requires ffmpeg and PEXELS_API_KEY. Writes marketing/matjakt-instagram.mp4.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from services.site import video  # noqa: E402
from scripts.optimize_site_video import ffmpeg_binary  # noqa: E402

OUT_DIR = ROOT / "marketing"
WORK_DIR = OUT_DIR / "build"
FINAL = OUT_DIR / "matjakt-instagram.mp4"

WIDTH, HEIGHT = 1080, 1920
SCENE_SECONDS = 3.8
INTRO_SECONDS = 2.2
OUTRO_SECONDS = 3.2
FADE = 0.45

# Instagram draws its own controls over the top and bottom of a Reel. Text
# placed outside this band is text sitting under a username or a Send button.
SAFE_TOP, SAFE_BOTTOM = 260, 520

BRAND_GREEN = (23, 59, 42)
BRAND_ORANGE = (242, 140, 40)

# Georgia and Segoe stand in for Fraunces and DM Sans. They are on every
# Windows machine, and a video that renders is worth more than one that needs
# a font install to build at all.
SERIF = "C:/Windows/Fonts/georgiab.ttf"
SANS = "C:/Windows/Fonts/segoeui.ttf"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def wrap(draw, text, typeface, max_width):
    lines, line = [], ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=typeface) <= max_width or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def scene_overlay(index: int, headline: str, caption: str, path: Path):
    """Text plus the gradient that makes it readable, as one PNG."""
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))

    # Darkens towards the bottom only, so the food stays visible up top.
    scrim = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    scrim_draw = ImageDraw.Draw(scrim)
    for y in range(HEIGHT):
        position = y / HEIGHT
        alpha = 0 if position < 0.42 else int(225 * ((position - 0.42) / 0.58) ** 1.5)
        scrim_draw.line([(0, y), (WIDTH, y)], fill=(12, 26, 19, alpha))
    image.alpha_composite(scrim)

    draw = ImageDraw.Draw(image)
    headline_font = font(SERIF, 86)
    caption_font = font(SANS, 44)
    margin = 78
    lines = wrap(draw, headline, headline_font, WIDTH - margin * 2)

    block = len(lines) * 104 + (60 if caption else 0)
    y = HEIGHT - SAFE_BOTTOM - block

    # The step number, so the sequence reads as a sequence.
    badge = 62
    draw.ellipse([margin, y - badge - 34, margin + badge, y - 34], fill=BRAND_ORANGE)
    number_font = font(SERIF, 34)
    number = str(index)
    draw.text((margin + badge / 2 - draw.textlength(number, font=number_font) / 2,
               y - badge - 34 + 11), number, font=number_font, fill=(43, 26, 8))

    for line in lines:
        draw.text((margin, y), line, font=headline_font, fill=(255, 255, 255))
        y += 104
    if caption:
        draw.text((margin, y + 8), caption, font=caption_font, fill=(255, 255, 255, 225))

    image.save(path)


def card(path: Path, title: str, subtitle: str = "", logo: Path | None = None,
         title_size: int = 96):
    """A full-frame typographic card - the open and the close."""
    image = Image.new("RGBA", (WIDTH, HEIGHT), BRAND_GREEN + (255,))
    draw = ImageDraw.Draw(image)

    centre = HEIGHT // 2
    if logo and logo.exists():
        mark = Image.open(logo).convert("RGBA").resize((260, 260), Image.LANCZOS)
        rounded = Image.new("L", (260, 260), 0)
        ImageDraw.Draw(rounded).rounded_rectangle([0, 0, 259, 259], radius=62, fill=255)
        mark.putalpha(rounded)
        image.alpha_composite(mark, ((WIDTH - 260) // 2, centre - 330))

    title_font = font(SERIF, title_size)
    lines = wrap(draw, title, title_font, WIDTH - 150)
    y = centre - (len(lines) * (title_size + 18)) // 2 + (60 if logo else 0)
    for line in lines:
        draw.text(((WIDTH - draw.textlength(line, font=title_font)) / 2, y),
                  line, font=title_font, fill=(255, 255, 255))
        y += title_size + 18

    if subtitle:
        subtitle_font = font(SANS, 46)
        draw.text(((WIDTH - draw.textlength(subtitle, font=subtitle_font)) / 2, y + 26),
                  subtitle, font=subtitle_font, fill=BRAND_ORANGE)

    image.convert("RGB").save(path, quality=95)


def run(args: list[str]) -> bool:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print("    ffmpeg:", "\n".join(result.stderr.strip().splitlines()[-4:]))
    return result.returncode == 0


# Picked BY EYE from a portrait contact sheet of ~60 candidates - the same
# lesson as the landing page: slug text does not tell you what a clip looks
# like. Bright Nordic kitchens, a written meal plan, fresh produce, a clean
# checkout. Search remains the fallback if an id disappears.
PORTRAIT_PICKS = {
    "hero": [9001860, 9001864],        # ljust vitt kök, kvinna lagar mat
    "valj": [9015743, 12009197],       # servering vid bordet
    "vecka": [8844930],                # veckoplan skrivs i anteckningsbok
    "lista": [38455504, 3832195],      # hand skriver inköpslista
    "produkter": [8801824, 9474086],   # färskvaror, paprika i handen
    "butiker": [8803792],              # korg med grönsaker genom butiken
    "billigast": [37101039, 13736697], # kassalinjen
}


def fetch_portrait_clips() -> dict:
    """Portrait footage for each scene, cached so a rebuild is not a re-download."""
    manifest_path = WORK_DIR / "portrait.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    clips, used, used_slugs = {}, set(), []
    for scene in video.SCENES:
        found = None
        for pick in PORTRAIT_PICKS.get(scene["key"], []):
            if pick in used:
                continue
            raw = video.fetch_by_id(pick)
            if raw:
                found = video._describe(raw, scene, "portrait", score=9.9)
                if found:
                    break
        if not found:
            found = video.find_clip(scene, used, orientation="portrait",
                                    used_slugs=used_slugs)
        if not found:
            # Landscape is a real fallback here: cropped it loses framing, but
            # a missing scene loses the story.
            found = video.find_clip(scene, used, orientation="landscape",
                                    used_slugs=used_slugs)
        if not found:
            print(f"  {scene['key']:<10} inget klipp")
            continue
        used.add(found["pexelsId"])
        used_slugs.append(set(video._slug_words(found["sourceUrl"])))
        destination = WORK_DIR / f"raw-{scene['key']}.mp4"
        video.download(found["downloadUrl"], destination)
        found["file"] = destination.name
        clips[scene["key"]] = found
        print(f"  {scene['key']:<10} {found['width']}x{found['height']}  {found['credit']}")

    manifest_path.write_text(json.dumps(clips, ensure_ascii=False, indent=2), encoding="utf-8")
    return clips


def main() -> int:
    ffmpeg = ffmpeg_binary()
    if not ffmpeg:
        print("ffmpeg saknas.")
        return 1
    if not video.pexels_key():
        print("PEXELS_API_KEY saknas.")
        return 1

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    print("Hämtar stående klipp:")
    clips = fetch_portrait_clips()
    if not clips:
        return 1

    segments: list[Path] = []

    # --- Intro ------------------------------------------------------------
    intro_png = WORK_DIR / "intro.jpg"
    card(intro_png, "Matjakt", "Planera veckan. Handla smartare.",
         logo=ROOT / "frontend/app/assets/icons/icon-512.png", title_size=132)
    intro_mp4 = WORK_DIR / "seg-00-intro.mp4"
    if not run([ffmpeg, "-y", "-loglevel", "error", "-loop", "1", "-i", str(intro_png),
                "-t", str(INTRO_SECONDS), "-r", "30",
                # A slow push in, so a still card still feels like film.
                "-vf", f"scale=-2:{int(HEIGHT*1.06)},crop={WIDTH}:{HEIGHT},"
                       f"zoompan=z='min(zoom+0.0006,1.08)':d={int(INTRO_SECONDS*30)}:"
                       f"s={WIDTH}x{HEIGHT}:fps=30,format=yuv420p",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20", str(intro_mp4)]):
        return 1
    segments.append(intro_mp4)

    # --- Scenerna ---------------------------------------------------------
    print("\nRenderar scener:")
    step = 0
    for scene in video.SCENES:
        clip = clips.get(scene["key"])
        if not clip:
            continue
        source = WORK_DIR / clip["file"]
        headline = scene["headline"]
        caption = scene.get("caption", "")
        # The hero clip opens the film, so it carries the promise rather than
        # a numbered step.
        if scene["key"] == "hero":
            caption = "Sju middagar efter din budget."
        else:
            step += 1

        overlay = WORK_DIR / f"text-{scene['key']}.png"
        scene_overlay(step or 1, headline, caption, overlay)

        segment = WORK_DIR / f"seg-{step:02d}-{scene['key']}.mp4"
        # Fill the frame from the centre whatever the source aspect is, then
        # lay the text on top and fade it in - the words should arrive after
        # the picture, not with it.
        chain = (
            f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},fps=30,setsar=1[bg];"
            f"[1:v]format=rgba,fade=t=in:st=0.35:d=0.5:alpha=1[txt];"
            f"[bg][txt]overlay=0:0:format=auto,format=yuv420p[v]"
        )
        if not run([ffmpeg, "-y", "-loglevel", "error",
                    "-t", str(SCENE_SECONDS), "-i", str(source),
                    # -loop 1 is not decoration. A single-frame PNG input has
                    # one frame at pts 0, and fade=t=in makes exactly that
                    # frame transparent; overlay then repeats it for the whole
                    # scene. Every headline was invisible.
                    "-loop", "1", "-i", str(overlay),
                    "-filter_complex", chain, "-map", "[v]",
                    "-t", str(SCENE_SECONDS), "-r", "30",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "21",
                    "-pix_fmt", "yuv420p", str(segment)]):
            return 1
        segments.append(segment)
        print(f"  {scene['key']:<10} {headline}")

    # --- Outro ------------------------------------------------------------
    outro_png = WORK_DIR / "outro.jpg"
    card(outro_png, video.CLOSING, "matjakt.store", title_size=104)
    outro_mp4 = WORK_DIR / "seg-99-outro.mp4"
    if not run([ffmpeg, "-y", "-loglevel", "error", "-loop", "1", "-i", str(outro_png),
                "-t", str(OUTRO_SECONDS), "-r", "30",
                "-vf", f"scale={WIDTH}:{HEIGHT},format=yuv420p",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20", str(outro_mp4)]):
        return 1
    segments.append(outro_mp4)

    # --- Sätt ihop med korsfade -------------------------------------------
    # Hard cuts would be simpler. They also look like a slideshow, and this is
    # the first thing most people will ever see of Matjakt.
    print("\nSätter ihop...")
    inputs, filters, previous, offset = [], [], "[0:v]", 0.0
    durations = [INTRO_SECONDS] + [SCENE_SECONDS] * (len(segments) - 2) + [OUTRO_SECONDS]
    for path in segments:
        inputs += ["-i", str(path)]
    for index in range(1, len(segments)):
        offset += durations[index - 1] - FADE
        label = f"[x{index}]"
        filters.append(f"{previous}[{index}:v]xfade=transition=fade:"
                       f"duration={FADE}:offset={offset:.2f}{label}")
        previous = label

    total = sum(durations) - FADE * (len(segments) - 1)
    # Fade up from black at the start and out at the end - a Reel that loops
    # should not slam back to frame one.
    filters.append(f"{previous}fade=t=in:st=0:d=0.5,"
                   f"fade=t=out:st={total - 0.6:.2f}:d=0.6[v]")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not run([ffmpeg, "-y", "-loglevel", "error"] + inputs +
               ["-filter_complex", ";".join(filters), "-map", "[v]",
                "-c:v", "libx264", "-preset", "slow", "-crf", "22",
                "-profile:v", "high", "-level", "4.0", "-pix_fmt", "yuv420p",
                "-r", "30", "-movflags", "+faststart", str(FINAL)]):
        return 1

    size = FINAL.stat().st_size
    print(f"\n{FINAL.relative_to(ROOT)}  {WIDTH}x{HEIGHT}  "
          f"{total:.1f}s  {size/1e6:.1f} MB")

    credits = OUT_DIR / "matjakt-instagram-credits.txt"
    credits.write_text(
        "Klipp i Matjakts Instagram-video. Alla från Pexels (Pexels License,\n"
        "fri kommersiell användning). Fotograferna listas för att vi ska kunna\n"
        "visa varifrån varje klipp kommer.\n\n" +
        "\n".join(f"{key:<10} {c['credit']:<24} {c['sourceUrl']}"
                  for key, c in clips.items()) + "\n",
        encoding="utf-8")
    print(f"{credits.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
