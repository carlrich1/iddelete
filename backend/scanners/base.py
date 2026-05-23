"""Scanner base class.

Each broker integration subclasses :class:`BaseScanner` and implements:

* :meth:`search`              – given identifiers, return a list of matches
* :meth:`submit_removal`      – file an opt-out for a profile_url
* :meth:`check_removal_status` – has the broker removed the listing yet?

A "match" is a dict shaped like::

    {
        "profile_url":      "https://example.com/p/abc123",
        "exposed_fields":   ["Full name", "Home address", "Phone number"],
        "match_confidence": 0.92,
    }

The dispatcher in ``scanners/__init__.py`` iterates registered scanners and
stores each match as an :class:`exposures` row. It is **always safe** to
return an empty list (e.g., when the broker is unavailable or has blocked
the request) — the exposure simply stays as "not found" and we try again
on the next scheduled scan.
"""

from __future__ import annotations

from typing import Any, ClassVar


class ScannerError(RuntimeError):
    """Recoverable scanner error. Caller logs and moves on."""


class BaseScanner:
    # ----- subclass declares these -----
    slug: ClassVar[str] = ""              # stable id e.g. "spokeo"
    name: ClassVar[str] = ""              # display name "Spokeo"
    homepage: ClassVar[str] = ""          # for the UI link
    removal_url: ClassVar[str] = ""       # public opt-out page
    rate_limit_seconds: ClassVar[float] = 5.0
    # If True, the scanner is honest about not having a programmatic
    # opt-out and the system will queue a manual review task instead.
    manual_removal_only: ClassVar[bool] = False

    # ----- override these -----

    def search(self, identifiers: dict) -> list[dict]:
        """Return a list of matches. Empty list = nothing found."""
        raise NotImplementedError

    def submit_removal(self, exposure_row, identifiers: dict) -> dict:
        """Submit an opt-out request for the given exposure.

        Return shape::

            {
                "status":    "submitted" | "failed" | "manual_required",
                "reference": "ticket-XYZ" | None,
                "details":   "free text",
            }
        """
        return {"status": "manual_required", "reference": None,
                "details": "No automated opt-out implemented yet."}

    def check_removal_status(self, exposure_row, reference: str | None) -> str:
        """Return ``pending`` | ``removed`` | ``failed``."""
        return "pending"
