# -*- coding: utf-8 -*-
"""Moms: är 59 kr inklusive eller exklusive 25 %?

Fram till B2 visste varken koden, Stripe eller kvittot. Checkout skickade
varken automatic_tax, customer_update eller tax_id_collection, och
startkontrollen läste bara beloppet - 5900 SEK/månad var "ok" oavsett om
Stripe betraktade summan som brutto eller netto. Skillnaden är 11,80 kr per
månadskund som antingen finns eller inte finns i bokföringen.

Svensk konsumentprissättning ska anges INKLUSIVE moms (prisinformationslagen
kräver totalpris till konsument), så `tax_behavior: "inclusive"` är rätt
svar och allt annat är ett fel som ska synas.

Modulen gör två saker:

* ``price_verdict`` avgör om ett Stripe-pris duger. Den är ren - in går
  prisobjektet som Stripe beskriver det, ut kommer "ok" eller en kort
  svensk orsak. Både uppstartskontrollen och kontrollrummet läser samma
  dom, så de aldrig kan säga olika saker om samma pris.
* ``tax_readiness`` frågar Stripe om Stripe Tax faktiskt är aktiverat.
  Svaret avgör om checkout får skicka ``automatic_tax[enabled]=true``.

Varför det sista är villkorat: automatic_tax mot ett konto utan aktiverad
Stripe Tax gör att Stripe vägrar skapa sessionen. Köpknappen hade slutat
fungera för alla i glappet mellan att koden deployas och att någon hinner
klicka i dashboarden. I stället upptäcker servern själv när dashboarden är
klar, och tills dess står det i /api/health och i kontrollrummet att momsen
inte är påslagen - synligt, inte gissat.
"""

import logging

from .stripe_client import StripeError, fetch_tax_settings

logger = logging.getLogger("matjakt.billing.tax")

# Rätt för svensk konsumentprissättning: priset ÄR totalpriset kunden betalar.
EXPECTED_TAX_BEHAVIOR = "inclusive"


def price_verdict(price, expected_amount, expected_interval, expected_currency="sek") -> str:
    """"ok", eller en kort svensk mening om vad som är fel med priset."""
    price = price if isinstance(price, dict) else {}
    recurring = price.get("recurring") if isinstance(price.get("recurring"), dict) else {}
    amount = price.get("unit_amount")
    currency = (price.get("currency") or "").lower()
    interval = recurring.get("interval")
    if amount != expected_amount or currency != expected_currency or interval != expected_interval:
        return (f"fel pris: {(amount or 0) / 100:.0f} "
                f"{(price.get('currency') or '').upper()}/{interval}")
    if not price.get("active"):
        return "priset är inaktivt i Stripe"
    if recurring.get("trial_period_days"):
        return "provperiod ligger på priset"
    behavior = price.get("tax_behavior")
    if behavior != EXPECTED_TAX_BEHAVIOR:
        # Den viktiga meningen i hela paketet. "unspecified" är Stripes
        # standard och betyder att ingen någonsin bestämt sig.
        return (f"moms saknas: tax_behavior={behavior or 'saknas'} "
                f"(ska vara {EXPECTED_TAX_BEHAVIOR})")
    return "ok"


def tax_readiness(secret_key, fetch=fetch_tax_settings) -> dict:
    """Är Stripe Tax aktiverat på kontot?

    Returnerar ``{"active": bool, "status": str|None, "reason": str|None}``.
    Allt som inte är ett tydligt "active" räknas som inte aktiverat - ett
    nätfel får aldrig läsas som klartecken, för klartecknet är det som
    skickar automatic_tax till Stripe.
    """
    if not secret_key:
        return {"active": False, "status": None, "reason": "Stripe är inte konfigurerat"}
    try:
        settings = fetch(secret_key)
    except StripeError as error:
        return {"active": False, "status": None, "reason": str(error)}
    except Exception as error:                       # aldrig ett stopp för uppstarten
        # Fångas brett med avsikt: den här funktionen körs i uppstartstråden
        # och i kontrollrummet, och ingen av dem får dö av ett oväntat svar.
        # Riktningen är säker - allt som inte är ett tydligt "active" gör att
        # automatic_tax INTE skickas.
        logger.warning("Stripe Tax-inställningarna kunde inte läsas: %s", error)
        return {"active": False, "status": None, "reason": "kunde inte läsas"}
    settings = settings if isinstance(settings, dict) else {}
    status = settings.get("status")
    if status == "active":
        return {"active": True, "status": status, "reason": None}
    details = settings.get("status_details") if isinstance(settings.get("status_details"), dict) else {}
    pending = details.get("pending") if isinstance(details.get("pending"), dict) else {}
    missing = pending.get("missing_fields")
    reason = "Stripe Tax är inte aktiverat"
    if missing:
        reason = f"Stripe Tax saknar {', '.join(str(field) for field in missing)}"
    return {"active": False, "status": status, "reason": reason}


def automatic_tax_allowed(check: dict) -> bool:
    """Får checkout skicka automatic_tax[enabled]=true?

    Bara när BÅDA halvorna är på plats: Stripe Tax aktiverat på kontot och
    varje konfigurerat pris satt inklusive moms. Halva vägen är inte en
    halv förbättring - det är en session Stripe vägrar skapa, eller en
    faktura utan moms på ett pris som säger sig innehålla den.
    """
    check = check if isinstance(check, dict) else {}
    tax = check.get("automaticTax") if isinstance(check.get("automaticTax"), dict) else {}
    return bool(tax.get("ready"))
