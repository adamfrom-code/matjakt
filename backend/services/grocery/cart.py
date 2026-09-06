# -*- coding: utf-8 -*-
"""Köp hela listan: FÖRBEREDELSE, inte en färdig funktion (§22).

Vad som finns här och varför just det:

Matjakt säljer inte mat. Butiken sköter kassa, betalning, leverans och
slutpris. Det Matjakt kan göra är att lämna över korgen så långt kedjan
tillåter, och att vara ärlig om hur långt det räckte. Den ärligheten är
hela poängen med den här modulen: en överföring som tyst tappar sex av
tjugo varor är värre än ingen överföring alls.

FYRA NIVÅER, i fallande ordning. En kedja stödjer den nivå den stödjer;
vi hittar inte på en högre.

  FULL_CART_API        kedjan har ett API som tar emot hela korgen
  BULK_LIST_IMPORT     kedjan tar emot en lista (text/CSV) att importera
  PRODUCT_DEEPLINK     en länk per produkt - användaren lägger i korgen
  STORE_HOMEPAGE_FALLBACK  bara butikens sida; listan finns kvar i Matjakt

INGA DOM-HACK. Att styra en butiks webbsida med skript är sprött (en
layoutändring och funktionen är död), och det ser för butiken ut som
automatiserad trafik. Varje provider här talar mot något butiken själv
publicerat, eller så säger den PRODUCT_DEEPLINK/STORE_HOMEPAGE_FALLBACK.

STATUS 2026-09-06: ingen kedja har en avtalad väg in. Registret nedan är
därför tomt på riktiga providers, och `capability_for` svarar
STORE_HOMEPAGE_FALLBACK för alla. Willys är tänkt POC när frågan om
villkor är löst - se docs/KOP_HELA_LISTAN.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FULL_CART_API = "FULL_CART_API"
BULK_LIST_IMPORT = "BULK_LIST_IMPORT"
PRODUCT_DEEPLINK = "PRODUCT_DEEPLINK"
STORE_HOMEPAGE_FALLBACK = "STORE_HOMEPAGE_FALLBACK"

# Fallande ordning: den första en provider klarar är den vi använder.
CAPABILITIES = (FULL_CART_API, BULK_LIST_IMPORT, PRODUCT_DEEPLINK, STORE_HOMEPAGE_FALLBACK)


@dataclass(frozen=True)
class BasketLine:
    """En rad på väg till butikens korg.

    `gtin` och `external_product_id` är det som gör överföringen exakt.
    Saknas båda kan raden bara överföras som TEXT, och det ska synas i
    resultatet - inte tystas ner."""
    name: str
    quantity: int = 1
    gtin: str | None = None
    external_product_id: str | None = None
    note: str | None = None

    @property
    def transferable_exactly(self) -> bool:
        return bool(self.gtin or self.external_product_id)


@dataclass
class CheckoutBasket:
    """Hela korgen plus vilken kedja och butik den gäller."""
    chain: str
    store_id: str | None = None
    lines: list[BasketLine] = field(default_factory=list)

    def add(self, line: BasketLine):
        self.lines.append(line)

    @property
    def exact_lines(self) -> list[BasketLine]:
        return [line for line in self.lines if line.transferable_exactly]


@dataclass
class HandoffResult:
    """Vad som faktiskt gick över, och vad som inte gjorde det.

    `unmatched` är inte ett fel utan ett SVAR: de raderna finns kvar i
    Matjakt och användaren får veta att de måste läggas i manuellt. En
    tom `unmatched` som döljer sex tappade varor är den bugg den här
    klassen är byggd för att omöjliggöra."""
    capability: str
    url: str | None = None
    transferred: int = 0
    unmatched: list[str] = field(default_factory=list)
    message: str = ""

    @property
    def complete(self) -> bool:
        return not self.unmatched


class CartProvider:
    """Basklassen en kedja implementerar när en väg in faktiskt finns."""

    chain: str = ""
    capability: str = STORE_HOMEPAGE_FALLBACK

    def handoff(self, basket: CheckoutBasket) -> HandoffResult:
        raise NotImplementedError


class StoreHomepageProvider(CartProvider):
    """Sista utvägen: öppna butikens sida, behåll listan i Matjakt.

    Ärlig och alltid tillgänglig. Den här används tills en kedja har en
    avtalad väg in - och den lovar ingenting den inte håller."""

    def __init__(self, chain: str, homepage: str):
        self.chain = chain
        self.homepage = homepage

    def handoff(self, basket: CheckoutBasket) -> HandoffResult:
        return HandoffResult(
            capability=STORE_HOMEPAGE_FALLBACK,
            url=self.homepage,
            transferred=0,
            unmatched=[line.name for line in basket.lines],
            message=f"{self.chain} tar inte emot en färdig korg än. Listan finns kvar här.",
        )


# Kedja -> provider. TOM med flit: ingen kedja har en avtalad väg in
# 2026-09-06, och en påhittad post här hade blivit ett löfte i gränssnittet.
PROVIDERS: dict[str, CartProvider] = {}

STORE_HOMEPAGES = {
    "Willys": "https://www.willys.se/",
    "Hemköp": "https://www.hemkop.se/",
    "City Gross": "https://www.citygross.se/",
    "ICA": "https://www.ica.se/",
    "Coop": "https://www.coop.se/",
    "Lidl": "https://www.lidl.se/",
}


def provider_for(chain: str) -> CartProvider:
    provider = PROVIDERS.get(chain)
    if provider:
        return provider
    return StoreHomepageProvider(chain, STORE_HOMEPAGES.get(chain, "https://www.google.com/search?q=" + chain))


def capability_for(chain: str) -> str:
    """Vad Matjakt kan lova för den här kedjan just nu. Frontend ska fråga
    HÄRIFRÅN och aldrig anta - en knapp som säger "Köp hela listan" på en
    kedja som bara klarar en hemsidalänk är ett löfte vi inte håller."""
    return provider_for(chain).capability


def basket_from_items(chain: str, items: list[dict], store_id: str | None = None) -> CheckoutBasket:
    """Bygger korgen ur samma radformat som Handla använder."""
    basket = CheckoutBasket(chain=chain, store_id=store_id)
    for item in items or []:
        name = str(item.get("name") or item.get("namn") or "").strip()
        if not name:
            continue
        product = item.get("product") or {}
        basket.add(BasketLine(
            name=name,
            quantity=max(1, int(item.get("packages") or item.get("quantity") or 1)),
            gtin=(product.get("gtin") or item.get("gtin")) or None,
            external_product_id=(product.get("productId") or item.get("productId")) or None,
        ))
    return basket
