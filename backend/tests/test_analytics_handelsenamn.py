# -*- coding: utf-8 -*-
"""Varje händelsenamn appen skickar måste finnas i ANALYTICS_EVENTS.

`_handle_analytics_event` svarar `400 Okänt event` på allt som inte står i
listan, och `trackEvent()` i appen sväljer varje fel med flit — mätning får
aldrig fälla ett klick. Summan av de två är att ett namn som glidit isär
tappas TYST: knappen fungerar, siffran blir aldrig till, och ingenting i
appen säger ifrån. Det upptäcktes förra gången i produktionsloggen, långt
efter att talen hade börjat ljuga.

Det här testet läser namnen ur frontenden i stället för att lita på att någon
minns att lägga till dem. Det går bara åt ett håll: allt appen SKICKAR måste
finnas i listan. Motsatsen prövas inte — `checkout_avbruten` och `mail_klick`
har medvetet sina namn i listan innan de har någon avsändare (se I7), och de
flesta händelserna i betalsteget skickas av servern, aldrig av appen.

Två saker utöver själva jämförelsen, för att kontrollen inte ska kunna bli
grön av att den slutat hitta något:

  * Varje `trackEvent(...)`-anrop måste gå att läsa ut. Ett anrop som testet
    inte kan tyda failar i stället för att hoppas över — annars kan nästa
    glapp gömma sig bakom en ny sorts argument.
  * Två avsändare bygger sitt namn av en variabel: `setView()` skickar
    `view_<vy>` och inställningsraderna `installning_<rad>`. De namnen står
    inte som text någonstans, och det var precis där de förra hålen satt.
    Mallarna expanderas därför mot värdemängden i källan — vyerna appen går
    till, raderna skärmen ritar ut — och båda har ett golv: hittar testet
    inga värden är det testet som är trasigt, inte ett godkänt läge.

Sist går varje namn hela vägen: `ServernTarEmotVarjeNamn` startar servern och
postar dem till `/api/analytics/event` med krav på 200. Det var 400:an som
tappade siffran, och en kontroll som bara jämför strängar hade fortsatt vara
grön om vägen fick en andra grind. Ett påhittat namn måste fortfarande ge
400 — att laga glappet får inte bli att öppna vägen för fritext.
"""

import json
import re
import sys
import threading
import unittest
from http import client as http_client
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()  # MATJAKT_DATA_DIR -> tempkatalog INNAN api_server importeras

import api_server  # noqa: E402
from services.accounts import ratelimit  # noqa: E402
from services.analytics import ANALYTICS_EVENTS  # noqa: E402

APP_DIR = Path(__file__).resolve().parents[2] / "frontend" / "app"
INDEX_HTML = APP_DIR / "index.html"

# `trackEvent(` och `app.trackEvent(` - men inte `trackEvent:` (standardvärdet
# i vymodulernas app-objekt) och inte definitionen i app.js.
ANROP = re.compile(r"(?<![\w$.])(?:[\w$]+\s*\.\s*)?trackEvent\s*\(")
DEFINITION = re.compile(r"function\s+$")
# Ett vanligt strängargument: trackEvent("vecka_skapad")
STRANGARGUMENT = re.compile(r"""^(['"])([A-Za-z0-9_]+)\1$""")
# En mall med EN inflikning: trackEvent(`view_${view}`)
MALLARGUMENT = re.compile(r"^`([A-Za-z0-9_]*)\$\{\s*([A-Za-z_$][\w$.]*)\s*\}`$")
# Vyerna appen faktiskt går till. Bottennavigeringen skickar sitt
# data-view-attribut rakt in i goToView(), så HTML:en är en avsändare den med.
VYANROP = re.compile(r"(?<![\w$.])(?:[\w$]+\s*\.\s*)?(?:setView|goToView)\s*\(\s*['\"]([A-Za-z0-9_]+)['\"]")
VYATTRIBUT = re.compile(r'data-view="([A-Za-z0-9_]+)"')
# Inställningsraderna: rad({ id: "budget", ... }) blir data-settings="budget",
# och attributet är det som flikas in i händelsenamnet.
INSTALLNINGSRAD = re.compile(r"rad\(\{\s*id:\s*['\"]([A-Za-z0-9_]+)['\"]")


