# -*- coding: utf-8 -*-
"""Frontendens cache-version finns på tre ställen och MÅSTE följas åt:
sw.js CACHE_NAME, index.html app.js?v= och styles.css?v=. Glider de isär
kan en användare köra gammal app.js mot ny CSS eller nytt API utan att
något säger till. Körs i CI och i releasechecken (docs/RELEASE.md).

    python backend/scripts/check_frontend_version.py         # exit 1 vid skevhet
    python backend/scripts/check_frontend_version.py --bump  # höj alla tre med ett
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SW = ROOT / "frontend" / "app" / "sw.js"
HTML = ROOT / "frontend" / "app" / "index.html"


def read_versions():
    sw = SW.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")
    cache = re.search(r'CACHE_NAME = "matjakt-shell-v(\d+)"', sw)
    app = re.search(r"app\.js\?v=(\d+)", html)
    css = re.search(r"styles\.css\?v=(\d+)", html)
    return {"sw.js CACHE_NAME": cache and int(cache.group(1)),
            "index.html app.js?v": app and int(app.group(1)),
            "index.html styles.css?v": css and int(css.group(1))}


def bump():
    versions = read_versions()
    new = max(v for v in versions.values() if v) + 1
    sw = re.sub(r'CACHE_NAME = "matjakt-shell-v\d+"', f'CACHE_NAME = "matjakt-shell-v{new}"', SW.read_text(encoding="utf-8"))
    SW.write_text(sw, encoding="utf-8", newline="\n")
    html = HTML.read_text(encoding="utf-8")
    html = re.sub(r"app\.js\?v=\d+", f"app.js?v={new}", html)
    html = re.sub(r"styles\.css\?v=\d+", f"styles.css?v={new}", html)
    HTML.write_text(html, encoding="utf-8", newline="\n")
    print(f"frontend-version -> {new}")


def main() -> int:
    if "--bump" in sys.argv:
        bump()
        return 0
    versions = read_versions()
    values = set(versions.values())
    if None in values or len(values) != 1:
        print("VERSIONSSKEVHET:", versions)
        return 1
    print(f"frontend-version {values.pop()} på alla tre ställen")
    return 0


if __name__ == "__main__":
    sys.exit(main())
