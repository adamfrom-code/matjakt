# -*- coding: utf-8 -*-
"""Veckans fynd som en publik, indexerbar sida: /fynd/vecka-{n}/.

Kampanjtorget finns redan som mejl. Samma data publicerad på webben är den
enda sidan på hela matjakt.store som får nytt innehåll varje vecka, och den
enda realistiska vägen till organisk sökning på "veckans erbjudanden Willys".
Mejlet blir då en utskickskanal för en sida som ändå indexeras.

MODULEN RENDERAR, DEN HÄMTAR INGET. `render_week()` är en ren funktion:
in med kampanjerna och veckonumret, ut med en färdig HTML-sträng. Hämtningen
ligger i backend/scripts/make_fynd_page.py. Det är därför sidan går att pröva
mot fixturer utan databas, prisserver eller nät - och därför acceptanstestet
kan köra båda formerna av indata mot samma funktion.

DE TVÅ FÄLTEN SOM INTE FINNS ÄN
C11 (docs/PAKET-C11-fynd.md) lägger till två fält på varje fynd:

    "recipeIds":   ["flaskfilerotmos", ...]   vilka recept fyndet passar i
    "savesOnWeek": 24.20                      kronor sparade på veckans mängd

C11 är inte byggd. Sidan läser fälten när de finns och faller tillbaka när de
inte gör det - den kraschar inte, och viktigare: den *ljuger inte*. Utan
`recipeIds` går det inte att påstå att ett fynd hör till en middag, och då
säger sidan det rakt ut i stället för att antyda motsatsen. Se
`_dela_upp()` och `INGEN_RECEPTKOPPLING`.

Underlaget mätt mot produktion 2026-09-11, före C11:

    Willys topp-10: tio glassar. Hemköp: tre Coca-Cola/Fanta.
    5 av 20 fynd går att koppla till ett recept.

Orsaken är `ORDER BY 1.0 - (campaign_price / regular_price) DESC` i
`campaign_deals()` - rankning på rent rabattdjup. Den ligger i Z-GROCERY och
rörs inte härifrån. Sidans värde är begränsat tills C11 landat; det som byggs
här är formen, och formen är rätt den dagen datan är det.

VAD SIDAN ALDRIG PÅSTÅR
  * Inget slutdatum. `validUntil` är alltid None i svaret - ingen kedja
    publicerar det - och ett påhittat "gäller t.o.m." är ett löfte butiken
    inte gett.
  * Ingen receptkoppling utan `recipeIds`.
  * Ingen "du sparar X kr på veckan" utan `savesOnWeek`. Rabatten i procent är
    butikens eget påstående och får visas; kronor sparade på en veckas mängd
    är vår räkning, och den finns inte förrän C11 räknar den.
  * Datumet då priserna lästes in står överst. En kampanjsida utan
    hämtningsdatum är en sida som åldras i tysthet.
"""

from __future__ import annotations

import html
import json
from datetime import date, datetime

DOMÄN = "https://matjakt.store"
APP = f"{DOMÄN}/app/"

# Sidan hör ihop med landningssidan och ska se ut som den: samma stilmall,
# samma typsnitt, samma tokens (docs/DESIGNSYSTEM-D.md). frontend/styles.css
# ligger i Z-STYLE och redigeras inte härifrån - sidan LÄNKAR till den och
# lägger sitt eget lilla block för fyndtabellen.
STILMALL = "/styles.css?v=4"

MÅNADER = ("januari", "februari", "mars", "april", "maj", "juni", "juli",
           "augusti", "september", "oktober", "november", "december")

VECKODAGAR = ("måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag")

INGEN_RECEPTKOPPLING = (
    "Just den här veckan kan vi inte visa vilka middagar fynden hör till. "
    "Kopplingen mellan en kampanjvara och ett recept byggs nattetid, och den "
    "är inte klar för alla varor än. Listan nedan är butikernas kampanjer som "
    "de ser ut - inte ett urval vi står för."
)


