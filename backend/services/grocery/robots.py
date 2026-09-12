# -*- coding: utf-8 -*-
"""robots.txt - läst, loggad och åtlydd före varje insamling.

VARFÖR DEN HÄR FILEN FINNS (D9). Coops och ICA:s robots.txt var utredda och
dokumenterade - men det är just de kedjorna vi INTE hämtar från. Willys,
Hemköp och City Gross, de tre som faktiskt hämtas varje natt, hade ingen läst
deras. Vi hade alltså gjort arbetet för de källor vi inte rör och hoppat över
det för dem vi rör.

Samtidigt utgav sig insamlaren för att vara Chrome 120 med ett
`Matjakt/1.0 (+grocery-collector)` på slutet - utan kontakt-URL. Att maskera
sig som webbläsare OCH identifiera sig halvvägs är den sämsta av två världar:
en kedja som vill säga nej kan inte hitta oss, och en kedja som vill säga ja
kan inte skilja oss från trafik den redan filtrerar. `USER_AGENT` här är den
ärliga varianten, samma form som dabas.py redan använt.

VAD SOM HÄNDER VID ETT FÖRBUD. Körningen STOPPAS - den kraschar inte. Ett
`Disallow` är ett svar, inte ett fel i vår kod: importen avslutas med
status `failed` och en text som säger vilken regel som stoppade den, och
larmkedjan (D1/D4) skickar den vidare eftersom ett misslyckat senaste försök
är ett eget larmvillkor.

FAIL-OPEN NÄR robots.txt INTE GÅR ATT LÄSA, och det är ett medvetet avsteg.
RFC 9309 säger att en klient BÖR behandla 5xx/oåtkomlig robots.txt som
"allt förbjudet". Vi loggar i stället en varning och fortsätter. Skälet: ett
femhundra på robots.txt är en blipp hos kedjans CDN, och den blippen skulle
annars stoppa hela nattens insamling för alla tre kedjorna på en gång - ett
driftfel förklätt till ett policybeslut. Det uppdraget kräver är att ett
FÖRBUD stoppar oss, och ett förbud är något robots.txt faktiskt säger.
En 404 (ingen robots.txt alls) betyder som alltid att allt är tillåtet.
"""

import logging
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from ..data_guard import guard_outbound_http

logger = logging.getLogger("matjakt.grocery.robots")

# Ärlig identitet med kontaktväg. Sidan /om-insamling finns ännu inte -
# UA:n pekar därför på startsidan tills I-vågen lägger upp den (se D9:s
# changelog-fragment); en UA som pekar på en 404 är sämre än en som pekar
# på en sida som finns.
USER_AGENT = "Matjakt/1.0 (+https://matjakt.store)"

# Token som robots.txt-regler matchas mot. RFC 9309: produktnamnet före
# snedstrecket, skiftlägesokänsligt.
AGENT_TOKEN = "Matjakt"

REQUEST_TIMEOUT_SECONDS = 10
# Så mycket av filen som hamnar i loggen. Hela robots.txt är sällan stor,
# men den ska inte kunna fylla loggen om någon lägger en megabyte där.
LOG_MAX_CHARS = 2000


class RobotsDisallowedError(Exception):
    """Kedjans robots.txt förbjuder en sökväg vi tänkte hämta."""

    def __init__(self, message: str, *, chain: str = "", url: str = ""):
        super().__init__(message)
        self.chain = chain
        self.url = url


class Beslut:
    """Utfallet av en robots-kontroll: vad som lästes och vad det betyder."""

    def __init__(self, *, allowed: bool, source: str, reason: str,
                 blocked_url: str = "", crawl_delay=None):
        self.allowed = allowed
        self.source = source            # robots.txt-adressen
        self.reason = reason            # läsbar mening, hamnar i statusen
        self.blocked_url = blocked_url
        self.crawl_delay = crawl_delay

    def __repr__(self):
        return f"<Beslut allowed={self.allowed} reason={self.reason!r}>"


