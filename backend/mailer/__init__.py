"""Pluggable email provider for ID Delete.

Swap providers by setting EY_EMAIL_PROVIDER in the environment:
  console (default), resend, postmark, sendgrid, smtp
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from .base import BaseEmailProvider, EmailMessage, EmailResult

log = logging.getLogger(__name__)

_PROVIDERS = {
    "console":  "backend.mailer.console.ConsoleProvider",
    "resend":   "backend.mailer.resend.ResendProvider",
    "postmark": "backend.mailer.postmark.PostmarkProvider",
    "sendgrid": "backend.mailer.sendgrid.SendGridProvider",
    "smtp":     "backend.mailer.smtp.SMTPProvider",
}

_lock = threading.Lock()
_provider: BaseEmailProvider | None = None


def _import_class(dotted: str):
    mod_name, cls_name = dotted.rsplit(".", 1)
    import importlib
    return getattr(importlib.import_module(mod_name), cls_name)


def get_provider() -> BaseEmailProvider:
    global _provider
    if _provider is not None:
        return _provider
    with _lock:
        if _provider is not None:
            return _provider
        name = (os.environ.get("EY_EMAIL_PROVIDER") or "console").strip().lower()
        target = _PROVIDERS.get(name)
        if not target:
            log.warning("Unknown EY_EMAIL_PROVIDER=%r - falling back to console", name)
            target = _PROVIDERS["console"]
        try:
            cls = _import_class(target)
            inst = cls()
            if not inst.is_configured():
                log.warning("Provider %s not configured - falling back to console", name)
                inst = _import_class(_PROVIDERS["console"])()
            _provider = inst
            log.info("Email provider: %s", inst.name)
            return _provider
        except Exception:
            log.exception("Failed to load provider %r - using console", name)
            _provider = _import_class(_PROVIDERS["console"])()
            return _provider


def reset_provider_for_tests() -> None:
    global _provider
    with _lock:
        _provider = None


def send(to: str, subject: str, html: str, text: str | None = None, **opts) -> EmailResult:
    msg = EmailMessage(to=to, subject=subject, html=html, text=text, **opts)
    return get_provider().send(msg)


def send_template(to: str, template: str, context=None, subject=None, **opts) -> EmailResult:
    from .base import render_template
    import datetime
    ctx = dict(context or {})
    ctx.setdefault("year", datetime.datetime.now(datetime.timezone.utc).year)
    html, text, subj = render_template(template, ctx)
    return send(to=to, subject=subject or subj, html=html, text=text, **opts)


def site_url() -> str:
    return (os.environ.get("EY_SITE_URL") or "https://iddelete.com").rstrip("/")


def notify(user_id, user_email, kind, short_body, template=None, context=None, *, conn=None):
    """Write a row to notifications AND send a templated email."""
    import time as _time
    if conn is not None:
        conn.execute(
            "INSERT INTO notifications(user_id, kind, body, created_at) VALUES (?,?,?,?)",
            (user_id, kind, short_body, _time.time()),
        )
    else:
        from .. import db as _db
        with _db.standalone_connection() as c:
            c.execute(
                "INSERT INTO notifications(user_id, kind, body, created_at) VALUES (?,?,?,?)",
                (user_id, kind, short_body, _time.time()),
            )
            c.commit()
    if not template or not user_email:
        return None
    try:
        return send_template(to=user_email, template=template, context=context, tag=kind)
    except Exception:
        log.exception("notify: email send failed kind=%s user=%s", kind, user_id)
        return None


__all__ = [
    "get_provider", "reset_provider_for_tests", "send", "send_template",
    "notify", "site_url",
    "BaseEmailProvider", "EmailMessage", "EmailResult",
]
