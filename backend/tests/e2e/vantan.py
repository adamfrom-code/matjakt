# -*- coding: utf-8 -*-
"""Väntan på klientens tillstånd - väckt av skrivningen, inte av klockan.

Den gamla `wait_for_state` läste `localStorage` var 250:e millisekund tills
en tidsgräns gick ut. Två fel följer av det, och båda har sänkt CI:

**Ett värde som skrivs och skrivs över mellan två avläsningar syns aldrig.**
Appen skriver hela tillståndet vid varje interaktion, och `pullAccountState`
skriver dessutom över det med kontots blob när synken svarar. Ligger de två
skrivningarna närmare varandra än stickprovet är värdet borta för den som
tittar - inte för att det inte fanns, utan för att ingen tittade just då.

**En långsam maskin går inte att skilja från en trasig app.** Tidsgränsen
mäter hur lång tid som gått, inte om appen gjort något. På en lastad
CI-maskin är två nätvändor efter varandra lätt fler sekunder än lokalt, och
då faller ett test som skulle ha blivit grönt en sekund senare.

Här görs i stället tvärtom: varje skrivning av `matjakt-state` bokförs i
sidan, och väntan prövar villkoret mot **varje tillstånd appen faktiskt
skrev** - i ordning, inget hoppat över. Väntan tar slut i samma ögonblick
som den skrivning som uppfyller villkoret sker.

Tidsgränsen finns kvar men betyder något annat: den mäter TYSTNAD. Att
appen inte skrivit på femton sekunder är ett riktigt besked ("den gör inget
mer"), till skillnad från "femton sekunder har gått" (som bara betyder att
maskinen är långsam).

Loopen ligger utanför browsertestet för att kunna prövas UTAN Playwright -
samma skäl som `diagnos.py`: en väntan som tyst väntar fel upptäcks annars
först den gång den behövs, och då är körningen redan förbi.
"""

import json

# Hur många skrivningar väntan som mest tar emot innan den ger upp. Ett tak,
# inte en tidsgräns: en app som skriver i en evig loop ska inte hänga
# testet, men den som gör tjugo skrivningar på väg fram ska få göra det.
TAK = 300

# Hur länge appen får vara TYST innan väntan ger upp. Den debouncade
# kontosynken är 1,5 s och premiumpollen 2 s; femton sekunder utan en enda
# skrivning betyder att ingen av dem är på väg.
TYSTNAD = 15.0


class Vantan(AssertionError):
    """Väntan gav upp. AssertionError så unittest rapporterar den som ett
    fel i testet och inte som en krasch i hjälparen."""


# Init-skript: bokför varje skrivning av matjakt-state i sidan.
#
# Läggs på CONTEXTEN före första sidan, så att den ligger på plats innan
# app.js kör sin första saveState(). Boken lever per dokument - en
# navigering nollställer den, vilket väntan känner igen på att numret
# gått bakåt.
SKRIVBOKEN = """
(() => {
  if (window.__matjaktSkrivbok) return;
  const bok = { nummer: 0, logg: [], tappade: 0, vantande: [] };
  window.__matjaktSkrivbok = bok;
  const original = Storage.prototype.setItem;
  Storage.prototype.setItem = function (nyckel, varde) {
    const svar = original.call(this, nyckel, varde);
    // EFTER den riktiga skrivningen, aldrig före: den som väcks ska kunna
    // läsa localStorage och se värdet som väckte hen. Och aldrig på ett
    // sätt som kan kasta - writeStoredState fångar sitt eget kvotfel, och
    // en bokföring som kastar hade blivit ett fel i appen i stället.
    if (nyckel === "matjakt-state") {
      try {
        bok.nummer += 1;
        bok.logg.push({ nummer: bok.nummer, text: String(varde) });
        // Taket gäller bara när ingen läser: väntan tömmer loggen vid
        // varje skörd, så i praktiken ligger det någon enstaka post här.
        // Skulle det ändå slå i taket räknas bortfallet - en väntan som
        // tappat skrivningar kan ha missat svaret, och det ska sägas rakt
        // ut i stället för att bli en tystnad som ser ut som ett besked.
        while (bok.logg.length > 200) { bok.logg.shift(); bok.tappade += 1; }
        for (const vack of bok.vantande.splice(0)) vack();
      } catch (fel) { /* bokföringen får aldrig sänka appen */ }
    }
    return svar;
  };
})();
"""

# Vad som står skrivet NU, plus var i boken vi befinner oss.
NULAGET = """
  () => ({ nummer: window.__matjaktSkrivbok ? window.__matjaktSkrivbok.nummer : null,
           tappade: window.__matjaktSkrivbok ? window.__matjaktSkrivbok.tappade : 0,
           text: localStorage.getItem("matjakt-state") })
"""

# Nästa skrivning(ar) efter `efter`. Löftet löses ut AV skrivningen - inte av
# en pollning som råkar titta i rätt ögonblick. Timern är enbart
# tystnadsvakten.
NASTA = """
  ([efter, millisekunder]) => new Promise(klar => {
    const bok = window.__matjaktSkrivbok;
    if (!bok) { klar({ saknas: true }); return; }
    const skorda = () => {
      const nya = bok.logg.filter(post => post.nummer > efter);
      bok.logg = [];                       // skördat är läst
      return { nummer: bok.nummer, tappade: bok.tappade, nya };
    };
    if (bok.nummer > efter) { klar(skorda()); return; }
    let klarmarkerad = false;
    const vack = () => {
      if (klarmarkerad) return;
      klarmarkerad = true;
      clearTimeout(id);
      klar(skorda());
    };
    const id = setTimeout(() => {
      if (klarmarkerad) return;
      klarmarkerad = true;
      bok.vantande = bok.vantande.filter(post => post !== vack);
      klar({ nummer: bok.nummer, tappade: bok.tappade, nya: [], tyst: true });
    }, millisekunder);
    bok.vantande.push(vack);
  })
"""


