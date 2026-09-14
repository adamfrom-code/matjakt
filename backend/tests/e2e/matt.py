# -*- coding: utf-8 -*-
"""Uppmätta pixlar är flyttal - tröskeln mäts med en tumme, inte en linjal.

`getBoundingClientRect().height` är `bottom - top`, och båda är
dubbelprecisionstal räknade från elementets plats på sidan. Ligger den
platsen på en bruten pixel - och det gör den så fort något ovanför raden har
en fraktionell höjd - blir differensen av två sådana tal inte exakt det CSS
skrev. En knapp med `height:44px` läste tillbaka

    43.999969482421875

alltså 44 - 2^-15, och fällde L2:s acceptanstest. Felet slog på M4, en PR vars
diff inte rör en enda fil appen laddar i webbläsaren, och samma innehåll
passerade vid omkörning. Det syns också i VILKEN körning som föll: CI kör
E2E:n två gånger, mot källan och mot `dist/frontend`. Källan gav 44 och
passerade, bundlet gav 44 - 2^-15 och föll. Samma CSS, samma knapp, samma
webbläsare - bara ett annat läge på sidan.

En andra väg till samma rest, funnen av L3: `.screen` bär animationen
`screen-in` (0,35 s), och en rect som mäts medan en transform är igång räknas
ut med lägre precision än layouten. Bägge vägarna slutar i samma sorts tal, och
ingen av dem säger något om knappens storlek.

**44 px är ett mått på en tumme, inte ett flyttal.** Kravet kommer ur Apple
HIG och WCAG 2.5.5 och handlar om vad ett finger träffar; en tumme märker
inte tre hundratusendels pixel. Toleransen här är därför en halv pixel - stor
nog att äta varje avrundning en layoutmotor kan hitta på, liten nog att en
knapp som verkligen krympt till 43,5 px fortfarande fälls.

Gäller INTE `scrollWidth`, `clientWidth`, `offsetHeight` eller
`window.innerWidth`. De är heltal - webbläsaren avrundar dem åt en - och en
tolerans där hade bara gjort grinden slappare utan att fånga något. Regeln här
gäller `getBoundingClientRect()` och det som räknas fram ur den, alltså de
värden som faktiskt kommer tillbaka som flyttal.

Att jämförelsen bor i en egen modul har två skäl. Den ska ha EN definition,
så att nästa mätning som skrivs ärver toleransen i stället för att uppfinna
en egen tröskel. Och den ska gå att pröva UTAN Playwright - samma skäl som
`diagnos.py` och `vantan.py`: en grind som tyst mäter fel upptäcks annars
först den gång den fäller någon annans PR, och då är körningen redan förbi.
"""

# Minsta träffyta i px. Apple HIG (44x44 pt) och WCAG 2.5.5.
TUMYTA_PX = 44

# Halv pixel. Mätfel ur layoutmotorn är i storleksordningen 2^-15 px; en halv
# pixel ligger tio tusen gånger över det och en tiondels pixel under vad en
# skärm kan rita. Allt däremellan mäter aritmetik, inte design.
SUBPIXEL_PX = 0.5


def golv(krav: float = TUMYTA_PX) -> float:
    """Kravet som ett tal att jämföra en uppmätt sida mot.

    Finns för mätningar som görs inne i webbläsaren och därför behöver
    tröskeln som ett tal att skicka in i `evaluate()` - så att JS-sidan
    ärver samma tolerans som `minst()` i stället för att bära en egen.
    """
    return krav - SUBPIXEL_PX


def minst(uppmatt: float, krav: float = TUMYTA_PX) -> bool:
    """Är den uppmätta sidan minst `krav`, mätt med en tumme?"""
    return uppmatt >= golv(krav)


def hogst(uppmatt: float, grans: float) -> bool:
    """Ryms det uppmätta innanför `grans`, mätt med en tumme?

    Samma tolerans åt andra hållet: ett block vars underkant hamnar
    0,00003 px under vikten ryms på skärmen. Det som INTE ryms ligger
    en halv pixel över, och det syns.
    """
    return uppmatt <= grans + SUBPIXEL_PX


def for_sma(matningar: dict, krav: float = TUMYTA_PX) -> dict:
    """De mätningar som faller under kravet - namn -> uppmätt värde.

    Returnerar det UPPMÄTTA värdet, inte bara namnet: "knappen är 24 px"
    går att åtgärda, "knappen är för liten" går att gissa om.
    """
    return {namn: varde for namn, varde in matningar.items()
            if not minst(varde, krav)}
