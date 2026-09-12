# -*- coding: utf-8 -*-
"""K2b: skilj "hittade en sårbarhet" från "kunde inte fråga".

K2 satte upp `pip-audit` och `npm audit` i security-jobbet. Båda ställer en
fråga över nätet - till PyPI respektive npm-registret - och det betyder att
båda kan misslyckas av skäl som inte har med beroendena att göra.

Det hände 2026-09-11 på main-committen d34d294, körning 34650990118:

    requests.exceptions.ConnectionError: ('Connection aborted.',
        ConnectionResetError(104, 'Connection reset by peer'))

En omkörning av exakt samma commit blev grön. Ingenting var sårbart;
uppkopplingen blinkade.

VARFÖR DET INTE ÄR EN BAGATELL. "Hemligheter och versioner" är en av fyra
obligatoriska statuscheckar i rulesetet, och sedan K4/K6 står jobbet dessutom
i releasekedjan (`deploy-staging` behöver `security`). En blipp mot PyPI
blockerade alltså varje öppen PR från varje agent tills en människa hittade
och körde om jobbet - och stoppade hela deployen på vägen.

GRINDEN MÅSTE ÄNDÅ KUNNA BLI RÖD. Ett CI-steg som inte kan faila är inget
CI-steg, och en sårbarhetsskanning som svarar "nja" är värre än ingen: den
ser grön ut. Därför är nedgraderingen till varning inte "det gick inte bra,
strunt i det" utan kräver POSITIVT BEVIS för att felet låg i transporten:

  1. FINNS ETT SVAR ÄR SVARET FACIT. Båda verktygen kör med maskinläsbar
     utdata (`--format=json`, `--json`). Går rapporten att tolka har frågan
     kommit fram, och då avgör rapporten: sårbarheter -> RÖTT, inga -> grönt.
     Ett nätmönster i en CVE-text kan inte nedgradera något, för texten läses
     aldrig när det finns en rapport.

  2. SAKNAS SVAR KRÄVS EN KÄND TRANSPORTSIGNATUR. Bara de mönster som står i
     NÄTFALL nedan - avbruten uppkoppling, DNS, timeout, 502/503/504, 429 -
     räknas som "kunde inte fråga" och görs om. Allt annat som misslyckas är
     OKÄNT och fäller grinden. Ett trasigt verktyg, en trasig låsfil eller ett
     verktyg som inte ens startar är röda, precis som förr.

  3. FÖRST EFTER ALLA FÖRSÖK BLIR DET EN VARNING. Tre försök med växande paus.
     Först när samtliga föll på transporten skrivs `::warning::` och steget
     släpper igenom.

MEDVETEN AVVÄGNING: ligger PyPI eller npm nere en hel dag går PR:er igenom
oskannade, med en varning på varje körning. Det är valt med öppna ögon. Den
andra vägen - röd grind - stoppar elva agenter och hela releasekedjan på ett
fel som inte finns i koden, och en obligatorisk check som fälls av någon
annans drift lärs man sig att köra om utan att läsa.

Kommandona står HÄR och inte i ci.yml med flit. Flaggorna som ger maskinläsbar
utdata hör ihop med tolken som läser den: skiljer man dem åt kan en ändring i
ci.yml tyst göra varje körning otolkbar, och då blir varje körning ett
"nätfall" - en grind som aldrig mer kan bli röd. Det är precis det felet det
här paketet finns för att stänga.

Körs som:  python backend/scripts/audit_deps.py pip
           python backend/scripts/audit_deps.py npm
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from collections import namedtuple

# ── Utfall ──────────────────────────────────────────────────────────────
REN = "ren"              # frågan kom fram, inget att rapportera  -> grönt
SÅRBARHET = "sårbarhet"  # frågan kom fram, det finns fynd        -> RÖTT
NÄTFALL = "nätfall"      # frågan kom aldrig fram                 -> varning
OKÄNT = "okänt"          # misslyckades utan transportsignatur    -> RÖTT

# Kända transportsignaturer. Listan är med flit kort och specifik: varje rad
# här är en väg för ett fel att slippa fälla grinden, så ett mönster som
# "error" eller "failed" hör inte hemma. Mönstret ur körning 34650990118
# står först i listan.
NÄTFALL_MÖNSTER = [
    r"Connection aborted",
    r"Connection reset by peer",
    r"ConnectionResetError",
    r"ConnectionError",
    r"ProtocolError",
    r"NewConnectionError",
    r"MaxRetryError",
    r"Max retries exceeded",
    r"Read timed out",
    r"ReadTimeout(?:Error)?",
    r"ConnectTimeout(?:Error)?",
    r"Remote end closed connection",
    r"IncompleteRead",
    r"Temporary failure in name resolution",
    r"Name or service not known",
    r"socket hang up",
    r"network timeout",
    r"\bE(?:CONNRESET|CONNREFUSED|TIMEDOUT|NETUNREACH|HOSTUNREACH|AI_AGAIN|NOTFOUND)\b",
    r"\bENOAUDIT\b",            # npm: revisionsändpunkten svarar inte
    r"\b(?:429|502|503|504)\b.{0,40}(?:Too Many Requests|Bad Gateway|Service Unavailable|Gateway Time)",
    r"Service ?Unavailable",
    r"\bTLS\b.{0,30}handshake",
    r"SSLError",
]
_NÄTFALL = [re.compile(m, re.IGNORECASE) for m in NÄTFALL_MÖNSTER]


def är_nätfall(text):
    """Raden som bär transportsignaturen, eller None.

    Returnerar raden och inte bara True, för att varningen i loggen ska kunna
    säga VAD som gick fel. "kunde inte fråga PyPI" utan orsak är omöjligt att
    skilja från en tyst avstängd grind.

    SISTA träffen, inte första. En traceback börjar i det innersta anropet och
    slutar med undantaget som faktiskt tog sig hela vägen upp, och pip skriver
    dessutom sina egna "Retrying (...) after connection broken by ..." på
    vägen. Den sista raden är den som en människa hade läst.
    """
    träff = None
    for rad in (text or "").splitlines():
        for mönster in _NÄTFALL:
            if mönster.search(rad):
                träff = rad.strip()
                break
    return träff


def _json_ur(text):
    """Rapporten i texten, eller None.

    Verktygen skriver sin rapport på stdout, men en pip-varning eller en
    npm-notis kan hamna före ELLER efter den, och `json.loads` på hela
    strängen kräver att dokumentet är det enda som står där.

    Det spelar roll åt fel håll: en rapport som inte går att tolka ser för
    resten av skriptet ut som "fick inget svar", och skulle en dag varenda
    körning se ut så vore grinden avstängd utan att någon märkte det.
    `raw_decode` läser ett dokument från en position och bryr sig inte om vad
    som följer efter.
    """
    text = (text or "").strip()
    if not text:
        return None
    avkodare = json.JSONDecoder()
    for start in sorted({p for p in (0, text.find("{"), text.find("[")) if p >= 0}):
        try:
            return avkodare.raw_decode(text, start)[0]
        except ValueError:
            continue
    return None


def _svans(ut, fel, rader=15):
    """De sista raderna av utdatan, till felmeddelandet vid OKÄNT."""
    text = "\n".join(t for t in (ut, fel) if (t or "").strip())
    return "\n".join(text.splitlines()[-rader:]) or "(ingen utdata)"


# ── Tolkarna: vad verktyget FAKTISKT svarade ────────────────────────────

def tolka_pip_audit(returkod, ut, fel):
    """pip-audit --format=json: {"dependencies": [{"name", "vulns": [...]}]}."""
    rapport = _json_ur(ut)
    if rapport is not None:
        paket = rapport.get("dependencies", []) if isinstance(rapport, dict) else rapport
        fynd = []
        for beroende in paket:
            sårbarheter = beroende.get("vulns") or []
            if sårbarheter:
                # dict.fromkeys: unika i ordning. pip-audit listar samma
                # rådgivning en gång per källa den hittade den i - jinja2 3.1.2
                # kom tillbaka med tio poster som var fem rådgivningar.
                id_n = ", ".join(dict.fromkeys(str(s.get("id", "?")) for s in sårbarheter))
                fynd.append(f"{beroende.get('name')} {beroende.get('version')}: {id_n}")
        if fynd:
            return SÅRBARHET, "\n".join(dict.fromkeys(fynd))
        return REN, f"inga kända sårbarheter i {len(paket)} låsta paket"

    # Ingen rapport. Kom frågan fram över huvud taget?
    rad = är_nätfall(ut + "\n" + fel)
    if rad:
        return NÄTFALL, rad
    if returkod == 0:
        return REN, "pip-audit avslutade utan fynd"
    return OKÄNT, _svans(ut, fel)


def tolka_npm_audit(returkod, ut, fel):
    """npm audit --json: metadata.vulnerabilities, eller {"error": {...}}."""
    rapport = _json_ur(ut)
    if isinstance(rapport, dict) and isinstance(rapport.get("error"), dict):
        # npm:s egen felrapport. Den är maskinläsbar men är INTE ett facit -
        # den betyder just att revisionen aldrig gjordes.
        kod = str(rapport["error"].get("code") or "")
        fel_text = json.dumps(rapport["error"], ensure_ascii=False)
        sammanfattning = str(rapport["error"].get("summary") or kod or fel_text)
        if är_nätfall(fel_text):
            return NÄTFALL, f"{kod}: {sammanfattning}" if kod else sammanfattning
        return OKÄNT, sammanfattning

    if isinstance(rapport, dict) and isinstance(rapport.get("metadata"), dict):
        nivåer = rapport["metadata"].get("vulnerabilities") or {}
        allvarliga = int(nivåer.get("high") or 0) + int(nivåer.get("critical") or 0)
        if allvarliga:
            namn = sorted(
                paket for paket, post in (rapport.get("vulnerabilities") or {}).items()
                if str(post.get("severity", "")).lower() in ("high", "critical")
            )
            return SÅRBARHET, f"{allvarliga} på hög eller kritisk nivå: " + ", ".join(namn or ["(onamngivna)"])
        # Medel och lägre blockerar inte - se kommentaren i ci.yml om varför
        # nivån står vid hög. De räknas upp så att de syns i loggen ändå.
        lägre = int(nivåer.get("total") or 0)
        return REN, f"inga sårbarheter på hög eller kritisk nivå ({lägre} på lägre nivåer)"

    rad = är_nätfall(ut + "\n" + fel)
    if rad:
        return NÄTFALL, rad
    if returkod == 0:
        return REN, "npm audit avslutade utan fynd"
    return OKÄNT, _svans(ut, fel)


def tolka_förberedelse(returkod, ut, fel):
    """Installationssteget: inget facit att hämta, bara lyckades/föll."""
    if returkod == 0:
        return REN, ""
    rad = är_nätfall(ut + "\n" + fel)
    return (NÄTFALL, rad) if rad else (OKÄNT, _svans(ut, fel))


# ── Revisionerna ────────────────────────────────────────────────────────

Revision = namedtuple("Revision", "namn verktyg förberedelse kommando tolk")

REVISIONER = {
    "pip": Revision(
        namn="pip-audit mot låsfilen",
        verktyg="pip-audit",
        # Körs bara när verktyget saknas. I CI är det varje gång; lokalt,
        # och i acceptanstestet där en attrapp ligger på PATH, hoppas det
        # över - det är också det som håller sviten borta från nätet.
        förberedelse=[[sys.executable, "-m", "pip", "install", "--quiet", "pip-audit"]],
        # Låsfilen, inte miljön: skanningen ska läsa exakt det träd som
        # installeras i produktionsimagen.
        kommando=["pip-audit", "-r", "backend/requirements.txt",
                  "--format=json", "--progress-spinner=off"],
        tolk=tolka_pip_audit,
    ),
    "npm": Revision(
        namn="npm audit (hög och uppåt)",
        verktyg="npm",
        förberedelse=[],
        # --audit-level=high styr npm:s egen returkod; tolken räknar hög och
        # kritisk själv ur metadata. Båda säger samma sak, och flaggan står
        # kvar för att kommandot ska gå att läsa och köra för hand.
        kommando=["npm", "audit", "--audit-level=high", "--json"],
        tolk=tolka_npm_audit,
    ),
}


def _kör(argv):
    """(returkod, stdout, stderr). Bytas ut i testerna."""
    try:
        färdig = subprocess.run(argv, capture_output=True, text=True)
    except OSError as fel:                       # verktyget finns inte alls
        return 127, "", f"{argv[0]}: {fel}"
    return färdig.returncode, färdig.stdout, färdig.stderr


def _ett_försök(revision, kör, finns=shutil.which):
    if finns(revision.verktyg) is None:
        for argv in revision.förberedelse:
            utfall, text = tolka_förberedelse(*kör(argv))
            if utfall != REN:
                return utfall, f"installationen av {revision.verktyg}: {text}"
    return revision.tolk(*kör(revision.kommando))


def kör_revision(revision, försök=3, paus=5.0, kör=_kör, sov=time.sleep, finns=shutil.which):
    """Kör revisionen och gör om den så länge felet ligger i transporten.

    Pausen växer (paus, 2*paus, ...) så att en registerstrul som varar tio
    sekunder hinner gå över utan att steget står och mal i en minut.
    """
    sista = ""
    for omgång in range(1, max(1, försök) + 1):
        utfall, text = _ett_försök(revision, kör, finns)
        if utfall != NÄTFALL:
            return utfall, text
        sista = text
        print(f"  försök {omgång}/{försök} nådde inte fram: {text}", flush=True)
        if omgång < försök:
            sov(paus * omgång)
    return NÄTFALL, sista


def annotera(nivå, rubrik, text, tak=3000):
    """GitHub-annotation. Nyrader måste kodas, annars klipps meddelandet.

    Taket är för att en lång fyndlista inte ska få GitHub att kasta hela
    annotationen. Fullständig utdata står alltid i loggen ovanför.
    """
    text = str(text)
    if len(text) > tak:
        text = text[:tak] + "\n... (hela listan står i steget ovanför)"
    kodad = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::{nivå} title={rubrik}::{kodad}", flush=True)


def main(argv=None):
    tolk = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    tolk.add_argument("ekosystem", choices=sorted(REVISIONER))
    tolk.add_argument("--forsok", type=int, default=3,
                      help="antal försök innan ett transportfel blir en varning (standard 3)")
    tolk.add_argument("--paus", type=float, default=5.0,
                      help="sekunder före omförsök; växer med omgången (standard 5)")
    argument = tolk.parse_args(argv)

    revision = REVISIONER[argument.ekosystem]
    print(f"{revision.namn}: {' '.join(revision.kommando)}", flush=True)
    utfall, text = kör_revision(revision, argument.forsok, argument.paus)

    if utfall == SÅRBARHET:
        print(f"KÄNDA SÅRBARHETER:\n{text}", flush=True)
        annotera("error", f"Kända sårbarheter ({argument.ekosystem})", text)
        return 1
    if utfall == OKÄNT:
        print(f"{revision.namn} misslyckades utan transportfel:\n{text}", flush=True)
        annotera("error", f"Sårbarhetsskanningen gick sönder ({argument.ekosystem})", text)
        return 1
    if utfall == NÄTFALL:
        print(f"{revision.namn}: nådde inte fram på {argument.forsok} försök.", flush=True)
        annotera("warning", f"Sårbarhetsskanningen kunde inte fråga ({argument.ekosystem})",
                 f"{text}\nTrädet är OSKANNAT i den här körningen - det är inte ett besked om "
                 f"att det är rent. Återkommer varningen körning efter körning är det ett fel "
                 f"att felsöka, inte en blipp.")
        return 0
    print(f"{revision.namn}: {text}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