def _slut_pa_strang(text: str, start: int) -> int | None:
    """Index precis efter strängen som börjar på `start`, eller None om den
    aldrig stängs."""
    citat = text[start]
    i = start + 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == citat:
            return i + 1
        i += 1
    return None


def _forsta_argumentet(text: str, oppen: int) -> str | None:
    """Första argumentet i anropet vars inledande parentes står på `oppen`.

    Går tecken för tecken i stället för med ett reguljärt uttryck: ett
    argument kan innehålla både parenteser och kommatecken inuti en sträng,
    och ett uttryck som gissar på närmaste `)` läser fel argument utan att
    märka det. Strängar hoppas över hela."""
    djup = 0
    i = oppen
    while i < len(text):
        tecken = text[i]
        if tecken in "\"'`":
            slut = _slut_pa_strang(text, i)
            if slut is None:
                return None
            i = slut
            continue
        if tecken in "([{":
            djup += 1
        elif tecken in ")]}":
            djup -= 1
            if djup == 0:
                return text[oppen + 1:i].strip()
        elif tecken == "," and djup == 1:
            return text[oppen + 1:i].strip()
        i += 1
    return None


def _kallfiler() -> list[Path]:
    return sorted(p for p in APP_DIR.rglob("*.js") if p.is_file())


def _vyer() -> set[str]:
    """Varje vy setView()/goToView() kan få - ur anropen och ur bottennavet."""
    vyer = set()
    for fil in _kallfiler():
        vyer.update(VYANROP.findall(fil.read_text(encoding="utf-8")))
    if INDEX_HTML.exists():
        vyer.update(VYATTRIBUT.findall(INDEX_HTML.read_text(encoding="utf-8")))
    return vyer


def _installningsrader() -> set[str]:
    """Varje id som blir en klickbar rad på Inställningar."""
    rader = set()
    for fil in _kallfiler():
        rader.update(INSTALLNINGSRAD.findall(fil.read_text(encoding="utf-8")))
    return rader


# Inflikningarna testet kan värdemängden för, och golvet för var och en. En
# mall med en variabel som INTE står här failar - att tyst räkna noll namn
# vore att låta nästa dynamiska avsändare glida förbi precis som de förra.
#
# Golven ligger med marginal under dagens antal (9 vyer, 11 rader). De ska
# fånga en avläsning som slutat matcha källan, inte snubbla på att ett paket
# lägger till eller tar bort en rad.
INFLIKNINGAR = {
    "view": (_vyer, 5),
    "button.dataset.settings": (_installningsrader, 6),
}


def _anrop() -> list[tuple[Path, int, str]]:
    """(fil, rad, argument) för varje trackEvent-anrop i frontend/app."""
    träffar = []
    for fil in _kallfiler():
        text = fil.read_text(encoding="utf-8")
        for match in ANROP.finditer(text):
            if DEFINITION.search(text[max(0, match.start() - 20):match.start()]):
                continue
            argument = _forsta_argumentet(text, match.end() - 1)
            rad = text.count("\n", 0, match.start()) + 1
            träffar.append((fil, rad, argument if argument is not None else ""))
    return träffar


