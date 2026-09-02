# -*- coding: utf-8 -*-
"""Primat-provider - ICA, Coop och Lidl via Primats betal-API i stället för
kedjornas egna webbplatser.

VARFÖR DENNA VÄG (utredd och live-verifierad 2026-09-02):
  - ICA: gamla apimgw-pub.ica.se dog i april 2024; dagens handla.ica.se
    kräver butiksval i ett robots-förbjudet flöde och ICA Gruppens villkor
    kräver skriftligt godkännande för kommersiell vidareanvändning. Ingen
    tillåten direktväg finns.
  - Coop: portal.api.coop.se är låst till Coops interna Azure AD-tenant -
    extern registrering går inte; coop.se:s villkor förbjuder kopiering.
  - Lidl: lidl.se publicerar inga ordinarie hyllpriser alls (bara kampanjer)
    och Lidl Plus-villkoren utesluter kommersiellt bruk.
  - Primat (https://primat.nu) tillåter uttryckligen kommersiellt byggande,
    täcker alla sex kedjorna med butiksspecifika priser, GTIN, kampanj- och
    medlemspriser. Butiksspecifika ICA-priser bevisade: 60 av 87 gemensamma
    GTIN skilde i pris mellan två Gävle-Maxi. Attribution krävs bara på
    gratisnivån (PRIMAT_ATTRIBUTION i services/pricing används redan).

ARKITEKTUR: samma mönster som övriga providers - hela butikskatalogen in i
grocery-databasen, sedan sköter den befintliga kanoniska matchningen och
prissättningsmotorn resten. Primats /products-SÖKNING används medvetet INTE
för prissättning: dess relevansrankning är brusig ("ägg" gav "Billinge ost"
hos Lidl) och Matjakts matcher är redan release-gate-testad.

Två anrop per katalog: GET /prices (butikens alla prisrader, cursor-
paginerade) ger pris/gtin/namn men SAKNAR paketstorlek och kategori;
POST /batch (100 uppslag/anrop) kompletterar med package/amount/unit/
category/jämförpris. Rader utan paketdata blir RawProduct med size=None -
prissättningsmotorn behandlar dem fail-closed (osäker rad, aldrig i säkra
totaler), precis som för alla andra kedjor.

KVOT OCH TAKT: gratisnivån är 60 anrop/min, 20 000 rader/dag, 200 rader/
anrop (App-nivån 250/min, 100 000 rader/dag). Providern håller sig under
takgränsen med en paus mellan anropen och slutar hämta vid max_rows - det
som redan hämtats behålls och körningen märks "blocked" med ärligt besked,
aldrig tyst trunkerad. Inga kringgåenden: träffar vi en gräns rapporterar
vi den.

NYCKELN läses ur miljön (PRIMAT_API_KEY), loggas aldrig och ingår aldrig i
någon RawProduct eller något felmeddelande.
"""

import logging
import os
import time
from datetime import datetime

from services.pricing.primat_client import PrimatError, _request

from ..base import GroceryProvider
from ..errors import ProviderBlockedError
from ..models import RawProduct, Store
from .citygross import normalize_gtin14

logger = logging.getLogger("matjakt.grocery.primat")

# Matjakts kedjenamn -> Primats kedjenycklar, alla sex. (primat_client.py:s
# CHAIN_TO_PRIMAT utelämnar medvetet Lidl/City Gross för fynd-flödet - här
# behövs hela kartan eftersom katalogimport ska kunna peka på vilken kedja
# som helst som Primat täcker.)
CHAIN_KEYS = {
    "ICA": "ica",
    "Coop": "coop",
    "Willys": "willys",
    "Hemköp": "hemkop",
    "Lidl": "lidl",
    "City Gross": "citygross",
}

# Matjakt är nationell - butikslistan är HELA svenska registret (GET /stores,
# ~2 800 butiker i ett anrop), aldrig ett postnummeruppslag. Vilka butiker som
# faktiskt importeras väljs av anroparen (efterfrågestyrt per användarort).

# Gratisnivåns tak är 200 rader/anrop; ett högre limit-värde skadar inte
# (servern klipper själv) men 200 håller sidorna förutsägbara.
PAGE_LIMIT = 200
BATCH_SIZE = 100

# 60 anrop/min på gratisnivån. 1.1 s mellanrum = ~54/min med marginal,
# utan att en Maxi-katalog (~225 anrop) tar mer än ~5 minuter.
SECONDS_BETWEEN_CALLS = 1.1