def robots_url(url: str) -> str:
    delar = urlsplit(url)
    return f"{delar.scheme}://{delar.netloc}/robots.txt"


def _fetch(url: str) -> tuple[str | None, str]:
    """robots.txt-innehållet, eller None när den inte gick att läsa.

    Returnerar (text, förklaring). En 404 ger ("", ...) - alltså en tom
    robots.txt, vilket betyder att allt är tillåtet."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        guard_outbound_http("robots.txt")
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
            return body, f"HTTP {response.status}"
    except urllib.error.HTTPError as error:
        if 400 <= error.code < 500:
            # Ingen robots.txt = inga begränsningar (RFC 9309 §2.3.1.3).
            return "", f"HTTP {error.code} - ingen robots.txt"
        return None, f"HTTP {error.code}"
    except Exception as error:      # nätverksfel, timeout, DNS
        return None, type(error).__name__


def check(urls, *, chain: str = "", agent: str = AGENT_TOKEN, fetch=None) -> Beslut:
    """Läser kedjans robots.txt och prövar varje sökväg vi tänkte hämta.

    `urls` är de faktiska adresserna insamlingen använder, inte en gissad
    prefix: det är skillnaden mellan att kontrollera regeln och att
    kontrollera sin egen uppfattning om den."""
    urls = [u for u in (urls or []) if u]
    if not urls:
        return Beslut(allowed=True, source="", reason="inga adresser att pröva")

    källa = robots_url(urls[0])
    # Slås upp vid anropet, inte vid definitionen: ett test som byter
    # ut _fetch ska påverka också den väg importern går.
    text, förklaring = (fetch or _fetch)(källa)
    if text is None:
        # Se modulens docstring: medvetet avsteg från RFC 9309.
        logger.warning("%s: robots.txt kunde inte läsas (%s) - fortsätter, "
                       "men utan att ha sett reglerna", chain or källa, förklaring)
        return Beslut(allowed=True, source=källa,
                      reason=f"robots.txt kunde inte läsas ({förklaring})")

    logger.info("%s robots.txt (%s, %d tecken):\n%s", chain or källa, förklaring,
                len(text), text[:LOG_MAX_CHARS] or "(tom)")

    parser = RobotFileParser()
    parser.set_url(källa)
    parser.parse(text.splitlines())

    for url in urls:
        if not parser.can_fetch(agent, url):
            # Ingen genitiv-s: kedjan heter Willys, och "Willyss"
            # är inte svenska. Kolon läser lika bra för både
            # "Willys" och "City Gross".
            regel = f"{chain or källa}: robots.txt tillåter inte {url}"
            logger.error("%s - insamlingen stoppas", regel)
            return Beslut(allowed=False, source=källa, reason=regel, blocked_url=url)

    fördröjning = parser.crawl_delay(agent)
    return Beslut(allowed=True, source=källa,
                  reason=f"robots.txt tillåter samtliga {len(urls)} sökvägar "
                         f"({förklaring})",
                  crawl_delay=fördröjning)


def ensure_allowed(provider, *, fetch=None) -> Beslut:
    """Kontrollerar providerns egna insamlingsadresser. Kastar vid förbud.

    En provider utan `robots_urls` kontrolleras inte: Primat-vägen är ett
    betalt API med ett avtal, inte en sajt vi hämtar från, och dabas.py har
    sin egen nyckel och sina egna villkor. robots.txt gäller den som hämtar
    från en webbplats."""
    urls = list(getattr(provider, "robots_urls", None) or [])
    if not urls:
        return Beslut(allowed=True, source="", reason="providern hämtar inte från en webbplats")
    chain = getattr(provider, "name", "") or ""
    beslut = check(urls, chain=chain, fetch=fetch)
    if not beslut.allowed:
        raise RobotsDisallowedError(beslut.reason, chain=chain, url=beslut.blocked_url)
    return beslut
