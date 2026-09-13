# -*- coding: utf-8 -*-
"""Avbockningen av handlingslistan - läst efter OMRITNINGEN, inte efter skrivningen.

T2 (#99) flyttade E2E:ns väntan från klockan till skrivningen: `wait_for_state`
väcks numera av att appen skriver `matjakt-state`, inte av att en tidsgräns
går ut. Det var rätt, och det räckte inte - för avbockningsloopen VÄNTAR på
skrivningen och LÄSER sedan DOM:en, och de två sakerna händer inte samtidigt.

`setItemStatus` i app.js gör dem i den här ordningen::

    saveState();          // skrivningen - det är den T2:s väntan väcks av
    invalidate("basket"); // omritningen - köad på requestAnimationFrame

Skrivningen sker alltså en bildruta FÖRE omritningen. I det glappet står
raden man just bockade av kvar med `data-bought` i DOM:en, och en läsning
där ger ett svar som redan är inaktuellt.

Den gamla loopen läste dessutom i TVÅ steg::

    knappar = page.locator("#shoppingList [data-bought]")
    if knappar.count() == 0:          # 1: hur många finns det?
        break
    vara = knappar.first.get_attribute("data-bought")   # 2: vad heter den?

`count()` är ett stickprov som svarar direkt; `get_attribute()` VÄNTAR in
ett element. Landar bildrutan mellan de två - och på en lastad maskin kan
den landa var som helst - så såg steg 1 den sista obockade raden och steg 2
en lista där ingen finns kvar. Då väntade Playwright ut hela sin tidsgräns
på ett element som aldrig kommer tillbaka:

    playwright._impl._errors.TimeoutError: Locator.get_attribute:
    Timeout 20000ms exceeded.
    waiting for locator("#shoppingList [data-bought]")

Tjugo sekunder, och sedan ett fel som handlar om en klocka i stället för om
appen. Det fällde slumpvis gröna PR:er och lärde alla att köra om.

Två regler följer, och båda bor här:

**ETT SVEP, INTE TVÅ.** Vad som är kvar läses i en enda `evaluate()`. Ett
svar som är inaktuellt är illa nog; två svar med en omritning emellan är
ett svar om ett läge som aldrig funnits.

**LÄS EFTER OMRITNINGEN.** Efter varje avbockning väntas raden in som
avbockad i DOM:en innan listan läses om. Tidsgränsen finns kvar men betyder
något annat: "appen bokförde avbockningen men ritade den aldrig" är ett
besked om appen, till skillnad från "tjugo sekunder gick" som bara var ett
besked om maskinen.

Loopen ligger utanför browsertestet för att kunna prövas UTAN Playwright -
samma skäl som `diagnos.py`, `vantan.py` och `matt.py`: en loop som väntar
fel upptäcks annars först den gång den behövs, och då är körningen förbi.
"""


class Avbockningen(AssertionError):
    """Avbockningen kom inte i mål. AssertionError så unittest rapporterar
    den som ett fel i testet och inte som en krasch i hjälparen."""


# Hur många varor listan som mest får innehålla. Ett tak, inte en tidsgräns:
# en lista som aldrig tar slut ska fällas, inte hänga körningen.
TAK = 80

# Hur många gånger ett klick får byta nod under sig innan det ges upp.
# Varje avbockning river listan och startar en ny prishämtning, så noden kan
# ritas bort mitt under Playwrights egen väntan på att den ska stå stilla.
# Ett klick som inte landade är inget fel - det är ett varv till.
KLICKFORSOK = 8


