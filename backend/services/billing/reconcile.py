"""Vägen tillbaka från en betalning till ett konto - och listan över när
den vägen brustit.

Två saker bor här, för de är samma fråga ställd i olika riktningar:

* ``matjakt_user_id`` läser ut vilket konto ett Stripe-objekt hör till när
  ``stripe_customer_id`` inte räcker. Webhooken använder den som andra
  försök innan den ger upp och ber Stripe komma tillbaka.
* ``orphan_subscriptions`` frågar Stripe vilka levande prenumerationer som
  finns och rapporterar dem vi inte kan knyta till ett konto. Det är den
  enda mekanism som hittar en kund som redan har betalat och blivit kvar på
  Free - webhooken kan bara rädda de fall den själv får se.

Modulen gör inga databasfrågor själv. Anroparen skickar in en funktion som
svarar på "känner vi det här kund-id:t?", så avstämningen kan testas utan
vare sig Stripe eller ett kontolager.
"""

from .stripe_client import list_subscriptions

# Prenumerationer där kunden betalar eller väntas betala - alltså de som
# ska motsvaras av Premium hos oss. En canceled prenumeration utan konto är
# inget problem; en active utan konto är en kund som betalar för ingenting.
LIVE_STATUSES = ("active", "trialing", "past_due")
MAX_PAGES = 20


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def matjakt_user_id(obj):
    """Kontots id ur ett Stripe-objekt, eller None.

    Letas i tur och ordning i prenumerationens metadata, i den expanderade
    kundens metadata och i ``client_reference_id`` (som Checkout Session
    bär). Allt tre sätts av stripe_client vid köp; att läsa alla tre gör
    fallbacken oberoende av vilket objekt som råkar komma in.

    Värdet är alltid en sträng hos Stripe och kan vara vad som helst - en
    manuellt redigerad metadata-rad i dashboarden till exempel. Därför
    returneras bara ett positivt heltal; allt annat är inget id.
    """
    obj = _as_dict(obj)
    candidates = [
        _as_dict(obj.get("metadata")).get("matjakt_user_id"),
        _as_dict(_as_dict(obj.get("customer")).get("metadata")).get("matjakt_user_id"),
        obj.get("client_reference_id"),
    ]
    for candidate in candidates:
        try:
            value = int(str(candidate).strip())
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def customer_id_of(obj):
    """Kund-id:t, oavsett om customer är ett id eller ett expanderat objekt."""
    customer = _as_dict(obj).get("customer")
    return customer.get("id") if isinstance(customer, dict) else customer


def _customer_email(subscription):
    customer = _as_dict(subscription.get("customer"))
    return customer.get("email") or None


def orphan_subscriptions(secret_key, is_known_customer, *, statuses=LIVE_STATUSES,
                         page_size=100, list_page=list_subscriptions):
    """Levande Stripe-prenumerationer utan matchande konto.

    ``is_known_customer`` får en lista kund-id och returnerar mängden av dem
    som finns på ett konto. Den frågas en gång per sida, inte en gång per
    rad.

    Returnerar ett dikt avsett att skickas rakt ut på admin-vägen:
    ``checked`` (hur många prenumerationer som lästes), ``orphans`` och
    ``truncated`` (sant om Stripe hade fler sidor än vi hämtade - då är
    listan ofullständig och det ska synas, inte gissas).
    """
    orphans, checked, truncated = [], 0, False
    for status in statuses:
        starting_after, pages = None, 0
        while True:
            page = list_page(secret_key, status=status, limit=page_size, starting_after=starting_after)
            rows = [row for row in (page.get("data") or []) if isinstance(row, dict)]
            checked += len(rows)
            known = is_known_customer([customer_id_of(row) for row in rows]) or set()
            for row in rows:
                customer = customer_id_of(row)
                if customer and customer in known:
                    continue
                orphans.append({
                    "subscriptionId": row.get("id"),
                    "customerId": customer,
                    "status": row.get("status"),
                    "created": row.get("created"),
                    "email": _customer_email(row),
                    # Finns hintet men inte kundraden är fallet räddningsbart
                    # utan att någon behöver gissa vem kunden är.
                    "matjaktUserId": matjakt_user_id(row),
                })
            pages += 1
            if not page.get("has_more") or not rows:
                break
            if pages >= MAX_PAGES:
                truncated = True
                break
            starting_after = rows[-1].get("id")
    orphans.sort(key=lambda row: row.get("created") or 0)
    return {"checked": checked, "orphanCount": len(orphans), "orphans": orphans,
            "truncated": truncated, "statuses": list(statuses)}
