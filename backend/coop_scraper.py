"""
Coop.se prisscraper (Playwright)
==================================
Samma mönster som ica_scraper.py och willys_scraper.py.
Coop kräver sannolikt inloggning/medlemskap för vissa priser
(medlemsrabatter) - separera "ordinarie pris" och "medlemspris"
om båda visas, det är relevant för Veckokassen att veta vilket som gäller.

KÖRNING:
    python coop_scraper.py
"""

from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

from common import Prisrad, skriv_csv, skriv_json, las_produktlista

POSTNUMMER = "80313"
SLEEP_MS = 1500
PRODUKTFIL = "sample_data/produkter.json"


def valj_butik(page, postnummer: str):
    """TODO: justera selektorer efter att ha inspekterat coop.se i Chrome."""
    page.goto("https://www.coop.se/", wait_until="networkidle")
    page.click("text=Välj butik")
    page.fill("input[type=search]", postnummer)
    page.wait_for_timeout(1000)
    page.click("[data-testid=store-result-item]")
    page.wait_for_timeout(1000)


def hamta_pris(page, url: str, produktnamn: str) -> Prisrad:
    page.goto(url, wait_until="networkidle")
    page.wait_for_timeout(SLEEP_MS)

    try:
        pris = page.locator("[data-testid=product-price]").first.inner_text()
    except Exception:
        pris = "EJ HITTAT - justera selector"

    return Prisrad(
        kedja="Coop",
        url=url,
        produktnamn=produktnamn,
        pris_kr=pris,
        butik_postnummer=POSTNUMMER,
        hamtad=datetime.now(timezone.utc).isoformat(),
    )


def main():
    produkter = [p for p in las_produktlista(PRODUKTFIL) if p.get("coop_url")]
    resultat = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="sv-SE")

        valj_butik(page, POSTNUMMER)

        for produkt in produkter:
            rad = hamta_pris(page, produkt["coop_url"], produkt["namn"])
            print(f"{rad.produktnamn}: {rad.pris_kr}")
            resultat.append(rad)

        browser.close()

    if resultat:
        skriv_csv(resultat, "resultat_coop.csv")
        skriv_json(resultat, "resultat_coop.json")
    else:
        print("Inga produkter med coop_url hittades i produktfilen. Fyll i sample_data/produkter.json.")


if __name__ == "__main__":
    main()