def _e(text) -> str:
    """Allt under här kommer ur butikernas egna produktnamn. Escapa allt."""
    return html.escape(str(text if text is not None else ""), quote=True)


def _kr(belopp) -> str:
    """39,00 kr. Komma som decimaltecken, hårt mellanslag före enheten så
    talet aldrig bryts från sitt "kr" vid radbrytning."""
    return f"{float(belopp):.2f}".replace(".", ",") + " kr"


def _datumtext(stund: datetime) -> str:
    return (f"{VECKODAGAR[stund.weekday()]} {stund.day} {MÅNADER[stund.month - 1]} "
            f"kl. {stund.hour:02d}.{stund.minute:02d}")


def _recept_av(fynd: dict) -> list:
    """recipeIds finns inte förrän C11. Tåligt mot både saknat fält, None,
    fel typ och tom lista - ett svar från en äldre server ska ge en sida, inte
    ett undantag."""
    ids = fynd.get("recipeIds")
    if not isinstance(ids, (list, tuple)):
        return []
    return [str(i) for i in ids if isinstance(i, str) and i.strip()]


def _sparat_av(fynd: dict):
    """savesOnWeek i kronor, eller None. Ett tal <= 0 är inget fynd att
    skylta med och behandlas som frånvarande."""
    värde = fynd.get("savesOnWeek")
    if isinstance(värde, bool) or not isinstance(värde, (int, float)):
        return None
    return float(värde) if värde > 0 else None


def _dela_upp(deals_by_chain: dict) -> tuple[list, dict]:
    """Delar fynden i (de som hör till en middag, resten per kedja).

    Det är hela sidans logik. Har ett fynd `recipeIds` hamnar det överst med
    sin receptkoppling; har det inte det ligger det kvar i kedjans egen
    tabell. Före C11 är första listan tom och sidan visar bara tabellerna.
    Efter C11 är den tvärtom nästan allt, och det är då sidan blir värd sin
    plats i sökresultaten."""
    med_recept = []
    per_kedja = {}
    for kedja, fynd_lista in (deals_by_chain or {}).items():
        kvar = []
        for fynd in fynd_lista or []:
            if not isinstance(fynd, dict) or not fynd.get("name"):
                continue
            if _recept_av(fynd):
                med_recept.append((kedja, fynd))
            else:
                kvar.append(fynd)
        if kvar:
            per_kedja[kedja] = kvar
    # Sortering: sparade kronor när C11 räknat dem, annars rabattdjup.
    med_recept.sort(key=lambda rad: (_sparat_av(rad[1]) or 0,
                                     rad[1].get("discountPercent") or 0), reverse=True)
    return med_recept, per_kedja


