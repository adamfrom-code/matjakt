# -*- coding: utf-8 -*-
"""Väntar tills backenden i drift KÖR den commit som just deployades.

K3. Fram till nu startade Render-hooken (ci.yml, jobbet `deploy-backend`) och
Pages-deployen (deploy.yml) av samma händelse. Pages är live på ~3 minuter,
Render på ~5. Däremellan fanns ett fönster där den NYA frontenden talade med
den GAMLA backenden, och klienten har inget API-versionskontrakt som fångar
det. Ett fält som tillkom i samma release fanns alltså inte i svaret, och
felet syntes som en tom vy hos användaren — i tre minuter, vid varje deploy.

Den här grinden stänger fönstret. `/api/health` bär redan `commit`
(api_server.py: `RENDER_GIT_COMMIT[:12]`), så frågan "kör drift den här
committen?" går att ställa utifrån, utan hemligheter. Pollningen håller
CI-körningen öppen tills svaret är ja — och en röd grind betyder att
Pages-deployen aldrig startar.

    python backend/scripts/wait_for_deploy.py \
        --url https://matjakt.onrender.com/api/health \
        --commit "$GITHUB_SHA" --timeout 480

Exitkoder: 0 = drift är minst lika ny som committen. 1 = blev inte det
inom fönstret.

K3c: grinden frågade först "kör drift EXAKT den här committen?" och det är
fel fråga. Render slår ihop snabba pushar och deployar den SENASTE, inte
varje commit. En natt med tjugo merger ger då grindkörningar som aldrig kan
bli gröna - produktionen kommer aldrig att köra just de mellanliggande
committarna. Det hände: K6c:s e4e55836 pollades i 466 s medan drift stod på
9968f6d, och drift gick sedan vidare till e836a3d utan att stanna på vår.

Invarianten som faktiskt ska skyddas är att FRONTENDEN ALDRIG ÄR NYARE ÄN
BACKENDEN. En backend som är nyare är i sin ordning. Frågan är alltså "är
drift minst lika ny som den här committen?" - alltså: är vår commit en
förfader till, eller lika med, den drift rapporterar.

Det spelar roll bortom en röd bock. En main som alltid är röd lär alla att
ignorera röd CI, och då är grinden sämre än ingen grind.

Allt som inte är "rätt commit" räknas som "inte ännu", aldrig som "fel":
Render svarar 502 medan den nya instansen startar, och en kall start kan ge
en avbruten anslutning. Först när fönstret är slut blir tystnaden ett fel.
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

# Samma bredd som /api/health rapporterar: RENDER_GIT_COMMIT[:12]. Jämförelsen
# sker på den kortare av de två, så en full 40-teckens SHA från GITHUB_SHA
# matchar ett 12-teckens svar utan att någon behöver klippa den för hand.
KORT = 12


def _hamta(url: str, timeout: float) -> dict:
    """Läser /api/health. Kastar vid allt som inte är ett JSON-objekt."""
    begaran = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": "matjakt-deploy-gate"})
    with urllib.request.urlopen(begaran, timeout=timeout) as svar:  # noqa: S310 - egen URL
        kropp = svar.read().decode("utf-8", "replace")
    data = json.loads(kropp)
    if not isinstance(data, dict):
        raise ValueError("health svarade inte med ett objekt")
    return data


def matchar(rapporterad, forvantad: str) -> bool:
    """Kör drift den commit vi väntar på?

    Tomt eller None betyder att RENDER_GIT_COMMIT inte är satt i miljön. Det
    är en felkonfiguration och får ALDRIG tolkas som en träff — annars
    passerar grinden alltid, vilket är värre än ingen grind alls.
    """
    if not rapporterad or not forvantad:
        return False
    n = min(len(str(rapporterad)), len(forvantad), KORT)
    if n < 7:  # kortare än ett git-prefix: för svagt för att lita på
        return False
    return str(rapporterad)[:n].lower() == forvantad[:n].lower()


def ar_minst_sa_ny(rapporterad, forvantad: str, *, kor=None) -> bool:
    """Har drift hunnit FÖRBI vår commit?

    Sant när `forvantad` är förfader till det drift rapporterar. Det är det
    normala utfallet när flera merger landar tätt: Render deployar den
    senaste och hoppar över mellanläggen.

    Faller tillbaka på False vid ALLT som inte är ett rent ja. Känner git
    inte igen den rapporterade committen - grund klon, force-push, en commit
    från en annan gren - är svaret nej och grinden pollar vidare. Att gissa
    "den är nog nyare" vore att göra grinden till dekoration.
    """
    if not rapporterad or not forvantad:
        return False
    kor = kor or (lambda arg: subprocess.run(
        arg, capture_output=True, text=True, timeout=20))
    try:
        svar = kor(["git", "merge-base", "--is-ancestor", forvantad, str(rapporterad)])
    except (OSError, subprocess.SubprocessError):
        return False
    return svar.returncode == 0


def vanta(url: str, commit: str, timeout: float, interval: float,
          *, sova=time.sleep, klocka=time.monotonic, skriv=print,
          http_timeout: float = 20.0) -> int:
    """Pollar tills `commit` rapporteras, eller tills fönstret är slut.

    `sova` och `klocka` är injicerade med flit: testet driver en hel
    åttaminutersvakt på nolltid utan att någon sekund passerar på riktigt.
    """
    start = klocka()
    forsok = 0
    senaste = "inget svar"
    while True:
        forsok += 1
        try:
            data = _hamta(url, http_timeout)
            rapporterad = data.get("commit")
            if matchar(rapporterad, commit):
                skriv(f"Drift kör {rapporterad} = {commit[:KORT]} efter {forsok} försök "
                      f"({klocka() - start:.0f} s).")
                return 0
            if ar_minst_sa_ny(rapporterad, commit):
                skriv(f"Drift kör {rapporterad}, som ligger EFTER {commit[:KORT]} "
                      f"({forsok} försök, {klocka() - start:.0f} s). Render deployade "
                      f"förbi vår commit - frontenden är alltså inte nyare än "
                      f"backenden, vilket är det grinden skyddar.")
                return 0
            senaste = f"commit={rapporterad!r}"
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as fel:
            # 502/503 under omstart, TLS-hicka, halvt svar. Inte ett fel än.
            senaste = f"{type(fel).__name__}: {fel}"
        forfluten = klocka() - start
        if forfluten + interval >= timeout:
            skriv(f"::error::Backenden kör varken {commit[:KORT]} eller något efter "
                  f"den, efter {forfluten:.0f} s "
                  f"({forsok} försök). Senast: {senaste}. Frontenden deployas INTE — "
                  f"drift och frontend hade hamnat i otakt. Kontrollera Renders bygglogg; "
                  f"rulla tillbaka med \"Deploy previous\" om bygget är trasigt.")
            return 1
        skriv(f"  försök {forsok} ({forfluten:.0f}/{timeout:.0f} s): {senaste}")
        sova(interval)


def main(argv=None) -> int:
    tolk = argparse.ArgumentParser(description="Vänta tills drift kör en given commit.")
    tolk.add_argument("--url", required=True, help="Full URL till /api/health")
    tolk.add_argument("--commit", required=True, help="SHA som ska rapporteras (GITHUB_SHA)")
    tolk.add_argument("--timeout", type=float, default=480.0, help="Sekunder att vänta (standard 480)")
    tolk.add_argument("--interval", type=float, default=15.0, help="Sekunder mellan försök")
    argument = tolk.parse_args(argv)
    if not argument.commit.strip():
        print("::error::--commit är tom - grinden kan inte avgöra något.")
        return 1
    return vanta(argument.url, argument.commit.strip(), argument.timeout, argument.interval)


if __name__ == "__main__":
    sys.exit(main())
