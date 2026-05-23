"""SendGrid (Twilio) email provider.

Docs: https://docs.sendgrid.com/api-reference/mail-send/mail-send

Required env vars:
    SENDGRID_API_KEY  API key with at least Mail Send permission
    EY_EMAIL_FROM     Verified sender
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import requests

from .base import BaseEmailProvider, EmailMessage, EmailResult

log = logging.getLogger("backend.mailer.sendgrid")

API_URL = "https://api.sendgrid.com/v3/mail/send"

_FROM_RE = re.compile(r"^\s*(.*?)\s*<([^>]+)>\s*$")


def _parse_addr(addr: str) -> dict[str, str]:
    m = _FROM_RE.match(addr)
    if m:
        return {"name": m.group(1) or "", "email": m.group(2)}
    return {"email": addr.strip()}


class SendGridProvider(BaseEmailProvider):
    name = "sendgrid"

    def __init__(self) -> None:
        self.api_key = os.environ.get("SENDGRID_API_KEY", "").strip()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _send_impl(self, msg: EmailMessage) -> EmailResult:
        payload: dict[str, Any] = {
            "personalizations": [{"to": [{"email": msg.to}]}],
            "from": _parse_addr(msg.resolved_from()),
            "subject": msg.subject,
            "content": [
                {"type": "text/plain", "value": msg.resolved_text()},
                {"type": "text/html", "value": msg.html},
            ],
        }
        if msg.resolved_reply_to():
            payload["reply_to"] = _parse_addr(msg.resolved_reply_to())
        if msg.tag:
            payload["categories"] = [msg.tag]
        if msg.headers:
            payload["headers"] = msg.headers

        resp = requests.post(
            API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        if resp.status_code >= 400:
            log.warning("SendGrid error %s: %s", resp.status_code, resp.text[:500])
            return EmailResult(
                ok=False,
                provider=self.name,
                error=f"http_{resp.status_code}: {resp.text[:300]}",
                raw=resp.text,
            )
        # SendGrid returns 202 with no body but message id in headers
        return EmailResult(
            ok=True,
            provider=self.name,
            message_id=resp.headers.get("X-Message-Id"),
        )