def _fyndrad(kedja: str, fynd: dict, recept_titlar: dict, *, visa_kedja: bool) -> str:
    namn = _e(fynd.get("name"))
    delar = []
    if fynd.get("size"):
        delar.append(_e(fynd["size"]))
    if fynd.get("brand"):
        delar.append(_e(fynd["brand"]))
    if visa_kedja:
        delar.append(_e(kedja))
    underrad = " · ".join(delar)

    pris = _kr(fynd["campaignPrice"])
    ordinarie = _kr(fynd["regularPrice"])
    rabatt = int(fynd.get("discountPercent") or 0)

    noteringar = []
    sparat = _sparat_av(fynd)
    if sparat is not None:
        noteringar.append(f"Du sparar {_kr(sparat)} på veckans mängd")
    lägsta = fynd.get("lowestSeen")
    if isinstance(lägsta, (int, float)) and not isinstance(lägsta, bool) \
            and lägsta >= float(fynd["campaignPrice"]):
        noteringar.append("Lägsta vi sett på 30 dagar")

    recept = _recept_av(fynd)
    receptrad = ""
    if recept:
        namngivna = [recept_titlar[r] for r in recept if r in recept_titlar]
        if namngivna:
            lista = ", ".join(_e(t) for t in namngivna[:3])
            mer = f" och {len(namngivna) - 3} till" if len(namngivna) > 3 else ""
            receptrad = f'<p class="fynd-recept">Används i {lista}{mer}.</p>'
        else:
            antal = len(recept)
            rätt = "rätt" if antal == 1 else "rätter"
            receptrad = f'<p class="fynd-recept">Passar i {antal} {rätt} i Matjakt.</p>'

    notrad = (f'<p class="fynd-not">{" · ".join(_e(n) for n in noteringar)}</p>'
              if noteringar else "")

    rader = [f'<p class="fynd-namn">{namn}</p>']
    if underrad:
        rader.append(f'<p class="fynd-meta">{underrad}</p>')
    if receptrad:
        rader.append(receptrad)
    if notrad:
        rader.append(notrad)
    text = "\n".join("          " + rad for rad in rader)

    return (
        '      <li class="fynd-rad">\n'
        '        <div class="fynd-text">\n'
        f'{text}\n'
        '        </div>\n'
        '        <div class="fynd-pris">\n'
        f'          <p class="fynd-nu">{pris}</p>\n'
        f'          <p class="fynd-ord">ord. {ordinarie} · −{rabatt} %</p>\n'
        '        </div>\n'
        '      </li>'
    )


def _json_ld(*, vecka: int, år: int, antal: int, kedjor: list, hämtad: datetime) -> str:
    """ItemList + en BreadcrumbList. Inget Offer-schema: Google kräver
    `priceValidUntil` eller `availability` för produkterbjudanden, och båda
    hade varit påhittade här - `validUntil` är alltid None i svaret."""
    data = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": f"Veckans erbjudanden vecka {vecka} {år}",
        "description": (f"{antal} kampanjvaror hos {_och(kedjor)}, inlästa "
                        f"{hämtad.date().isoformat()}."),
        "url": f"{DOMÄN}/fynd/vecka-{vecka}/",
        "inLanguage": "sv-SE",
        "numberOfItems": antal,
        "datePublished": hämtad.date().isoformat(),
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def _och(namn: list) -> str:
    namn = list(namn)
    if not namn:
        return ""
    if len(namn) == 1:
        return namn[0]
    return ", ".join(namn[:-1]) + " och " + namn[-1]


