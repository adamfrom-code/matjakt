# -*- coding: utf-8 -*-
"""Frontendens cache-version: härledd ur bygget, inte skriven i källan.

    python backend/scripts/check_frontend_version.py                   # källan
    python backend/scripts/check_frontend_version.py --build dist/frontend

K5 — LIKHET ÄR INTE FÄRSKHET. Den första kontrollen krävde bara att de tre
talen (sw.js CACHE_NAME, app.js?v=, styles.css?v=) var LIKA. Den sa ingenting
om att de skulle ha HÖJTS när frontenden ändrats, och det var precis det felet
som fanns: en PR som rörde `frontend/app/app.js` utan bump var grön, och GitHub
Pages HTTP-cache serverade den gamla app.js under exakt samma URL medan service
workern behöll sin kopia tills CACHE_NAME bytte. Det står ordagrant i sw.js
egen inledning — "sidan var uppdaterad, telefonerna visade de gamla tre
veckotyperna" — och den enda kontrollen mot det var att någon kom ihåg.

L9 — GRINDEN FLYTTADES TILL BYGGET, OCH BLEV STARKARE AV DET. Kravet "höjd
version" gick att uppfylla bara genom att någon redigerade tre rader för hand,
och de tre raderna var det enda åtta parallella grenar konfliktade på. Nu bär
källan en platshållare och bygget stämplar in eran plus en DIGEST över varje
fil under app/ i utdatan. Den här grinden räknar om digesten — med en egen
implementation, inte genom att fråga byggskriptet om dess eget svar — och
kräver att stämpeln i bygget är exakt den digesten.

Skillnaden mot förr är riktningen på beviset. Förr: "någon har höjt ett tal,
förhoppningsvis för att innehållet ändrats". Nu: "cache-nyckeln ÄR det som
ligger i bygget". Ett bygge vars innehåll gått vidare utan att stämpeln följt
med är alltså fortfarande rött — samma fel som förr, bevisat i stället för
påmint. Och ett bygge där platshållaren står kvar är rött, för en ostämplad
CACHE_NAME i produktion är en cache-nyckel som aldrig byter.

Regeln för digesten står i scripts/frontend_version.mjs och är implementerad
två gånger, en gång där och en gång här. Ändra aldrig den ena ensam: CI kör
den här grinden mot ett riktigt bygge, så en divergens blir röd.
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SW = ROOT / "frontend" / "app" / "sw.js"
HTML = ROOT / "frontend" / "app" / "index.html"
GENERATOR = ROOT / "scripts" / "frontend_version.mjs"

# Allt härunder levereras till webbläsaren och ligger bakom samma
# cache-stämpel: modulerna i src/ (buntade till app.js i bygget), styles.css,
# bilderna i assets/, receptbanken i data/, manifestet och admin-sidan. Det är
# också precis den mängd digesten täcker.
BEVAKAD = "frontend/app/"

SW_MONSTER = r'CACHE_NAME = "matjakt-shell-v([^"]*)"'
APP_MONSTER = r"app\.js\?v=([^\"']*)"
CSS_MONSTER = r"styles\.css\?v=([^\"']*)"


def _ur_generatorn(namn: str, monster: str) -> str:
    """Eran och platshållaren har EN definition, och den ligger på JS-sidan."""
    traff = re.search(monster, GENERATOR.read_text(encoding="utf-8"))
    if not traff:
        raise RuntimeError(f"hittade inte {namn} i {GENERATOR.relative_to(ROOT)}")
    return traff.group(1)


PLATSHALLARE = _ur_generatorn("PLACEHOLDER", r'export const PLACEHOLDER = "([^"]+)"')
ERA = int(_ur_generatorn("RELEASE", r"export const RELEASE = (\d+);"))


def _stamplar(sw: str, html: str):
    """Vad de tre ställena säger, precis som de står."""
    cache = re.search(SW_MONSTER, sw)
    app = re.search(APP_MONSTER, html)
    css = re.search(CSS_MONSTER, html)
    return {"sw.js CACHE_NAME": cache and cache.group(1),
            "index.html app.js?v": app and app.group(1),
            "index.html styles.css?v": css and css.group(1)}


def _samstammig(stamplar):
    """Den enda stämpeln, eller None om de tre inte är eniga."""
    varden = set(stamplar.values())
    if None in varden or len(varden) != 1:
        return None
    return varden.pop()


# ── digesten ───────────────────────────────────────────────────────────────

def _normalisera(relativ: str, byte: bytes) -> bytes:
    """De två stämplade filerna hashas med stämpeln tillbakaställd.

    Utan det hade digesten berott på sig själv. Inget annat i filerna rörs, så
    en ändrad rad i sw.js eller index.html syns fortfarande i digesten.
    """
    if relativ == "sw.js":
        text = re.sub(r'CACHE_NAME = "matjakt-shell-v[^"]*"',
                      f'CACHE_NAME = "matjakt-shell-v{PLATSHALLARE}"',
                      byte.decode("utf-8"))
        return text.encode("utf-8")
    if relativ == "index.html":
        text = byte.decode("utf-8")
        text = re.sub(r"app\.js\?v=[^\"']*", f"app.js?v={PLATSHALLARE}", text)
        text = re.sub(r"styles\.css\?v=[^\"']*", f"styles.css?v={PLATSHALLARE}", text)
        return text.encode("utf-8")
    return byte


def filer_i(katalog: Path):
    """Varje fil under katalogen som (relativ POSIX-sökväg, byte), sorterad."""
    return sorted(((fil.relative_to(katalog).as_posix(), fil.read_bytes())
                   for fil in katalog.rglob("*") if fil.is_file()),
                  key=lambda par: par[0])


def digest(filer) -> str:
    summa = hashlib.sha256()
    for relativ, byte in filer:
        summa.update(relativ.encode("utf-8"))
        summa.update(b"\0")
        summa.update(hashlib.sha256(_normalisera(relativ, byte)).digest())
    return summa.hexdigest()


def stampel_for(filer) -> str:
    return f"{ERA}-{digest(filer)[:10]}"


# ── källgrinden ────────────────────────────────────────────────────────────

def kolla_kallan(skriv=print) -> int:
    """Versionen får inte stå i källan. Den raden VAR konflikten."""
    stamplar = _stamplar(SW.read_text(encoding="utf-8"), HTML.read_text(encoding="utf-8"))
    fel = [f"{var}: {vad!r}" for var, vad in stamplar.items() if vad != PLATSHALLARE]
    if fel:
        skriv(f"::error::Frontend-versionen står i källan igen - {', '.join(fel)}")
        skriv("")
        skriv(f"De tre ställena under {BEVAKAD} ska bära {PLATSHALLARE} och inget annat.")
        skriv("Ett tal där är tre handredigerade rader som måste vara lika, som kan SJUNKA")
        skriv("när grenar mergas i annan ordning än de skapades, och som varje gren som rör")
        skriv("frontenden måste ändra - alltså en garanterad konflikt. Bygget stämplar in")
        skriv("stämpeln i stället:")
        skriv("")
        skriv("    npm run build")
        skriv("")
        return 1
    skriv(f"Källan bär {PLATSHALLARE} på alla tre ställen - ingen version att konflikta om.")
    return 0


# ── bygggrinden ────────────────────────────────────────────────────────────

def kolla_bygget(katalog: str, skriv=print) -> int:
    """Cache-stämpeln i bygget MÅSTE vara digesten av bygget."""
    bygge = Path(katalog)
    app = bygge / "app" if (bygge / "app").is_dir() else bygge
    sw_fil, html_fil = app / "sw.js", app / "index.html"
    if not sw_fil.is_file() or not html_fil.is_file():
        skriv(f"::error::{app} ser inte ut som ett frontendbygge - sw.js eller index.html saknas.")
        skriv("    npm run build    bygger dist/frontend")
        return 1

    filer = filer_i(app)
    kvar = [relativ for relativ, byte in filer if PLATSHALLARE.encode("utf-8") in byte]
    if kvar:
        skriv(f"::error::{PLATSHALLARE} står kvar i bygget: {', '.join(kvar)}")
        skriv("")
        skriv("En ostämplad cache-nyckel är en nyckel som aldrig byter: service workern")
        skriv("skulle cacha under samma namn för alltid, och ingen deploy efter den skulle")
        skriv("nå en telefon som redan varit inne. Det ska stanna bygget, inte släppas")
        skriv("igenom tyst.")
        return 1

    stamplar = _stamplar(sw_fil.read_text(encoding="utf-8"), html_fil.read_text(encoding="utf-8"))
    stampel = _samstammig(stamplar)
    if stampel is None:
        skriv(f"::error::VERSIONSSKEVHET i bygget: {stamplar}")
        skriv("")
        skriv("De tre ställena skrivs ur ETT värde. Säger de olika saker kan en telefon köra")
        skriv("gammal app.js mot ny CSS, och ett bygge på en skev version är ingenting att")
        skriv("deploya.")
        return 1

    vantad = stampel_for(filer)
    if stampel != vantad:
        skriv(f"::error::Cache-stämpeln i bygget är {stampel}, men innehållet i {app} "
              f"har digesten {vantad}.")
        skriv("")
        skriv("Stämpeln ska VARA det som ligger i bygget. Är den något annat har innehållet")
        skriv("gått vidare utan att cache-nyckeln följt med - exakt det fel grinden finns")
        skriv("för. GitHub Pages HTTP-cache serverar då den gamla app.js under samma URL,")
        skriv("och service workern behåller sin kopia tills CACHE_NAME byter: en")
        skriv("återvändande användare kör förra releasen utan att något säger till.")
        skriv("")
        skriv("Bygg om i stället för att skriva stämpeln för hand:")
        skriv("")
        skriv("    npm run build")
        skriv("")
        return 1

    skriv(f"{app}: cache-stämpel {stampel} = era {ERA} + digest över {len(filer)} filer.")
    return 0


def main(argv=None) -> int:
    tolk = argparse.ArgumentParser(description="Frontendens cache-version: härledd, inte skriven.")
    tolk.add_argument("--build", metavar="KATALOG", default=None,
                      help="kontrollera stämpeln i ett bygge (t.ex. dist/frontend)")
    # De gamla flaggorna fanns för ett tal i källan. Att bara ta bort dem hade
    # gett ett argparse-fel utan förklaring i varje gammal körning.
    tolk.add_argument("--bump", action="store_true", help=argparse.SUPPRESS)
    tolk.add_argument("--require-bump", action="store_true", help=argparse.SUPPRESS)
    tolk.add_argument("--base", default=None, help=argparse.SUPPRESS)
    argument = tolk.parse_args(argv)

    if argument.bump or argument.require_bump:
        print("Versionen står inte längre i källan och kan därför inte bumpas per paket.")
        print("Bygget stämplar in eran plus en digest över det som byggts:")
        print("")
        print("    npm run build")
        print("    python backend/scripts/check_frontend_version.py --build dist/frontend")
        print("")
        print("Eran - den läsbara etiketten, inte cache-nyckeln - höjs vid release med")
        print("    node scripts/frontend_version.mjs --bump")
        return 1

    if argument.build:
        return kolla_kallan() or kolla_bygget(argument.build)
    return kolla_kallan()


if __name__ == "__main__":
    sys.exit(main())
