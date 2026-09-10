# -*- coding: utf-8 -*-
"""Kontots hela dataexport - GDPR art. 15 och 20.

WHY. Raderingen fanns och var gedigen. Exporten fanns inte alls.
`GET /api/account/state` gav appstaten och ingenting annat: inte
e-postadressen, inte prenumerationshistoriken, inte hushållsmedlemskapet,
inte samtyckestidpunkten. Rätten till dataportabilitet är rätten att få ut
det i ett maskinläsbart format, inte att få tillbaka det man själv skrev in
i appen.

SJU KATEGORIER, ALLA NAMNGIVNA. `CATEGORIES` är kontraktet, och testet läser
den listan. Det är avsiktligt tråkigt: en kategori som glöms bort ska synas
som ett rött test, inte som en tom nyckel ingen märker.

ALDRIG HEMLIGHETER. Exporten är en fil personen laddar ner, mejlar vidare
och glömmer i en nedladdningsmapp. Lösenordshash, salt, återställningstoken
och sessioner ingår inte - de är inte "hennes data" i någon användbar
mening, och de är precis det som gör en läckt fil farlig.
"""

from datetime import datetime, timezone

from ..observability import METRICS

# Kontraktet. Raden är avsiktligt kort och avsiktligt hårdkodad.
CATEGORIES = ("konto", "syncedState", "hushall", "skafferi", "lista", "analytics", "prenumeration")

FORMAT_VERSION = 1


def _parsed_state(raw):
    """Appstaten som JSON om den går att läsa, annars råsträngen.

    Att tyst kasta något som inte parsar vore att utelämna data ur en
    dataexport - hellre en sträng personen kan titta på."""
    if not raw:
        return None
    import json
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


def build(account_store, household_store, analytics_store, token: str) -> dict:
    """Hela exporten för den inloggade. Kastar `AccountError` utan session."""
    account = account_store.export_account(token)      # kastar om ingen session
    user_id = account["konto"]["id"]

    hushall, lista, skafferi = None, [], []
    if household_store is not None:
        try:
            household_id = household_store.household_id_for_user(user_id)
            if household_id:
                hushall = household_store.household_for(household_id, user_id)
                lista = household_store.shopping_items(household_id, user_id)
                skafferi = household_store.inventory_items(household_id, user_id)
        except Exception:
            # Ett trasigt hushållslager får inte göra hela exporten omöjlig -
            # då blir svaret på "ge mig min data" ett 500. Kategorin blir
            # tom och resten levereras.
            hushall, lista, skafferi = None, [], []

    analytics = []
    if analytics_store is not None:
        try:
            analytics = analytics_store.user_days(user_id)
        except Exception:
            analytics = []

    METRICS.incr("account_exports_total")
    export = {
        "konto": account["konto"],
        "syncedState": _parsed_state(account["syncedState"]),
        "hushall": hushall,
        "skafferi": skafferi,
        "lista": lista,
        "analytics": analytics,
        "prenumeration": account["prenumeration"],
        "meta": {
            "format": FORMAT_VERSION,
            "exporteradVid": datetime.now(timezone.utc).isoformat(),
            "kategorier": list(CATEGORIES),
            # Vad som medvetet INTE finns här, så att den som läser filen inte
            # tror att den är ofullständig.
            "utelamnat": ["lösenordshash", "salt", "återställningstoken",
                          "verifieringstoken", "sessioner"],
        },
    }
    return export
