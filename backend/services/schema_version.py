# -*- coding: utf-8 -*-
"""`PRAGMA user_version`: databasen säger själv vilken schemaversion den bär.

Bakgrund. K4 (PR #101) lade in ett `rollback`-jobb i CI som startar
föregående live-deploy av sig själv när rökprovet faller. Efter en sådan
återställning kör GAMMAL kod mot en databas som NY kod redan har migrerat.
K6 bevisade att det går bra - migrationerna är rent additiva, se
`tests/test_migrationer.py`. Men frågan "vilken schemaversion bär den här
filen?" var fortfarande en gissning: man fick öppna sqlite för hand och
jämföra kolumnlistor mot en commit man hoppades var rätt, mitt i natten,
med en incident igång.

SQLite har ett fält för precis det. `PRAGMA user_version` är fyra byte i
databashuvudet som ingen annan rör, den följer med filen genom kopior och
backupper, och den kostar ingenting att läsa.

VARFÖR MAX OCH INTE TILLDELNING. `stämpla()` sänker aldrig en version, och
det är hela poängen efter en återställning. Den gamla koden känner bara sitt
eget nummer, öppnar en databas som är stämplad högre, och det värdefulla i
det läget är just att filen fortsätter säga "jag är migrerad av en nyare
release än den som kör mig nu". Skrev vi ner den vore upplysningen borta i
samma sekund den behövdes. En stämpel som bara går uppåt är dessutom sann
oavsett i vilken ordning deployerna råkade gå.

NUMREN. Ett lager = en databasfil = en egen räknare. Siffrorna betyder
ingenting över lagergränsen: `KONTON = 1` och `RECEPT = 1` är inte "samma
version", de är två tabeller som var för sig aldrig ändrats sedan stämpeln
infördes. **0 betyder "aldrig stämplad"** - en databas som senast rördes av
kod från före det här paketet, eller en fil som inte är någon av våra.

Bumpa numret i SAMMA commit som schemaändringen. Glöms det failar
`tests/test_migrationer.py`: det testet jämför lagrets schema mot fixturen i
`tests/fixturer/scheman/` och kräver en höjd version så fort en kolumn
tillkommit. Stämpeln är till för att gå att lita på, och en version som
står still medan schemat rör sig är värre än ingen version alls.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Ett lager, ett nummer. Namnen är samma som fixturerna i
# tests/fixturer/scheman/ heter, så att ett testfel pekar på rätt fil.
#
# 1 = schemat som det såg ut när stämpeln infördes (K6b, 2026-09-11). Alla
# migrationer som fanns då ligger under 1; de är inte numrerade var för sig
# och kan inte bli det i efterhand, eftersom produktionsdatabaserna redan
# hade kört dem utan att lämna spår om vilka.
KONTON = 1
BUTIKSDATA = 1
RECEPT = 1
HUSHALL = 1
PRISCACHE = 1

#: För diagnostik och för testet: lagrets namn -> versionen dagens kod skriver.
VERSIONER = {
    "konton": KONTON,
    "butiksdata": BUTIKSDATA,
    "recept": RECEPT,
    "hushall": HUSHALL,
    "priscache": PRISCACHE,
}


def läs(anslutning: sqlite3.Connection) -> int:
    """Schemaversionen databasen bär just nu. 0 = aldrig stämplad."""
    return int(anslutning.execute("PRAGMA user_version").fetchone()[0])


def stämpla(anslutning: sqlite3.Connection, version: int) -> int:
    """Stämplar databasen med `version` - men sänker den aldrig.

    Returnerar versionen filen bär efteråt, vilket är `max(nuvarande,
    version)`. Är den redan högre skrivs ingenting alls: se modulens
    docstring om varför en återställd release inte får skriva ner stämpeln.

    Anropas sist i lagrets migrering, när schemat faktiskt ÄR det version
    påstår. Pragman skriver rakt i databashuvudet och behöver ingen commit -
    men körs den inne i en öppen transaktion följer den med den
    transaktionen, vilket är rätt: rullar migreringen tillbaka ska stämpeln
    göra det också.
    """
    nuvarande = läs(anslutning)
    version = int(version)
    if version <= nuvarande:
        return nuvarande
    # Ingen parameterbindning: sqlite tar inte `PRAGMA user_version = ?`.
    # int() ovan är därför inte kosmetik utan det som gör raden ofarlig.
    anslutning.execute(f"PRAGMA user_version = {version}")
    return version


def läs_fil(väg: Path | str) -> int:
    """Versionen i en databasFIL, utan att öppna lagret som äger den.

    Det här är avläsningen en människa gör efter en återställning: peka på
    filen på disk och få ett tal, utan att importera ett lager vars kod
    skulle migrera databasen i samma andetag som den svarade på frågan.

        python -c "from services.schema_version import läs_fil; \\
                   print(läs_fil('backend/data/accounts.db'))"

    Filen öppnas skrivskyddat. Saknas den, eller är den inte en databas,
    blir svaret 0 - samma svar som "aldrig stämplad", eftersom skillnaden
    inte spelar någon roll för den som frågar.
    """
    väg = Path(väg)
    if not väg.exists():
        return 0
    try:
        anslutning = sqlite3.connect(f"file:{väg}?mode=ro", uri=True)
    except sqlite3.Error:
        return 0
    try:
        return läs(anslutning)
    except sqlite3.Error:
        return 0
    finally:
        anslutning.close()
