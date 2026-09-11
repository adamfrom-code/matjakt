# -*- coding: utf-8 -*-
"""K4: rulla tillbaka Render till föregående LYCKADE deploy.

Rökprovet (backend/scripts/smoke.py) kan bli rött efter att en deploy redan
gått live. Då står produktionen med en trasig release och den enda vägen
tillbaka var att någon loggade in i Renders dashboard och tryckte "Deploy
previous" - vilket förutsätter att någon är vaken.

Skriptet gör samma sak över Renders API: hämtar tjänstens deploy-historik,
hittar den senaste `live`-deployen som INTE är den vi just skickade upp, och
startar om den committen.

    python backend/scripts/render_rollback.py --service srv-xxxx --exclude "$GITHUB_SHA"

Behöver RENDER_API_KEY i miljön. Saknas nyckeln - eller tjänst-id:t - säger
skriptet det rakt ut och returnerar 2: "kunde inte rulla tillbaka" är ett
annat besked än "rullade tillbaka", och det måste synas i loggen så att en
människa tar över. Det får ALDRIG se ut som en lyckad återställning.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.render.com/v1"

SAKNAS = 2  # förutsättning saknas - en människa måste ta över
MISSLYCKADES = 1


def _anrop(väg: str, nyckel: str, metod: str = "GET", kropp=None, timeout: float = 30.0):
    data = json.dumps(kropp).encode("utf-8") if kropp is not None else None
    begäran = urllib.request.Request(f"{API}{väg}", data=data, method=metod, headers={
        "Accept": "application/json",
        "Authorization": f"Bearer {nyckel}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(begäran, timeout=timeout) as svar:  # noqa: S310
        return svar.status, json.loads(svar.read().decode("utf-8", "replace") or "null")


def välj_mål(deployer, uteslut: str | None):
    """Senaste deployen som faktiskt VAR live och inte är den trasiga.

    Render svarar med nyaste först. `live` betyder att den en gång servade
    trafik - en `build_failed` eller `canceled` är inget att rulla tillbaka
    till, och det är just den sortens val man gör fel klockan tre på natten.
    """
    for post in deployer:
        deploy = post.get("deploy", post) or {}
        commit = ((deploy.get("commit") or {}).get("id") or "")
        if deploy.get("status") != "live":
            continue
        if uteslut and commit and commit.lower().startswith(uteslut[:12].lower()):
            continue
        return deploy
    return None


def main(argv=None) -> int:
    tolk = argparse.ArgumentParser(description="Rulla tillbaka Render till föregående live-deploy.")
    tolk.add_argument("--service", default=os.environ.get("RENDER_SERVICE_ID", ""),
                      help="Renders tjänst-id (srv-...)")
    tolk.add_argument("--exclude", default=None, help="SHA som INTE får väljas (den trasiga)")
    tolk.add_argument("--dry-run", action="store_true", help="visa målet, starta inget")
    argument = tolk.parse_args(argv)

    nyckel = os.environ.get("RENDER_API_KEY", "").strip()
    if not nyckel or not argument.service.strip():
        print("::error::Kan inte rulla tillbaka automatiskt: RENDER_API_KEY eller "
              "RENDER_SERVICE_ID saknas. Produktionen står kvar på den release som "
              "just föll rökprovet. Gå till Renders dashboard -> tjänsten -> Deploys "
              "-> senaste gröna -> \"Redeploy\", och lägg sedan in hemligheterna så "
              "att nästa gång går av sig själv.")
        return SAKNAS

    try:
        _, svar = _anrop(f"/services/{argument.service}/deploys?limit=20", nyckel)
    except (urllib.error.URLError, OSError, ValueError) as fel:
        print(f"::error::Kunde inte läsa deploy-historiken från Render: {fel}")
        return MISSLYCKADES

    mål = välj_mål(svar or [], (argument.exclude or "").strip() or None)
    if mål is None:
        print("::error::Hittade ingen tidigare live-deploy att rulla tillbaka till. "
              "Produktionen måste hanteras för hand.")
        return MISSLYCKADES

    commit = ((mål.get("commit") or {}).get("id") or "")[:12]
    if argument.dry_run:
        print(f"Skulle rulla tillbaka till {commit} (deploy {mål.get('id')}).")
        return 0

    try:
        _anrop(f"/services/{argument.service}/rollback", nyckel, metod="POST",
               kropp={"deployId": mål.get("id")})
    except (urllib.error.URLError, OSError, ValueError) as fel:
        print(f"::error::Renders API avvisade återställningen till {commit}: {fel}")
        return MISSLYCKADES

    print(f"::warning::Rullade tillbaka produktionen till {commit}. Releasen som föll "
          f"rökprovet är INTE live längre - men felet finns kvar i main och nästa "
          f"deploy tar med sig det igen. Åtgärda innan nästa merge.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
