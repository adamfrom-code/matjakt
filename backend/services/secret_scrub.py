# -*- coding: utf-8 -*-
"""Ta bort hemligheter ur text som kan nå ett öga utifrån.

VARFÖR DEN HÄR FINNS. En Primat-nyckel med radbrytning fick urllib att kasta
"Invalid header value b'Bearer <hela nyckeln>'". importer sparade undantagets
text rakt av i grocery_collector_runs.error_message, och provider_status
serverar det fältet som errorMessage via /api/grocery/status - som är
PUBLIK. Nyckeln låg läsbar för vem som helst tills den byttes.

Två lager, båda behövs:

  1. Skrubba INNAN lagring, så hemligheten aldrig hamnar i databasen.
  2. Skrubba INNAN utskick, så rader som redan lagrats inte läcker och så
     en ny kodväg som glömmer lager 1 ändå inte exponerar något.

Skrubbningen matchar på VÄRDET först - den säkraste metoden, för då spelar
det ingen roll hur undantaget formulerade sig - och därefter på mönster, för
nycklar vi inte känner till (en roterad nyckel som fortfarande finns i ett
gammalt felmeddelande, till exempel)."""

from __future__ import annotations

import os
import re

# Miljövariabler vars värden aldrig får synas i text som lämnar servern.
HEMLIGA_VARIABLER = (
    "PRIMAT_API_KEY", "MATJAKT_ADMIN_TOKEN", "MATJAKT_MAIL_SECRET",
    "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "SMTP_PASSWORD",
    "DABAS_API_KEY", "MATJAKT_PREMIUM_CODE",
)

# Kortare än så är inte en hemlighet utan ett ord, och att ersätta det skulle
# göra felmeddelanden obegripliga utan att skydda något.
MINSTA_LANGD = 12

DOLT = "‹dolt›"

# Mönster för hemligheter vi INTE har värdet på: en roterad nyckel i en gammal
# rad, eller en nyckel från en tjänst som inte står i listan ovan.
_MONSTER = (
    re.compile(r"(?i)\b(bearer|token|api[-_]?key)\s+\S{12,}"),
    re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{8,}"),
    re.compile(r"\bprimat_(?:live|test)_[A-Za-z0-9]{8,}"),
    re.compile(r"(?i)\b(x-api-key|authorization)\s*[:=]\s*\S+"),
)


def scrub(text, extra: tuple[str, ...] = ()) -> str:
    """Texten utan kända hemligheter. Tom sträng in ger tom sträng ut."""
    if not text:
        return ""
    ut = str(text)
    varden = [os.environ.get(namn, "") for namn in HEMLIGA_VARIABLER]
    varden.extend(extra)
    # Längsta först: annars kan en kort delsträng dela sönder en längre
    # hemlighet och lämna svansen kvar i klartext.
    for varde in sorted((v.strip() for v in varden if v), key=len, reverse=True):
        if len(varde) >= MINSTA_LANGD:
            ut = ut.replace(varde, DOLT)
    for monster in _MONSTER:
        ut = monster.sub(lambda m: f"{m.group(1)} {DOLT}" if m.groups() else DOLT, ut)
    return ut
