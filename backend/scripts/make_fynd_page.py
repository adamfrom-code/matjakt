# -*- coding: utf-8 -*-
"""Bygger veckans fyndsida: frontend/fynd/vecka-{n}/index.html.

    python backend/scripts/make_fynd_page.py                     # lokal prisdatabas
    python backend/scripts/make_fynd_page.py --base https://matjakt.onrender.com
    python backend/scripts/make_fynd_page.py --from-json fynd.json --week 37

matjakt.store ligger på GitHub Pages: `scripts/build_frontend.mjs` kopierar
`frontend/` rakt av, och den katalogen är allt som finns på domänen. Det
betyder att en vecka bara existerar om dess HTML är committad. Det här
skriptet skriver den, skriver om arkivsidan `/fynd/` och lägger in adresserna
i `frontend/sitemap.xml`.

VARFÖR SIDAN ÄR COMMITTAD OCH INTE BYGGD I DEPLOYEN
Det finns ingen tredje väg. Backenden serverar aldrig matjakt.store, och
deploy-jobbet ligger i .github/** som har en enda ägare. En committad sida är
dessutom en sida man kan läsa i en PR innan den går ut - och en kampanjsida
som går ut fel är sämre än ingen.

Sidan är innehåll, inte en byggartefakt: den granskas, den versioneras, och
den ska gå att se i historiken vilken vecka som sa vad. CLAUDE.md §6 gäller
byggartefakter (dist/, marketing/build/, audit-utdata) - inte publicerade
sidor.

RUTINEN
Torsdag morgon, samma dag som Kampanjtorget mejlas:

    python backend/scripts/make_fynd_page.py --base https://matjakt.onrender.com
    git add frontend/fynd frontend/sitemap.xml
    git commit -m "fynd: vecka N"

Skriptet vägrar skriva en sida utan fynd (`exit 1`): en tom kampanjsida med
veckans nummer i rubriken ser ut som en produkt som slutat fungera.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from services.site import fynd_page  # noqa: E402

FRONTEND = ROOT / "frontend"
FYND = FRONTEND / "fynd"
SITEMAP = FRONTEND / "sitemap.xml"
TIDSZON = ZoneInfo("Europe/Stockholm")

# Samma veckonummer som Kampanjtorget-mejlet (services/mailings.py) och
# analytics-kohorterna: ISO-vecka i svensk tid. Två nummer på samma vecka är
# ett fel ingen upptäcker förrän någon jämför ett mejl med en sida.
def _nu() -> datetime:
    return datetime.now(TIDSZON)


def hämta_via_http(bas: str) -> dict:
    adress = bas.rstrip("/") + "/api/grocery/campaigns"
    begäran = urllib.request.Request(adress, headers={"User-Agent": "matjakt-fyndsida"})
    try:
        with urllib.request.urlopen(begäran, timeout=60) as svar:
            return json.loads(svar.read().decode("utf-8")).get("deals", {})
    except urllib.error.URLError as fel:
        # En Python installerad via Homebrew saknar ofta rotcertifikaten
        # ("CERTIFICATE_VERIFY_FAILED"). Det är inte ett fel i servern, och
        # den som står här ska inte behöva gissa det.
        if "CERTIFICATE_VERIFY_FAILED" in str(fel):
            raise SystemExit(
                f"{adress}: tolken litar inte på något rotcertifikat.\n"
                "Kör /Applications/Python*/Install\\ Certificates.command, eller hämta\n"
                f"  curl -s {adress} > fynd.json\n"
                "och kör om med --from-json fynd.json.") from None
        raise SystemExit(f"{adress}: {fel}") from None


def hämta_lokalt(per_kedja: int) -> dict:
    from services.grocery import api as grocery_api
    return grocery_api.campaign_deals(per_chain=per_kedja).get("deals", {})


def recepttitlar(fynd_per_kedja: dict, bas: str | None) -> dict:
    """recipeIds -> rubrik. Ett id i klartext på en publik sida är en läcka av
    vår databas, inte en upplysning till läsaren. Går titeln inte att slå upp
    säger sidan "passar i N rätter" i stället - se fynd_page._fyndrad."""
    ids = {r for lista in fynd_per_kedja.values() for f in lista or []
           for r in fynd_page._recept_av(f if isinstance(f, dict) else {})}
    if not ids:
        return {}
    titlar = {}
    if bas:
        for recept_id in sorted(ids):
            try:
                adress = f"{bas.rstrip('/')}/api/recipes/{urllib.parse.quote(recept_id)}"
                with urllib.request.urlopen(adress, timeout=20) as svar:
                    data = json.loads(svar.read().decode("utf-8"))
                if data.get("title"):
                    titlar[recept_id] = data["title"]
            except Exception:
                continue
        return titlar
    try:
        from services.recipes import api as recept_api
        for recept_id in sorted(ids):
            recept = recept_api.get(recept_id)
            if recept and recept.get("title"):
                titlar[recept_id] = recept["title"]
    except Exception:
        pass
    return titlar


def kända_veckor() -> list:
    """[(vecka, år, antal, hämtad-datum)] ur de sidor som redan ligger i
    frontend/fynd/, nyaste först. Arkivet byggs om ur katalogen i stället för
    ur ett register - en sida som finns ska stå i arkivet även om registret
    kommit bort."""
    veckor = []
    for katalog in sorted(FYND.glob("vecka-*")):
        sida = katalog / "index.html"
        if not sida.exists():
            continue
        html = sida.read_text(encoding="utf-8")
        vecka = int(katalog.name.split("-", 1)[1])
        antal = len(re.findall(r'<li class="fynd-rad">', html))
        datum = re.search(r'"datePublished": "(\d{4}-\d{2}-\d{2})"', html)
        år = re.search(r'"name": "Veckans erbjudanden vecka \d+ (\d{4})"', html)
        veckor.append((vecka, int(år.group(1)) if år else date.today().year, antal,
                       datum.group(1) if datum else date.today().isoformat()))
    return sorted(veckor, key=lambda rad: (rad[1], rad[0]), reverse=True)


def skriv_sitemap(veckor: list) -> int:
    """Lägger in fyndsidorna i sitemapen utan att röra de rader som redan
    står där. robots.txt pekar hit; en ny sida som inte hamnar i sitemapen
    indexeras inte, och ingen märker det."""
    xml = SITEMAP.read_text(encoding="utf-8")
    xml = re.sub(r"\n  <url>\n    <loc>https://matjakt\.store/fynd/[^<]*</loc>.*?</url>",
                 "", xml, flags=re.S)
    block = "".join(
        f"\n  <url>\n    <loc>{loc}</loc>\n    <lastmod>{lastmod}</lastmod>\n"
        f"    <changefreq>{freq}</changefreq>\n    <priority>{pri}</priority>\n  </url>"
        for loc, lastmod, freq, pri in fynd_page.sitemap_poster(veckor))
    xml = xml.replace("\n</urlset>", block + "\n</urlset>")
    SITEMAP.write_text(xml, encoding="utf-8")
    return len(veckor) + 1


def main() -> int:
    tolk = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    tolk.add_argument("--base", help="server att hämta kampanjerna från, "
                                     "t.ex. https://matjakt.onrender.com")
    tolk.add_argument("--from-json", help="läs {\"deals\": ...} eller {kedja: [...]} ur en fil")
    tolk.add_argument("--week", type=int, help="veckonummer (standard: ISO-veckan nu)")
    tolk.add_argument("--per-chain", type=int, default=8,
                      help="fynd per kedja (standard 8, samma som mejlet)")
    tolk.add_argument("--allow-empty", action="store_true",
                      help="skriv sidan även utan fynd (bara för att pröva mallen)")
    argument = tolk.parse_args()

    nu = _nu()
    vecka = argument.week or nu.isocalendar()[1]
    år = nu.isocalendar()[0]

    if argument.from_json:
        rå = json.loads(Path(argument.from_json).read_text(encoding="utf-8"))
        fynd = rå.get("deals", rå)
    elif argument.base:
        fynd = hämta_via_http(argument.base)
    else:
        fynd = hämta_lokalt(argument.per_chain)

    antal = sum(len(v or []) for v in fynd.values())
    if antal == 0 and not argument.allow_empty:
        print("Inga fynd att publicera. En tom kampanjsida med veckans nummer i "
              "rubriken ser ut som en produkt som slutat fungera - skriver inget.",
              file=sys.stderr)
        return 1

    titlar = recepttitlar(fynd, argument.base)
    med_recept = sum(1 for lista in fynd.values() for f in lista or []
                     if isinstance(f, dict) and fynd_page._recept_av(f))
    html = fynd_page.render_week(fynd, vecka=vecka, år=år, hämtad=nu, recept_titlar=titlar)

    katalog = FYND / f"vecka-{vecka}"
    katalog.mkdir(parents=True, exist_ok=True)
    (katalog / "index.html").write_text(html, encoding="utf-8")
    print(f"frontend/fynd/vecka-{vecka}/index.html  {antal} fynd, "
          f"{med_recept} med receptkoppling")

    veckor = kända_veckor()
    (FYND / "index.html").write_text(fynd_page.render_index(veckor), encoding="utf-8")
    print(f"frontend/fynd/index.html  {len(veckor)} veckor")
    print(f"frontend/sitemap.xml  {skriv_sitemap(veckor)} fyndadresser inlagda")

    if med_recept == 0:
        print("\nInget av fynden bär recipeIds. Sidan listar butikernas kampanjer\n"
              "som de är och säger det rakt ut. C11 (docs/PAKET-C11-fynd.md) är det\n"
              "som gör listan till ett urval värt att söka upp.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
