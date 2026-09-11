# -*- coding: utf-8 -*-
"""Bygger de sex butiksskärmbilderna för App Store och Google Play.

    python backend/scripts/make_store_screenshots.py            # fixturdata
    python backend/scripts/make_store_screenshots.py --base http://127.0.0.1:8000

Skärmbilder är det enskilt mest konverterande i en butikslistning, och
`store/appstore/metadata/` innehöll bara textfiler. Det här skriptet kör
appen i en riktig webbläsare, i riktiga enhetsmått, och sparar sex bilder
per format:

    vecka        veckokortet med budgetmätaren
    handla       inköpslistan
    jamforelse   butiksjämförelsen
    recept       ett recept
    skafferi     skafferiet
    sparat       "Du sparar"-kortet

Formaten är Apples två obligatoriska telefonstorlekar plus Plays. Enhetsmått
räknas som CSS-viewport x device_scale_factor, så bilden blir exakt så många
pixlar Apple kräver - en skalad skärmdump med fel mått avvisas vid inlämning.

VAR BILDERNA HAMNAR OCH VARFÖR DE INTE ÄR COMMITTADE
Utdata går till store/appstore/screenshots/ och store/play/screenshots/, och
de katalogerna ska INTE läggas i git: bilderna är genererade (CLAUDE.md §6),
väger några megabyte styck och byter innehåll varje gång appen ändras.
Kör skriptet inför inlämningen, ladda upp, släng. Skriptet skriver aldrig
någon annanstans - test_butiksmetadata.py håller fast det.

TVÅ LÄGEN
  --fixture (standard) startar E2E:ns egen server med syntetisk prisdata för
    tre butiker i Gävle. Den kräver ingen riktig prisdatabas och ger samma
    bilder varje gång - men priserna är påhittade.
  --base <url> kör mot en server du redan startat (`npm run backend`). Det
    är läget att använda inför en riktig inlämning: butiksnamnen och
    priserna på bilderna blir då de som verkligen gäller.

Kräver Playwright: pip install playwright && python -m playwright install chromium
"""

import argparse
import itertools
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

APPSTORE_UT = ROOT / "store" / "appstore" / "screenshots"
PLAY_UT = ROOT / "store" / "play" / "screenshots"

# (mapp, katalog, CSS-bredd, CSS-höjd, skalfaktor) -> pixelmått.
# 6,7" = 1290x2796 och 6,5" = 1242x2688 är Apples två obligatoriska
# telefonformat (docs/IOS_RELEASE.md); Play vill ha minst 1080 px bredd.
FORMAT = (
    ("iphone-6.7", APPSTORE_UT, 430, 932, 3),
    ("iphone-6.5", APPSTORE_UT, 414, 896, 3),
    ("telefon", PLAY_UT, 360, 640, 3),
)

# Scenerna, i den ordning de ska ligga i butiken: det första kortet är det
# enda de flesta ser.
SCENER = ("vecka", "handla", "jamforelse", "recept", "skafferi", "sparat")

POSTNUMMER = "80252"     # samma ort som E2E-fixturen prissätter
BUDGET = "900"


def _vänta(sida, väljare, timeout=30_000):
    sida.wait_for_selector(väljare, state="visible", timeout=timeout)


def _vänta_pa_priser(sida, sekunder=45):
    """En bild av texten "pris hämtas ..." är värdelös i en butikslistning."""
    for _ in range(sekunder * 2):
        if "pris hämtas" not in (sida.locator("#shoppingCost").inner_text() or ""):
            return
        time.sleep(0.5)


def _synlig(sida, väljare, sekunder=45) -> bool:
    """Väntar på att ett element ska bli synligt, men svarar False i stället
    för att kasta - en scen som inte går att nå ska rapporteras, inte döda
    körningen mitt i."""
    for _ in range(sekunder * 2):
        plats = sida.locator(väljare)
        if plats.count() and plats.first.is_visible():
            return True
        time.sleep(0.5)
    return False


def logga_in(sida, epost: str, lösenord: str, registrera: bool):
    """Butiksbilderna ska visa produkten, och butiksjämförelsen och
    sparkortet är Premium. Utan ett Premium-konto blir två av sex scener
    omöjliga att nå - inte för att något är trasigt, utan för att en
    gratisanvändare aldrig ser dem."""
    sida.click("#profileBtn")
    _vänta(sida, "#accountModal")
    flik = "register" if registrera else "login"
    sida.click(f'[data-account-tab="{flik}"]')
    sida.fill(f"#{flik}Email", epost)
    sida.fill(f"#{flik}Password", lösenord)
    sida.click(f'#account{flik.capitalize()}Form button[type="submit"]')
    _vänta(sida, "#accountLoggedIn" if registrera else "#profileBtn")
    if sida.locator("#accountModal").is_visible():
        sida.click("#accountModal .account-modal-close")
        sida.wait_for_selector("#accountModal", state="hidden", timeout=15_000)


