# -*- coding: utf-8 -*-
"""Renderar frontend/og-image.svg till frontend/og-image.png, 1200x630.

Varför en PNG finns bredvid SVG:en: **ingen plattform stöder SVG som
`og:image`.** Facebook, LinkedIn, Slack, iMessage, X, WhatsApp och Discord
hoppar alla över den och visar en tom grå ruta i stället. SVG:en är källan
man redigerar; PNG:en är den som delas.

    python backend/scripts/make_og_image.py

Rendering kräver ett verktyg som kan SVG. Skriptet letar efter, i tur och
ordning: rsvg-convert, chromium/chrome (headless), och ger annars upp med ett
begripligt fel - aldrig en trasig PNG. Utdata kontrolleras mot 1200x630 innan
den skrivs över den gamla; ett delat kort med fel mått blir beskuret hos
hälften av mottagarna.

PNG:en är spårad med flit. Den är en sajttillgång på samma sätt som klippen
under frontend/site/video/, inte en byggartefakt: CI har ingen SVG-renderare
och delningskortet måste finnas i det som deployas.
"""

import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SVG = ROOT / "frontend" / "og-image.svg"
PNG = ROOT / "frontend" / "og-image.png"
WIDTH, HEIGHT = 1200, 630

CHROME_KANDIDATER = (
    "chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)


def png_matt(data: bytes) -> tuple[int, int] | None:
    """Bredd och höjd ur IHDR. Ingen Pillow - måtten står på fast plats i
    varje giltig PNG, och ett beroende till för en kontroll är ett för
    mycket."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def rendera(ut: Path) -> str:
    if (rsvg := shutil.which("rsvg-convert")):
        subprocess.run([rsvg, "-w", str(WIDTH), "-h", str(HEIGHT),
                        "-o", str(ut), str(SVG)], check=True)
        return "rsvg-convert"
    for kandidat in CHROME_KANDIDATER:
        körbar = shutil.which(kandidat) or (kandidat if Path(kandidat).exists() else None)
        if not körbar:
            continue
        subprocess.run([körbar, "--headless", "--disable-gpu", "--hide-scrollbars",
                        f"--screenshot={ut}", f"--window-size={WIDTH},{HEIGHT}",
                        SVG.as_uri()],
                       check=True, capture_output=True)
        return Path(körbar).name
    raise SystemExit(
        "Ingen SVG-renderare hittades. Installera rsvg-convert (brew install librsvg,\n"
        "apt install librsvg2-bin) eller ha Chrome/Chromium i PATH, och kör om.")


def main() -> int:
    if not SVG.exists():
        print(f"{SVG} saknas", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        ut = Path(tmp) / "og.png"
        verktyg = rendera(ut)
        data = ut.read_bytes()
    mått = png_matt(data)
    if mått != (WIDTH, HEIGHT):
        print(f"{verktyg} gav {mått}, inte {(WIDTH, HEIGHT)} - skriver inte över "
              f"{PNG.name}", file=sys.stderr)
        return 1
    PNG.write_bytes(data)
    print(f"{PNG.relative_to(ROOT)}: {WIDTH}x{HEIGHT}, {len(data)/1024:.1f} kB ({verktyg})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
