# -*- coding: utf-8 -*-
"""OSS: den första kunden utanför Sverige, upptäckt när hon dyker upp.

Prenumerationen går att köpa från vilket EU-land som helst, och då gäller
KÖPARLANDETS momssats via One Stop Shop. Stripe Tax räknar rätt sats av sig
självt - men OSS-REGISTRERINGEN är Adams, och den görs hos Skatteverket, inte
i en dashboard.

B2 kontrollerade prisobjekten och kontots skatteinställningar. Den läste
aldrig kundernas adresser, så den första tyska kunden hade varit osynlig
tills en granskning hittade henne - och då med retroaktiv moms i ett land vi
inte var registrerade i.

Den här modulen är den saknade halvan: den frågar Stripe vilka BETALANDE
kunder som har en adress utanför Sverige, och larmar på den första.

TRE SAKER SOM ÄR MEDVETNA

**Bara betalande kunder räknas.** En avslutad prenumeration i Tyskland är
ingen pågående OSS-skyldighet. LIVE_STATUSES är samma mängd som avstämningen
i B1 använder, av samma skäl: "levande nog att äga kontot".

**Okänd adress är inte ett larm.** Vi kan inte påstå att en kund är
utländsk för att fältet är tomt. Den räknas i stället i `unknownCountry`, för
en växande sådan siffra betyder att `customer_update[address]=auto` inte
fungerar - och det är en annan sak att åtgärda.

**Larmet är ett larm, inte ett fel.** Momsen blir rätt ändå - Stripe Tax
räknar köparlandets sats. Det som saknas är en registrering, och det gör
kontrollrummet gult, inte rött: `ok` fortsätter handla om konfigurationen.
"""

import logging

from .reconcile import customer_id_of
from .stripe_client import list_subscriptions

logger = logging.getLogger("matjakt.billing.oss")

# Adam From, enskild firma, org.nr 199511045651, momsregistrerad i Sverige.
HOME_COUNTRY = "SE"
# Prenumerationer där kunden betalar eller väntas betala - alltså de som kan
# utlösa en OSS-skyldighet. Samma mängd som avstämningen i B1.
LIVE_STATUSES = ("active", "trialing", "past_due")
MAX_PAGES = 20


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def customer_country(subscription) -> str | None:
    """Kundens landskod ur en expanderad prenumeration, versaler eller None.

    Tre källor i tur och ordning, och ordningen är sanningsordning:

    1. `customer.address.country` - faktureringsadressen kunden angav i
       Checkout (B2 satte `customer_update[address]=auto` just för att den
       ska sparas i stället för att kastas bort när sessionen stängs).
    2. `customer.shipping.address.country` - reserv för kunder som skapades
       innan dess.
    3. `customer.tax.location.country` - Stripes EGEN bedömning, den som
       faktiskt avgjorde momssatsen på fakturan. Står den i konflikt med en
       gammal adress är det den här som gäller för OSS.
    """
    customer = _as_dict(_as_dict(subscription).get("customer"))
    candidates = [
        _as_dict(customer.get("address")).get("country"),
        _as_dict(_as_dict(customer.get("shipping")).get("address")).get("country"),
        _as_dict(_as_dict(customer.get("tax")).get("location")).get("country"),
    ]
    for candidate in candidates:
        if candidate and str(candidate).strip():
            return str(candidate).strip().upper()
    return None


def _summary(subscription, country) -> dict:
    customer = _as_dict(_as_dict(subscription).get("customer"))
    return {
        "subscriptionId": subscription.get("id"),
        "customerId": customer_id_of(subscription),
        "status": subscription.get("status"),
        "country": country,
        # Adressen behövs för att åtgärda fallet; vägen är admin-gated som
        # allt annat i kontrollrummet.
        "email": customer.get("email"),
        "created": subscription.get("created"),
    }


def foreign_customers(secret_key, *, statuses=LIVE_STATUSES, page_size=100,
                      list_page=None, home=HOME_COUNTRY) -> dict:
    """Betalande kunder med adress utanför `home`.

    Returnerar ett dikt avsett att gå rakt ut på admin-vägen:

    * `alarm` - sant så fort EN sådan kund finns. Det är hela paketet.
    * `countries` - vilka länder, sorterade. Det Adam behöver för att veta
      var registreringen ska göras.
    * `unknownCountry` - kunder utan adress alls. Inte ett larm, men en
      siffra som ska vara noll.
    * `truncated` - sant när Stripe hade fler sidor än vi hämtade. Då är
      listan ofullständig, och det ska SYNAS i stället för att gissas: en
      tom lista av fel skäl är värre än ingen lista.
    """
    # Slås upp HÄR, inte i signaturen: ett default som binds vid def-tid går
    # inte att byta ut, och då kan testerna inte hålla sig utanför nätet.
    list_page = list_page or list_subscriptions
    home = (home or HOME_COUNTRY).upper()
    foreign, checked, unknown, truncated = [], 0, 0, False
    for status in statuses:
        starting_after, pages = None, 0
        while True:
            page = list_page(secret_key, status=status, limit=page_size,
                             starting_after=starting_after)
            rows = [row for row in (_as_dict(page).get("data") or []) if isinstance(row, dict)]
            checked += len(rows)
            for row in rows:
                country = customer_country(row)
                if country is None:
                    unknown += 1
                elif country != home:
                    foreign.append(_summary(row, country))
            pages += 1
            if not _as_dict(page).get("has_more") or not rows:
                break
            if pages >= MAX_PAGES:
                truncated = True
                break
            starting_after = rows[-1].get("id")
    foreign.sort(key=lambda row: (row.get("country") or "", row.get("created") or 0))
    countries = sorted({row["country"] for row in foreign})
    return {
        "home": home,
        "checked": checked,
        "alarm": bool(foreign),
        "foreignCount": len(foreign),
        "foreign": foreign,
        "countries": countries,
        "unknownCountry": unknown,
        "truncated": truncated,
        "reason": _reason(countries, truncated),
    }


def _reason(countries, truncated) -> str | None:
    """En mening Adam kan agera på, eller None när allt är som det ska."""
    if not countries:
        return "ofullständig lista - Stripe hade fler sidor" if truncated else None
    lands = ", ".join(countries)
    return (f"betalande kunder med adress i {lands} - köparlandets momssats "
            f"gäller via OSS, och OSS-registreringen görs hos Skatteverket")


def unavailable(reason: str) -> dict:
    """Svaret när kontrollen inte gick att göra.

    Larmar INTE: ett nätfel mot Stripe är inte en tysk kund. Men det säger
    att kontrollen inte kördes, så ingen läser en tom lista som ett besked."""
    return {"home": HOME_COUNTRY, "checked": 0, "alarm": False, "foreignCount": 0,
            "foreign": [], "countries": [], "unknownCountry": 0, "truncated": False,
            "reason": reason, "available": False}
