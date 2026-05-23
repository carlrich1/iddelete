"""WhitePages scanner — production scaffold.

This module shows the *shape* of a real-broker integration. It is
intentionally conservative:

* It uses only the broker's public, advertised opt-out endpoint.
* It honours ``robots.txt`` and a 30-second per-request rate limit.
* ``search()`` does NOT actually scrape result pages (which would
  violate the WhitePages Terms of Use). Instead, it returns an empty
  list — in production you would replace this with a vendor-supplied
  data feed, a contractual API key, or a manual-review queue.
* ``submit_removal()`` constructs the opt-out POST payload but only
  fires it when ``EY_LIVE_REQUESTS=1`` is set, so an accidental run
  doesn't send live requests during development.

Treat this as **the skeleton you build out** when you have the legal
clearance, residential proxies, and CAPTCHA-solving service that
production-grade removal services use.
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
class WhitePagesScanner(BaseScanner):
    slug = "whitepages"
    name = "WhitePages"
    homepage = "https://www.whitepages.com"
    removal_url = "https://www.whitepages.com/suppression-requests"
    rate_limit_seconds = 30.0

    # --- search ------------------------------------------------------------

    def search(self, identifiers: dict) -> list[dict]:
        # WhitePages' search pages are protected by anti-bot measures and
        # their ToS forbids automated scraping. In production this is replaced
        # with either:
        #   1. A vendor API feed of broker listings, or
        #   2. A manual-review human-in-the-loop queue.
        # We return empty here so the rest of the system keeps working.
        log.debug("[whitepages] search() is a no-op without a data feed")
        return []

    # --- opt-out -----------------------------------------------------------

    def submit_removal(self, exposure_row, identifiers: dict) -> dict:
        """Compose a WhitePages suppression request.

        WhitePages' public opt-out form (``/suppression-requests``) accepts:
            * profile_url
            * first_name, last_name
            * email (for the confirmation link)

        We fire the POST only when EY_LIVE_REQUESTS=1.
        """
        payload = {
            "profile_url": exposure_row["profile_url"] or "",
            "first_name":  identifiers.get("first_name", ""),
            "last_name":   identifiers.get("last_name", ""),
            "email":       identifiers.get("email", ""),
        }
        if not LIVE:
            return {
                "status": "submitted",
                "reference": f"DRY-WP-{exposure_row['id']:08d}",
                "details": f"Dry run (EY_LIVE_REQUESTS unset). Would POST: {urlencode(payload)}",
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
                allow_redirects=True,
            )
            if r.status_code >= 400:
                return {"status": "failed", "reference": None,
                        "details": f"HTTP {r.status_code}: {r.text[:200]}"}
            return {
                "status": "submitted",
                "reference": f"WP-{int(time.time())}-{exposure_row['id']}",
                "details": "Opt-out form submitted; awaiting email confirmation.",
            }
        except Exception as e:
            return {"status": "failed", "reference": None, "details": str(e)}

    # --- status check ------------------------------------------------------

    def check_removal_status(self, exposure_row, reference):
        # In production: re-search the broker for the same profile_url and,
        # if it 404s or no longer matches the identifiers, mark "removed".
        return "pending"