def onboarda(sida, bas: str):
    """Fyra steg och en vecka. Samma flöde som browser-E2E:n kör, så om
    onboardingen ändras faller det här skriptet samtidigt som testerna."""
    sida.goto(f"{bas}/app/", wait_until="domcontentloaded")
    _vänta(sida, "#onboardingModal")
    sida.click('[data-ob-adj="vuxna"][data-delta="1"]')
    sida.click("#onboardingNext")
    sida.fill("#obBudget", BUDGET)
    sida.click("#onboardingNext")
    sida.click("#onboardingNext")                      # kost & allergier: inget valt
    sida.fill("#obPostcode", POSTNUMMER)
    sida.click("#onboardingNext")
    sida.wait_for_selector("#onboardingModal", state="hidden", timeout=60_000)
    if sida.locator("#planModal").is_visible():
        sida.click('[data-choose-plan="standard"]')
        sida.wait_for_selector("#planModal", state="hidden", timeout=30_000)
    _vänta(sida, "#weekOverview")


def förvärm(sida):
    """Butikskorten, jämförelseknappen och sparkortet på Hem finns alla
    först när serverns prisjämförelse svarat. Utan det här blir tre av sex
    scener en bild av ett tomt tillstånd, vilket är värre än ingen bild."""
    sida.click('.bottom-nav-item[data-view="basket"]')
    _vänta(sida, "#storeCards .store-card", timeout=90_000)
    _vänta_pa_priser(sida)


def gå_till(sida, scen: str) -> bool:
    """Ställer appen i den vy scenen ska visa. False = scenen gick inte att
    nå, och då ska skriptet säga det i stället för att spara en bild av
    föregående skärm."""
    if scen == "vecka":
        sida.click('.bottom-nav-item[data-view="week"]')
        _vänta(sida, "#weekOverview")
    elif scen == "handla":
        sida.click('.bottom-nav-item[data-view="basket"]')
        _vänta(sida, "#shoppingTitle")
        _vänta_pa_priser(sida)
    elif scen == "jamforelse":
        # Jämförelseknappen sitter bland butikskorten på Handla, och finns
        # bara när serverns jämförelse kröner en kedja.
        sida.click('.bottom-nav-item[data-view="basket"]')
        if not _synlig(sida, "#storeCardsCompareBtn"):
            return False
        sida.click("#storeCardsCompareBtn")
        _vänta(sida, "#comparisonTitle")
    elif scen == "recept":
        sida.click('.bottom-nav-item[data-view="recipes"]')
        _vänta(sida, "#recipesHeading")
        if not _synlig(sida, "#recipeShelves [data-shelf-recipe], [data-details]", sekunder=20):
            return False
        sida.locator("#recipeShelves [data-shelf-recipe], [data-details]").first.click()
        _vänta(sida, "#recipePage")
    elif scen == "skafferi":
        sida.click('.bottom-nav-item[data-view="pantry"]')
        _vänta(sida, "#pantryTitle")
    elif scen == "sparat":
        # Sparkortet visas bara när det finns riktig aritmetik bakom det -
        # två jämförbara butiker och en faktisk skillnad. Syns det inte
        # finns det inget sant att fotografera.
        sida.click('.bottom-nav-item[data-view="home"]')
        if not _synlig(sida, "#openStatsBtn"):
            return False
        sida.click("#openStatsBtn")
        _vänta(sida, "#statsTitle")
        # Sparsiffrorna bygger på handlade veckor. Ett nyss skapat konto har
        # ingen historik, och då står det "Underlag saknas" på skärmen - en
        # sann skärm, men inte en bild att sälja med.
        if "Underlag saknas" in (sida.locator("#statSavedWeek").inner_text() or ""):
            print("    sparat: skärmen saknar historik (\"Underlag saknas\"). Kör "
                  "--base mot ett konto som handlat klart en vecka för en bild "
                  "värd att lämna in.", file=sys.stderr)
    else:
        raise ValueError(scen)
    # Layouten hinner lägga sig; annars fångas ett halvritat tillstånd.
    sida.wait_for_timeout(800)
    return True


