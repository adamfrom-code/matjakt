# -*- coding: utf-8 -*-
"""Leveransen av en vecka - läst efter OMRITNINGEN, inte efter klicket.

"Skapa min vecka" gör tre saker i EN och samma händelse (chooseMenu i app.js)::

    setWeekPlan(...); saveState();    // skrivningen  - synkron, i klicket
    veckanLevereras(true); render();  // omritningen  - köad på requestAnimationFrame
    setView("week");                  // vyklassen    - synkron, i klicket

Skrivningen och vyklassen är alltså på plats när Playwrights klick kommer
tillbaka; veckolistan och butikskorten ritas en bildruta senare. I det
glappet står FÖRRA bildrutan kvar - och den är inte tom. Onboardingens sista
steg har redan byggt en vecka i tysthet (postnumret laddar butikerna, och
`onBranchesLoaded` kör `chooseMenu(false)`) och prissatt den bakom rutan:
tre butikskort, två av dem låsta, för ögonblicket (G8) har inte börjat än.

`complete_onboarding` läste sedan DOM:en direkt efter klicket. Varje villkor
den hade - rutan borta, `view-week`, en rad i listan, erbjudanderaden - var
sant redan om den gamla bildrutan. Och G8-testet räknade hänglås i samma
glapp::

    AssertionError: 2 != 0 : ['CG\\nCity Gross\\nSe pris med Premium',
                              'H\\nHemköp\\nSe pris med Premium']

Två låsta kort och inget öppet: klickets `clearPriceSnapshots()` hade tömt
totalerna men lämnat de låsta kedjorna kvar, och korten ritades ur resterna
medan den nya prissättningen var i luften (att det är produktens sak att
laga står i docs/changelog.d/T5.md). Lokalt hinner bildrutan alltid före
nästa CDP-vända; på en lastad CI-maskin gör den det inte - och ett test som
läser i glappet är rött ungefär så ofta som maskinen är långsam.

Regeln är T2b:s (avbockning.py), uttryckt om leveransen:

**LÄS EFTER OMRITNINGEN.** Raderna som står i listan FÖRE klicket märks
(`markera_raderna`). Varje omritning byter ut varenda `.vecka-dag`-nod
(`innerHTML =` i renderBasket), så en märkt rad som står kvar är beviset på
att omritningen inte landat - oavsett om den nya veckan råkar likna den
gamla. Väntan släpper när ingen märkt rad finns kvar OCH varje recept-id i
den plan klicket skrev står i listan.

**VÄCKT AV OMRITNINGEN, INTE AV KLOCKAN.** En MutationObserver på
`#weekPlanList` löser ut löftet i samma ögonblick som listan byts ut.
Tidsgränsen mäter tystnad i DOM:en: "appen skrev veckan men ritade den
aldrig" är ett besked om appen, till skillnad från "tjugo sekunder gick",
som bara var ett besked om maskinen.

Tolkningen av svaret ligger utanför browsertestet för att kunna prövas UTAN
Playwright (tests/test_e2e_leverans.py) - samma skäl som vantan.py,
avbockning.py och matt.py: en väntan som tyst släpper fel upptäcks annars
först den gång den behövs, och då är körningen redan förbi.
"""

# Hur länge DOM:en får vara TYST innan väntan ger upp. Klickets omritning är
# köad på nästa bildruta; femton sekunder utan att listan byts ut betyder
# att den inte är på väg - inte att maskinen är långsam.
TYSTNAD = 15.0

# Attributet som märker förra bildrutans rader. Sätts av testet, aldrig av
# appen, och försvinner med noden när listan ritas om.
MARKE = "data-e2e-fore-leveransen"


class Leveransen(AssertionError):
    """Leveransen ritades aldrig, eller fel vecka ritades. AssertionError så
    unittest rapporterar den som ett fel i testet och inte som en krasch i
    hjälparen."""


# Märker raderna som står i veckolistan NU. Returnerar hur många det var.
MARKERA_RADERNA = """
  (marke) => {
    const rader = [...document.querySelectorAll("#weekPlanList .vecka-dag")];
    rader.forEach(rad => rad.setAttribute(marke, "1"));
    return rader.length;
  }
"""

# Väntan: löftet löses ut AV omritningen, inte av en pollning som råkar
# titta i rätt ögonblick. Timern är enbart tystnadsvakten. Svaret bär alltid
# lägesbilden - vad som är ritat, hur många gamla rader som står kvar, vilka
# id som saknas - så beskedet kan säga vad som hände i stället för "timeout".
VECKAN_RITAD = """
  ([ids, marke, millisekunder]) => new Promise(klar => {
    const lista = document.getElementById("weekPlanList");
    if (!lista) { klar({ lista: false }); return; }
    const lage = () => {
      const ritade = [...lista.querySelectorAll("[data-week-details]")]
        .map(el => el.getAttribute("data-week-details"));
      return { ritade,
               gamla: lista.querySelectorAll("[" + marke + "]").length,
               saknas: ids.filter(id => !ritade.includes(id)) };
    };
    const ritad = l => l.gamla === 0 && l.saknas.length === 0;
    let nu = lage();
    if (ritad(nu)) { klar({ lista: true, ritad: true, ...nu }); return; }
    let avslutad = false;
    const observer = new MutationObserver(() => {
      if (avslutad) return;
      nu = lage();
      if (!ritad(nu)) return;
      avslutad = true; observer.disconnect(); clearTimeout(vakt);
      klar({ lista: true, ritad: true, ...nu });
    });
    const vakt = setTimeout(() => {
      if (avslutad) return;
      avslutad = true; observer.disconnect();
      klar({ lista: true, ritad: false, tyst: true, ...lage() });
    }, millisekunder);
    observer.observe(lista, { childList: true, subtree: true });
  })
"""