def render_week(deals_by_chain: dict, *, vecka: int, år: int, hämtad: datetime,
                recept_titlar: dict | None = None) -> str:
    """HTML för en veckas fyndsida. Ren funktion - inga filer, inget nät."""
    recept_titlar = recept_titlar or {}
    med_recept, per_kedja = _dela_upp(deals_by_chain)
    kedjor = sorted(set(list(per_kedja) + [k for k, _ in med_recept]))
    antal = len(med_recept) + sum(len(v) for v in per_kedja.values())

    titel = f"Veckans erbjudanden vecka {vecka} – {_och(kedjor)}" if kedjor \
        else f"Veckans erbjudanden vecka {vecka}"
    beskrivning = (
        f"{antal} kampanjvaror hos {_och(kedjor)} vecka {vecka}, med ordinarie pris "
        f"och rabatt. Priserna är inlästa {hämtad.date().isoformat()} – Matjakt "
        f"gissar aldrig ett pris." if antal else
        f"Vecka {vecka}: inga kampanjer kunde läsas in.")
    kanonisk = f"{DOMÄN}/fynd/vecka-{vecka}/"

    delar = [f"""<!DOCTYPE html>
<html lang="sv">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#ECEEEF">
  <title>{_e(titel)} | Matjakt</title>
  <meta name="description" content="{_e(beskrivning)}">
  <link rel="canonical" href="{kanonisk}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="Matjakt">
  <meta property="og:locale" content="sv_SE">
  <meta property="og:url" content="{kanonisk}">
  <meta property="og:title" content="{_e(titel)}">
  <meta property="og:description" content="{_e(beskrivning)}">
  <meta property="og:image" content="{DOMÄN}/og-image.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{_e(titel)}">
  <meta name="twitter:description" content="{_e(beskrivning)}">
  <meta name="twitter:image" content="{DOMÄN}/og-image.png">
  <link rel="icon" href="/app/assets/icons/icon-192.png">
  <link rel="apple-touch-icon" href="/app/assets/icons/apple-touch-icon.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600&family=Newsreader:ital,opsz,wght@0,6..72,300..700;1,6..72,300..600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{STILMALL}">
  <script type="application/ld+json">
{_json_ld(vecka=vecka, år=år, antal=antal, kedjor=kedjor, hämtad=hämtad)}
  </script>
  <style>
    /* Bara det fyndlistan behöver. Tokens, typsnitt, knappar och rader
       kommer ur frontend/styles.css (Z-STYLE) - den redigeras inte härifrån.
       Radien är noll och accenten bär ingen status: DESIGNSYSTEM-D 2.3. */
    .fynd-lista{{margin:0;padding:0;list-style:none;border-top:1px solid var(--rule)}}
    .fynd-rad{{display:flex;gap:var(--sp-5);align-items:flex-start;justify-content:space-between;
      padding:var(--sp-5) 0;border-bottom:1px solid var(--rule)}}
    .fynd-text{{min-width:0}}
    .fynd-namn{{margin:0;font:500 16px/1.3 var(--f-ui)}}
    .fynd-meta{{margin:2px 0 0;color:var(--ink-3);font-size:13px}}
    .fynd-recept{{margin:6px 0 0;font-size:13px;color:var(--ink-2)}}
    .fynd-not{{margin:4px 0 0;font-size:13px;color:var(--ink-3)}}
    .fynd-pris{{flex:0 0 auto;text-align:right;white-space:nowrap}}
    .fynd-nu{{margin:0;font:400 22px/1.1 var(--f-disp)}}
    .fynd-ord{{margin:2px 0 0;color:var(--ink-3);font-size:13px}}
    .fynd-kedja{{margin:var(--sp-7) 0 0}}
    .fynd-kedja h2{{margin:0 0 var(--sp-3)}}
    .fynd-hamtad{{color:var(--ink-3);font-size:14px;margin:0 0 var(--sp-6)}}
    .fynd-tomt{{padding:var(--sp-6) 0;color:var(--ink-2)}}
    @media (max-width:480px){{
      .fynd-rad{{gap:var(--sp-4)}}
      .fynd-nu{{font-size:19px}}
    }}
  </style>
</head>
<body>
  <header class="site-topbar">
    <a class="site-wordmark" href="/">Matjakt</a>
    <nav class="site-nav" aria-label="Huvudmeny">
      <a href="/#sa-fungerar-det">Så funkar det</a>
      <a href="/#pris">Pris</a>
      <a href="/#vanliga-fragor">Vanliga frågor</a>
    </nav>
    <a class="site-btn site-btn-primary site-btn-sm" href="/app/">Öppna appen</a>
  </header>

  <main class="site-wrap">
    <section class="site-section">
      <p class="site-eyebrow">KAMPANJTORGET</p>
      <h1>Veckans erbjudanden – vecka {vecka}</h1>
      <p class="site-lead">{"Kampanjer hos " + _e(_och(kedjor)) + ", med ordinarie pris bredvid kampanjpriset." if kedjor else "Inga kampanjer kunde läsas in."}</p>
      <p class="fynd-hamtad">Priserna lästes in {_e(_datumtext(hämtad))}. Kampanjerna
        gäller så länge butiken har dem kvar – vi hittar aldrig på ett slutdatum
        butiken inte gett oss.</p>"""]

    if antal == 0:
        delar.append("""
      <p class="fynd-tomt">Inga kampanjer kunde läsas in den här veckan. Det är
        inte samma sak som att butikerna saknar erbjudanden – det betyder att vi
        inte kunde läsa dem, och då säger vi det i stället för att visa något vi
        inte vet.</p>""")
    else:
        if med_recept:
            delar.append(f"""
      <h2>Fynd som hamnar i en middag</h2>
      <p class="site-lead">Ett fynd du inte använder är inget fynd. De här
        kampanjvarorna är ingredienser i recept Matjakt kan planera in åt dig.</p>
      <ul class="fynd-lista">
{chr(10).join(_fyndrad(k, f, recept_titlar, visa_kedja=True) for k, f in med_recept)}
      </ul>""")
        else:
            delar.append(f"""
      <p class="site-note">{INGEN_RECEPTKOPPLING}</p>""")

        for kedja in sorted(per_kedja):
            rubrik = "Övriga kampanjer hos " + _e(kedja) if med_recept else _e(kedja)
            delar.append(f"""
      <div class="fynd-kedja">
        <h2>{rubrik}</h2>
        <ul class="fynd-lista">
{chr(10).join(_fyndrad(kedja, f, recept_titlar, visa_kedja=False) for f in per_kedja[kedja])}
        </ul>
      </div>""")

    delar.append(f"""
    </section>

    <section class="site-section site-cta">
      <h2>Kampanjerna är bara halva jobbet</h2>
      <p class="site-lead">Matjakt lägger in fynden i middagar du faktiskt lagar,
        räknar vad hela veckan kostar och visar vilken butik som blir billigast.</p>
      <p class="site-actions"><a class="site-btn site-btn-primary" href="{APP}">Kom igång gratis</a></p>
      <p class="site-note">Gratis att använda. Inget kort. Inget konto krävs för att prova.</p>
    </section>
  </main>

  <footer class="site-footer site-wrap">
    <a class="site-wordmark" href="/">Matjakt</a>
    <nav aria-label="Sidfot">
      <a href="/fynd/">Alla veckor</a>
      <a href="mailto:adamfrom@icloud.com">adamfrom@icloud.com</a>
      <a href="/integritetspolicy.html">Integritetspolicy</a>
      <a href="/anvandarvillkor.html">Användarvillkor</a>
    </nav>
    <p>Priserna kommer från butikskedjornas egna uppgifter. Produktinformation
      delvis från Dabas. Klipp från Pexels.</p>
  </footer>
  <script src="/traffic.js" defer></script>
</body>
</html>
""")
    return "".join(delar)