def fånga(playwright, bas: str, format_namn, katalog, bredd, höjd, skala,
          konto=None) -> list[str]:
    katalog.mkdir(parents=True, exist_ok=True)
    misslyckade = []
    webbläsare = playwright.chromium.launch()
    try:
        kontext = webbläsare.new_context(viewport={"width": bredd, "height": höjd},
                                         device_scale_factor=skala, locale="sv-SE",
                                         is_mobile=True, has_touch=True)
        sida = kontext.new_page()
        onboarda(sida, bas)
        if konto:
            konto(sida)
        förvärm(sida)
        for nummer, scen in enumerate(SCENER, 1):
            if not gå_till(sida, scen):
                misslyckade.append(scen)
                print(f"    {scen}: gick inte att nå - ingen bild sparad", file=sys.stderr)
                continue
            fil = katalog / f"{format_namn}-{nummer}-{scen}.png"
            sida.screenshot(path=str(fil))
            print(f"    {fil.relative_to(ROOT)}  {bredd * skala}x{höjd * skala}")
        kontext.close()
    finally:
        webbläsare.close()
    return misslyckade


def main() -> int:
    tolk = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    tolk.add_argument("--base", help="adress till en server som redan kör, t.ex. http://127.0.0.1:8000")
    tolk.add_argument("--login", metavar="EPOST:LÖSENORD",
                      help="logga in med ett befintligt Premium-konto (bara med --base). "
                           "Utan det går butiksjämförelsen och sparkortet inte att fotografera.")
    argument = tolk.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright saknas: pip install playwright && python -m playwright install chromium",
              file=sys.stderr)
        return 1

    server = None
    konto = None
    if argument.base:
        bas = argument.base.rstrip("/")
        if not re.match(r"^https?://", bas):
            print("--base måste vara en http(s)-adress", file=sys.stderr)
            return 1
        if argument.login:
            epost, _, lösenord = argument.login.partition(":")
            konto = lambda sida: logga_in(sida, epost, lösenord, registrera=False)
    else:
        # E2E:ns egen server: riktiga ApiHandler, egna tempdatabaser,
        # syntetisk prisdata. Den finns redan och är noggrant uppsatt -
        # att kopiera hit den hade gett två versioner att hålla i synk.
        #
        # Datakatalogen pekas om till en tempkatalog INNAN api_server
        # importeras. Utan det öppnar importen backend/data och skriver
        # onboardingens konto och vecka i den riktiga databasen - samma
        # spärr som services/data_guard.py finns till för.
        import tempfile
        temp = tempfile.mkdtemp(prefix="matjakt-skarmbilder-")
        os.environ["MATJAKT_DATA_DIR"] = temp
        os.environ["MATJAKT_TEST_MODE"] = "1"
        for hemlighet in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "SMTP_HOST",
                          "SMTP_USER", "SMTP_PASSWORD", "PRIMAT_API_KEY", "DABAS_API_KEY",
                          "MATJAKT_ADMIN_TOKEN", "MATJAKT_PREMIUM_CODE"):
            os.environ[hemlighet] = ""
        sys.path.insert(0, str(ROOT / "backend" / "tests"))
        from tests.e2e.test_consumer_journey import _Server
        import api_server
        server = _Server()
        bas = server.base
        print(f"fixturserver på {bas} (data i {temp})")

        # itertools.count i stället för en muterbar standardparameter: samma
        # räknare, men utan listan som delas mellan anrop och som ruff (B006)
        # med rätta kallar en fälla - den som råkar kalla konto(sida, [0])
        # nollställer den tyst för alla.
        löpnummer = itertools.count(1)

        def konto(sida):
            """Registrerar ett engångskonto och ger det Premium direkt i
            fixturdatabasen. Butiksjämförelsen och sparkortet är
            Premium-funktioner; utan det här fotograferar skriptet en
            gratisvy och rapporterar två saknade scener."""
            epost = f"skarmbild-{next(löpnummer)}-{int(time.time())}@matjakt.local"
            logga_in(sida, epost, "Skarmbild!2026", registrera=True)
            with api_server.ACCOUNT_STORE.connection as anslutning:
                anslutning.execute("UPDATE users SET premium = 1 WHERE email = ?", (epost,))
            # Omladdning så appen hämtar sina entitlements på nytt.
            sida.reload(wait_until="domcontentloaded")
            _vänta(sida, '.bottom-nav-item[data-view="week"]', timeout=60_000)

    misslyckade = {}
    try:
        with sync_playwright() as playwright:
            for format_namn, katalog, bredd, höjd, skala in FORMAT:
                print(f"{format_namn} ({bredd * skala}x{höjd * skala}):")
                fel = fånga(playwright, bas, format_namn, katalog, bredd, höjd, skala, konto)
                if fel:
                    misslyckade[format_namn] = fel
    finally:
        if server:
            server.close()

    if misslyckade:
        print(f"\nSaknade scener: {misslyckade}", file=sys.stderr)
        print("En butikslistning med fem av sex bilder är inte klar att lämna in.",
              file=sys.stderr)
        return 1
    print(f"\n{len(SCENER) * len(FORMAT)} bilder klara. De är GENERERADE - "
          f"ladda upp dem, committa dem inte.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