def _epoch(iso_timestamp) -> float | None:
    """"2026-09-02T03:32:13Z" -> epoktid. None in, None ut."""
    if not iso_timestamp:
        return None
    try:
        return datetime.fromisoformat(str(iso_timestamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class PrimatProvider(GroceryProvider):
    name = "primat"

    def __init__(self, chain: str, api_key: str | None = None,
                 max_rows: int | None = None):
        if chain not in CHAIN_KEYS:
            raise ValueError(f"Primat täcker inte kedjan {chain!r}")
        if max_rows is None:
            # Styrbart utan koddeploy: gratisnivån har 20 000 rader/dag och
            # en full Maxi-katalog kostar ~30 000 (pris + batch), så på
            # gratisnivån behöver taket sättas lägre än standardvärdet.
            max_rows = int(os.environ.get("PRIMAT_MAX_ROWS_PER_RUN", "40000"))
        self.chain = chain
        self._primat_chain = CHAIN_KEYS[chain]
        self._api_key = api_key or os.environ.get("PRIMAT_API_KEY") or None
        # Tak för hur många datarader (prisrader + batchsvar) en körning får
        # kosta av dagskvoten. Nås taket avbryts hämtningen ÄRLIGT - det
        # hämtade behålls och körningen rapporteras "blocked", se
        # get_products.
        self._max_rows = max_rows
        self._rows_spent = 0
        self._last_call = 0.0

    # ------------------------------------------------------------------ API
    def _call(self, method: str, path: str, params=None, body=None):
        if not self._api_key:
            raise PrimatError("PRIMAT_API_KEY är inte satt - Primat-import kräver nyckeln i miljön")
        wait = SECONDS_BETWEEN_CALLS - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()
        return _request(method, path, api_key=self._api_key, params=params, body=body)

    # ---------------------------------------------------------------- stores
    def get_stores(self) -> list[Store]:
        """Kedjans ALLA svenska butiker, ur Primats nationella register
        (GET /stores - hela landet i ett anrop, med adress, postnummer, ort
        och koordinater).

        Butiker med täckningsnivån "offers_only" (bara kampanjrader, inga
        ordinarie priser) markeras active=False: de duger inte till att
        prissätta en matkorg, och att importera dem vore att bygga en
        katalog där nästan varje rad saknar pris."""
        result = self._call("GET", "/stores")
        stores = []
        for row in result.get("data", []):
            if row.get("chain") != self._primat_chain or not row.get("store_id"):
                continue
            coordinates = row.get("coordinates") or {}
            stores.append(Store(
                id=0, chain=self.chain,
                external_store_id=str(row["store_id"]),
                name=row.get("name") or "", city=row.get("city"),
                postal_code=(row.get("postcode") or "").replace(" ", "") or None,
                address=row.get("address"),
                latitude=coordinates.get("latitude"),
                longitude=coordinates.get("longitude"),
                active=(row.get("tier") == "full"),
                provider="primat"))
        return stores

    # -------------------------------------------------------------- products
    def get_products(self, store_id: str) -> list[RawProduct]:
        store_key = f"{self._primat_chain}:{store_id}"

        # Steg 1: butikens prisrader (flata: pris/gtin/namn, ingen paket-
        # storlek). Halva radbudgeten reserveras åt steg 2 - varje hämtad
        # produkt kostar en batchrad till, och en katalog UTAN paketdata
        # vore bara fail-closed-rader.
        price_budget = self._max_rows // 2
        price_rows: list[dict] = []
        cursor = None
        truncated = False
        while True:
            params = {"stores": store_key, "limit": PAGE_LIMIT}
            if cursor:
                params["cursor"] = cursor
            page = self._call("GET", "/prices", params=params)
            rows = page.get("data") or []
            price_rows.extend(rows)
            self._rows_spent += len(rows)
            cursor = page.get("next_cursor")
            if not cursor or not rows:
                break
            if self._rows_spent >= price_budget:
                truncated = True
                logger.warning("Primat %s: radbudgeten (%d för priser av %d totalt) "
                               "nådd - katalogen blir partiell men komplett per rad",
                               store_key, price_budget, self._max_rows)
                break

        # Steg 2: paketstorlek/kategori/jämförpris via /batch för ALLT som
        # hämtades - även vid trunkering, så en partiell katalog består av
        # kompletta rader i stället för många paketlösa.
        details: dict[str, dict] = {}
        for start in range(0, len(price_rows), BATCH_SIZE):
            if self._rows_spent >= self._max_rows:
                truncated = True
                logger.warning("Primat %s: radtaket %d nått under /batch - "
                               "resterande rader saknar paketdata", store_key, self._max_rows)
                break
            chunk = price_rows[start:start + BATCH_SIZE]
            lookups = [{"chain": self._primat_chain, "store_id": store_id,
                        "product_id": row.get("product_id")} for row in chunk]
            result = self._call("POST", "/batch", body={"lookups": lookups})
            for entry in result.get("data", []):
                for product in entry.get("results", []) or []:
                    pid = product.get("product_id")
                    if pid:
                        details[pid] = product
            self._rows_spent += len(chunk)

        products = []
        for row in price_rows:
            normalized = self.normalize_product((row, details.get(row.get("product_id")), store_id))
            if normalized is not None:
                products.append(normalized)

        if truncated:
            # Ärligt avbrott i stället för tyst partiell katalog: det som
            # hämtats sparas av importern (partial_products), körningen
            # märks "blocked" och beskedet säger varför.
            raise ProviderBlockedError(
                f"Primats radtak ({self._max_rows} rader) nåddes - {len(products)} "
                f"produkter sparade, resten av katalogen väntar på nästa körning/kvot",
                partial_products=products)
        return products

    def health_check(self) -> bool:
        """Ett billigt /me-anrop: nås Primat och gäller nyckeln? Svarar
        också nej när kvoten i praktiken är slut för dagen."""
        try:
            me = self._call("GET", "/me")
        except PrimatError:
            return False
        plan = me.get("plan") or {}
        used = plan.get("rows_returned_today")
        cap = plan.get("rows_per_day")
        if used is not None and cap is not None and used >= cap:
            return False
        return bool(me.get("user"))

    def get_product_details(self, product_id: str, store_id: str) -> RawProduct | None:
        try:
            product = self._call(
                "GET", f"/products/{self._primat_chain}/{store_id}/{product_id}")
        except PrimatError:
            return None
        if not product or not product.get("product_id"):
            return None
        price_shape = self._detail_to_price_row(product)
        return self.normalize_product((price_shape, product, store_id))

    @staticmethod
    def _detail_to_price_row(product: dict) -> dict:
        """Ett /products-detaljsvar (nästlade prices{}) till samma flata form
        som /prices-raderna, så normalize_product bara behöver EN form."""
        prices = product.get("prices") or {}
        offer = prices.get("offer") or {}
        multi = prices.get("multiprice") or {}
        return {
            "chain": product.get("chain"), "store_id": product.get("store_id"),
            "product_id": product.get("product_id"), "name": product.get("name"),
            "brand": product.get("brand"), "gtin": product.get("gtin"),
            "changed_at": product.get("changed_at"),
            "price": prices.get("regular"), "member_price": prices.get("member"),
            "multi_price": multi.get("price"), "multi_count": multi.get("quantity"),
            "effective_price": prices.get("effective"),
            "offer_price": offer.get("price"), "offer_label": offer.get("label"),
            "offer_valid_until": offer.get("valid_until"),
        }

    def normalize_product(self, raw_product) -> RawProduct | None:
        """(prisrad, batchdetalj-eller-None, store_id) -> RawProduct.

        FAIL CLOSED: en rad helt utan pris (varken ordinarie eller effektivt
        - typiskt kampanjskuggor i offers_only-data) blir None och sparas
        inte alls. Hellre en saknad produkt än en produkt som ser prissatt
        ut men inte är det."""
        price_row, detail, store_id = raw_product
        detail = detail or {}

        regular = price_row.get("price")
        offer_price = price_row.get("offer_price")
        effective = price_row.get("effective_price")
        if regular is None and effective is None and offer_price is None:
            return None

        # Kampanjpris bara när det faktiskt är LÄGRE än ordinarie (samma
        # regel som City Gross-providern): "offer" med samma belopp är bara
        # skyltning, och ett högre värde vore fel att kalla kampanj.
        campaign = None
        if offer_price is not None and (regular is None or offer_price < regular):
            campaign = offer_price

        comparison = (detail.get("prices") or {}).get("comparison") or {}
        urls = detail.get("urls") or {}

        return RawProduct(
            chain=self.chain,
            external_product_id=str(price_row.get("product_id")),
            name=price_row.get("name") or "",
            store_id=str(store_id),
            store_name="",
            gtin=normalize_gtin14(price_row.get("gtin")),
            brand=price_row.get("brand") or detail.get("brand"),
            size=detail.get("package"),
            quantity=detail.get("amount"),
            unit=detail.get("unit"),
            category=detail.get("category"),
            image_url=None,  # gratisnivån saknar bildfält; App-nivån ger
                             # kedjans original-URL utan bildrättigheter -
                             # Open Food Facts-fallbacken är kvar rätt väg.
            regular_price=regular,
            campaign_price=campaign,
            member_price=price_row.get("member_price"),
            multibuy_price=price_row.get("multi_price"),
            unit_price=comparison.get("price"),
            source_url=urls.get("source"),
            fetched_at=_epoch(detail.get("confirmed_at") or price_row.get("changed_at")),
        )
