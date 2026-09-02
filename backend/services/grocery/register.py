# -*- coding: utf-8 -*-
"""Det nationella butiksregistret - alla svenska butiker Matjakt känner till.

Matjakt är en nationell tjänst; Gävle är bara första testmarknaden. Registret
gör butiksmodellen datadriven: EN källa (Primats /stores, hela svenska
registret i ett anrop - 2 825 butiker verifierat 2026-09-02) fyller
grocery_stores med kedja, butiks-id, namn, adress, postnummer, ort och
koordinater, så att postnummer -> närliggande butiker kan besvaras helt ur
egen databas utan API-anrop per uppslag.

PRISSÄTTNINGSMODELL PER KEDJA (pricing_scope) - kedjorna är olika på
riktigt och modellen ska inte låtsas något annat:

  NATIONAL        Samma pris i hela landet. EN importerad katalog gäller
                  varje butik i kedjan. Willys/Hemköp: verifierat - deras
                  endpoints ignorerar storeId (byte-identiska svar för olika
                  butiker, se providers/willys.py). Lidl: kedjans egen
                  profil är enhetliga rikspriser.
  STORE_SPECIFIC  Varje butik sätter egna priser. BARA butiker vars katalog
                  faktiskt importerats får prissättas - att visa en annan
                  butiks priser vore fel data. ICA: bevisat (60 av 87
                  gemensamma GTIN skilde mellan två Gävle-Maxi). Coop:
                  butiksscopade rader hos Primat. City Gross: butiksscopad
                  sökning (store=storeNumber), konservativt butiksspecifik.
  REGIONAL        Reserverad för kedjor med prisregioner - ingen känd ännu.

provider-kolumnen säger vilken datakälla som levererar KEDJANS priser
(axfood/citygross-providrarna för de tre släppta kedjorna, Primat för
ICA/Coop/Lidl). Registret själv är geografi och får aldrig ensamt göra en
butik prissättningsbar.
"""

import logging

from services.pricing.primat_client import PrimatError, _request

logger = logging.getLogger("matjakt.grocery.register")

PRIMAT_TO_CHAIN = {
    "ica": "ICA", "coop": "Coop", "willys": "Willys",
    "hemkop": "Hemköp", "lidl": "Lidl", "citygross": "City Gross",
}

CHAIN_PRICING_SCOPE = {
    "Willys": "NATIONAL",
    "Hemköp": "NATIONAL",
    "Lidl": "NATIONAL",
    "ICA": "STORE_SPECIFIC",
    "Coop": "STORE_SPECIFIC",
    "City Gross": "STORE_SPECIFIC",
}

CHAIN_PRICE_PROVIDER = {
    "Willys": "axfood",
    "Hemköp": "axfood",
    "City Gross": "citygross",
    "ICA": "primat",
    "Coop": "primat",
    "Lidl": "primat",
}


def fetch_national_register(api_key: str) -> list[dict]:
    """Primats hela svenska butiksregister, mappat till Matjakts kedjenamn.

    Raden bär tier ("full" = helt sortiment med priser hos Primat,
    "offers_only" = bara kampanjrader) - avgörande för vilka
    STORE_SPECIFIC-butiker som ens KAN få en katalog importerad."""
    result = _request("GET", "/stores", api_key=api_key)
    rows = []
    for row in result.get("data", []):
        chain = PRIMAT_TO_CHAIN.get(row.get("chain"))
        if not chain or not row.get("store_id"):
            continue
        coordinates = row.get("coordinates") or {}
        rows.append({
            "chain": chain,
            "external_store_id": str(row["store_id"]),
            "name": row.get("name") or "",
            "city": row.get("city"),
            "postal_code": (row.get("postcode") or "").replace(" ", "") or None,
            "address": row.get("address"),
            "latitude": coordinates.get("latitude"),
            "longitude": coordinates.get("longitude"),
            "tier": row.get("tier"),
        })
    return rows


def sync_store_register(db, api_key: str) -> dict:
    """Skriver hela nationella registret till grocery_stores.

    active-flaggan betyder "kan den här butikens priser över huvud taget
    finnas hos Matjakt": för NATIONAL-kedjor är varje butik aktiv (kedjans
    katalog gäller den), för STORE_SPECIFIC-kedjor bara full-tier-butiker
    (offers_only kan aldrig ge en hel matkorg). Kostar ~2 800 rader av
    Primat-dygnskvoten - körs veckovis, inte nattligt: butiker byter inte
    adress varje dag.

    Rör ALDRIG priser: registret är geografi. Befintliga butiksrader (de
    tre släppta kedjornas importbutiker) berikas med adress/koordinater
    via samma upsert - deras priser och katalogkoppling påverkas inte."""
    rows = fetch_national_register(api_key)
    per_chain: dict[str, int] = {}
    for row in rows:
        chain = row["chain"]
        scope = CHAIN_PRICING_SCOPE.get(chain, "STORE_SPECIFIC")
        active = True if scope == "NATIONAL" else row.get("tier") == "full"
        db.upsert_store(
            chain=chain, external_store_id=row["external_store_id"],
            name=row["name"], city=row["city"], postal_code=row["postal_code"],
            address=row["address"], latitude=row["latitude"], longitude=row["longitude"],
            active=active, provider=CHAIN_PRICE_PROVIDER.get(chain),
            pricing_scope=scope)
        per_chain[chain] = per_chain.get(chain, 0) + 1
    logger.info("Butiksregistret synkat: %s", per_chain)
    return {"totalt": sum(per_chain.values()), "perKedja": per_chain}
