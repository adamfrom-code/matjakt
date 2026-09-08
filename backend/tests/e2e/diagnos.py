# -*- coding: utf-8 -*-
"""Vad som sänkte täckningen, läst ur prissättningens riktiga svar.

Ligger utanför browsertestet för att kunna prövas UTAN Playwright: att
diagnosen läser rätt nycklar är precis den sortens sak som annars upptäcks
först den gång man behöver den, och då är körningen redan förbi."""

import json


def rader_som_saenker_taeckningen(result: dict) -> dict:
    """VILKA rader som drar ner täckningen, inte hur många.

    "16 av 19" säger att tre rader inte räknades, men inte vilka - och utan
    namnen går felet inte att söka vidare på efter att CI-loggen rullat
    förbi. Täckningen räknar EXAKTA rader (pricing.price_list), så en rad
    kan falla ur på två sätt: ingen produkt alls, eller ett gissat
    paketantal. De två betyder helt olika saker och hålls isär.
    """
    osaekra = [row.get("name") for row in (result.get("matchedItems") or [])
               if row.get("rowUncertain") or not row.get("exactPackaging", True)]
    saknade = [row.get("name") for row in (result.get("missingItems") or [])]
    return {"osäkra": sorted(n for n in osaekra if n),
            "saknade": sorted(n for n in saknade if n)}


# Vilka fält ur en prissättningsbegäran som får skrivas ut. WHITELISTA, inte
# svartlista: en svartlista släpper igenom allt någon lägger till senare, och
# begäran går genom en logg som hamnar i CI-utskrifter. Authorization-huvudet
# läses aldrig, och e-post eller postnummer finns inte bland nycklarna nedan.
BEGARANS_FALT = ("chain", "chains", "people", "recipeIds", "excludeItems", "stores")


def _vara(post: dict) -> dict:
    """En rad ur items, reducerad till det som påverkar beräkningen."""
    return {"name": post.get("name") or post.get("namn"),
            "amount": post.get("amount") if post.get("amount") is not None else post.get("total"),
            "unit": post.get("unit")}


def sammanfatta_begaran(post_data) -> dict:
    """Vad anropet FRÅGADE om - inte vad skärmen visade efteråt.

    Skärmens och lagringens tillstånd vid assertionen är kompletterande
    information: de läses efter att flera omgångar prissättning hunnit köra,
    och säger därför ingenting säkert om vad just det felande anropet
    innehöll. Den enda källan till det är begärans egen kropp.
    """
    if not post_data:
        return {"kropp": "saknas"}
    try:
        payload = json.loads(post_data)
    except (TypeError, ValueError):
        return {"kropp": "gick inte att tolka"}
    if not isinstance(payload, dict):
        return {"kropp": "ovantad form"}
    ut = {nyckel: payload[nyckel] for nyckel in BEGARANS_FALT if nyckel in payload}
    varor = payload.get("items") or payload.get("varor")
    if isinstance(varor, list):
        ut["items"] = [_vara(v) for v in varor if isinstance(v, dict)]
    # Skafferiavdraget ändrar vad som behöver köpas och alltså nämnaren.
    skafferi = payload.get("pantry")
    if isinstance(skafferi, dict):
        ut["pantry"] = dict(sorted(skafferi.items()))
    return ut


def sammanfatta_svar(status: int, data) -> dict:
    """Svaret, per kedja, plus vilka rader som sänkte täckningen."""
    if not isinstance(data, dict):
        return {"status": status, "kropp": "ingen json"}
    if "results" not in data:
        # /api/pricing/list eller ett låst svar: ta det som faktiskt finns.
        kort = {k: data[k] for k in ("locked", "feature", "freeChain", "error") if k in data}
        if isinstance(data.get("items"), list):
            kort["items"] = len(data["items"])
            kort["utanPris"] = sorted(
                p.get("ingredient") for p in data["items"]
                if isinstance(p, dict) and p.get("totalCost") is None and p.get("ingredient"))
        return {"status": status, **kort}
    rader = []
    for r in data["results"]:
        rad = {k: r.get(k) for k in
               ("chain", "locked", "comparable", "realPriceItems", "totalItems", "hasData")}
        if not r.get("locked") and r.get("comparable") is False:
            rad.update(rader_som_saenker_taeckningen(r))
        rader.append(rad)
    return {"status": status, "results": rader}
