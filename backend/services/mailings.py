# -*- coding: utf-8 -*-
"""Utskick: mallarna, och maskinen som skickar tre av dem.

MALLARNA (KINDS) är elva; SCHEDULED_KINDS är de tre som schemaläggaren
faktiskt skickar idag. Skillnaden är data, inte vilja: åtta av mallarna
behöver siffror appen inte samlar in ännu (ett veckoförslag per konto, en
sparsumma per månad, senast sedd, antal skapade veckor). De är byggda,
prövade och går att förhandsvisa; den dag siffran finns kopplas mallen in
utan att copyn behöver skrivas om. Varje renderare som väntar på data säger
det i sin egen docstring - ingen av dem hittar på ett tal.

REGLERNA, i den ordning de gäller:

  1. Samtycke. Marknadsföring går bara till konton som tackat ja
     (users.marketing_consent = 1) OCH verifierat sin adress - annars kan
     vem som helst registrera någon annans mejl och prenumerera den på
     reklam. Verifierings- och lösenordsmejl är transaktionella och rör
     inte den här modulen.
  2. Avsluta när som helst. Varje utskick bär en avprenumerationslänk med
     en HMAC-signerad token (ingen inloggning krävs för att avsluta) och
     en List-Unsubscribe-header så mejlklienter kan visa sin egen knapp.
     Saknas hemligheten som signerar länkarna skickas INGENTING.
  3. En gång. mail_log är sanningen om vad som skickats: välkomststegen
     skickas högst en gång per konto, Kampanjtorget högst en gång per dag.
     En krasch mitt i en körning dubblerar inte nästa.
  4. Aldrig tomt. Ett Kampanjtorg utan ett enda fynd skickas inte alls.
  5. Av tills vidare. MATJAKT_MAILINGS_ENABLED=1 krävs, plus konfigurerad
     SMTP. En lokal körning mejlar aldrig någon av sig själv.

Tider är Europe/Stockholm av samma skäl som nattjobben.
"""

import functools
import hashlib
import hmac
import html as html_lib
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from .email.mailer import REPLY_TO_EMAIL

try:
    from zoneinfo import ZoneInfo
    STOCKHOLM = ZoneInfo("Europe/Stockholm")
except Exception:  # pragma: no cover
    STOCKHOLM = None

logger = logging.getLogger("matjakt.mailings")

# Alla mallar som finns. Ordningen är livscykelns: adressen, de första
# dagarna, veckorytmen, och sedan de som bara går ut när något hänt.
KINDS = (
    "verify", "welcome_3", "welcome_7", "kampanjtorget", "veckoplan",
    "manadsrapport", "vinn_tillbaka", "overgiven_vecka",
    "premium_uppgradering", "hushallsinbjudan", "dunning",
)
# De som schemaläggaren skickar. Att lägga till en mall i KINDS ändrar
# INGENTING om vad som går ut - den listan är den här, och den är kort med
# flit. Utskicksreglerna (samtycke, verifierad adress, en gång per konto,
# aldrig ett tomt torg) gäller oförändrat för dem.
SCHEDULED_KINDS = ("welcome_3", "welcome_7", "kampanjtorget")
SEND_AT = "08:00"              # Europe/Stockholm
KAMPANJTORGET_WEEKDAY = 3      # torsdag (måndag = 0)
CHECK_INTERVAL_SECONDS = 30
DEALS_PER_CHAIN = 8
# Välkomststegen har ett fönster: ett konto som var avstängt från utskick
# i tre veckor och sedan tackar ja ska inte få "dag 3"-mejlet i efterhand.
WELCOME_WINDOWS = {"welcome_3": (3, 7), "welcome_7": (7, 21)}


def _now():
    return datetime.now(STOCKHOLM) if STOCKHOLM else datetime.now()


# ---- Avprenumeration ---------------------------------------------------------
def unsubscribe_token(user_id: int, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), f"unsub:{int(user_id)}".encode("utf-8"),
                    hashlib.sha256).hexdigest()[:32]


def unsubscribe_valid(user_id, token: str, secret: str) -> bool:
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return False
    if not secret or not token:
        return False
    return hmac.compare_digest(unsubscribe_token(user_id, secret), str(token))


def unsubscribe_url(api_base: str, user_id: int, secret: str) -> str:
    return f"{api_base.rstrip('/')}/mail/unsubscribe?u={int(user_id)}&t={unsubscribe_token(user_id, secret)}"


