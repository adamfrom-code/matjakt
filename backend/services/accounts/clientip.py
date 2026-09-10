# -*- coding: utf-8 -*-
"""Vem är det som ringer? Rate limiterns enda nyckel för anonyma vägar.

WHY. Bakom en proxy ser varje anrop ut att komma från proxyn. Utan
`X-Forwarded-For` hamnar hela världen i EN hink och de tio första
misslyckade inloggningarna någonstans låser ute alla andra. Så headern
måste läsas — men den är delvis skriven av den som ringer.

RÄKNA BAKIFRÅN, ALDRIG FRAMIFRÅN. En proxy som *lägger till* (nginx
`proxy_add_x_forwarded_for`, och de flesta edge-proxies) bygger listan
vänster→höger: klientens egen text först, den adress proxyn själv såg
sist. Skickar en angripare `X-Forwarded-For: 1.2.3.4` blir det servern ser

    X-Forwarded-For: 1.2.3.4, <angriparens verkliga IP>

Att ta `[0]` är alltså att läsa exakt det fältet angriparen skrev, och
hinken kan bytas ut för varje anrop: rate limitern blir dekoration. Den
enda posten proxyn själv har fyllt i är den SISTA. Står två betrodda
proxies i kedjan är det den näst sista, och så vidare — därför
`MATJAKT_TRUSTED_HOPS` (standard 1: Render har en).

VALIDERAS. Posten vi landar på är fortfarande text från nätet i det fall
kedjan är kortare än väntad. Bara något som faktiskt är en IP-adress får
bli en hinknyckel; annars används TCP-motpartens adress. Annars kan den
som ringer själv välja hinknamn — och skriva vad som helst i en kolumn
som följer med i backupen.
"""

import ipaddress
import os

MAX_IP_LENGTH = 64


def trusted_hops(environ=None) -> int:
    """Hur många led i `X-Forwarded-For` som är våra egna proxies.

    Render terminerar TLS i ett (1) led. Läggs en CDN framför blir det två,
    och då räknar `MATJAKT_TRUSTED_HOPS=2` rätt. Skräpvärden faller till 1
    hellre än att krascha uppstarten — men aldrig till 0, för 0 vore
    "lita på hela listan"."""
    raw = str((environ if environ is not None else os.environ).get("MATJAKT_TRUSTED_HOPS", "")).strip()
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 1


def _normalized(candidate: str) -> str:
    """En riktig IP-adress, eller tom sträng. Tar `[::1]:443` och
    `1.2.3.4:5678` som proxies ibland skriver, och kastar allt annat."""
    value = (candidate or "").strip()[:MAX_IP_LENGTH]
    if not value:
        return ""
    if value.startswith("[") and "]" in value:            # [2001:db8::1]:443
        value = value[1:value.index("]")]
    elif value.count(":") == 1 and "." in value:          # 1.2.3.4:5678
        value = value.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return ""


def client_ip(forwarded_header: str, peer_address: str, *, trust_proxy: bool, hops: int = 1) -> str:
    """Adressen som rate limitern får nyckla på.

    `forwarded_header` är rå `X-Forwarded-For`. `peer_address` är den
    adress TCP-anslutningen faktiskt kommer från. Utan betrodd proxy vinner
    alltid `peer_address`: en klient som pratar direkt med oss kan skriva
    vad som helst i headern."""
    if trust_proxy and forwarded_header:
        parts = [part.strip() for part in forwarded_header.split(",") if part.strip()]
        wanted = max(1, int(hops or 1))
        if len(parts) >= wanted:
            found = _normalized(parts[-wanted])
            if found:
                return found
        # Kortare kedja än väntat (någon strippade headern, eller anropet
        # kom in vid sidan av proxyn) - då är motparten det enda vi vet.
    return _normalized(peer_address) or (peer_address or "").strip()[:MAX_IP_LENGTH]