class HandelsenamnenMotListan(unittest.TestCase):
    def setUp(self):
        self.anrop = _anrop()
        self.varden = {namn: las() for namn, (las, _golv) in INFLIKNINGAR.items()}

    def test_appen_har_avsandare_att_lasa(self):
        """Golvet: hittar testet inga anrop är det testet som är trasigt."""
        self.assertGreaterEqual(len(self.anrop), 8, "för få trackEvent-anrop hittade i frontend/app - "
                                                    "matchar ANROP fortfarande hur appen skickar?")
        for namn, (_las, golv) in INFLIKNINGAR.items():
            self.assertGreaterEqual(len(self.varden[namn]), golv,
                                    f"för få värden hittade för ${{{namn}}} - uttrycket matchar inte källan längre")

    def test_varje_anrop_gar_att_lasa_ut(self):
        """Ett argument testet inte kan tyda failar. Annars vore det fritt
        fram att smyga förbi kontrollen med en ny sorts uttryck."""
        for fil, rad, argument in self.anrop:
            with self.subTest(fil=fil.name, rad=rad):
                self.assertTrue(
                    STRANGARGUMENT.match(argument) or MALLARGUMENT.match(argument),
                    f"{fil.name}:{rad}: trackEvent({argument!r}) - argumentet går inte att läsa ut. "
                    f"Är det en ny sorts namn måste det här testet lära sig det, "
                    f"annars kan namnet glida ifrån ANALYTICS_EVENTS oupptäckt.",
                )

    def test_varje_skickat_namn_finns_i_analytics_events(self):
        """Acceptanskriteriet: inget namn appen skickar får ge 400."""
        saknade = []
        for fil, rad, argument in self.anrop:
            for namn in self._namnen(argument, fil, rad):
                if namn not in ANALYTICS_EVENTS:
                    saknade.append(f"{namn} ({fil.name}:{rad})")
        self.assertEqual(saknade, [], "Appen skickar namn som servern svarar 400 på och tappar tyst. "
                                      "Lägg till dem i ANALYTICS_EVENTS i services/analytics/store.py: "
                                      + ", ".join(saknade))

    def _namnen(self, argument: str, fil: Path, rad: int) -> list[str]:
        strang = STRANGARGUMENT.match(argument)
        if strang:
            return [strang.group(2)]
        mall = MALLARGUMENT.match(argument)
        if mall:
            prefix, variabel = mall.group(1), mall.group(2)
            # Bara inflikningar testet vet värdemängden för. En okänd
            # variabel är inte "ingen händelse" - det är ett hål, och då
            # ska testet säga det i stället för att räkna noll namn.
            self.assertIn(variabel, INFLIKNINGAR,
                          f"{fil.name}:{rad}: trackEvent(`{prefix}${{{variabel}}}`) - testet vet inte "
                          f"vilka värden {variabel} kan ha, så namnen kan inte prövas mot listan. "
                          f"Lägg avläsningen i INFLIKNINGAR.")
            return [f"{prefix}{värde}" for värde in sorted(self.varden[variabel])]
        return []


class ServernTarEmotVarjeNamn(unittest.TestCase):
    """Kontrollen ovan säger att namnet står i listan. Den här säger att
    servern faktiskt svarar 200 på det.

    Skillnaden är inte akademisk: det var 400:an som tappade siffran, och
    ett test som bara läser en mängd skulle fortsätta vara grönt om vägen
    fick en andra grind. Här går varje namn appen skickar hela vägen genom
    hanteraren, precis som från en riktig knapp."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), api_server.ApiHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def _posta(self, namn):
        # Hinken är per IP och alla anrop här delar 127.0.0.1.
        ratelimit.clear_on_success("analytics", "127.0.0.1")
        anslutning = http_client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            anslutning.request("POST", "/api/analytics/event",
                               body=json.dumps({"event": namn}).encode("utf-8"),
                               headers={"Content-Type": "application/json"})
            svar = anslutning.getresponse()
            rå = svar.read()
            return svar.status, (json.loads(rå) if rå else None)
        finally:
            anslutning.close()

    def test_varje_namn_appen_skickar_tas_emot(self):
        prövare = HandelsenamnenMotListan("test_varje_skickat_namn_finns_i_analytics_events")
        prövare.setUp()
        namnen = sorted({namn for fil, rad, argument in prövare.anrop
                         for namn in prövare._namnen(argument, fil, rad)})
        self.assertGreaterEqual(len(namnen), 8, "inga namn att pröva - läsningen är trasig")
        for namn in namnen:
            with self.subTest(namn=namn):
                status, kropp = self._posta(namn)
                self.assertEqual(status, 200, f"{namn} avvisas av servern: {kropp}")

    def test_ett_pahittat_namn_avvisas_fortfarande(self):
        """Listan är en allowlist, inte fritext. Att laga glappet får inte bli
        att öppna vägen för vad som helst."""
        status, _ = self._posta("nagot_appen_aldrig_skickar")
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
