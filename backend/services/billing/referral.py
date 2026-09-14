# -*- coding: utf-8 -*-
"""Hänvisningsprogrammet: en personlig kod per konto.

Den som bjuder in får en månad Premium när den inbjudna byggt sin **första
vecka**. Den inbjudna får sin månad direkt.

VARFÖR VILLKORET ÄR "FÖRSTA VECKAN" OCH INTE "REGISTRERAD"

Ett registrerat konto som aldrig skapar en vecka är inte en kund - det är en
e-postadress. Betalar vi ut på registrering betalar vi för tomma konton, och
det enda som växer är kostnaden. Villkoret är därför `vecka_skapad`, och
signalen är exakt den som J3 byggde: `AccountStore.mark_first_week`, atomär
och sann bara på övergången. H5 hänger sig på den som en krok
(`api_server.ApiHandler.ACTIVATION_HOOKS`) i stället för att bygga en egen
väg, för två vägar till samma händelse betyder förr eller senare två svar.

BELÖNINGENS LÄNGD ÄR EN KONSTANT PÅ ETT STÄLLE

`REFERRAL_REWARD_DAYS` nedan. Både den inbjudnas direktbelöning och den
inbjudandes utbetalning läser den, koden som skapas bär den som sin
`grant_days`, och texten i appen hämtar den via /api/referral. Anledningen
är konkret: J3 gör Premium till enda sättet att dela lista med familjen, så
belöningen blir dyrare i samma stund som den blir mer lockande. Den dagen
talet ska ändras - uppåt för att driva tillväxt, nedåt för att den kostar för
mycket - ska det vara en rad, inte en jakt genom flödet.
"""

import logging

from . import codes as premium_codes

logger = logging.getLogger("matjakt.billing.referral")

# EN MÅNAD. Ett tal, ett ställe. Den inbjudna får det direkt, den som bjöd in
# får samma antal dagar när den inbjudna skapat sin första vecka.
REFERRAL_REWARD_DAYS = 30

# Hänvisningskoder syns i delade länkar och SMS. Prefixet gör det uppenbart
# vad koden är, och skiljer den från en kampanjkod i supportärenden.
REFERRAL_PREFIX = "MJ-"
REFERRAL_LABEL = "hänvisning"


def code_for(store: premium_codes.PremiumCodeStore, user_id) -> str | None:
    """Kontots egen kod. Skapas vid FÖRSTA förfrågan, inte vid registrering -
    ett konto som aldrig delar behöver ingen rad.

    Returnerar den råa koden bara när den just skapades; därefter finns bara
    hashen och `label`/`uses` att visa. Det är samma regel som för varje
    annan hemlighet i Matjakt, och den är skälet till att /api/referral
    lämnar ut koden EN gång och sedan sparar den på kontot."""
    existing = store.owned_by(user_id)
    if existing:
        return None
    return store.create(label=REFERRAL_LABEL, grant_days=REFERRAL_REWARD_DAYS,
                        owner_user_id=user_id, prefix=REFERRAL_PREFIX,
                        # Ingen utgång och inget tak: en personlig kod som
                        # läcker kostar en månad per konto som löser in den,
                        # och varje sådant konto måste dessutom BYGGA en
                        # vecka innan ägaren får något. Taket ligger i
                        # arbetet, inte i räknaren.
                        max_uses=None, expires_at=None)


def reward_on_first_week(store, accounts, user_id) -> dict | None:
    """Kroken. Anropas när `user_id` skapat sin FÖRSTA vecka.

    Betalar ut till den som bjöd in - aldrig till den som just aktiverade,
    hon fick sin månad redan vid inlösen. Returnerar en sammanfattning, eller
    None när kontot inte kom in via en hänvisning.

    `mark_rewarded` är atomär och körs FÖRE utbetalningen: skulle två
    aktiveringssignaler nå hit samtidigt vinner den ena, och den andra får
    None. Hellre en utebliven belöning vid en kapplöpning än två."""
    pending = store.pending_reward(user_id)
    if not pending:
        return None
    owner_id = pending["owner_user_id"]
    if not store.mark_rewarded(pending["code_hash"], user_id):
        return None                      # någon annan hann betala ut
    days = int(pending.get("grant_days") or REFERRAL_REWARD_DAYS)
    until = accounts.extend_premium(owner_id, days)
    logger.info("Hänvisning utbetald: konto %s fick %s dagar för konto %s",
                owner_id, days, user_id)
    return {"rewardedUserId": owner_id, "days": days, "premiumUntil": until}


def activation_hook(store):
    """Formen `billing/activation.on_first_week` vill ha: (accounts, user_id).

    `store` får vara lagret självt ELLER en nollställig funktion som hämtar
    det. Skillnaden är inte kosmetisk. Sluter kroken om lagret vid IMPORT
    pekar den för alltid på den anslutning som fanns då, och varje
    uppsättning som byter ut lagret - alltså varje test som inte vill skriva
    i den riktiga databasen - tvingas bygga om kroken själv. Då är det inte
    längre serverns inkoppling som prövas, utan testets egen kopia av den:
    `ACTIVATION_HOOKS = ()` i api_server hade gått obemärkt förbi."""
    def hook(accounts, user_id):
        resolved = store() if callable(store) else store
        return reward_on_first_week(resolved, accounts, user_id)
    return hook


def share_text(code: str, app_url: str) -> dict:
    """Färdig text att dela. Användaren ska inte behöva formulera den själv -
    samma regel som för hushållsinbjudan."""
    url = f"{app_url.rstrip('/')}/?kod={code}"
    return {
        "code": code,
        "url": url,
        "rewardDays": REFERRAL_REWARD_DAYS,
        "shareTitle": "En månad Matjakt Premium",
        "shareText": (f"Jag använder Matjakt för att planera veckans middagar efter "
                      f"riktiga butikspriser. Med min kod får du {REFERRAL_REWARD_DAYS} "
                      f"dagar Premium gratis: {url}"),
    }
