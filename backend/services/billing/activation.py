# -*- coding: utf-8 -*-
"""Den första skapade veckan - och de saker som händer när den händer.

Matjakt tog medvetet bort provperioden 2026-08-31. Det var rätt beslut på
fel provperiod: en trial vid REGISTRERING testar nyfikenhet, och nyfikenhet
konverterar inte. En trial efter AKTIVERING testar produkten på någon som
redan har en vecka planerad och just sett att det skiljer 214 kr mellan
butikerna. Det är ett helt annat köpbeslut.

Därför finns ETT ställe som vet vad "kontot skapade sin första vecka"
betyder, och allt som ska belönas hänger på det:

* J3 ger sju dagars Premium.
* H5 (hänvisningen) betalar ut belöningen till den som bjöd in - just för
  att villkoret ska vara `vecka_skapad`, inte registrering, så vi inte
  betalar för tomma konton.

Signalen kommer från två håll och får bara utlösa EN gång:

1. `/api/pricing/week` - servern prissätter en vecka. Det är den starkaste
   signalen, för den går inte att fejka utan att faktiskt använda
   produkten.
2. `/api/analytics/event` med `vecka_skapad` - klienten säger det själv.

Att lita på (2) ensamt hade varit att låta vem som helst trigga sin egen
trial genom att posta ett event. Det spelar mindre roll än det låter -
belöningen är bunden till kontot och kan bara delas ut en gång - men (1)
finns för att signalen ska vara sann även när ingen mäter.

`AccountStore.mark_first_week` är atomär och returnerar True BARA på
övergången. Allt här nedanför bygger på det: körs funktionen tio gånger
händer belöningen en gång.
"""

import logging

logger = logging.getLogger("matjakt.billing.activation")

# Sju dagar. Ett tal, ett ställe. Ändras det här ändras det överallt -
# köpsidan läser det via /api/entitlements, inte ur en egen sträng.
ACTIVATION_TRIAL_DAYS = 7


def on_first_week(accounts, user_id, *, hooks=()) -> dict | None:
    """Anropas när ett konto kan ha skapat sin första vecka.

    Returnerar None när det INTE var den första (det vanliga fallet: varje
    vecka efter den första), annars en sammanfattning av vad som delades ut.

    Varje hook får (accounts, user_id) och körs i sin egen try: en trasig
    hänvisningsutbetalning får inte hindra provperioden, och tvärtom. Det
    här är en belöningsväg, inte en betalväg - den får aldrig vara skälet
    till att prissättningen av en vecka misslyckas."""
    if not user_id:
        return None
    try:
        first = accounts.mark_first_week(user_id)
    except Exception:
        logger.exception("Kunde inte markera första veckan för konto %s", user_id)
        return None
    if not first:
        return None
    granted = {"firstWeek": True, "trialDays": None, "hooks": []}
    try:
        trial_ends = accounts.grant_activation_trial(user_id, ACTIVATION_TRIAL_DAYS)
        if trial_ends:
            granted["trialDays"] = ACTIVATION_TRIAL_DAYS
            granted["trialEndsAt"] = trial_ends
    except Exception:
        logger.exception("Kunde inte bevilja aktiveringstrial för konto %s", user_id)
    for hook in hooks:
        try:
            result = hook(accounts, user_id)
            if result:
                granted["hooks"].append(result)
        except Exception:
            logger.exception("En aktiveringskrok föll för konto %s", user_id)
    return granted