def tolka(text):
    """Blobben som ett läge. En tom lagring är ett tomt läge, inte ett fel -
    så läser `local_state()` den och så läser appen den."""
    return json.loads(text) if text else {}


def vanta_pa_tillstand(nulage, nasta, predikat, vad="tillstånd",
                       tystnad=TYSTNAD, tak=TAK):
    """Väntar tills `predikat` är sant om något tillstånd appen SKRIVIT.

    `nulage()` ger `(nummer, läge)` - vad som står skrivet nu och hur många
    skrivningar boken sett. `nasta(efter, tystnad)` blockerar tills det
    finns skrivningar efter `efter` och ger `(nummer, [lägen])`, eller en
    tom lista när appen varit tyst hela tystnadsfönstret.

    De två skickas in i stället för en sida, så att loopen går att pröva
    utan Playwright - den är det enda här som kan vänta fel.
    """
    nummer, senast = nulage()
    if predikat(senast):
        return senast
    sedda = 0
    while sedda < tak:
        nummer, lagen = nasta(nummer, tystnad)
        if not lagen:
            raise Vantan(_tyst(vad, sedda, senast, tystnad))
        for lage in lagen:
            sedda += 1
            senast = lage
            if predikat(lage):
                return lage
    raise Vantan(f"{vad}: {sedda} skrivningar och villkoret blev aldrig sant"
                 f" (taket {tak}); senast: {_kort(senast)}")


def _tyst(vad, sedda, senast, tystnad):
    if sedda:
        return (f"{vad}: appen skrev {sedda} gånger utan att villkoret blev sant,"
                f" och har varit tyst i {tystnad:g} s; senast: {_kort(senast)}")
    return (f"{vad}: appen skrev aldrig - tyst i {tystnad:g} s efter händelsen;"
            f" lagringen står kvar på: {_kort(senast)}")


def _kort(lage):
    return json.dumps(lage, ensure_ascii=False)[:600]


def sidans_skrivbok(page):
    """`(nulage, nasta)` mot en riktig Playwright-sida."""
    # Bortfall RÄKNAT FRÅN att den här väntan började. Vad boken hann tappa
    # dessförinnan hör till något som redan hänt och angår inte den här
    # väntan; det som tappas medan vi väntar gör det.
    utgangslage = None

    def granska(svar):
        """Boken får aldrig svara halvt. Har den tappat poster medan väntan
        pågick kan svaret ha stått i en av dem, och då vore ett lugnt
        "villkoret blev aldrig sant" en lögn."""
        nonlocal utgangslage
        tappade = svar.get("tappade") or 0
        if utgangslage is None:
            utgangslage = tappade
        elif tappade > utgangslage:
            borta = tappade - utgangslage
            utgangslage = tappade
            raise Vantan(f"skrivboken tappade {borta} skrivningar medan väntan pågick"
                         " - svaret kan ha stått i en av dem. Höj taket i SKRIVBOKEN,"
                         " eller vänta närmare händelsen.")
        return svar

    def nulage():
        svar = granska(page.evaluate(NULAGET))
        if svar["nummer"] is None:
            raise Vantan("skrivboken saknas i sidan - lades SKRIVBOKEN på contexten"
                         " före första sidan? Utan den vore väntan blind.")
        return svar["nummer"], tolka(svar["text"])

    def nasta(efter, tystnad):
        try:
            svar = page.evaluate(NASTA, [efter, int(tystnad * 1000)])
        except Exception as fel:                       # noqa: BLE001
            # Navigering mitt i väntan: dokumentet - och boken med det - är
            # borta. Det nya dokumentets lagring är i sig ett nytt läge att
            # pröva villkoret mot, så väntan läser om där i stället för att
            # kalla det tystnad. Allt ANNAT fel går vidare orört - en stängd
            # sida är inte en navigering, och ska inte se ut som en.
            if not _navigerade(fel):
                raise
            page.wait_for_load_state()
            nummer, lage = nulage()
            return nummer, [lage]
        if svar.get("saknas"):
            # Boken borta utan att anropet kastade: sidan bytte dokument
            # mellan två anrop. Läs om - och saknas boken på riktigt säger
            # nulage() det rakt ut i stället för att vänta blint.
            page.wait_for_load_state()
            nummer, lage = nulage()
            return nummer, [lage]
        granska(svar)
        # Numret kan ha gått BAKÅT här: en navigering hann ske och det nya
        # dokumentet har en ny bok som börjar om på noll. Väntan bryr sig
        # inte - den läser numret den fick och frågar efter nästa.
        return svar["nummer"], [tolka(post["text"]) for post in svar["nya"]]

    return nulage, nasta


def _navigerade(fel) -> bool:
    """Bara navigeringar. En stängd sida eller ett protokollfel är något
    annat och ska bubbla upp som sig själv."""
    text = str(fel)
    return ("Execution context was destroyed" in text
            or "Cannot find context" in text
            or "frame was detached" in text.lower())
