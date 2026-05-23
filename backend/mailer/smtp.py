"""Generic SMTP email provider.

Required env vars:
    SMTP_HOST       e.g. smtp.example.com
    SMTP_PORT       587 (STARTTLS) or 465 (SSL) or 25 (plain)
    SMTP_USER
    SMTP_PASSWORD
    EY_EMAIL_FROM

Optional:
    SMTP_USE_TLS    "1" to use STARTTLS (default for port 587)
    SMTP_USE_SSL    "1" to use direct SSL (default for port 465)
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage as MIMEMessage

from .base import BaseEmailProvider, EmailMessage, EmailResult

log = logging.getLogger("backend.mailer.smtp")


class SMTPProvider(BaseEmailProvider):
    name = "smtp"

    def __init__(self) -> None:
        self.host = os.environ.get("SMTP_HOST", "").strip()
        self.port = int(os.environ.get("SMTP_PORT", "587"))
        self.user = os.environ.get("SMTP_USER", "").strip()
        self.password = os.environ.get("SMTP_PASSWORD", "")
        self.use_ssl = os.environ.get("SMTP_USE_SSL") == "1" or self.port == 465
        self.use_tls = (
            os.environ.get("SMTP_USE_TLS", "1") == "1" and not self.use_ssl
        )

    def is_configured(self) -> bool:
        return bool(self.host)

    def _send_impl(self, msg: EmailMessage) -> EmailResult:
        mime = MIMEMessage()
        mime["From"] = msg.resolved_from()
        mime["To"] = msg.to
        mime["Subject"] = msg.subject
        if msg.resolved_reply_to():
            mime["Reply-To"] = msg.resolved_reply_to()
        for k, v in msg.headers.items():
            mime[k] = v
        mime.set_content(msg.resolved_text())
        mime.add_alternative(msg.html, subtype="html")

        if self.use_ssl:
            client = smtplib.SMTP_SSL(self.host, self.port, timeout=15)
        else:
            client = smtplib.SMTP(self.host, self.port, timeout=15)

        try:
            client.ehlo()
            if self.use_tls:
                client.starttls()
                client.ehlo()
            if self.user:
                client.login(self.user, self.password)
            client.send_message(mime)
        finally:
            try:
                client.quit()
            except Exception:
                pass

        return EmailResult(ok=True, provider=self.name)
