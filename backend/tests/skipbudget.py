# -*- coding: utf-8 -*-
"""K6: en skip som ingen räknar är en test som inte finns.

Sviten hoppar över ett par tester i varje körning - ingen admin-token i
miljön, ingen Willys-data i en ren checkout, `clips.json` som byggs och inte
committas. Var och en av dem är rimlig. Problemet är att `unittest` skriver
ut `skipped=4` och går vidare, så ingen upptäcker dagen de blir fem, och
ingen upptäcker dagen de blir trettio. En svit som tyst slutar köra en
tredjedel av sig själv ser exakt likadan ut som en som kör allt.

"Noll skip" går inte att kräva: några av dem beror på vad som finns i
miljön, och de skiljer sig mellan en utvecklarmaskin och en CI-runner.
Budgeten är därför en LISTA över vilka skip som är kända och accepterade,
och en regel: en skip vars orsak inte står på listan fäller körningen när
`MATJAKT_STRICT=1` är satt.

Matchningen sker på ORSAKEN, inte på testets namn. Orsaken är den mening
författaren skrev om varför testet inte kan köra här; den överlever en
omdöpning, en flytt till en annan fil och en ny testklass. Ett nytt skip har
per definition en ny orsak.

Listan ligger i backend/tests/tillatna_skip.txt. Den växer bara genom en
commit någon läser.
"""

import os
from pathlib import Path

HÄR = Path(__file__).resolve().parent
LISTA = HÄR / "tillatna_skip.txt"


def strikt_läge(miljö=None) -> bool:
    """MATJAKT_STRICT=1 slår på budgeten. CI sätter den; lokalt är den av."""
    miljö = os.environ if miljö is None else miljö
    return str(miljö.get("MATJAKT_STRICT", "")).strip() == "1"


def läs_tillåtna(text: str):
    """En orsak per rad. `#` är kommentar, tomma rader hoppas över."""
    tillåtna = []
    for rad in text.splitlines():
        rad = rad.split("#", 1)[0].strip()
        if rad:
            tillåtna.append(rad)
    return tillåtna


def tillåten(orsak: str, tillåtna) -> bool:
    """Prefixmatchning: orsaken får bära detaljer listan inte känner till.

    "openssl saknas (3.0 krävs)" matchar posten "openssl saknas". Utan
    prefix hade varje orsak som bär ett filnamn eller ett felmeddelande
    behövt stå ordagrant i listan, och listan hade blivit omöjlig att hålla.
    """
    text = (orsak or "").strip()
    if not text:
        # En skip utan orsak går aldrig att bedöma - och den som skriver en
        # sådan har inte tänkt klart. Den räknas som otillåten.
        return False
    return any(text.startswith(post) for post in tillåtna)


def otillåtna(skippade, tillåtna):
    """[(test-id, orsak)] som INTE står på listan."""
    return [(namn, orsak) for namn, orsak in skippade if not tillåten(orsak, tillåtna)]


def döm(skippade, tillåtna, skriv=print) -> int:
    """0 om varje skip är känd, 1 annars. Skriver alltid ut vad som hoppades."""
    okända = otillåtna(skippade, tillåtna)
    if skippade:
        skriv(f"Skip-budget: {len(skippade)} överhoppade tester, "
              f"{len(skippade) - len(okända)} kända.")
    if not okända:
        return 0
    skriv("")
    skriv(f"::error::{len(okända)} överhoppade tester står inte i "
          f"backend/tests/tillatna_skip.txt:")
    for namn, orsak in okända:
        skriv(f"    {namn}")
        skriv(f"        orsak: {orsak!r}")
    skriv("")
    skriv("En skip som ingen räknar är en test som inte finns. Antingen ska")
    skriv("testet kunna köra här - det är nästan alltid rätt svar - eller så")
    skriv("ska orsaken stå i listan med en rad om varför, så att nästa person")
    skriv("ser att den är ett medvetet beslut och inte ett förbiseende.")
    return 1
