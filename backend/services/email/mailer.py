"""Minimal transactional email sender - stdlib only (smtplib/email), so it works
with any SMTP provider (Gmail app password, SendGrid/Postmark/AWS SES SMTP relay,
a self-hosted mail server, ...) without picking a vendor SDK/dependency. Configured
entirely via env vars - see .env.example. If unconfigured, send_email() raises
MailError so callers can surface a clear "not set up yet" message instead of
silently pretending an email went out.
"""

import smtplib
from email.mime.text import MIMEText


class MailError(Exception):
    """Raised for both "not configured" and real SMTP delivery errors."""


def is_configured(config) -> bool:
    """Whether mail can even be attempted. Callers use this to answer
    honestly BEFORE claiming a mail was sent - an unconfigured server is a
    fact about the server, identical for every address, so saying it out
    loud leaks nothing about which accounts exist."""
    return bool(config.get("host") and config.get("from_email"))


def send_email(config, to_email, subject, body_text):
    host = config.get("host")
    from_email = config.get("from_email")
    if not host or not from_email:
        raise MailError("E-post är inte konfigurerat på servern ännu")
    message = MIMEText(body_text, "plain", "utf-8")
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = to_email
    try:
        with smtplib.SMTP(host, int(config.get("port") or 587), timeout=15) as smtp:
            smtp.starttls()
            if config.get("user") and config.get("password"):
                smtp.login(config["user"], config["password"])
            smtp.sendmail(from_email, [to_email], message.as_string())
    except (smtplib.SMTPException, OSError) as error:
        raise MailError(f"Kunde inte skicka e-post: {error}")
