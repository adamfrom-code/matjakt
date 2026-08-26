"""
Willys.se prisscraper (Playwright)
===================================
Samma mönster som ica_scraper.py. Willys produktsidor visar också
"Snart kommer du se alla varor..." innan varukorg/butik är vald,
vilket bekräftar att priset laddas via JS efter butiksval - precis
som hos ICA. Selektorerna nedan är GISSNINGAR, justera via F12.

KÖRNING:
    python willys_scraper.py
"""

from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

from common import Prisrad, skriv_csv, skriv_json, las_produktlista

POSTNUMMER = "80313"
SLEEP_MS = 1500
PRODUKTFIL = "sample_data/produkter.json"


def valj_butik(page, postnummer: str):
    """TODO: justera selektorer efter att ha inspekterat willys.se i Chrome."""
    page.goto("https://www.willys.se/", wait_until="networkidle")
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
        kedja="Willys",
        url=url,
        produktnamn=produktnamn,
        pris_kr=pris,
        butik_postnummer=POSTNUMMER,
        hamtad=datetime.now(timezone.utc).isoformat(),
    )


def main():
    produkter = [p for p in las_produktlista(PRODUKTFIL) if p.get("willys_url")]
    resultat = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="sv-SE")

        valj_butik(page, POSTNUMMER)

        for produkt in produkter:
            rad = hamta_pris(page, produkt["willys_url"], produkt["namn"])
            print(f"{rad.produktnamn}: {rad.pris_kr}")
            resultat.append(rad)

        browser.close()

    if resultat:
        skriv_csv(resultat, "resultat_willys.csv")
        skriv_json(resultat, "resultat_willys.json")
    else:
        print("Inga produkter med willys_url hittades i produktfilen.")


if __name__ == "__main__":
    main()
