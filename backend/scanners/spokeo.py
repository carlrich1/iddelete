"""Spokeo scanner — production scaffold.

See the docstring in ``whitepages.py`` for the design rationale. The same
pattern applies here: search is intentionally a no-op without a licensed
data feed; submit_removal builds the payload and only fires live when
``EY_LIVE_REQUESTS=1``.
"""

from __future__ import annotations

import logging
import os
import time
from urllib.parse import urlencode

from .base import BaseScanner, ScannerError
from . import register

log = logging.getLogger(__name__)

USER_AGENT = "ID Delete/1.0 (+https://iddelete.com/bot)"
LIVE = os.environ.get("EY_LIVE_REQUESTS") == "1"


@register
class SpokeoScanner(BaseScanner):
    slug = "spokeo"
    name = "Spokeo"
    homepage = "https://www.spokeo.com"
    removal_url = "https://www.spokeo.com/optout"
    rate_limit_seconds = 30.0

    def search(self, identifiers: dict) -> list[dict]:
        log.debug("[spokeo] search() is a no-op without a data feed")
        return []

    def submit_removal(self, exposure_row, identifiers: dict) -> dict:
        payload = {
            "url":   exposure_row["profile_url"] or "",
            "email": identifiers.get("email", ""),
        }
        if not LIVE:
            return {
                "status": "submitted",
                "reference": f"DRY-SP-{exposure_row['id']:08d}",
                "details": f"Dry run. Would POST: {urlencode(payload)}",
            }
        try:
            import requests
        except ImportError as e:
            raise ScannerError("requests library not installed") from e
        try:
            r = requests.post(
                self.removal_url,
                data=payload,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
                timeout=20,
            )
            if r.status_code >= 400:
                return {"status": "failed", "reference": None,
                        "details": f"HTTP {r.status_code}: {r.text[:200]}"}
            return {
                "status": "submitted",
                "reference": f"SP-{int(time.time())}-{exposure_row['id']}",
                "details": "Submitted; Spokeo will email a confirmation link.",
            }
        except Exception as e:
            return {"status": "failed", "reference": None, "details": str(e)}

    def check_removal_status(self, exposure_row, reference):
        return "pending"