def bocka_av_listan(kvar, klicka, avbockad, ritad, tak=TAK, forsok=KLICKFORSOK):
    """Bockar av varenda rad i listan och ger tillbaka namnen i tur och ordning.

    De fyra stegen skickas in i stället för en sida, så att loopen går att
    pröva utan Playwright - den är det enda här som kan läsa fel.

    - ``kvar()`` ger namnen som ännu bär ``data-bought``, lästa i ETT svep.
    - ``klicka(namn)`` bockar av raden. Ett klick som inte landar är inget
      fel; loopen prövar ``avbockad`` efteråt och försöker igen.
    - ``avbockad(namn)`` svarar om appen BOKFÖRDE avbockningen (tillståndet
      appen skrev, inte DOM:en).
    - ``ritad(namn)`` blockerar tills appen RITADE den. Det är den som
      håller nästa ``kvar()`` från att svara på ett läge som redan passerat.

    Att de två sista är skilda åt är hela poängen: det var precis mellan dem
    den gamla loopen läste.
    """
    avbockade = []
    for _ in range(tak):
        återstår = kvar()
        if not återstår:
            return avbockade
        namn = återstår[0]

        # Samma vara två gånger betyder att appen bokförde och ritade en
        # avbockning som sedan gick tillbaka. Det är ett riktigt fel och ska
        # heta det - den gamla loopen hade snurrat vidare tills taket tog
        # slut och sedan skyllt på listan.
        if namn in avbockade:
            raise Avbockningen(
                f"{namn} bockades av och ritades som avbockad, men stod strax"
                f" efter kvar som obockad i listan; avbockade hittills:"
                f" {avbockade}")

        for _ in range(forsok):
            klicka(namn)
            if avbockad(namn):
                break
        else:
            raise Avbockningen(
                f"{namn} gick inte att bocka av på {forsok} försök;"
                f" avbockade hittills: {avbockade}")

        # HÄR, och inte en rad tidigare, blir DOM:en läsbar igen.
        ritad(namn)
        avbockade.append(namn)

    raise Avbockningen(
        f"listan tog aldrig slut - {tak} avbockningar och det stod fortfarande"
        f" varor kvar; senast avbockade: {avbockade[-5:]}")


def raden(namn, behallare="#shoppingList"):
    """Väljaren för EN obockad rad, fäst vid varans namn.

    Ett namn är ett stabilt fäste; `>> nth=0` och `.first` är det inte -
    de betyder "den nod som råkar ligga först just nu", och listan ritas om
    under fötterna på den som frågar.
    """
    return f'{behallare} [data-bought="{namn}"]'


def forsta_obockade(page, behallare="#shoppingList"):
    """Namnet på första obockade raden, läst i ETT svep - eller None.

    Finns för de call-sites som bara vill åt EN rad och inte bockar av hela
    listan. De läste förut i två steg (`count()` och sedan `get_attribute()`)
    och bar därmed samma latenta fel som loopen: de råkade bara aldrig stå
    med en tom lista i glappet. `None` när listan är tom - inget väntande.
    """
    namn = page.evaluate(
        """(sel) => {
             const el = document.querySelector(sel + ' [data-bought]');
             return el ? el.getAttribute('data-bought') : null;
           }""",
        behallare)
    return namn or None


def sidans_lista(page, las_tillstand, behallare="#shoppingList",
                 klickgrans_ms=4000, ritgrans_ms=20000):
    """De fyra stegen mot en riktig Playwright-sida.

    ``las_tillstand`` skickas in i stället för att importeras, så att modulen
    kan läsas och prövas utan Playwright.
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    def kvar():
        # ETT svep. Namnen läses i sidan, i ett och samma ögonblick - inte
        # count() följt av get_attribute(), som är två ögonblick med en
        # omritning emellan.
        return page.evaluate(
            """(sel) => Array.from(document.querySelectorAll(sel + ' [data-bought]'))
                             .map(el => el.getAttribute('data-bought'))""",
            behallare)

    def klicka(namn):
        try:
            page.click(raden(namn, behallare), timeout=klickgrans_ms)
        except PlaywrightTimeoutError:
            pass  # omritad under klicket - läs tillståndet och försök igen

    def avbockad(namn):
        return namn in (las_tillstand().get("avklarade") or [])

    def ritad(namn):
        # Den avbockade raden ligger kvar på sin plats i avdelningen och
        # byter `data-bought` mot `data-need` (L3 - avbockad rad står kvar
        # där den hör hemma). Att vänta in `data-need` är därför ett besked
        # om att omritningen LANDAT, inte bara att den gamla noden är borta.
        #
        # MINST en rad, inte exakt en: samma vara kan stå på flera rader
        # (två rätter som båda behöver grädde), och status hänger på namnet
        # - så alla rader med namnet vänder i samma omritning.
        page.wait_for_selector(f'{behallare} [data-need="{namn}"]',
                               timeout=ritgrans_ms)

    return kvar, klicka, avbockad, ritad
