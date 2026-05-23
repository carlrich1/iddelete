"""Scanner registry and dispatcher.

Each scanner is a subclass of ``BaseScanner`` registered via ``register()``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Iterable, Type

from .base import BaseScanner, ScannerError
from ..db import standalone_connection, now

log = logging.getLogger(__name__)

_REGISTRY: list[Type[BaseScanner]] = []


def register(cls: Type[BaseScanner]) -> Type[BaseScanner]:
    if cls.slug in (c.slug for c in _REGISTRY):
        log.warning("Scanner with slug %r already registered; replacing", cls.slug)
        _REGISTRY[:] = [c for c in _REGISTRY if c.slug != cls.slug]
    _REGISTRY.append(cls)
    return cls


def registered() -> list[Type[BaseScanner]]:
    return list(_REGISTRY)


# Always-on mock scanner
from . import mock  # noqa: E402,F401

if os.environ.get("EY_REAL_SCANNERS") == "1":
    try:
        from . import whitepages  # noqa: F401
        from . import spokeo      # noqa: F401
        from . import beenverified  # noqa: F401
    except Exception as e:
        log.exception("Failed to load real scanners: %s", e)


def _identifiers_for(user_row) -> dict:
    name = (user_row["name"] or "").strip()
    parts = name.split(" ", 1)
    return {
        "name": name,
        "first_name": parts[0] if parts else "",
        "last_name": parts[1] if len(parts) > 1 else "",
        "email": user_row["email"],
        "phone": user_row["phone"] or "",
        "city": user_row["city"] or "",
        "state": user_row["state"] or "",
        "dob": user_row["dob"] or "",
    }


def run_full_scan(user_id: int) -> None:
    """Run every registered scanner for a single user, recording results."""
    with standalone_connection() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            log.warning("run_full_scan: user %d not found", user_id)
            return

        ident = _identifiers_for(user)
        run = conn.execute(
            "INSERT INTO scan_runs(user_id, started_at, status) VALUES (?,?,?)",
            (user_id, now(), "running"),
        )
        scan_run_id = run.lastrowid
        conn.commit()

        new_count = 0
        scanners = registered()
        log.info("Scanning user %d across %d brokers", user_id, len(scanners))

        for cls in scanners:
            scanner = cls()
            try:
                matches = scanner.search(ident)
            except ScannerError as e:
                log.warning("[%s] search failed: %s", scanner.slug, e)
                continue
            except Exception as e:
                log.exception("[%s] unexpected error: %s", scanner.slug, e)
                continue

            for m in matches:
                exposed_json = json.dumps(m.get("exposed_fields", []))
                try:
                    conn.execute(
                        "INSERT INTO exposures(user_id, broker_slug, broker_name, profile_url, "
                        "exposed_fields, match_confidence, status, last_checked_at, created_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (user_id, scanner.slug, scanner.name, m.get("profile_url"),
                         exposed_json, m.get("match_confidence", 0.9), "found", now(), now()),
                    )
                    new_count += 1
                except Exception:
                    conn.execute(
                        "UPDATE exposures SET last_checked_at = ? "
                        "WHERE user_id = ? AND broker_slug = ? "
                        "AND COALESCE(profile_url,'') = COALESCE(?,'')",
                        (now(), user_id, scanner.slug, m.get("profile_url")),
                    )
            time.sleep(scanner.rate_limit_seconds)

        conn.execute(
            "UPDATE scan_runs SET finished_at = ?, brokers_scanned = ?, "
            "new_exposures = ?, status = ? WHERE id = ?",
            (now(), len(scanners), new_count, "complete", scan_run_id),
        )
        conn.commit()
        log.info("Scan for user %d complete: %d new exposures", user_id, new_count)

        try:
            from ..mailer import notify, site_url
            notify(
                user_id=user_id, user_email=user["email"], kind="scan_complete",
                short_body=f"Scan complete - found you on {new_count} site(s).",
                template="scan_complete",
                context={"brokers_scanned": len(scanners), "found_count": new_count,
                         "dashboard_url": f"{site_url()}/dashboard.html"},
                conn=conn,
            )
            conn.commit()
        except Exception:
            log.exception("scan_complete notify failed")


def schedule_full_scan(user_id: int) -> None:
    t = threading.Thread(target=run_full_scan, args=(user_id,), daemon=True)
    t.start()


def list_scanners() -> list[dict]:
    """Public-safe metadata about all registered scanners (for /api/brokers)."""
    out = []
    for cls in registered():
        out.append({
            "slug": cls.slug,
            "name": cls.name,
            "homepage": cls.homepage,
            "removal_url": cls.removal_url,
        })
    return out
