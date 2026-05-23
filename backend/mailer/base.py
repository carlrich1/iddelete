"""Abstract base class and shared types for email providers.

Each provider implements ``send(message)`` and ``is_configured()``. The
factory in ``__init__.py`` instantiates one provider for the lifetime
of the process.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class EmailMessage:
    to: str
    subject: str
    html: str
    text: str | None = None
    from_addr: str | None = None
    reply_to: str | None = None
    tag: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    def resolved_from(self) -> str:
        return (
            self.from_addr
            or os.environ.get("EY_EMAIL_FROM")
            or "ID Delete <hello@iddelete.com>"
        )

    def resolved_reply_to(self) -> str | None:
        return self.reply_to or os.environ.get("EY_EMAIL_REPLY_TO") or None

    def resolved_text(self) -> str:
        """Always return a plain-text body, generating one from HTML if
        the caller didn't supply one."""
        if self.text:
            return self.text
        # Strip tags as a last-resort fallback
        cleaned = re.sub(r"<style[\s\S]*?</style>", "", self.html)
        cleaned = re.sub(r"<script[\s\S]*?</script>", "", cleaned)
        cleaned = re.sub(r"<br\s*/?>", "\n", cleaned)
        cleaned = re.sub(r"</p>", "\n\n", cleaned)
        cleaned = re.sub(r"<[^>]+>", "", cleaned)
        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


@dataclass
class EmailResult:
    ok: bool
    provider: str
    message_id: str | None = None
    error: str | None = None
    raw: Any = None


# ---------------------------------------------------------------------------
# Base provider
# ---------------------------------------------------------------------------

class BaseEmailProvider:
    """Subclasses implement ``_send_impl`` and ``is_configured``."""

    name: str = "base"

    def is_configured(self) -> bool:  # pragma: no cover - default
        return True

    def send(self, msg: EmailMessage) -> EmailResult:
        try:
            return self._send_impl(msg)
        except Exception as e:
            log.exception("[%s] send failed: %s", self.name, e)
            return EmailResult(ok=False, provider=self.name, error=str(e))

    def _send_impl(self, msg: EmailMessage) -> EmailResult:  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def _load_text(path: Path) -> str | None:
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def render_template(
    template: str, context: dict[str, Any]
) -> tuple[str, str, str]:
    """Render <template>.html and (optional) <template>.txt using Jinja2.

    Returns (html, text, subject). Subject is extracted from the HTML
    ``<title>`` tag if present.
    """
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    html_tmpl = env.get_template(f"{template}.html")
    html = html_tmpl.render(**context)

    text = ""
    txt_path = TEMPLATES_DIR / f"{template}.txt"
    if txt_path.is_file():
        txt_tmpl = env.get_template(f"{template}.txt")
        text = txt_tmpl.render(**context)

    subj_match = re.search(r"<title>([\s\S]*?)</title>", html, re.IGNORECASE)
    subject = (subj_match.group(1).strip() if subj_match else "ID Delete")
    return html, text, subject
