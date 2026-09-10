# -*- coding: utf-8 -*-
"""Ångerrätten: distansavtalslagen, och varför köpflödet inte får sakna en
kryssruta.

Lag (2005:59) om distansavtal och avtal utanför affärslokaler ger konsumenten
fjorton dagars ångerrätt. För en digital tjänst som levereras direkt gäller
undantaget i 2 kap. 11 § punkt 11 bara om kunden

  1. uttryckligen har SAMTYCKT till att leveransen påbörjas under ångerfristen,
     och
  2. GODKÄNT att ångerrätten därmed upphör.

Båda delarna, uttryckligen, före köpet. Fanns ingen sådan ruta någonstans i
Matjakts köpflöde: varje kund kunde använda Premium i tretton dagar och kräva
hela pengarna tillbaka, och vi hade inget att invända.

Texten står HÄR och ingen annanstans. Backend kräver samtycket innan en
Checkout-session skapas, och samma sträng går ut till frontend via
/api/entitlements så rutan aldrig kan säga en annan sak än den som sparas.

VERSION är inte dekoration. Ändras ordalydelsen är det ett nytt samtycke -
ett sparat "ja" till en äldre text bevisar ingenting om den nya. Ett konto
med en gammal version får därför frågan igen vid nästa köp.
"""

VERSION = 1

TEXT = ("Jag vill få tillgång till Premium direkt och godkänner att min "
        "ångerrätt upphör när tjänsten levererats.")

# Visas under rutan. Ingen del av samtycket - men utan den ser rutan ut som
# ett villkor man klickar bort, och den är hela poängen med att den finns.
NOTE = ("Utan det här kan vi inte öppna Premium direkt, eftersom du då har "
        "fjorton dagars ångerrätt på en tjänst som redan levererats.")

# Svaret till klienten när samtycket saknas. Koden är det UI:t växlar på;
# texten är det användaren ska se.
ERROR_CODE = "WITHDRAWAL_CONSENT_REQUIRED"
ERROR_TEXT = "Kryssa i rutan om ångerrätten för att kunna gå vidare till betalningen."


def terms() -> dict:
    """Ångerrättsblocket i /api/entitlements. Frontend renderar rutan ur det
    här, precis som den renderar priserna ur pricing - så texten i rutan och
    texten som sparas är samma sträng, alltid."""
    return {"version": VERSION, "text": TEXT, "note": NOTE}


def consent_is_current(version) -> bool:
    """Räcker ett sparat samtycke för ett köp NU?

    Bara om det finns och gäller den nuvarande ordalydelsen. Saknat samtycke
    och ett samtycke till en äldre text behandlas lika: frågan ställs igen.
    """
    try:
        return int(version) == VERSION
    except (TypeError, ValueError):
        return False