def render_index(veckor: list) -> str:
    """Arkivsidan /fynd/. En vecka utan en stabil ingång blir en lös sida som
    bara mejlet känner till; den här länkar ihop dem och ger sökmotorn en väg
    in till varje ny vecka utan att sitemapen måste hinna först.

    `veckor` är [(vecka, år, antal_fynd, hämtad_datum)], nyaste först."""
    titel = "Veckans erbjudanden – arkiv"
    beskrivning = ("Alla veckors kampanjer hos Willys, Hemköp och City Gross, "
                   "med ordinarie pris och rabatt.")
    rader = "\n".join(
        f'        <li class="fynd-rad">\n'
        f'          <div class="fynd-text">\n'
        f'            <p class="fynd-namn"><a href="/fynd/vecka-{v}/">Vecka {v}, {å}</a></p>\n'
        f'            <p class="fynd-meta">Inläst {d}</p>\n'
        f'          </div>\n'
        f'          <div class="fynd-pris"><p class="fynd-ord">{n} fynd</p></div>\n'
        f'        </li>'
        for v, å, n, d in veckor) or \
        '        <li class="fynd-rad"><div class="fynd-text">' \
        '<p class="fynd-meta">Inga veckor publicerade än.</p></div></li>'

    return f"""<!DOCTYPE html>
<html lang="sv">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#ECEEEF">
  <title>{titel} | Matjakt</title>
  <meta name="description" content="{beskrivning}">
  <link rel="canonical" href="{DOMÄN}/fynd/">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="Matjakt">
  <meta property="og:locale" content="sv_SE">
  <meta property="og:url" content="{DOMÄN}/fynd/">
  <meta property="og:title" content="{titel}">
  <meta property="og:description" content="{beskrivning}">
  <meta property="og:image" content="{DOMÄN}/og-image.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{titel}">
  <meta name="twitter:description" content="{beskrivning}">
  <meta name="twitter:image" content="{DOMÄN}/og-image.png">
  <link rel="icon" href="/app/assets/icons/icon-192.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600&family=Newsreader:ital,opsz,wght@0,6..72,300..700;1,6..72,300..600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{STILMALL}">
  <style>
    .fynd-lista{{margin:0;padding:0;list-style:none;border-top:1px solid var(--rule)}}
    .fynd-rad{{display:flex;gap:var(--sp-5);align-items:flex-start;justify-content:space-between;
      padding:var(--sp-5) 0;border-bottom:1px solid var(--rule)}}
    .fynd-namn{{margin:0;font:500 16px/1.3 var(--f-ui)}}
    .fynd-namn a{{color:var(--accent)}}
    .fynd-meta{{margin:2px 0 0;color:var(--ink-3);font-size:13px}}
    .fynd-pris{{flex:0 0 auto;text-align:right;white-space:nowrap}}
    .fynd-ord{{margin:0;color:var(--ink-3);font-size:13px}}
  </style>
</head>
<body>
  <header class="site-topbar">
    <a class="site-wordmark" href="/">Matjakt</a>
    <nav class="site-nav" aria-label="Huvudmeny">
      <a href="/#sa-fungerar-det">Så funkar det</a>
      <a href="/#pris">Pris</a>
      <a href="/#vanliga-fragor">Vanliga frågor</a>
    </nav>
    <a class="site-btn site-btn-primary site-btn-sm" href="/app/">Öppna appen</a>
  </header>

  <main class="site-wrap">
    <section class="site-section">
      <p class="site-eyebrow">KAMPANJTORGET</p>
      <h1>Veckans erbjudanden</h1>
      <p class="site-lead">Willys, Hemköps och City Gross kampanjer, vecka för
        vecka, med ordinarie pris bredvid kampanjpriset. Priserna läses in varje
        natt – vi gissar aldrig ett pris.</p>
      <ul class="fynd-lista">
{rader}
      </ul>
    </section>
  </main>

  <footer class="site-footer site-wrap">
    <a class="site-wordmark" href="/">Matjakt</a>
    <nav aria-label="Sidfot">
      <a href="mailto:adamfrom@icloud.com">adamfrom@icloud.com</a>
      <a href="/integritetspolicy.html">Integritetspolicy</a>
      <a href="/anvandarvillkor.html">Användarvillkor</a>
    </nav>
    <p>Priserna kommer från butikskedjornas egna uppgifter. Produktinformation
      delvis från Dabas. Klipp från Pexels.</p>
  </footer>
  <script src="/traffic.js" defer></script>
</body>
</html>
"""


def sitemap_poster(veckor: list) -> list:
    """(loc, lastmod, changefreq, priority) för arkivet och varje vecka.

    Arkivet uppdateras varje vecka, en enskild veckosida gör det aldrig igen -
    `changefreq` säger det, så sökmotorn slutar hämta om gamla veckor."""
    poster = [(f"{DOMÄN}/fynd/", max((d for _, _, _, d in veckor), default=date.today().isoformat()),
               "weekly", "0.6")]
    for vecka, _, _, hämtad in veckor:
        poster.append((f"{DOMÄN}/fynd/vecka-{vecka}/", hämtad, "never", "0.5"))
    return poster
