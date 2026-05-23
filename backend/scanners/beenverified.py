"""BeenVerified scanner — production scaffold.

Same caveats as the WhitePages and Spokeo modules. BeenVerified's opt-out
form requires the user to click an email confirmation link — that step is
intentionally outside the scope of automation here (the user must own that
inbox), so the scheduler will wait for the email reply rather than treating
the form submission as final.
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
class BeenVerifiedScanner(BaseScanner):
    slug = "beenverified"
    name = "BeenVerified"
    homepage = "https://www.beenverified.com"
    removal_url = "https://www.beenverified.com/app/optout/search"
    rate_limit_seconds = 30.0

    def search(self, identifiers: dict) -> list[dict]:
        log.debug("[beenverified] search() is a no-op without a data feed")
        return []

    def submit_removal(self, exposure_row, identifiers: dict) -> dict:
        payload = {
            "first_name": identifiers.get("first_name", ""),
            "last_name":  identifiers.get("last_name", ""),
            "email":      identifiers.get("email", ""),
            "profile":    exposure_row["profile_url"] or "",
        }
        if not LIVE:
            return {
                "status": "submitted",
                "reference": f"DRY-BV-{exposure_row['id']:08d}",
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
                "reference": f"BV-{int(time.time())}-{exposure_row['id']}",
                "details": "Submitted; awaiting customer's email confirmation.",
            }
        except Exception as e:
            return {"status": "failed", "reference": None, "details": str(e)}

    def check_removal_status(self, exposure_row, reference):
        return "pending"
