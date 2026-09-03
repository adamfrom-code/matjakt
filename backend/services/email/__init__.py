from .mailer import MailError, is_configured, send_email

__all__ = ["MailError", "is_configured", "send_email"]
from .mailer import MailNotConfigured, MailSendFailed, check_transport  # noqa: E402,F401
