# -*- coding: utf-8 -*-
"""Utskick: välkomstserien och Kampanjtorget.

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

try:
    from zoneinfo import ZoneInfo
    STOCKHOLM = ZoneInfo("Europe/Stockholm")
except Exception:  # pragma: no cover
    STOCKHOLM = None

logger = logging.getLogger("matjakt.mailings")

KINDS = ("welcome_3", "welcome_7", "kampanjtorget")
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
        result = {kind: 0 for kind in KINDS}
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
def _kr(value) -> str:
    return f"{float(value):.2f}".replace(".", ",") + " kr"


def _bildlank(url) -> str:
    """Bara https-bilder släpps in i ett mejl. En url ur providerdata är inte
    vår att lita på: ett "javascript:" eller "data:" i ett href/src är precis
    den vägen ett utskick blir en attackyta. Allt annat än https ger tom
    sträng, och då renderas raden utan bild i stället för med en trasig."""
    text = str(url or "").strip()
    return text if text.startswith("https://") else ""


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


def _layout(title: str, paragraphs_html: str, app_url: str, unsubscribe: str) -> str:
    return f"""<!doctype html><html lang="sv"><body style="margin:0;padding:0;background:#f6f3ea;color:#1c1b18;">
<div style="max-width:560px;margin:0 auto;padding:32px 20px;font:16px/1.55 Georgia,'Times New Roman',serif;">
<p style="margin:0 0 24px;font-size:13px;letter-spacing:.04em;color:#6b665c;">MATJAKT</p>
<h1 style="font-size:24px;font-weight:normal;margin:0 0 18px;">{html_lib.escape(title)}</h1>
{paragraphs_html}
<hr style="border:0;border-top:1px solid #d9d4c7;margin:28px 0 14px;">
<p style="font-size:12px;color:#6b665c;margin:0;">Du får det här mejlet för att du tackade ja till utskick i Matjakt.
<a href="{html_lib.escape(unsubscribe)}" style="color:#6b665c;">Avsluta utskicken</a> ·
<a href="{html_lib.escape(app_url)}" style="color:#6b665c;">Öppna Matjakt</a></p>
</div></body></html>"""


def _footer_text(app_url: str, unsubscribe: str) -> str:
    return (f"\n\n--\nDu får det här mejlet för att du tackade ja till utskick i Matjakt.\n"
            f"Avsluta utskicken: {unsubscribe}\nÖppna Matjakt: {app_url}\n")


def render_welcome(step: str, app_url: str, unsubscribe: str) -> tuple:
    """(ämne, text, html) för welcome_3 / welcome_7."""
    if step == "welcome_3":
        subject = "Tre dagar med Matjakt: tre saker som sparar mest"
        points = [
            ("Fynden på Hem-fliken.", "Kampanjpriserna kommer från butikerna själva varje natt. Ett fynd som "
             "hamnar i din vecka sänker totalen direkt."),
            ("Byt ut ett recept.", "Gillar du inte torsdagens middag byter du den med ett tryck. Priset räknas om på en gång."),
            ("Bocka av i butiken.", "Inköpslistan är sorterad som hyllorna och kommer ihåg vad du redan har hemma."),
        ]
        intro = "Du har haft Matjakt i tre dagar. Det här är de tre sakerna som gör störst skillnad på matkontot."
    else:
        subject = "En vecka med Matjakt"
        points = [
            ("Planera nästa vecka nu.", "De som planerar på söndagen handlar billigast, för då är kampanjerna nya."),
            ("Skafferiet.", "Lägg in det du redan har så räknar Matjakt bort det från listan och priset."),
            ("Alla butiker.", "Gratisversionen visar den billigaste butiken för din vecka. Premium visar alla, "
             "så du kan välja den som passar din dag."),
        ]
        intro = "En vecka har gått. Här är det som brukar avgöra om Matjakt fastnar eller inte."
    text = intro + "\n\n" + "\n\n".join(f"{head} {body}" for head, body in points) + \
        f"\n\nÖppna Matjakt: {app_url}" + _footer_text(app_url, unsubscribe)
    body_html = f"<p>{html_lib.escape(intro)}</p>" + "".join(
        f"<p><strong style=\"font-weight:600;\">{html_lib.escape(head)}</strong> {html_lib.escape(body)}</p>"
        for head, body in points) + \
        f"<p style=\"margin-top:24px;\"><a href=\"{html_lib.escape(app_url)}\" style=\"color:#1c1b18;\">Öppna Matjakt</a></p>"
    return subject, text, _layout(subject, body_html, app_url, unsubscribe)


def render_kampanjtorget(deals_by_chain: dict, chains: list, app_url: str, unsubscribe: str, week: int):
    """(ämne, text, html) - eller None när det inte finns ett enda fynd att
    visa för de valda kedjorna. Ett tomt torg skickas aldrig."""
    sections = [(chain, deals_by_chain.get(chain) or []) for chain in chains]
    sections = [(chain, deals[:DEALS_PER_CHAIN]) for chain, deals in sections if deals]
    if not sections:
        return None
    names = [chain for chain, _ in sections]
    listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " och " + names[-1]
    subject = f"Kampanjtorget vecka {week}: bästa fynden hos {listed}"
    intro = ("Veckans bästa kampanjpriser, hämtade från butikerna själva. Procenten är mot ordinarie pris; "
             "\"lägsta vi sett\" är det lägsta priset Matjakt noterat för varan senaste 30 dagarna.")
    # Bästa fyndet över ALLA valda kedjor lyfts ut och visas stort överst.
    # Ett mejl med tolv likadana rader läses inte; ett med ett tydligt bästa
    # fynd gör det. Raden ligger kvar i sin kedjas lista också - att plocka
    # bort den skulle göra kedjans avsnitt ofullständigt.
    bäst_kedja, bäst = max(
        ((chain, deal) for chain, deals in sections for deal in deals),
        key=lambda par: par[1].get("discountPercent") or 0)
    text_parts = [intro, f"\nVECKANS BÄSTA FYND\n  {bäst['name']}: "
                  f"{_kr(bäst['campaignPrice'])} (ord. {_kr(bäst['regularPrice'])}, "
                  f"-{int(bäst['discountPercent'])} %) hos {bäst_kedja}"]
    html_parts = [f"<p>{html_lib.escape(intro)}</p>", _hero(bäst, bäst_kedja)]
    for chain, deals in sections:
        text_parts.append(f"\n{chain}\n" + "-" * len(chain))
        html_parts.append(f"<h2 style=\"font-size:18px;font-weight:normal;margin:26px 0 8px;\">{html_lib.escape(chain)}</h2>")
        rows = []
        for deal in deals:
            label = deal["name"] + (f" {deal['size']}" if deal.get("size") else "") + \
                (f", {deal['brand']}" if deal.get("brand") else "")
            price = f"{_kr(deal['campaignPrice'])} (ord. {_kr(deal['regularPrice'])}, -{deal['discountPercent']} %)"
            lowest = deal.get("lowestSeen")
            note = ""
            if lowest is not None and float(lowest) >= float(deal["campaignPrice"]):
                note = " Lägsta vi sett."
            text_parts.append(f"  {label}: {price}.{note}")
            muted = 'style="font-size:12px;color:#6b665c;"'
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
        html_parts.append("<table style=\"width:100%;border-collapse:collapse;font-size:15px;\">" + "".join(rows) + "</table>")
    text_parts.append(f"\nLägg fynden i din vecka: {app_url}")
    html_parts.append(f"<p style=\"margin-top:24px;\"><a href=\"{html_lib.escape(app_url)}\" style=\"color:#1c1b18;\">Lägg fynden i din vecka</a></p>")
    text = "\n".join(text_parts) + _footer_text(app_url, unsubscribe)
    return subject, text, _layout(f"Kampanjtorget vecka {week}", "".join(html_parts), app_url, unsubscribe)


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
                 pause_seconds: float = 0.2):
        self.store = store
        self.sender = sender
        self.deals_provider = deals_provider
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
            kinds = ["welcome_3", "welcome_7"]
            if now.weekday() == KAMPANJTORGET_WEEKDAY:
                kinds.append("kampanjtorget")
            deals = None
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

    def _render(self, kind: str, row, deals, now):
        unsub = unsubscribe_url(self.api_base, row["id"], self.secret)
        if kind == "kampanjtorget":
            chains = chains_for_user(row["synced_state"], self.released_chains)
            return render_kampanjtorget(deals, chains, self.app_url, unsub, now.isocalendar()[1])
        return render_welcome(kind, self.app_url, unsub)

    def preview(self, kind: str, to_email: str, now=None) -> dict:
        """Skickar ett exempel av `kind` till en adress (admin). Kräver bara
        SMTP - inte att utskicken är påslagna - så Adam kan se mejlen innan
        någon annan får dem. Loggas inte i mail_log."""
        if kind not in KINDS:
            raise ValueError("Okänt utskick")
        if not self.mail_configured():
            raise RuntimeError("SMTP är inte konfigurerat")
        now = now or _now()
        unsub = unsubscribe_url(self.api_base, 0, self.secret or "preview")
        if kind == "kampanjtorget":
            rendered = render_kampanjtorget(self.deals_provider() or {}, list(self.released_chains),
                                            self.app_url, unsub, now.isocalendar()[1])
            if rendered is None:
                raise RuntimeError("Inga fynd i databasen just nu - Kampanjtorget skulle inte skickas")
        else:
            rendered = render_welcome(kind, self.app_url, unsub)
        subject, text, body_html = rendered
        self.sender(to_email, subject, text, body_html, unsub)
        return {"ok": True, "kind": kind, "subject": subject}
