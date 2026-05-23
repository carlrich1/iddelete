"""Postmark email provider.

Docs: https://postmarkapp.com/developer/api/email-api

Required env vars:
    POSTMARK_API_KEY  Server token (NOT the account token)
    EY_EMAIL_FROM     Verified sender signature
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from .base import BaseEmailProvider, EmailMessage, EmailResult

log = logging.getLogger("backend.mailer.postmark")

API_URL = "https://api.postmarkapp.com/email"


class PostmarkProvider(BaseEmailProvider):
    name = "postmark"

    def __init__(self) -> None:
        self.api_key = os.environ.get("POSTMARK_API_KEY", "").strip()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _send_impl(self, msg: EmailMessage) -> EmailResult:
        payload: dict[str, Any] = {
            "From": msg.resolved_from(),
            "To": msg.to,
            "Subject": msg.subject,
            "HtmlBody": msg.html,
            "TextBody": msg.resolved_text(),
            "MessageStream": os.environ.get("POSTMARK_STREAM", "outbound"),
        }
        if msg.resolved_reply_to():
            payload["ReplyTo"] = msg.resolved_reply_to()
        if msg.tag:
            payload["Tag"] = msg.tag
        if msg.headers:
            payload["Headers"] = [
                {"Name": k, "Value": v} for k, v in msg.headers.items()
            ]

        resp = requests.post(
            API_URL,
            json=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Postmark-Server-Token": self.api_key,
            },
            timeout=15,
        )
        if resp.status_code >= 400:
            log.warning("Postmark error %s: %s", resp.status_code, resp.text[:500])
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
            message_id=body.get("MessageID"),
            raw=body,
        )
