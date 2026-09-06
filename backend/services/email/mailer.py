"""Minimal transactional email sender - stdlib only (smtplib/email), so it works
with any SMTP provider (Gmail app password, SendGrid/Postmark/AWS SES SMTP relay,
a self-hosted mail server, ...) without picking a vendor SDK/dependency. Configured
entirely via env vars - see .env.example. If unconfigured, send_email() raises
MailError so callers can surface a clear "not set up yet" message instead of
silently pretending an email went out.
"""

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid, parseaddr

from ..data_guard import guard_outbound_call


class MailError(Exception):
    """Base for both "not configured" and real SMTP delivery errors. `code`
    är maskinläsbart så UI:t kan skilja fallen åt utan att tolka text."""

    code = "MAIL_ERROR"


class MailNotConfigured(MailError):
    """SMTP saknas på servern - ett serverfaktum, lika för alla adresser."""

    code = "MAIL_NOT_CONFIGURED"


class MailSendFailed(MailError):
    """SMTP finns men leveransen gick fel. Användarsäker text utåt, den
    råa SMTP-texten i `detail` för loggen."""

    code = "MAIL_SEND_FAILED"

    def __init__(self, detail: str):
        super().__init__("Mejlservern svarar inte just nu. Försök igen om en stund.")
        self.detail = detail


# STARTTLS utan context verifierar inte serverns certifikat på Python < 3.12
# (produktionens image är jammy/3.10) - en aktiv MITM kunde då läsa
# SMTP-lösenordet och varje återställningslänk. create_default_context()
# kräver giltig kedja och rätt värdnamn.
def is_configured(config) -> bool:
    """Whether mail can even be attempted. Callers use this to answer
    honestly BEFORE claiming a mail was sent - an unconfigured server is a
    fact about the server, identical for every address, so saying it out
    loud leaks nothing about which accounts exist."""
    return bool(config.get("host") and config.get("from_email"))


def send_email(config, to_email, subject, body_text, body_html=None, unsubscribe_url=None):
    """Text alltid; HTML som alternativ när det finns. `unsubscribe_url`
    sätter List-Unsubscribe så mejlklienter kan visa sin egen avsluta-knapp -
    utskicksmodulen (services/mailings) skickar aldrig utan den."""
    host = config.get("host")
    from_email = config.get("from_email")
    if not host or not from_email:
        raise MailNotConfigured("E-post är inte konfigurerat på servern ännu")
    guard_outbound_call("en SMTP-server")
    # Kuvertadressen (MAIL FROM) är den bara adressen; From-huvudet får ett
    # namn. Date och Message-ID sätts uttryckligen - utan dem ger
    # SpamAssassins MISSING_DATE/MISSING_MID poäng och mejlet hamnar i
    # skräpposten trots DKIM.
    display_name, envelope_from = parseaddr(from_email)
    envelope_from = envelope_from or from_email
    if body_html:
        message = MIMEMultipart("alternative")
        message.attach(MIMEText(body_text, "plain", "utf-8"))
        message.attach(MIMEText(body_html, "html", "utf-8"))
    else:
        message = MIMEText(body_text, "plain", "utf-8")
    message["Subject"] = subject
    message["From"] = formataddr((display_name or "Matjakt", envelope_from))
    message["To"] = to_email
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=envelope_from.rsplit("@", 1)[-1] or None)
    if unsubscribe_url:
        message["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    try:
        with smtplib.SMTP(host, int(config.get("port") or 587), timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if config.get("user") and config.get("password"):
                smtp.login(config["user"], config["password"])
            smtp.sendmail(envelope_from, [to_email], message.as_string())
    except (smtplib.SMTPException, OSError) as error:
        raise MailSendFailed(f"Kunde inte skicka e-post: {error}")


def check_transport(config):
    """Anslut + STARTTLS + inloggning + NOOP - inget mejl. Låter en endpoint
    säga "mejlservern svarar inte" FÖRE kontouppslaget, identiskt för varje
    adress, i stället för att lova ett mejl som aldrig går iväg."""
    if not is_configured(config):
        raise MailNotConfigured("E-post är inte konfigurerat på servern ännu")
    guard_outbound_call("en SMTP-server")
    try:
        with smtplib.SMTP(config["host"], int(config.get("port") or 587), timeout=10) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if config.get("user") and config.get("password"):
                smtp.login(config["user"], config["password"])
            smtp.noop()
    except (smtplib.SMTPException, OSError) as error:
        raise MailSendFailed(f"SMTP-kontroll misslyckades: {error}")
