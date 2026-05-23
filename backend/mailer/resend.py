"""Resend (resend.com) email provider.

Docs: https://resend.com/docs/api-reference/emails/send-email

Required env vars:
    RESEND_API_KEY    Server-side API key from the Resend dashboard
    EY_EMAIL_FROM     "ID Delete <hello@iddelete.com>" (or whatever you
                      verified). Defaults if unset.

Optional:
    EY_EMAIL_REPLY_TO
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from .base import BaseEmailProvider, EmailMessage, EmailResult

log = logging.getLogger("backend.mailer.resend")

API_URL = "https://api.resend.com/emails"


class ResendProvider(BaseEmailProvider):
    name = "resend"

    def __init__(self) -> None:
        self.api_key = os.environ.get("RESEND_API_KEY", "").strip()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _send_impl(self, msg: EmailMessage) -> EmailResult:
        payload: dict[str, Any] = {
            "from": msg.resolved_from(),
            "to": [msg.to] if isinstance(msg.to, str) else list(msg.to),
            "subject": msg.subject,
            "html": msg.html,
            "text": msg.resolved_text(),
        }
        if msg.resolved_reply_to():
            payload["reply_to"] = msg.resolved_reply_to()
        if msg.tag:
            payload["tags"] = [{"name": "category", "value": msg.tag}]
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
            log.warning("Resend error %s: %s", resp.status_code, resp.text[:500])
            return EmailResult(
                ok=False,
                provider=self.name,
                error=f"http_{resp.status_code}: {resp.text[:300]}",
                raw=resp.text,
            )
        body = resp.json()
        return EmailResult(
            ok=True,
            provider=self.name,
            message_id=body.get("id"),
            raw=body,
        )