# ---- Lagring ----------------------------------------------------------------
class MailingStore:
    """mail_log i kontodatabasen (samma anslutning som AccountStore) - och
    därför under SAMMA lås (se AccountStore.lock)."""

    def __init__(self, connection, lock=None):
        self._connection = connection
        self._lock = lock if lock is not None else threading.RLock()
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS mail_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                day TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                UNIQUE (user_id, kind, day)
            );
            """
        )
        self._connection.commit()

    def recipients(self, kind: str, today) -> list:
        """Konton som ska ha `kind` i dag: samtycke, verifierad adress,
        inte redan skickat. Returnerar rader med id, email, synced_state."""
        # En mall utan mottagarregel har ingen mottagarkrets - att gissa fram
        # en vore att uppfinna ett utskick. Elva mallar finns, tre skickas.
        if kind not in SCHEDULED_KINDS:
            raise ValueError(f"{kind} har ingen mottagarregel och skickas inte av schemaläggaren")
        base = ("SELECT id, email, synced_state, created_at FROM users "
                "WHERE marketing_consent = 1 AND email_verified = 1 ")
        if kind == "kampanjtorget":
            rows = self._connection.execute(
                base + "AND NOT EXISTS (SELECT 1 FROM mail_log m WHERE m.user_id = users.id "
                "AND m.kind = ? AND m.day = ?) ORDER BY id", (kind, today.isoformat())).fetchall()
        else:
            after, before = WELCOME_WINDOWS[kind]
            rows = self._connection.execute(
                base + "AND substr(created_at, 1, 10) <= ? AND substr(created_at, 1, 10) > ? "
                "AND NOT EXISTS (SELECT 1 FROM mail_log m WHERE m.user_id = users.id AND m.kind = ?) "
                "ORDER BY id",
                ((today - timedelta(days=after)).isoformat(),
                 (today - timedelta(days=before)).isoformat(), kind)).fetchall()
        return rows

    def log(self, user_id: int, kind: str, today) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO mail_log (user_id, kind, day, sent_at) VALUES (?, ?, ?, ?)",
                (int(user_id), kind, today.isoformat(),
                 datetime.now(timezone.utc).isoformat()))

    def counts(self, days: int = 30) -> dict:
        since = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
        # Bara de schemalagda: mail_log innehåller aldrig något annat, och
        # åtta permanenta nollor i kontrollrummet läser som ett fel.
        result = {kind: 0 for kind in SCHEDULED_KINDS}
        for kind, count in self._connection.execute(
                "SELECT kind, COUNT(*) FROM mail_log WHERE day >= ? GROUP BY kind", (since,)):
            result[kind] = int(count)
        return result

    def consenting(self) -> dict:
        row = self._connection.execute(
            "SELECT SUM(marketing_consent = 1), SUM(marketing_consent = 1 AND email_verified = 1) FROM users"
        ).fetchone()
        return {"tackatJa": int(row[0] or 0), "tackatJaOchVerifierade": int(row[1] or 0)}


# ---- Mallar -----------------------------------------------------------------
#
# All copy står ordagrant ur Bilaga 1 i docs/UPPDRAG-MATJAKT.md. Tre regler
# gäller varje mall, och de är kodade så att de går att pröva:
#
#   1. DOLD PREHEADER FÖRST. Preheadern är raden inkorgen visar efter ämnet.
#      Utan den plockar Gmail den första synliga texten i mejlet - som här
#      var ordmärket "MATJAKT" följt av rubriken en gång till. Två av tre
#      rader i inkorgen sa alltså ingenting.
#   2. CTA SOM KNAPP, aldrig som textlänk i brödtexten. Knappen är en
#      <table> och minst 44 px hög (samma minsta träffyta som appen).
#   3. BILDEN BÄR ALDRIG BUDSKAPET. Gmail och Outlook blockerar bilder som
#      standard; namn, pris och rabatt står därför som text (se _hero).

# Knappens mått. Höjden sätts tre gånger med flit: height-ATTRIBUTET för
# Outlooks Word-motor, padding + line-height för alla andra, och height i
# style som gardering. 13 + 18 + 13 = 44.
BUTTON_PADDING_Y = 13
BUTTON_LINE_HEIGHT = 18
BUTTON_MIN_HEIGHT = 44
BUTTON_HEIGHT = 2 * BUTTON_PADDING_Y + BUTTON_LINE_HEIGHT

_INK = "#1c1b18"
_MUTED = "#6b665c"
_PAPER = "#f6f3ea"
_LINE = "#e6e1d4"


def _kr(value) -> str:
    return f"{float(value):.2f}".replace(".", ",") + " kr"


def _bildlank(url) -> str:
    """Bara https-bilder släpps in i ett mejl. En url ur providerdata är inte
    vår att lita på: ett "javascript:" eller "data:" i ett href/src är precis
    den vägen ett utskick blir en attackyta. Allt annat än https ger tom
    sträng, och då renderas raden utan bild i stället för med en trasig."""
    text = str(url or "").strip()
    return text if text.startswith("https://") else ""


def _lank(url) -> str:
    """Samma resonemang som _bildlank, fast för href. En knapp som pekar på
    "javascript:" är en knapp vi själva har byggt åt en angripare."""
    text = str(url or "").strip()
    return text if text.startswith("https://") or text.startswith("http://") else ""


def _rich(text: str) -> str:
    """Escapa först, fetstila sedan. **så här** blir <strong>, och ingenting
    annat i copyn kan bli markup - ordningen är hela poängen."""
    escaped = html_lib.escape(str(text))
    parts = escaped.split("**")
    out = []
    for index, part in enumerate(parts):
        out.append(f'<strong style="font-weight:600;">{part}</strong>' if index % 2 else part)
    return "".join(out)


def _plain(text: str) -> str:
    return str(text).replace("**", "")


def _preheader(text: str) -> str:
    """Dold rad överst: det inkorgen visar efter ämnesraden.

    display:none räcker inte ensamt - flera klienter visar ändå texten om
    den har höjd, och Outlook behöver mso-hide. Utfyllnaden efteråt hindrar
    klienten från att fylla på med brödtextens första ord."""
    padding = "&#847;&zwnj;&nbsp;" * 40
    return ('<div style="display:none;font-size:1px;line-height:1px;max-height:0;'
            'max-width:0;opacity:0;overflow:hidden;mso-hide:all;color:transparent;">'
            f'{html_lib.escape(str(text))}{padding}</div>')


def _button(url: str, label: str, *, secondary: bool = False) -> str:
    """CTA som knapp.

    <table> och inte <div>: Outlooks Word-motor ignorerar padding och
    border-radius på ett <a>/<div>, så en div-knapp blir en understruken
    textrad hos varje Outlook-användare - alltså exakt den textlänk vi
    försökte komma bort ifrån. Tabellcellen får både height-attribut och
    height i style, och länken sin höjd ur padding + line-height, så knappen
    är minst 44 px i alla tre fallen."""
    href = html_lib.escape(_lank(url))
    if secondary:
        cell_bg, text_color, border = "#ffffff", _INK, f"border:1px solid {_INK};"
    else:
        cell_bg, text_color, border = _INK, "#ffffff", ""
    return (
        '<table role="presentation" border="0" cellpadding="0" cellspacing="0" '
        'style="border-collapse:separate;margin:26px 0 8px;">'
        f'<tr><td align="center" bgcolor="{cell_bg}" height="{BUTTON_MIN_HEIGHT}" '
        f'style="height:{BUTTON_MIN_HEIGHT}px;background:{cell_bg};border-radius:8px;{border}">'
        f'<a href="{href}" style="display:block;padding:{BUTTON_PADDING_Y}px 28px;'
        f'font-family:Helvetica,Arial,sans-serif;font-size:16px;font-weight:600;'
        f'line-height:{BUTTON_LINE_HEIGHT}px;color:{text_color};text-decoration:none;">'
        f'{html_lib.escape(label)}</a></td></tr></table>'
    )


def _hero(deal, chain) -> str:
    """Veckans bästa fynd, stort och överst.

    BILDEN FÅR ALDRIG BÄRA BUDSKAPET. Gmail och Outlook blockerar bilder som
    standard, så namn, pris och rabatt står som text - blockeras bilden ser
    mejlet fortfarande komplett ut, det tappar bara ett foto.

    Just därför är alt tom. Varunamnet står som rubrik direkt under bilden,
    så en alt-text med samma namn läses upp två gånger av en skärmläsare och
    syns dubbelt när bilden blockeras. En bild vars innehåll redan står i
    texten bredvid är dekorativ, och då är tom alt det korrekta."""
    bild = _bildlank(deal.get("imageUrl"))
    label = deal["name"] + (f" {deal['size']}" if deal.get("size") else "")
    bild_html = (
        f'<img src="{html_lib.escape(bild)}" alt="" width="240" '
        f'style="display:block;margin:0 auto 14px;max-width:240px;height:auto;border:0;">'
    ) if bild else ""
    return (
        '<table style="width:100%;border-collapse:collapse;background:#fff;'
        'border:1px solid #e6e1d4;border-radius:10px;margin:0 0 26px;">'
        '<tr><td style="padding:22px 20px;text-align:center;">'
        '<p style="margin:0 0 12px;font-size:12px;letter-spacing:.08em;color:#6b665c;">'
        'VECKANS BÄSTA FYND</p>'
        f'{bild_html}'
        f'<p style="margin:0 0 6px;font-size:20px;font-weight:bold;">{html_lib.escape(label)}</p>'
        f'<p style="margin:0 0 4px;font-size:34px;font-weight:bold;line-height:1.1;">'
        f'{html_lib.escape(_kr(deal["campaignPrice"]))}</p>'
        f'<p style="margin:0;font-size:14px;color:#6b665c;">'
        f'ord. {html_lib.escape(_kr(deal["regularPrice"]))} &middot; '
        f'<strong style="color:#1c1b18;">&minus;{int(deal["discountPercent"])} %</strong> hos '
        f'{html_lib.escape(chain)}</p>'
        '</td></tr></table>'
    )


# ---- Block: en copy-rad, två utgåvor ----------------------------------------
# Varje stycke skrivs EN gång och renderas till både text och HTML. Skrevs de
# var för sig skulle textversionen sluta uppdateras - den som läser utan HTML
# fick då ett annat, sämre mejl än alla andra.
def _blocks_html(blocks) -> str:
    out = []
    for block in blocks:
        kind = block[0]
        if kind == "p":
            out.append(f'<p style="margin:0 0 16px;">{_rich(block[1])}</p>')
        elif kind == "lead":
            out.append(f'<p style="margin:0 0 16px;"><strong style="font-weight:600;">'
                       f'{html_lib.escape(block[1])}</strong> {_rich(block[2])}</p>')
        elif kind == "stat":
            out.append(f'<p style="margin:0 0 8px;font-size:18px;">'
                       f'<strong style="font-weight:600;">{html_lib.escape(block[1])}</strong> '
                       f'{html_lib.escape(block[2])}</p>')
        elif kind == "raw":
            out.append(block[1])
    return "".join(out)


def _blocks_text(blocks) -> str:
    out = []
    for block in blocks:
        kind = block[0]
        if kind == "p":
            out.append(_plain(block[1]))
        elif kind == "lead":
            out.append(f"{block[1]} {_plain(block[2])}")
        elif kind == "stat":
            out.append(f"{block[1]} {block[2]}")
        elif kind == "raw":
            out.append(block[2])
    return "\n\n".join(part for part in out if part)


def _layout(title: str, paragraphs_html: str, app_url: str, unsubscribe, preheader: str,
            buttons_html: str = "") -> str:
    """Preheadern ligger FÖRE ordmärket - den ska vara det första klienten
    hittar. `unsubscribe=None` betyder transaktionellt mejl: ingen
    avprenumerationslänk, eftersom det inte går att avsäga sig ett kvitto."""
    if unsubscribe:
        foot = ('Du får det här mejlet för att du tackade ja till utskick i Matjakt. '
                f'<a href="{html_lib.escape(_lank(unsubscribe))}" style="color:{_MUTED};">Avsluta utskicken</a> &middot; '
                f'<a href="{html_lib.escape(_lank(app_url))}" style="color:{_MUTED};">Öppna Matjakt</a>')
    else:
        foot = ('Du får det här mejlet för att du har ett konto i Matjakt. '
                f'Svara på mejlet om du undrar något &mdash; {html_lib.escape(REPLY_TO_EMAIL)}')
    # meta charset: MIME-delen deklarerar utf-8, men flera klienter (och varje
    # "visa i webbläsaren"-länk) läser dokumentet fristående och gissar då
    # latin-1 - då blir "Kycklingfilé" till "KycklingfilÃ©" i hela mejlet.
    return f"""<!doctype html><html lang="sv"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:{_PAPER};color:{_INK};">
{_preheader(preheader)}
<div style="max-width:560px;margin:0 auto;padding:32px 20px;font:16px/1.55 Georgia,'Times New Roman',serif;">
<p style="margin:0 0 24px;font-size:13px;letter-spacing:.04em;color:{_MUTED};">MATJAKT</p>
<h1 style="font-size:24px;font-weight:normal;margin:0 0 18px;">{html_lib.escape(title)}</h1>
{paragraphs_html}
{buttons_html}
<hr style="border:0;border-top:1px solid #d9d4c7;margin:28px 0 14px;">
<p style="font-size:12px;color:{_MUTED};margin:0;">{foot}</p>
</div></body></html>"""


def _footer_text(app_url: str, unsubscribe) -> str:
    if not unsubscribe:
        return ("\n\n--\nDu får det här mejlet för att du har ett konto i Matjakt.\n"
                f"Svara på mejlet om du undrar något: {REPLY_TO_EMAIL}\n")
    return (f"\n\n--\nDu får det här mejlet för att du tackade ja till utskick i Matjakt.\n"
            f"Avsluta utskicken: {unsubscribe}\nÖppna Matjakt: {app_url}\n")


# ---- Copyn ------------------------------------------------------------------
# Ämnesrad, A/B-varianter, preheader och knapptext för varje mall, ordagrant
# ur Bilaga 1. {fält} fylls av mallens egen data.
#
# "ab": False betyder att varianterna står kvar som copy men INTE roteras.
# Kampanjtorget är det enda sådana fallet, och skälet är en uttrycklig regel:
# ämnesraden ska bära det bästa fyndets namn OCH pris. Två av bilagans tre
# varianter för den mallen gör inte det ("Kampanjtorget vecka {v}: {n} fynd
# värda att planera runt" har varken vara eller pris), så att rotera in dem
# hade brutit regeln för en tredjedel av mottagarna.
TEMPLATES = {
    "verify": {
        "subjects": (
            "Ett klick kvar – sen bygger vi din första matvecka",
            "Välkommen till Matjakt. Bekräfta din adress så sätter vi igång",
            "Din matvecka väntar – verifiera adressen först",
        ),
        "preheader": "Klart på tio sekunder. Sen väljer du budget och Matjakt gör resten.",
        "button": "Verifiera min adress",
        "transactional": True,
    },
    "welcome_3": {
        "subjects": (
            "Tre saker i Matjakt som sänker matkontot mest",
            "Har du hittat fynden på Hem-fliken än?",
            "De tre knapparna som gör störst skillnad på matkontot",
        ),
        "preheader": "Kampanjpriserna uppdateras varje natt. De som hamnar i din vecka sänker totalen direkt.",
        "button": "Öppna Matjakt",
    },
    "welcome_7": {
        "subjects": (
            "Söndagskvällen är den billigaste stunden i veckan",
            "En vecka in – så här får du ut mest av Matjakt",
            "Planera på söndag, handla billigare på måndag",
        ),
        "preheader": "Nya kampanjer varje vecka. Den som planerar innan de tar slut handlar billigast.",
        "button": "Planera nästa vecka",
    },
    "kampanjtorget": {
        "subjects": (
            "Veckans bästa fynd: {vara} för {pris} hos {kedja}",
            "Kampanjtorget vecka {v}: {n} fynd värda att planera runt",
            "−{procent} % på {vara} den här veckan",
        ),
        "ab": False,
        "preheader": "Hämtat direkt från butikerna i natt. Lägg fynden i veckan så räknas totalen om.",
        "button": "Lägg fynden i min vecka",
    },
    "veckoplan": {
        "subjects": (
            "Din matvecka är förberedd – vill du ha den?",
            "Söndag. Ska vi göra klart veckan?",
            "{n} middagar, {belopp} kr, femton minuter",
        ),
        "preheader": "Vi har lagt ett förslag åt dig. Byt det du inte gillar, resten är klart.",
        "button": "Se veckans förslag",
    },
    "manadsrapport": {
        "subjects": (
            "Du sparade {belopp} kr på maten i {månad}",
            "{månad} i siffror: {belopp} kr kvar på kontot",
            "Din matmånad: {belopp} kr billigare än vanligt",
        ),
        "preheader": "Så här ser det ut när någon annan räknar åt dig.",
        "button": "Se hela {månad}",
        "button2": "Dela min månad",
    },
    "vinn_tillbaka": {
        "subjects": (
            "Priserna har ändrats sedan du var här sist",
            "Vi har hållit koll medan du varit borta",
            "{namn}, din budget står kvar – veckan är ny",
        ),
        "preheader": "{antal} nya kampanjer sedan ditt senaste besök. Din budget och ditt skafferi finns kvar.",
        "button": "Bygg veckan igen",
    },
    "overgiven_vecka": {
        "subjects": (
            "Din vecka ligger klar – listan är inte avbockad",
            "{n} middagar väntar på en handlingsrunda",
            "Glömde du inköpslistan?",
        ),
        "preheader": "Listan är sorterad som hyllorna och vet vad du redan har hemma.",
        "button": "Öppna inköpslistan",
    },
    "premium_uppgradering": {
        "subjects": (
            "Du använder Matjakt varje vecka. Det finns mer att hämta",
            "Sju middagar, alla butiker, alla veckotyper – 59 kr",
            "Vad Premium hade gjort med dina senaste tre veckor",
        ),
        "preheader": "59 kr i månaden. Ungefär vad ett paket kaffe kostar.",
        "button": "Testa Premium",
    },
    "hushallsinbjudan": {
        "subjects": (
            "{namn} väntar fortfarande på dig i Matjakt",
            "Din inbjudan till {hushåll} ligger kvar",
            "Två personer, en inköpslista",
        ),
        "preheader": "Samma lista i två telefoner. Den som handlar bockar av, den andra ser det direkt.",
        "button": "Gå med i {hushåll}",
        "transactional": True,
    },
    "dunning": {
        "subjects": (
            "Betalningen gick inte igenom – Premium är kvar i sju dagar",
        ),
        "preheader": "Uppdatera kortet så fortsätter allt som vanligt. Vi försöker igen automatiskt.",
        "button": "Uppdatera betalsättet",
        "transactional": True,
    },
}


def subject_variants(kind: str, data: dict = None) -> tuple:
    """Alla ämnesrader för mallen, ifyllda. Index 0 är den som skickas när
    ingen variant valts."""
    return tuple(text.format(**(data or {})) for text in TEMPLATES[kind]["subjects"])


def variant_for(kind: str, user_id) -> int:
    """Vilken A/B-arm ett konto hamnar i. Deterministiskt på (mall, konto),
    så samma person får samma variant vid ett omtag - annars mäter man sin
    egen slump - och olika varianter i olika mallar."""
    spec = TEMPLATES[kind]
    arms = len(spec["subjects"]) if spec.get("ab", True) else 1
    if arms <= 1 or user_id is None:
        return 0
    digest = hashlib.sha256(f"{kind}:{int(user_id)}".encode("utf-8")).digest()
    return digest[0] % arms


def _compose(kind: str, blocks, data: dict, app_url: str, unsubscribe, *,
             variant: int = 0, button_url: str = None, button2_url: str = None,
             heading: str = None) -> tuple:
    """(ämne, text, html) ur mallens copy och dess block. En väg in för alla
    elva mallarna: preheadern, knappen och foten kan då inte glömmas bort i
    en av dem."""
    spec = TEMPLATES[kind]
    subjects = subject_variants(kind, data)
    subject = subjects[variant % len(subjects)]
    preheader = spec["preheader"].format(**data)
    label = spec["button"].format(**data)
    target = button_url or app_url
    buttons = _button(target, label)
    text_tail = [f"{label}: {target}"]
    if spec.get("button2"):
        label2 = spec["button2"].format(**data)
        buttons += _button(button2_url or app_url, label2, secondary=True)
        text_tail.append(f"{label2}: {button2_url or app_url}")
    text = (_blocks_text(blocks) + "\n\n" + "\n".join(text_tail)
            + _footer_text(app_url, unsubscribe))
    html = _layout(heading or subject, _blocks_html(blocks), app_url, unsubscribe,
                   preheader, buttons)
    return subject, text, html


# ---- De elva mallarna -------------------------------------------------------
def render_verify(verify_url: str, app_url: str, *, variant: int = 0) -> tuple:
    """Dag 0. Transaktionellt - ingen avregistrering - men det mest öppnade
    mejl Matjakt någonsin skickar, och därför det som bär första löftet."""
    blocks = [
        ("p", "Hej!"),
        ("p", "Roligt att du är här. Klicka på knappen nedan så är din adress verifierad och kontot ditt."),
        ("p", "Sen är det tre steg till en färdig matvecka:"),
        ("lead", "1. Säg vad veckan får kosta.", "Och hur många ni är hemma."),
        ("lead", "2. Matjakt bygger veckan.", "Middagar som håller budgeten, prissatta mot "
         "butikernas verkliga priser – inte uppskattningar."),
        ("lead", "3. Ta med listan.", "Den är sorterad som hyllorna och räknar bort det du redan har hemma."),
        ("p", "Om du inte skapade kontot kan du strunta i det här mejlet. Då händer ingenting."),
    ]
    return _compose("verify", blocks, {}, app_url, None, variant=variant, button_url=verify_url)


def render_welcome(step: str, app_url: str, unsubscribe: str, *, variant: int = 0) -> tuple:
    """(ämne, text, html) för welcome_3 / welcome_7."""
    if step == "welcome_3":
        blocks = [
            ("p", "Du har haft Matjakt i tre dagar. Här är de tre sakerna som gör mest "
             "för matkontot – tar en minut var."),
            ("lead", "Lägg ett fynd i veckan.", "På Hem-fliken ligger veckans kampanjpriser, "
             "hämtade från butikerna själva varje natt. Trycker du in ett i veckan räknas "
             "totalen om direkt."),
            ("lead", "Byt ut en middag du inte gillar.", "Torsdagen känns fel? Ett tryck, ny "
             "rätt, nytt pris. Du behöver inte acceptera veckan som den kom."),
            ("lead", "Fyll skafferiet.", "Lägg in ris, pasta och konserver du redan har. "
             "Matjakt räknar bort dem från både listan och priset – det är ofta där de "
             "första hundralapparna ligger."),
            ("p", "Ta två minuter i kväll. Nästa vecka går det på trettio sekunder."),
        ]
    else:
        blocks = [
            ("p", "En vecka har gått. Här är det som brukar avgöra om Matjakt fastnar eller inte."),
            ("lead", "Planera på söndagen.", "Kampanjerna är som färskast då, och de flesta "
             "hinner planera innan de tar slut. Femton minuter i soffan blir en vecka du "
             "inte behöver tänka på."),
            ("lead", "Låt skafferiet jobba.", "Ju mer du lägger in, desto mindre står på "
             "listan. Matjakt föreslår gärna rätter av det du redan har."),
            ("lead", "Se var veckan blir billigast.", "Gratisversionen visar den billigaste "
             "kvalificerade butiken för just din vecka. Premium visar alla butikers priser "
             "sida vid sida, så du kan välja den som ligger på din väg hem."),
            ("p", "Har du redan en vecka igång? Då är du längre än de flesta."),
        ]
    return _compose(step, blocks, {}, app_url, unsubscribe, variant=variant)


# ---- Låt fynden välja menyn --------------------------------------------------
_RAKNEORD = {1: "En", 2: "Två", 3: "Tre", 4: "Fyra", 5: "Fem", 6: "Sex", 7: "Sju"}


def deals_menu(deals_by_chain: dict, recipes, *, matcher=None, count: int = 4) -> list:
    """"Fyra middagar byggda på veckans reor" - fynden väljer menyn.

    Det omvända greppet ("så många av veckans fynd finns i DIN plan") mättes
    och höll inte: bara 19 av 240 recept berörs av en normal kampanjvecka, så
    en användare med fyra middagar får noll träffar ungefär sju gånger av tio.
    Den här riktningen fungerar varje vecka i stället, eftersom den utgår från
    fynden och letar rätt, inte tvärtom.

    `matcher` är services/grocery/pricing.product_matches_ingredient, som är
    medvetet konservativ: "Laxfilé färsk 400 g" matchar inte "Lax". Den
    räknar alltså hellre för lågt än för högt, vilket är rätt håll för en
    siffra i ett mejl. Importeras sent - matchningen behövs bara den dag
    Kampanjtorget går ut.
    """
    if matcher is None:  # pragma: no cover - täcks av det riktiga anropet
        from .grocery.pricing import product_matches_ingredient as matcher
    ranked = sorted(
        ((chain, deal) for chain, deals in (deals_by_chain or {}).items() for deal in (deals or [])),
        key=lambda par: par[1].get("discountPercent") or 0, reverse=True)
    menu, used = [], set()
    for chain, deal in ranked:
        if len(menu) >= count:
            break
        for recipe in recipes or []:
            name = recipe.get("name") or recipe.get("title")
            if not name or name in used:
                continue
            for ingredient in recipe.get("ingredients") or recipe.get("ingredientNames") or []:
                if matcher(deal.get("name") or "", str(ingredient), deal.get("brand")):
                    menu.append({"recipe": name, "slug": recipe.get("slug"),
                                 "ingredient": str(ingredient), "chain": chain, "deal": deal})
                    used.add(name)
                    break
            if len(menu) and menu[-1]["recipe"] == name:
                break
    return menu


def _menu_section(menu: list) -> tuple:
    """(html, text) för menyavsnittet. Rubriken räknar rätterna i ord, för
    det är så en meny skrivs - och siffran är alltid sann, aldrig avrundad
    uppåt till "fyra" när det bara blev tre."""
    if not menu:
        return "", ""
    ord_ = _RAKNEORD.get(len(menu), str(len(menu)))
    rubrik = f"{ord_} middagar byggda på veckans reor" if len(menu) != 1 else \
        "En middag byggd på veckans reor"
    rows, text_rows = [], [rubrik.upper()]
    for post in menu:
        deal = post["deal"]
        label = deal["name"] + (f" {deal['size']}" if deal.get("size") else "")
        pris = (f"{_kr(deal['campaignPrice'])} · &minus;{int(deal['discountPercent'])} % hos "
                f"{html_lib.escape(post['chain'])}")
        rows.append(
            '<tr><td style="padding:10px 0;border-bottom:1px solid #e6e1d4;">'
            f'<strong style="font-weight:600;">{html_lib.escape(post["recipe"])}</strong>'
            f'<br><span style="font-size:13px;color:{_MUTED};">'
            f'{html_lib.escape(label)} &middot; {pris}</span></td></tr>')
        text_rows.append(f"  {post['recipe']}\n    {label}: {_kr(deal['campaignPrice'])} "
                         f"(-{int(deal['discountPercent'])} %) hos {post['chain']}")
    html = (f'<h2 style="font-size:18px;font-weight:normal;margin:26px 0 8px;">{html_lib.escape(rubrik)}</h2>'
            '<table style="width:100%;border-collapse:collapse;font-size:15px;">'
            + "".join(rows) + "</table>"
            f'<p style="margin:12px 0 0;font-size:13px;color:{_MUTED};">'
            'Inköpslistan för de här rätterna finns i appen.</p>')
    return html, "\n".join(text_rows) + "\n\n  Inköpslistan för de här rätterna finns i appen."


def render_kampanjtorget(deals_by_chain: dict, chains: list, app_url: str, unsubscribe: str,
                         week: int, *, variant: int = 0, menu: list = None):
    """(ämne, text, html) - eller None när det inte finns ett enda fynd att
    visa för de valda kedjorna. Ett tomt torg skickas aldrig."""
    sections = [(chain, deals_by_chain.get(chain) or []) for chain in chains]
    sections = [(chain, deals[:DEALS_PER_CHAIN]) for chain, deals in sections if deals]
    if not sections:
        return None
    # Bästa fyndet över ALLA valda kedjor lyfts ut och visas stort överst.
    # Ett mejl med tolv likadana rader läses inte; ett med ett tydligt bästa
    # fynd gör det. Raden ligger kvar i sin kedjas lista också - att plocka
    # bort den skulle göra kedjans avsnitt ofullständigt.
    bäst_kedja, bäst = max(
        ((chain, deal) for chain, deals in sections for deal in deals),
        key=lambda par: par[1].get("discountPercent") or 0)
    # ÄMNESRADEN BÄR FYNDET, INTE KEDJEREGISTRET. "bästa fynden hos Willys,
    # Hemköp och City Gross" säger var något finns; "Kycklingfilé för 79,90 kr"
    # säger vad. Det senare öppnas.
    data = {
        "vara": bäst["name"], "pris": _kr(bäst["campaignPrice"]), "kedja": bäst_kedja,
        "procent": int(bäst["discountPercent"]), "v": week,
        "n": sum(len(deals) for _, deals in sections),
    }
    intro = ("Veckans kampanjpriser, hämtade från butikerna själva i natt. Procenten är mot "
             "ordinarie pris, och \"lägsta vi sett\" betyder att varan inte varit billigare "
             "någon dag de senaste trettio dagarna.")
    hero_text = (f"VECKANS BÄSTA FYND\n  {bäst['name']}: {_kr(bäst['campaignPrice'])} "
                 f"(ord. {_kr(bäst['regularPrice'])}, -{int(bäst['discountPercent'])} %) hos {bäst_kedja}")
    blocks = [("p", intro), ("raw", _hero(bäst, bäst_kedja), hero_text)]
    for chain, deals in sections:
        rows, text_rows = [], [chain, "-" * len(chain)]
        for deal in deals:
            label = deal["name"] + (f" {deal['size']}" if deal.get("size") else "") + \
                (f", {deal['brand']}" if deal.get("brand") else "")
            price = f"{_kr(deal['campaignPrice'])} (ord. {_kr(deal['regularPrice'])}, -{deal['discountPercent']} %)"
            lowest = deal.get("lowestSeen")
            note = ""
            if lowest is not None and float(lowest) >= float(deal["campaignPrice"]):
                note = " Lägsta vi sett."
            text_rows.append(f"  {label}: {price}.{note}")
            muted = f'style="font-size:12px;color:{_MUTED};"'
            note_html = f'<br><span {muted}>Lägsta vi sett</span>' if note else ""
            campaign_html = html_lib.escape(_kr(deal["campaignPrice"]))
            regular_html = html_lib.escape(_kr(deal["regularPrice"]))
            percent = int(deal["discountPercent"])
            # Miniatyren får en egen smal kolumn med fast bredd, så raderna
            # står i linje även för de varor som saknar bild - annars hoppar
            # texten i sidled och listan blir svårläst.
            tumnagel = _bildlank(deal.get("imageUrl"))
            bild_cell = (
                f'<img src="{html_lib.escape(tumnagel)}" alt="" width="44" '
                f'style="display:block;width:44px;height:auto;border:0;border-radius:6px;">'
            ) if tumnagel else "&nbsp;"
            rows.append(
                '<tr>'
                '<td width="56" style="padding:8px 12px 8px 0;border-bottom:1px solid #e6e1d4;'
                'vertical-align:middle;">' + bild_cell + '</td>'
                '<td style="padding:8px 0;border-bottom:1px solid #e6e1d4;vertical-align:middle;">'
                f'<strong style="font-weight:600;">{html_lib.escape(label)}</strong>{note_html}</td>'
                '<td style="padding:8px 0 8px 12px;border-bottom:1px solid #e6e1d4;text-align:right;'
                'white-space:nowrap;vertical-align:middle;">'
                f'<strong style="font-weight:bold;">{campaign_html}</strong>'
                f'<br><span {muted}>ord. {regular_html} · &minus;{percent} %</span></td></tr>')
        blocks.append((
            "raw",
            f'<h2 style="font-size:18px;font-weight:normal;margin:26px 0 8px;">{html_lib.escape(chain)}</h2>'
            '<table style="width:100%;border-collapse:collapse;font-size:15px;">' + "".join(rows) + "</table>",
            "\n".join(text_rows)))
    menu_html, menu_text = _menu_section(menu or [])
    if menu_html:
        blocks.append(("raw", menu_html, menu_text))
    blocks.append(("p", "Trycker du in ett fynd i veckan byter Matjakt ut en rätt mot en som "
                        "använder varan – och räknar om vad hela veckan kostar."))
    return _compose("kampanjtorget", blocks, data, app_url, unsubscribe, variant=variant,
                    heading=f"Kampanjtorget vecka {week}")


def render_veckoplan(app_url: str, unsubscribe: str, *, namn: str, antal_middagar,
                     belopp, variant: int = 0) -> tuple:
    """Söndagens veckoplanmejl. KRÄVER DATA SOM INTE SAMLAS IN ÄNNU: ett
    färdigt veckoförslag per konto räknas fram i appen, aldrig på servern, så
    {n} och {belopp} finns inte att hämta. Mallen är byggd och prövad; den
    dagen H1:s söndagsförslag finns server-side kopplas den in."""
    data = {"namn": namn, "n": antal_middagar, "belopp": belopp}
    blocks = [
        ("p", f"Hej {namn},"),
        ("p", f"Ny vecka, nya priser. Matjakt har ett förslag klart: **{antal_middagar} "
              f"middagar för ungefär {belopp} kr**, byggt på din budget och den här veckans kampanjer."),
        ("p", "Gillar du inte torsdagen byter du den. Vill du ha billigare drar du ner "
              "budgeten. Sen är listan klar."),
        ("p", "Femton minuter nu, och du slipper frågan \"vad ska vi äta\" sex kvällar i rad."),
    ]
    return _compose("veckoplan", blocks, data, app_url, unsubscribe, variant=variant)


def render_manadsrapport(app_url: str, unsubscribe: str, *, namn: str, månad: str, belopp,
                         antal_middagar, antal_fynd, dela_url: str = None,
                         variant: int = 0) -> tuple:
    """Månadsrapporten. KRÄVER DATA SOM INTE SAMLAS IN ÄNNU: ingen sparsumma
    per konto och månad lagras någonstans (H2/H3 bygger den)."""
    data = {"namn": namn, "månad": månad, "belopp": belopp,
            "antal": antal_middagar, "fynd": antal_fynd}
    blocks = [
        ("p", f"Hej {namn},"),
        ("p", f"Här är din {månad} med Matjakt:"),
        ("stat", f"{belopp} kr", "sparat mot ordinarie pris"),
        ("stat", f"{antal_middagar} middagar", "planerade"),
        ("stat", f"{antal_fynd} kampanjvaror", "som hamnade i dina veckor"),
        ("p", "Siffran är en uppskattning – den jämför vad du handlade mot vad samma varor "
              "kostat till ordinarie pris. Ingen exakt vetenskap, men den pekar åt rätt håll."),
        ("p", "Vet du någon som suckar över matpriserna? Skicka den här länken. Matjakt är "
              "gratis att använda."),
    ]
    return _compose("manadsrapport", blocks, data, app_url, unsubscribe, variant=variant,
                    button2_url=dela_url or app_url)


def render_vinn_tillbaka(app_url: str, unsubscribe: str, *, namn: str, antal_kampanjer,
                         variant: int = 0) -> tuple:
    """14-30 dagar utan inloggning. KRÄVER DATA SOM INTE SAMLAS IN ÄNNU:
    users har ingen last_seen, och antalet nya kampanjer sedan ett datum går
    inte att fråga efter i grocery-lagret idag."""
    data = {"namn": namn, "antal": antal_kampanjer}
    blocks = [
        ("p", f"Hej {namn},"),
        ("p", f"Det var ett tag sedan. Under tiden har vi läst in butikernas priser varje "
              f"natt – **{antal_kampanjer} nya kampanjer** sedan du var här sist."),
        ("p", "Allt ditt står kvar: budgeten, skafferiet, rätterna du gillade och de du "
              "hoppade över. Du behöver inte börja om, bara trycka en gång."),
        ("p", "Om Matjakt inte var något för dig är det helt okej – då kan du avsluta "
              "utskicken längst ner, så hör vi inte av oss mer."),
    ]
    return _compose("vinn_tillbaka", blocks, data, app_url, unsubscribe, variant=variant)


def render_overgiven_vecka(app_url: str, unsubscribe: str, *, antal_middagar, belopp,
                           butik: str, variant: int = 0) -> tuple:
    """Skapad vecka, listan aldrig avbockad. KRÄVER DATA SOM INTE SAMLAS IN
    ÄNNU: avbockningen lever i appens localStorage och i synced_state, och
    ingen serverfråga svarar på "obockad lista"."""
    data = {"n": antal_middagar, "belopp": belopp, "butik": butik}
    blocks = [
        ("p", "Hej,"),
        ("p", f"Du byggde en vecka med {antal_middagar} middagar men listan är fortfarande "
              f"obockad. Den ligger kvar och är fortfarande prissatt mot dagens priser – "
              f"**{belopp} kr hos {butik}**."),
        ("p", "Öppna den i butiken så bockar du av medan du går. Den är sorterad efter "
              "hyllorna, inte efter recepten, så du slipper springa fram och tillbaka."),
        ("p", "Handlade du redan? Markera varorna som köpta så flyttas de till skafferiet "
              "och räknas bort nästa vecka."),
    ]
    return _compose("overgiven_vecka", blocks, data, app_url, unsubscribe, variant=variant)


def render_premium_uppgradering(app_url: str, unsubscribe: str, *, namn: str, antal_veckor,
                                variant: int = 0) -> tuple:
    """Efter tredje skapade veckan. KRÄVER DATA SOM INTE SAMLAS IN ÄNNU:
    ingen räknare för "antal skapade veckor" per konto finns (I7 lägger till
    händelserna)."""
    data = {"namn": namn, "antal": antal_veckor}
    blocks = [
        ("p", f"Hej {namn},"),
        ("p", f"Du har byggt {antal_veckor} veckor med Matjakt. Det betyder att du använder "
              f"gratisversionen så långt den räcker – så här ser resten ut:"),
        ("lead", "Alla butikers priser sida vid sida.", "Idag ser du den billigaste. Med "
         "Premium ser du hela jämförelsen och kan välja butiken som ligger på vägen hem."),
        ("lead", "Sju middagar i stället för fem.", "Hela veckan planerad, inte bara vardagarna."),
        ("lead", "Live-priser och kampanjbevakning.", "Priset per vara hämtas i samma stund du tittar."),
        ("lead", "Hela hushållet.", "Upp till tolv personer på samma lista, med notis när någon bockar av."),
        ("lead", "Månadsrapporten.", "Svart på vitt vad Matjakt sparat åt dig."),
        ("p", "**59 kr i månaden, eller 399 kr för ett år.** Avsluta när du vill, direkt i appen."),
    ]
    return _compose("premium_uppgradering", blocks, data, app_url, unsubscribe, variant=variant)


def render_hushallsinbjudan(join_url: str, app_url: str, *, inbjudare: str, hushåll: str,
                            variant: int = 0) -> tuple:
    """Inbjudan som ligger kvar. Transaktionellt: mottagaren har inte tackat
    ja till marknadsföring, hon har blivit inbjuden av en människa."""
    data = {"namn": inbjudare, "hushåll": hushåll}
    blocks = [
        ("p", "Hej,"),
        ("p", f"{inbjudare} bjöd in dig till **{hushåll}** i Matjakt men du har inte gått med än."),
        ("p", "När ni delar hushåll delar ni samma vecka och samma inköpslista. Den som står "
              "i butiken bockar av, den andra ser det hända. Ingen köper mjölk två gånger."),
        ("p", "Länken gäller fortfarande."),
    ]
    return _compose("hushallsinbjudan", blocks, data, app_url, None, variant=variant,
                    button_url=join_url)


def render_dunning(billing_url: str, app_url: str, *, namn: str, belopp, datum: str,
                   variant: int = 0) -> tuple:
    """Betalningen gick inte igenom. Transaktionellt - ett kvitto går inte
    att avregistrera sig från. Kopplas in i J5 (Stripe invoice.payment_failed)."""
    data = {"namn": namn, "belopp": belopp, "datum": datum}
    blocks = [
        ("p", f"Hej {namn},"),
        ("p", f"Din bank nekade den senaste dragningen på {belopp} kr. Det är oftast ett "
              f"kort som gått ut, inget mer."),
        ("p", f"**Premium ligger kvar till {datum}** medan vi försöker igen. Uppdaterar du "
              f"kortet innan dess märker du ingenting."),
    ]
    return _compose("dunning", blocks, data, app_url, None, variant=variant,
                    button_url=billing_url)


# ---- Förhandsvisning ---------------------------------------------------------
# TESTDATA, aldrig riktiga kunduppgifter: förhandsvisningen finns för att man
# ska kunna TITTA på ett mejl innan någon får det, och ett exempel med en
# riktig människas namn i är en läcka i ett publikt repo.
PREVIEW_DATA = {
    "verify": {"verify_url": "https://matjakt.store/app/?verify=exempel"},
    "veckoplan": {"namn": "Alex", "antal_middagar": 5, "belopp": 742},
    "manadsrapport": {"namn": "Alex", "månad": "september", "belopp": 486,
                      "antal_middagar": 21, "antal_fynd": 9},
    "vinn_tillbaka": {"namn": "Alex", "antal_kampanjer": 318},
    "overgiven_vecka": {"antal_middagar": 5, "belopp": 689, "butik": "Willys"},
    "premium_uppgradering": {"namn": "Alex", "antal_veckor": 3},
    "hushallsinbjudan": {"inbjudare": "Alex", "hushåll": "Familjen Ek",
                         "join_url": "https://matjakt.store/app/?invite=exempel"},
    "dunning": {"namn": "Alex", "belopp": 59, "datum": "24 september",
                "billing_url": "https://matjakt.store/app/?konto=betalning"},
}


def render_preview(kind: str, app_url: str, unsubscribe: str, *, deals=None, week: int = 1,
                   recipes=None, variant: int = 0) -> tuple:
    """Ett renderat exempel av vilken mall som helst, på testdata. Samma väg
    som skarpa utskick går - annars kan förhandsvisningen inte bevisa något
    om mejlet som faktiskt skickas."""
    if kind not in KINDS:
        raise ValueError("Okänt utskick")
    data = dict(PREVIEW_DATA.get(kind) or {})
    if kind == "verify":
        return render_verify(data["verify_url"], app_url, variant=variant)
    if kind in ("welcome_3", "welcome_7"):
        return render_welcome(kind, app_url, unsubscribe, variant=variant)
    if kind == "kampanjtorget":
        menu = deals_menu(deals or {}, recipes or []) if recipes else None
        return render_kampanjtorget(deals or {}, list((deals or {}).keys()), app_url,
                                    unsubscribe, week, variant=variant, menu=menu)
    if kind == "hushallsinbjudan":
        return render_hushallsinbjudan(data.pop("join_url"), app_url, variant=variant, **data)
    if kind == "dunning":
        return render_dunning(data.pop("billing_url"), app_url, variant=variant, **data)
    renderer = {"veckoplan": render_veckoplan, "manadsrapport": render_manadsrapport,
                "vinn_tillbaka": render_vinn_tillbaka,
                "overgiven_vecka": render_overgiven_vecka,
                "premium_uppgradering": render_premium_uppgradering}[kind]
    return renderer(app_url, unsubscribe, variant=variant, **data)


def chains_for_user(synced_state, released: tuple) -> list:
    """Användarens favoritbutik om den är en släppt kedja, annars alla
    släppta. Ett mejl om Coop-fynd skickas aldrig: vi har inga Coop-priser."""
    try:
        blob = json.loads(synced_state) if synced_state else {}
    except (TypeError, ValueError):
        blob = {}
    chosen = blob.get("butik") if isinstance(blob, dict) else None
    if chosen in released:
        return [chosen]
    return list(released)


# ---- Schemaläggaren ---------------------------------------------------------

def _synchronized(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


for _name, _member in list(vars(MailingStore).items()):
    if callable(_member) and not _name.startswith("_"):
        setattr(MailingStore, _name, _synchronized(_member))


class MailingScheduler:
    """Timertråd som 08:00 varje dag skickar välkomststegen och på torsdagar
    Kampanjtorget. `sender(to, subject, text, html, unsubscribe_url)` gör
    själva avsändningen; `deals_provider()` ger {kedja: [fynd]}."""

    def __init__(self, store, sender, deals_provider, *, api_base: str, app_url: str,
                 secret: str, enabled: bool, mail_configured, released_chains: tuple,
                 pause_seconds: float = 0.2, recipes_provider=None):
        self.store = store
        self.sender = sender
        self.deals_provider = deals_provider
        # Valfri: [{"name": ..., "ingredients": [...]}, ...]. Finns den byggs
        # menyavsnittet "Fyra middagar byggda på veckans reor"; saknas den
        # ser Kampanjtorget ut precis som förut.
        self.recipes_provider = recipes_provider
        self._menus = {}
        self.api_base = api_base
        self.app_url = app_url
        self.secret = secret or ""
        self.enabled = bool(enabled)
        self.mail_configured = mail_configured  # callable -> bool
        self.released_chains = tuple(released_chains)
        self.pause_seconds = pause_seconds
        self._stop = threading.Event()
        self._thread = None
        self._last_fired = None
        self._lock = threading.Lock()
        self.last_run = None

    # -- drift --
    def blocked_reason(self):
        if not self.enabled:
            return "MATJAKT_MAILINGS_ENABLED är inte satt"
        if not self.mail_configured():
            return "SMTP är inte konfigurerat"
        if not self.secret:
            return "ingen hemlighet för avprenumerationslänkar (MATJAKT_MAIL_SECRET eller admin-token)"
        return None

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "blockerat": self.blocked_reason(),
            "skickasKl": SEND_AT, "kampanjtorgetDag": "torsdag", "timezone": "Europe/Stockholm",
            "senasteKorning": self.last_run,
            "skickadeSenaste30Dagarna": self.store.counts(30),
            "mottagare": self.store.consenting(),
        }

    def start(self):
        if self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="matjakt-mailings", daemon=True)
        self._thread.start()
        logger.info("Utskicksjobb startat (%s)", self.blocked_reason() or "aktivt")

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(CHECK_INTERVAL_SECONDS):
            try:
                self._tick()
            except Exception:
                logger.exception("Utskicksjobbets tick misslyckades")

    def _tick(self, now=None):
        now = now or _now()
        stamp = now.strftime("%Y-%m-%d")
        if now.strftime("%H:%M") != SEND_AT or self._last_fired == stamp:
            return
        self._last_fired = stamp
        self.run_due(now)

    # -- körning --
    def run_due(self, now=None) -> dict:
        """Skickar allt som ska ut i dag. Returnerar en sammanfattning och
        skriver aldrig något om spärrarna säger nej."""
        now = now or _now()
        today = now.date()
        reason = self.blocked_reason()
        summary = {"dag": today.isoformat(), "blockerat": reason, "skickat": {}, "fel": {}}
        if reason:
            self.last_run = summary
            return summary
        with self._lock:
            kinds = [kind for kind in SCHEDULED_KINDS if kind != "kampanjtorget"]
            if now.weekday() == KAMPANJTORGET_WEEKDAY:
                kinds.append("kampanjtorget")
            deals = None
            self._menus = {}   # en meny per kedjeuppsättning, inte per mottagare
            for kind in kinds:
                sent = failed = 0
                for row in self.store.recipients(kind, today):
                    try:
                        if kind == "kampanjtorget":
                            if deals is None:
                                deals = self.deals_provider() or {}
                            rendered = self._render(kind, row, deals, now)
                            if rendered is None:
                                continue  # tomt torg för den här personen
                        else:
                            rendered = self._render(kind, row, None, now)
                        subject, text, body_html = rendered
                        self.sender(row["email"], subject, text, body_html,
                                    unsubscribe_url(self.api_base, row["id"], self.secret))
                        self.store.log(row["id"], kind, today)
                        sent += 1
                    except Exception:
                        failed += 1
                        logger.exception("Utskick %s till konto %s misslyckades", kind, row["id"])
                    if self.pause_seconds:
                        time.sleep(self.pause_seconds)
                summary["skickat"][kind] = sent
                summary["fel"][kind] = failed
        self.last_run = summary
        logger.info("Utskick klart: %s", summary)
        return summary

    def _menu_for(self, deals, chains):
        """Menyn beror på kedjorna, inte på personen - så den räknas en gång
        per kedjeuppsättning (högst fyra per körning) i stället för en gång
        per mottagare. Matchningen är den dyra delen."""
        if not self.recipes_provider:
            return None
        key = tuple(chains)
        if key not in self._menus:
            try:
                recipes = self.recipes_provider() or []
                self._menus[key] = deals_menu({c: deals.get(c) or [] for c in chains}, recipes)
            except Exception:
                # En meny är en bonus. Faller receptbanken bort ska mejlet gå
                # ändå - fynden är det mejlet handlar om.
                logger.exception("Kunde inte bygga menyn ur veckans fynd")
                self._menus[key] = []
        return self._menus[key]

    def _render(self, kind: str, row, deals, now):
        unsub = unsubscribe_url(self.api_base, row["id"], self.secret)
        variant = variant_for(kind, row["id"])
        if kind == "kampanjtorget":
            chains = chains_for_user(row["synced_state"], self.released_chains)
            return render_kampanjtorget(deals, chains, self.app_url, unsub,
                                        now.isocalendar()[1], variant=variant,
                                        menu=self._menu_for(deals, chains))
        return render_welcome(kind, self.app_url, unsub, variant=variant)

    def render(self, kind: str, now=None, *, variant: int = 0):
        """Ett renderat exempel, utan att något skickas. Alla elva mallarna -
        även de åtta som väntar på data - går att titta på här; de åtta
        renderas på PREVIEW_DATA, som är påhittade exempelvärden och aldrig
        en riktig kunds siffror."""
        if kind not in KINDS:
            raise ValueError("Okänt utskick")
        now = now or _now()
        unsub = unsubscribe_url(self.api_base, 0, self.secret or "preview")
        deals = self.deals_provider() or {} if kind == "kampanjtorget" else None
        recipes = None
        if kind == "kampanjtorget" and self.recipes_provider:
            try:
                recipes = self.recipes_provider() or []
            except Exception:
                logger.exception("Kunde inte hämta recept till förhandsvisningen")
        return render_preview(kind, self.app_url, unsub, deals=deals,
                              week=now.isocalendar()[1], recipes=recipes, variant=variant)

    def preview(self, kind: str, to_email: str, now=None) -> dict:
        """Skickar ett exempel av `kind` till en adress (admin). Kräver bara
        SMTP - inte att utskicken är påslagna - så Adam kan se mejlen innan
        någon annan får dem. Loggas inte i mail_log."""
        if kind not in KINDS:
            raise ValueError("Okänt utskick")
        if not self.mail_configured():
            raise RuntimeError("SMTP är inte konfigurerat")
        now = now or _now()
        rendered = self.render(kind, now)
        if rendered is None:
            raise RuntimeError("Inga fynd i databasen just nu - Kampanjtorget skulle inte skickas")
        # List-Unsubscribe hör inte hemma på ett transaktionellt mejl: det
        # går inte att avsäga sig ett kvitto, och en avsluta-knapp som inte
        # betyder något lär mottagaren att våra knappar inte betyder något.
        unsub = (None if TEMPLATES[kind].get("transactional")
                 else unsubscribe_url(self.api_base, 0, self.secret or "preview"))
        subject, text, body_html = rendered
        self.sender(to_email, subject, text, body_html, unsub)
        return {"ok": True, "kind": kind, "subject": subject}
