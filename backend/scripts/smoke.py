# -*- coding: utf-8 -*-
"""K4: rökprov mot en LEVANDE Matjakt - staging eller produktion.

Före det här paketet såg kontrollen efter en deploy ut så här: en människa
öppnade `/api/health` i en flik och tittade. Det fångar "servern svarar inte"
och ungefär inget annat. En deploy som startar, svarar `ok: true` och har
tappat hela prisplattformen ser likadan ut i den fliken som en frisk.

Rökprovet frågar därför sex saker som var och en har gått sönder på riktigt,
och som var och en är billig att ställa:

  1. `/api/health` svarar 200 och `ok: true`.
  2. `commit` i svaret är den commit som just deployades. Utan det kan
     provet ha lyckats mot den GAMLA processen medan den nya kraschade i
     starten - grönt prov, trasig release.
  3. `platform.active` är sant: prisplattformen har referenspriser och
     butiker. Utan den servar appen tomma veckor, och det syns inte i `ok`.
  4. `/api/recipes` svarar 200. Receptbanken byggs ur committad JSON vid
     start; en deploy på tom disk har startat utan den förut.
  5. `/api/account/state` UTAN token svarar 401. Går den till 200 ligger
     någons sparade vecka öppen.
  6. En admin-väg svarar 404 utan token. Admin-ytan ska inte ens synas.
  7. Stripe kör i det läge miljön ska köra i. `--stripe-lage test` mot
     staging, `live` mot produktion. En deploy som byter läge under fötterna
     på miljön ser frisk ut i allt annat: staging med `sk_live_` debiterar
     riktiga kort, produktion med `sk_test_` tar inte emot en enda betalning
     och säger ingenting om det.

Punkt 5 och 6 är säkerhetsgränser, inte hälsa. De står här därför att det är
efter en deploy de kan ha flyttat sig, och därför att provet är det sista
som körs innan frontenden släpps på.

    python backend/scripts/smoke.py --url https://matjakt.onrender.com/api \\
        --commit "$GITHUB_SHA"

`--commit` och `--stripe-lage` är valfria: utan dem hoppas punkt 2 respektive
7 över. Exitkod 0 = allt grönt, 1 = minst ett prov föll, och då står det
VILKET och vad som kom i stället.

Stripe-provet faller bara på ett MISSMATCH, aldrig på att Stripe saknas helt.
Skillnaden är avsiktlig och viktig: ett rött rökprov mot produktion utlöser en
automatisk återställning, och att rulla tillbaka en release för att en nyckel
aldrig sattes hade varit värre än felet.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

# En admin-väg som finns i api_server och som ALDRIG får svara utan token.
# GET, utan sidoeffekter.
ADMINVÄG = "/admin/primat-status"

TIDSGRÄNS = 20.0


def hämta(url: str, token: str | None = None, timeout: float = TIDSGRÄNS):
    """(status, kropp-som-dict-eller-None). Ett HTTP-fel är ett svar, inte ett fel."""
    begäran = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": "matjakt-smoke"})
    if token:
        begäran.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(begäran, timeout=timeout) as svar:  # noqa: S310
            rå = svar.read().decode("utf-8", "replace")
            status = svar.status
    except urllib.error.HTTPError as fel:
        rå = fel.read().decode("utf-8", "replace")
        status = fel.code
    try:
        return status, json.loads(rå)
    except (ValueError, json.JSONDecodeError):
        return status, None


def _commit_matchar(rapporterad, förväntad: str) -> bool:
    if not rapporterad or not förväntad:
        return False
    n = min(len(str(rapporterad)), len(förväntad), 12)
    return n >= 7 and str(rapporterad)[:n].lower() == förväntad[:n].lower()


def prov(bas: str, commit: str | None, hämtare=hämta, stripe_läge: str | None = None):
    """Kör alla prov. Returnerar [(namn, ok, detalj)] i körd ordning.

    `hämtare` är injicerad så testerna kan köra hela provet mot en riktig
    men påhittad server, utan nät och utan en deploy.
    """
    bas = bas.rstrip("/")
    resultat = []

    status, hälsa = hämtare(f"{bas}/health")
    hälsa = hälsa if isinstance(hälsa, dict) else {}
    resultat.append(("health svarar 200 och ok", status == 200 and hälsa.get("ok") is True,
                     f"status={status} ok={hälsa.get('ok')!r}"))

    if commit:
        rapporterad = hälsa.get("commit")
        resultat.append((f"drift kör {commit[:12]}", _commit_matchar(rapporterad, commit),
                         f"health.commit={rapporterad!r}"))

    plattform = hälsa.get("platform")
    aktiv = plattform.get("active") if isinstance(plattform, dict) else None
    resultat.append(("prisplattformen är aktiv", aktiv is True, f"platform.active={aktiv!r}"))

    audit = hälsa.get("pricingAudit")
    # Auditen är grön när den inte rapporterar en RÖD gate. Saknas den helt
    # har den aldrig körts i den här miljön - det är inte ett fel i deployen.
    audit_ok = True if not isinstance(audit, dict) else audit.get("gate") != "red"
    resultat.append(("prisauditen är inte röd", audit_ok, f"pricingAudit={audit!r}"))

    status, _ = hämtare(f"{bas}/recipes?limit=1")
    resultat.append(("recipes svarar 200", status == 200, f"status={status}"))

    status, _ = hämtare(f"{bas}/account/state")
    resultat.append(("account/state utan token svarar 401", status == 401, f"status={status}"))

    status, _ = hämtare(f"{bas}{ADMINVÄG}")
    resultat.append(("adminvägen svarar 404 utan token", status == 404, f"status={status}"))

    if stripe_läge:
        stripe = hälsa.get("stripe")
        läge = stripe.get("mode") if isinstance(stripe, dict) else None
        # MISSMATCH faller, SAKNAS gör det inte: ett rött rökprov mot
        # produktion utlöser en automatisk återställning, och att rulla
        # tillbaka en release för att en nyckel aldrig sattes vore värre än
        # felet. Det farliga - staging som debiterar riktiga kort, eller en
        # produktion som tyst slutar ta emot betalningar - är just ett
        # missmatch.
        ok = läge is None or läge == stripe_läge
        detalj = f"stripe.mode={läge!r}" + ("  (Stripe är inte uppsatt här)" if läge is None else "")
        resultat.append((f"stripe kör i {stripe_läge}-läge", ok, detalj))

    return resultat


def rapportera(resultat, skriv=print) -> int:
    fallna = [(namn, detalj) for namn, ok, detalj in resultat if not ok]
    for namn, ok, detalj in resultat:
        skriv(f"  {'OK  ' if ok else 'FEL '} {namn}   ({detalj})")
    if not fallna:
        skriv(f"Rökprov: {len(resultat)}/{len(resultat)} gröna.")
        return 0
    skriv("")
    skriv(f"::error::{len(fallna)} av {len(resultat)} rökprov föll:")
    for namn, detalj in fallna:
        skriv(f"    {namn} - {detalj}")
    return 1


def main(argv=None) -> int:
    tolk = argparse.ArgumentParser(description="Rökprov mot en levande Matjakt.")
    tolk.add_argument("--url", required=True, help="API-bas, t.ex. https://matjakt.onrender.com/api")
    tolk.add_argument("--commit", default=None, help="SHA som drift ska rapportera (valfri)")
    tolk.add_argument("--stripe-lage", dest="stripe_lage", default=None, choices=["test", "live"],
                      help="läget miljön SKA köra i: test för staging, live för produktion")
    argument = tolk.parse_args(argv)
    commit = (argument.commit or "").strip() or None
    print(f"Rökprov mot {argument.url}"
          + (f" för {commit[:12]}" if commit else " (ingen commit-kontroll)"))
    return rapportera(prov(argument.url, commit, stripe_läge=argument.stripe_lage))


if __name__ == "__main__":
    sys.exit(main())