def tolka(svar, ids, tystnad=TYSTNAD):
    """Beskedet ur väntans svar - None när veckan är ritad.

    Ren funktion, så varje sätt väntan kan sluta på går att pröva utan
    browser. Ordningen är avsiktlig: en lista som saknas är ett annat fel än
    en omritning som aldrig kom, som är ett annat fel än fel vecka på
    skärmen - och de tre lagas på tre olika ställen."""
    if not svar.get("lista"):
        return "veckolistan (#weekPlanList) finns inte i sidan - är appen laddad?"
    if svar.get("ritad"):
        return None
    ids = list(ids)
    gamla = int(svar.get("gamla") or 0)
    ritade = list(svar.get("ritade") or [])
    saknas = list(svar.get("saknas") or [])
    if gamla:
        return (f"appen skrev veckan men ritade den aldrig: {gamla} rad(er) från före"
                f" klicket står kvar efter {tystnad:g} s tyst DOM;"
                f" skrivet={ids} ritat={ritade}")
    return ("omritningen landade men veckan på skärmen är inte den som skrevs:"
            f" saknas={saknas} skrivet={ids} ritat={ritade}")


def markera_raderna(page, marke=MARKE):
    """Märker förra bildrutans rader. Anropas FÖRE klicket."""
    return page.evaluate(MARKERA_RADERNA, marke)


def vanta_pa_leveransen(page, ids, tystnad=TYSTNAD, marke=MARKE):
    """Väntar tills listan ritats om med exakt de recept klicket skrev.

    Returnerar lägesbilden (ritade id, noll gamla rader). Kastar `Leveransen`
    med ett besked om vad som hände när den inte gör det."""
    ids = list(ids)
    if not ids:
        raise ValueError("en levererad vecka utan recept är ingen leverans att vänta på")
    svar = page.evaluate(VECKAN_RITAD, [ids, marke, int(tystnad * 1000)])
    fel = tolka(svar, ids, tystnad)
    if fel:
        raise Leveransen(fel)
    return svar


# ---- prisbilden: spridningsraden och korten i ETT svep --------------------
#
# G8-testet läste i tre steg: spridningsraden synlig (en väntan), sedan
# antalet låsta kort (ett stickprov), sedan kortens texter (ett till). Mellan
# två av dem hann korten ritas om - och de ritas om många gånger efter
# leveransen: render-bussen, varje receptdetalj som landar (renderBasket
# direkt), och varje prissvar. Ett läge där raden syns OCH två kort är låsta
# har aldrig funnits på skärmen; det var två svar om två olika bildrutor.
#
# T2b:s regel igen: ETT SVEP, INTE TVÅ. Raden och korten läses i samma
# JS-vända, där DOM:en inte kan bytas ut mellan de två frågorna. Väntan
# väcks av omritningen (MutationObserver) och släpper i det ögonblick raden
# är synlig - med korten ur exakt den bildrutan.
PRISBILDEN = """
  (millisekunder) => new Promise(klar => {
    const las = () => {
      const rad = document.getElementById("storeSpreadTeaser");
      if (!rad || rad.hidden || !rad.getClientRects().length) return null;
      return { spridning: rad.textContent,
               kort: [...document.querySelectorAll("#storeCards .store-card")].map(k => ({
                 text: k.innerText, last: k.classList.contains("locked"),
                 betalvagg: k.hasAttribute("data-store-card-paywall") })) };
    };
    let nu = las();
    if (nu) { klar({ ritad: true, ...nu }); return; }
    let avslutad = false;
    const observer = new MutationObserver(() => {
      if (avslutad) return;
      nu = las();
      if (!nu) return;
      avslutad = true; observer.disconnect(); clearTimeout(vakt);
      klar({ ritad: true, ...nu });
    });
    const vakt = setTimeout(() => {
      if (avslutad) return;
      avslutad = true; observer.disconnect();
      const rad = document.getElementById("storeSpreadTeaser");
      klar({ ritad: false, tyst: true, rad: !!rad,
             kort: [...document.querySelectorAll("#storeCards .store-card")].map(k => k.innerText) });
    }, millisekunder);
    observer.observe(document.body, { childList: true, subtree: true,
                                      attributes: true, attributeFilter: ["hidden"] });
  })
"""


def tolka_prisbilden(svar, tystnad=TYSTNAD):
    """Beskedet ur väntans svar - None när spridningsraden syntes."""
    if svar.get("ritad"):
        return None
    if not svar.get("rad"):
        return "spridningsraden (#storeSpreadTeaser) finns inte i sidan - är appen laddad?"
    return (f"spridningsraden syntes aldrig: {tystnad:g} s tyst DOM efter att veckan"
            f" ritats; korten just nu={list(svar.get('kort') or [])}")


def vanta_pa_prisbilden(page, tystnad=TYSTNAD):
    """Väntar tills spridningsraden syns och ger korten ur SAMMA bildruta.

    Returnerar {"spridning": text, "kort": [{"text", "last", "betalvagg"}]}.
    Kastar `Leveransen` när raden aldrig kommer."""
    svar = page.evaluate(PRISBILDEN, int(tystnad * 1000))
    fel = tolka_prisbilden(svar, tystnad)
    if fel:
        raise Leveransen(fel)
    return {"spridning": svar["spridning"], "kort": svar["kort"]}
