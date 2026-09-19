# -*- coding: utf-8 -*-
"""Den första skapade veckan - och det som händer när den händer.

Registreringstrialen togs bort 2026-08-31 ("59/399, ingen automatisk
trial"). J3 lade sedan en trial på ett annat ställe i tratten - sju dagars
Premium efter den första skapade veckan - och affärsbeslutet 2026-09-19
tog bort även den: INGEN automatisk trial, varken vid registrering eller
vid aktivering. Premium är Free / Premium månad / Premium år, punkt.
Gamla trialer som redan delats ut läses fortfarande (accounts/store.py,
`trial_ends_at`) och får löpa ut av sig själva; ingen ny kan skrivas, för
metoden som skrev dem finns inte längre.

Kvar är SIGNALEN. Ett ställe vet vad "kontot skapade sin första vecka"
betyder, och det som fortfarande hänger på den:

* H5 (hänvisningen) betalar ut belöningen till den som bjöd in - just för
  att villkoret ska vara `vecka_skapad`, inte registrering, så vi inte
  betalar för tomma konton.

Signalen kommer från två håll och får bara utlösa EN gång:

1. `/api/pricing/week` - servern prissätter en vecka. Det är den starkaste
   signalen, för den går inte att fejka utan att faktiskt använda
   produkten.
2. `/api/analytics/event` med `vecka_skapad` - klienten säger det själv.

`AccountStore.mark_first_week` är atomär och returnerar True BARA på
övergången. Allt här nedanför bygger på det: körs funktionen tio gånger
händer belöningen en gång.
"""

import logging

logger = logging.getLogger("matjakt.billing.activation")


def on_first_week(accounts, user_id, *, hooks=()) -> dict | None:
    """Anropas när ett konto kan ha skapat sin första vecka.

    Returnerar None när det INTE var den första (det vanliga fallet: varje
    vecka efter den första), annars en sammanfattning av vad krokarna gav.
    Ingen entitlement ändras här - det är J3b:s hela poäng, och
    test_packaging_j3.TheActivationTrialIsGone vaktar det.

    Varje hook får (accounts, user_id) och körs i sin egen try: en trasig
    hänvisningsutbetalning får inte hindra nästa krok. Det här är en
    belöningsväg, inte en betalväg - den får aldrig vara skälet till att
    prissättningen av en vecka misslyckas."""
    if not user_id:
        return None
    try:
        first = accounts.mark_first_week(user_id)
    except Exception:
        logger.exception("Kunde inte markera första veckan för konto %s", user_id)
        return None
    if not first:
        return None
    granted = {"firstWeek": True, "hooks": []}
    for hook in hooks:
        try:
            result = hook(accounts, user_id)
            if result:
                granted["hooks"].append(result)
        except Exception:
            logger.exception("En aktiveringskrok föll för konto %s", user_id)
    return granted
