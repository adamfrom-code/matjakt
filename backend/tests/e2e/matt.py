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


# ---------------------------------------------------------------------------
# L2c: EN RECT SOM ÄR IDEL NOLLOR ÄR INGEN MÄTNING.
#
# Allt ovan handlar om att en uppmätt pixel är ett flyttal. Det här är ett
# annat fel med samma offer. CI läste
#
#     {'hojd': 0, 'vanster': False, 'hoger': False}
#
# alltså noll rakt igenom, och `minst(0)` är falskt hur vid toleransen än är.
# En halv pixel räddar inte en nolla, och ska inte göra det.
#
# Veckolistan ritas av `renderBasket` med `$("weekPlanList").innerHTML = ...`
# (app.js). Varje omritning byter alltså ut VARJE `.vecka-dag`-nod. Playwright
# slår upp elementet i en CDP-vända och kör sedan sin `evaluate()` i nästa;
# landar omritningen mellan de två mäter man en nod som inte sitter i
# dokumentet längre, och `getBoundingClientRect()` på en avhängd nod är idel
# nollor. Inget kast, ingen varning - bara en knapp som ser 0 px hög ut.
#
# Mätt, inte gissat. Tjugo mätningar av samma knapp i en riktig browser:
#
#     omritning var 2:a ms   gamla mätningen   nya mätningen
#     ingen (som lokalt)     0/20 nollor       -
#     var 2:a ms             20/20 nollor      0/20 nollor
#
# Lokalt hinner bildrutan alltid först och felet finns inte. Det är därför
# det är CI:s fel och inte utvecklarens - samma sak T2b fann för avbockningen.
#
# Regeln är densamma som T2b:s, uttryckt om mätning:
#
# **ETT SVEP, INTE TVÅ.** Noden söks upp OCH mäts i samma `evaluate()`. Inom
# en JS-vända kan DOM:en inte bytas ut, så det finns inget glapp att dela
# mätningen i. Under stormen ovan kostade den nya mätningen ett enda svep -
# min och max - för den behövde aldrig göra om något.
#
# **ETT SVEP UTAN RITAD NOD ÄR INGET MÄTVÄRDE.** Det är omtaget, och det
# gäller det andra fallet: vyn har inte ritats ännu när testet tittar. Då
# finns ingen nod att mäta, och svaret är "kom tillbaka nästa bildruta" -
# inte "noll pixlar".
#
# Grinden blir INTE slappare. En knapp som verkligen är 0 px - display:none,
# en kollapsad förälder - ger samma svar varje svep och fälls när taket är
# slut. Det som ändras är beskedet: "appen ritade den aldrig" är ett besked
# om appen, till skillnad från "0 >= 43.5 är falskt", som bara var ett
# besked om när Playwright råkade titta.
# ---------------------------------------------------------------------------

# Hur många svep en mätning som mest tar innan den ger upp. Ett tak, inte en
# tidsgräns - samma skäl som TAK i vantan.py: en app som aldrig ritar knappen
# ska fällas, en långsam maskin ska inte fällas för att den är långsam.
SVEPTAK = 60


class Oritad(AssertionError):
    """Ingen ritad nod att mäta, efter varje svep taket tillät."""


def mat(svep, tak: int = SVEPTAK) -> dict:
    """Mät genom att svepa tills ett svep träffar en ritad nod.

    `svep()` gör EN mätning och returnerar antingen måtten eller None när
    det inte fanns någon ritad nod att mäta. None är inte ett mätvärde och
    räknas aldrig som ett.

    Loopen ligger utanför browsertestet för att kunna prövas UTAN Playwright
    - samma skäl som `vantan.py` och `avbockning.py`: en mätning som tyst
    mäter fel upptäcks annars först den gång den fäller någon annans PR.
    """
    if tak < 1:
        raise ValueError("taket måste vara minst ett svep")
    for _ in range(tak):
        matning = svep()
        if matning is not None:
            return matning
    raise Oritad(
        f"ingen ritad nod att mäta efter {tak} svep - appen ritade den aldrig, "
        "eller ritar om den i en evig loop")


# Ett svep: sök upp noden OCH mät den i samma vända. Att slå upp elementet i
# Python och mäta det i en andra vända är just det glappet en omritning ryms i.
SVEP_JS = """
    ([valjare, index, golv]) => {
      const el = document.querySelectorAll(valjare)[index];
      // Ingen nod, eller en som just bytts ut av en omritning: `isConnected`
      // är falskt för den avhängda. Nollrect:en fångar resten - en förälder
      // med display:none ritar heller ingenting att mäta.
      if (!el || !el.isConnected) return null;
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return null;
      const mitt = r.top + r.height / 2;
      const träffar = (x, y) => {
        const t = document.elementFromPoint(x, y);
        return !!(t && (t === el || el.contains(t)));
      };
      const kant = (golv - r.width) / 2;
      return {
        hojd: r.height,
        vanster: kant <= 0 || träffar(r.left - kant + 1, mitt),
        hoger: kant <= 0 || träffar(r.right + kant - 1, mitt),
      };
    }
"""


def sidans_traffyta(page, valjare: str, index: int = 0,
                    krav: float = TUMYTA_PX, tak: int = SVEPTAK) -> dict:
    """Träffytan för den `index`:e noden som matchar `valjare`, mätt med tumme.

    Playwright-kopplingen till `mat()`. All logik som kan mäta fel bor i
    `mat()` och prövas utan browser; det här är sladden mellan den och sidan.
    """
    return mat(lambda: page.evaluate(SVEP_JS, [valjare, index, golv(krav)]), tak=tak)
