# -*- coding: utf-8 -*-
"""Frontendens cache-version finns på tre ställen och MÅSTE följas åt:
sw.js CACHE_NAME, index.html app.js?v= och styles.css?v=. Glider de isär
kan en användare köra gammal app.js mot ny CSS eller nytt API utan att
något säger till. Körs i CI och i releasechecken (docs/RELEASE.md).

    python backend/scripts/check_frontend_version.py         # exit 1 vid skevhet
    python backend/scripts/check_frontend_version.py --bump  # höj alla tre med ett

K5 — LIKHET ÄR INTE FÄRSKHET. Kontrollen ovan krävde att de tre talen var
LIKA. Den sa ingenting om att de skulle ha HÖJTS när frontenden ändrats, och
det var precis det felet som fanns: en PR som rörde `frontend/app/app.js`
utan bump var grön, och GitHub Pages HTTP-cache serverade den gamla app.js
under exakt samma URL. Det är felet som står beskrivet i sw.js egna
inledningsrad — "the site was updated, phones still showed the old three week
types" — och den enda kontroll som fanns mot det var att någon kom ihåg.

    python backend/scripts/check_frontend_version.py --require-bump --base <ref>

Failar om något under `frontend/app/` skiljer sig mot basen utan att
versionen höjts. `--base` är den commit ändringen mäts från; utelämnas den
används sammanslagningspunkten mot `origin/main`.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SW = ROOT / "frontend" / "app" / "sw.js"
HTML = ROOT / "frontend" / "app" / "index.html"

# Allt härunder levereras till webbläsaren och ligger bakom samma
# cache-version: modulerna i src/, styles.css, ikonerna, receptbanken i
# data/, admin-sidan. Ändras något av det utan bump kan en återvändande
# användare få den gamla filen på samma URL.
BEVAKAD = "frontend/app/"

SW_MONSTER = r'CACHE_NAME = "matjakt-shell-v(\d+)"'
APP_MONSTER = r"app\.js\?v=(\d+)"
CSS_MONSTER = r"styles\.css\?v=(\d+)"

NOLLSHA = "0" * 40


def _git(*argument, kontrollera=False):
    """Kör git i repo-roten. Returnerar (kod, stdout)."""
    klar = subprocess.run(["git", *argument], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    if kontrollera and klar.returncode != 0:
        raise RuntimeError(f"git {' '.join(argument)}: {klar.stderr.strip()}")
    return klar.returncode, klar.stdout


def _versioner_ur_text(sw: str, html: str):
    cache = re.search(SW_MONSTER, sw)
    app = re.search(APP_MONSTER, html)
    css = re.search(CSS_MONSTER, html)
    return {"sw.js CACHE_NAME": cache and int(cache.group(1)),
            "index.html app.js?v": app and int(app.group(1)),
            "index.html styles.css?v": css and int(css.group(1))}


def read_versions():
    return _versioner_ur_text(SW.read_text(encoding="utf-8"), HTML.read_text(encoding="utf-8"))


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


def _samstammig(versioner):
    """Det enda talet, eller None om de tre inte är eniga."""
    varden = set(versioner.values())
    if None in varden or len(varden) != 1:
        return None
    return varden.pop()


def los_bas(onskad: str | None) -> str | None:
    """Vilken commit mäts ändringen mot?

    Ordningen är avsiktlig. CI skickar alltid med en bas ur händelsen
    (`pull_request.base.sha`, `merge_group.base_sha`, `push.before`) - det är
    den enda som är exakt rätt. Utan den, eller när den är nollSHA:t en
    nyskapad gren ger, används sammanslagningspunkten mot main, som är rätt
    svar lokalt.
    """
    kandidater = []
    if onskad and onskad.strip() and onskad.strip() != NOLLSHA:
        kandidater.append(onskad.strip())
    for ref in ("origin/main", "main"):
        kod, ut = _git("merge-base", ref, "HEAD")
        if kod == 0 and ut.strip():
            kandidater.append(ut.strip())
    for kandidat in kandidater:
        kod, ut = _git("rev-parse", "--verify", f"{kandidat}^{{commit}}")
        if kod == 0 and ut.strip():
            return ut.strip()
    return None


def andrade_frontendfiler(bas: str):
    """Filer under frontend/app/ som skiljer sig mellan basen och HEAD."""
    kod, ut = _git("diff", "--name-only", f"{bas}...HEAD")
    if kod != 0:  # grenarna har ingen gemensam historia: jämför rakt av
        kod, ut = _git("diff", "--name-only", bas, "HEAD")
        if kod != 0:
            raise RuntimeError(f"kunde inte diffa mot {bas[:12]}")
    return sorted(rad for rad in ut.splitlines() if rad.startswith(BEVAKAD))


def versioner_vid(bas: str):
    """Läser de tre talen som de såg ut i basen."""
    kod_sw, sw = _git("show", f"{bas}:frontend/app/sw.js")
    kod_html, html = _git("show", f"{bas}:frontend/app/index.html")
    if kod_sw != 0 or kod_html != 0:
        return None
    return _versioner_ur_text(sw, html)


def krav_pa_hojning(onskad_bas: str | None, skriv=print) -> int:
    """K5-grinden: rörd frontend utan höjd version är ett byggfel."""
    bas = los_bas(onskad_bas)
    if bas is None:
        skriv("::error::Hittade ingen bas att jämföra mot (varken --base, origin/main "
              "eller main). Färskhetskontrollen kan inte avgöra något och vägrar "
              "därför att passera - en grind som inte vet svarar aldrig ja.")
        return 1

    andrade = andrade_frontendfiler(bas)
    if not andrade:
        skriv(f"Inget under {BEVAKAD} ändrat mot {bas[:12]} - ingen bump krävs.")
        return 0

    nu = _samstammig(read_versions())
    if nu is None:
        skriv("VERSIONSSKEVHET:", read_versions())
        return 1

    fore = versioner_vid(bas)
    if fore is None:
        skriv(f"Kunde inte läsa frontend-versionen i {bas[:12]} - behandlas som "
              f"ny frontend, bumpen kan inte krävas.")
        return 0
    tidigare = _samstammig(fore)
    if tidigare is None:
        # Basen var redan skev. Det är inte den här PR:ens fel, och likheten
        # ovan är redan kontrollerad - släpp igenom.
        skriv(f"Basen {bas[:12]} var redan versionsskev {fore} - bara likheten krävs här.")
        return 0

    if nu > tidigare:
        skriv(f"frontend-version {tidigare} -> {nu} för {len(andrade)} ändrade filer "
              f"under {BEVAKAD}.")
        return 0

    skriv(f"::error::{len(andrade)} filer under {BEVAKAD} är ändrade mot {bas[:12]}, "
          f"men frontend-versionen står kvar på {nu} (basen: {tidigare}).")
    for fil in andrade[:10]:
        skriv(f"    {fil}")
    if len(andrade) > 10:
        skriv(f"    ... och {len(andrade) - 10} till")
    skriv("")
    skriv("GitHub Pages HTTP-cache serverar den gamla filen under samma URL, och "
          "service workern behåller sin gamla kopia tills CACHE_NAME byter. En "
          "återvändande användare kör alltså den förra releasen utan att något "
          "säger till - precis felet som står beskrivet överst i sw.js.")
    skriv("")
    skriv("    python backend/scripts/check_frontend_version.py --bump")
    skriv("")
    skriv("höjer alla tre talen med ett. Committa dem tillsammans med ändringen.")
    return 1


def main(argv=None) -> int:
    tolk = argparse.ArgumentParser(description="Frontendens cache-version: lika, och färsk.")
    tolk.add_argument("--bump", action="store_true", help="höj alla tre talen med ett")
    tolk.add_argument("--require-bump", action="store_true",
                      help="faila om frontend/app/ ändrats utan att versionen höjts")
    tolk.add_argument("--base", default=None,
                      help="commit att mäta ändringen mot (standard: merge-base mot origin/main)")
    argument = tolk.parse_args(argv)

    if argument.bump:
        bump()
        return 0

    versions = read_versions()
    om_eniga = _samstammig(versions)
    if om_eniga is None:
        print("VERSIONSSKEVHET:", versions)
        return 1
    print(f"frontend-version {om_eniga} på alla tre ställen")

    if argument.require_bump:
        return krav_pa_hojning(argument.base)
    return 0


if __name__ == "__main__":
    sys.exit(main())
