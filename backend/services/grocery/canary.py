# -*- coding: utf-8 -*-
"""Kanariefågeln: ett känt GTIN med ett känt prisintervall, per kedja.

VARFÖR (D10). Publiceringsgaten räknar rader och radformat, och D2 lade till
medianförändringen. Alla tre svarar på "ser insamlingen normal ut?" utan att
någonsin titta på en vara någon faktiskt känner igen. En kedja som byter
API-form kan mycket väl fortsätta leverera tiotusen välformade rader - bara
inte rätt rader.

Kanariefågeln är den billigaste möjliga upptäckten av "sajten ändrade sig":
EN vara vi vet finns, till ett pris vi vet ungefär vad det är. Hittas den
inte längre, eller kostar den plötsligt 165 kronor i stället för 16,50, har
något gått sönder mellan kedjans sida och vår databas - och det syns samma
morgon i stället för när en kund undrar varför mjölken kostar som en oxfilé.

VARORNA ÄR VERIFIERADE, INTE VALDA PÅ KÄNSLA. Varje rad nedan står redan i
providerns egen utredning, med datum och observerat pris. Ingen kedja får en
kanariefågel på gissning: en kedja utan verifierad vara rapporterar
`configured: False`, vilket är ett ärligt "vi vet inte" och inte ett tyst
godkänt.

INTERVALLEN ÄR VIDA MED FLIT. De ska INTE fånga att mjölken gått upp en
krona - det är inte ett fel, det är en prisändring, och det är hela poängen
med Matjakt. De ska fånga storleksordningsfel: öre tolkade som kronor, ett
paketpris där ett kilopris ska stå, en tom eller felmappad prisrad. Ett
intervall som larmar på verkliga prisrörelser blir ett larm man slutar läsa.
"""

import logging

logger = logging.getLogger("matjakt.grocery.canary")

CANARIES = {
    # Verifierad live 2026-08-30 (providers/citygross.py, providers/hemkop.py):
    # samma GTIN fanns hos alla tre kedjorna, till 16,50 hos Willys och City
    # Gross och 17,70 hos Hemköp. Att det är samma vara i tre kedjor är också
    # en poäng i sig - kanariefågeln kontrollerar då korsmatchningen på köpet.
    "Willys": {
        "gtin": "07340083443893",
        "name": "Mellanmjölk Längre Hållbarhet 1,5 l (GARANT)",
        "observed": 16.50, "observed_at": "2026-08-30",
        "min_price": 5.0, "max_price": 60.0,
    },
    "Hemköp": {
        "gtin": "07340083443893",
        "name": "Mellanmjölk Längre Hållbarhet 1,5 l (GARANT)",
        "observed": 17.70, "observed_at": "2026-08-30",
        "min_price": 5.0, "max_price": 60.0,
    },
    "City Gross": {
        "gtin": "07340083443893",
        "name": "Mellanmjölk Längre Hållbarhet 1,5 l (GARANT)",
        "observed": 16.50, "observed_at": "2026-08-30",
        "min_price": 5.0, "max_price": 60.0,
    },
    # Verifierad live 2026-09-02 mot Primats /prices och /batch
    # (providers/primat.py, testfixturen i tests/test_primat_provider.py).
    "Lidl": {
        "gtin": "07310865093530",
        "name": "Klyftpotatis 750 g (Harvest Basket)",
        "observed": 10.90, "observed_at": "2026-09-02",
        "min_price": 3.0, "max_price": 40.0,
    },
    # ICA och Coop saknar med flit rad här. Ingen vara ur de kedjorna är
    # verifierad härifrån med både GTIN och observerat pris, och en
    # kanariefågel man hittat på är sämre än ingen alls: den ger ett grönt
    # svar på en fråga ingen ställt. Lägg till raden samma dag som en
    # körning har bekräftat en vara.
}


def _price_row(store, chain: str, gtin: str):
    return store.connection.execute(
        """
        SELECT cp.regular_price, cp.campaign_price, cp.fetched_at, p.name
        FROM grocery_current_prices cp
        JOIN grocery_products p ON p.id = cp.product_id
        -- Prisradens EGEN butik avgör kedjan. Att gå via produkten hade
        -- låtit en kedjas pris svara för en annans så fort ett GTIN delas.
        JOIN grocery_stores st ON st.id = cp.store_id
        WHERE st.chain = ? AND p.gtin = ?
        ORDER BY cp.fetched_at DESC
        LIMIT 1
        """,
        (chain, gtin),
    ).fetchone()


def check(store, chain: str) -> dict:
    """Kanariefågeln för en kedja, läst ur den publicerade prisbilden.

    Läser `grocery_current_prices` - alltså det kunderna faktiskt får -
    och inte staging. En vara som staged men inte publicerats har ingen
    kund sett, och då är det inte den vi ska larma om."""
    canary = CANARIES.get(chain)
    if not canary:
        return {"chain": chain, "configured": False, "ok": True,
                "reason": "ingen verifierad kanariefågel för kedjan"}
    resultat = {"chain": chain, "configured": True, "gtin": canary["gtin"],
                "expected": canary["name"], "price": None}
    try:
        rad = _price_row(store, chain, canary["gtin"])
    except Exception as fel:               # trasig databas ska inte fälla kollen
        logger.exception("Kanariekollen för %s kunde inte läsa databasen", chain)
        return {**resultat, "ok": True, "reason": f"kunde inte läsas ({type(fel).__name__})"}

    if rad is None:
        return {**resultat, "ok": False,
                "reason": (f"{canary['name']} (GTIN {canary['gtin']}) finns inte längre "
                           f"i {chain}s prisbild - varan fanns där {canary['observed_at']}")}

    pris = rad["campaign_price"] or rad["regular_price"]
    resultat["price"] = pris
    if pris is None:
        return {**resultat, "ok": False,
                "reason": f"{canary['name']} finns hos {chain} men utan pris"}
    if not (canary["min_price"] <= pris <= canary["max_price"]):
        return {**resultat, "ok": False,
                "reason": (f"{canary['name']} kostar {pris:.2f} kr hos {chain} - utanför "
                           f"{canary['min_price']:.0f}-{canary['max_price']:.0f} kr "
                           f"(observerat {canary['observed']:.2f} kr {canary['observed_at']})")}
    return {**resultat, "ok": True, "reason": None}


def check_all(store, chains=None) -> list:
    """Alla kedjor med en kanariefågel, eller de som anges."""
    kedjor = list(chains) if chains is not None else list(CANARIES)
    return [check(store, chain) for chain in kedjor]


def log_result(resultat: dict) -> dict:
    """Skriver utfallet i loggen. Returnerar samma dict, så anroparen kan
    skriva `canary.log_result(canary.check(...))`."""
    if not resultat.get("configured"):
        logger.info("Kanariekoll %s: ingen kanariefågel konfigurerad", resultat.get("chain"))
    elif resultat.get("ok"):
        logger.info("Kanariekoll %s: %s kostar %s kr - rimligt",
                    resultat.get("chain"), resultat.get("expected"), resultat.get("price"))
    else:
        logger.error("Kanariekoll %s MISSLYCKADES: %s",
                     resultat.get("chain"), resultat.get("reason"))
    return resultat
