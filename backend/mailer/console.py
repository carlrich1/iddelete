"""Console email provider — logs the message instead of sending.

This is the default in development (and the safe fallback if a real
provider is misconfigured), so signup, password reset, etc. don't
crash when no API key is set.
"""

from __future__ import annotations

import logging

from .base import BaseEmailProvider, EmailMessage, EmailResult

log = logging.getLogger("backend.mailer.console")


class ConsoleProvider(BaseEmailProvider):
    name = "console"

    def is_configured(self) -> bool:
        return True

    def _send_impl(self, msg: EmailMessage) -> EmailResult:
        log.info(
            "[email/console] to=%s from=%s subject=%r\n----- TEXT -----\n%s\n"
            "----- HTML -----\n%s\n----- END -----",
            msg.to,
            msg.resolved_from(),
            msg.subject,
            msg.resolved_text(),
            msg.html[:2000],
        )
        return EmailResult(
            ok=True,
            provider=self.name,
            message_id=f"console-{id(msg):x}",
        )
