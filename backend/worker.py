"""Background worker — scheduled re-scans and removal queue.

Uses APScheduler in BackgroundScheduler mode so it shares the Flask
process. For production scale, swap this for a separate worker (RQ,
Celery, Dramatiq) reading from Redis.
"""

from __future__ import annotations

import json
import logging
import os
import time

from apscheduler.schedulers.background import BackgroundScheduler

from .db import standalone_connection, now
from .scanners import run_full_scan, registered

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def process_removal_queue() -> None:
    """For each exposure in 'found' status, submit a removal request."""
    scanners_by_slug = {c.slug: c for c in registered()}
    with standalone_connection() as conn:
        rows = conn.execute(
            """
            SELECT e.*, u.name as user_name, u.email as user_email,
                   u.phone, u.dob, u.city, u.state
            FROM exposures e
            JOIN users u ON u.id = e.user_id
            WHERE e.status = 'found'
            LIMIT 100
            """
        ).fetchall()

        for row in rows:
            cls = scanners_by_slug.get(row["broker_slug"])
            if not cls:
                log.warning("No scanner registered for slug=%s", row["broker_slug"])
                continue
            scanner = cls()
            name = row["user_name"] or ""
            parts = name.split(" ", 1)
            ident = {
                "name": name,
                "first_name": parts[0] if parts else "",
                "last_name": parts[1] if len(parts) > 1 else "",
                "email": row["user_email"],
                "phone": row["phone"] or "",
                "city": row["city"] or "",
                "state": row["state"] or "",
                "dob": row["dob"] or "",
            }
            try:
                result = scanner.submit_removal(row, ident)
            except Exception as e:
                log.exception("submit_removal failed for exposure %d", row["id"])
                result = {"status": "failed", "reference": None, "details": str(e)}

            attempt = conn.execute(
                "SELECT COUNT(*) FROM removal_requests WHERE exposure_id = ?",
                (row["id"],),
            ).fetchone()[0] + 1

            conn.execute(
                """
                INSERT INTO removal_requests(exposure_id, attempt_num, sent_at,
                                             status, response_body, reference)
                VALUES (?,?,?,?,?,?)
                """,
                (row["id"], attempt, now(), result["status"],
                 result.get("details"), result.get("reference")),
            )

            if result["status"] == "submitted":
                conn.execute(
                    "UPDATE exposures SET status='req', requested_at=?, last_checked_at=? WHERE id=?",
                    (now(), now(), row["id"]),
                )
            elif result["status"] == "manual_required":
                conn.execute(
                    "UPDATE exposures SET status='manual', last_checked_at=? WHERE id=?",
                    (now(), row["id"]),
                )
            # 'failed' leaves status as 'found' so we retry on next pass.
            conn.commit()


def check_removal_statuses() -> None:
    """For exposures in 'req' status, ask the scanner if they're gone yet."""
    scanners_by_slug = {c.slug: c for c in registered()}
    with standalone_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM exposures WHERE status = 'req' LIMIT 200"
        ).fetchall()
        for row in rows:
            cls = scanners_by_slug.get(row["broker_slug"])
            if not cls:
                continue
            scanner = cls()
            last_req = conn.execute(
                """SELECT reference FROM removal_requests
                   WHERE exposure_id = ? ORDER BY id DESC LIMIT 1""",
                (row["id"],),
            ).fetchone()
            ref = last_req["reference"] if last_req else None
            try:
                outcome = scanner.check_removal_status(row, ref)
            except Exception:
                log.exception("check_removal_status failed for exposure %d", row["id"])
                outcome = "pending"

            if outcome == "removed":
                conn.execute(
                    "UPDATE exposures SET status='gone', removed_at=?, last_checked_at=? WHERE id=?",
                    (now(), now(), row["id"]),
                )
                conn.execute(
                    "INSERT INTO notifications(user_id, kind, body, created_at) VALUES (?,?,?,?)",
                    (row["user_id"], "removed",
                     f"Removed from {row['broker_name']}.", now()),
                )
            else:
                conn.execute(
                    "UPDATE exposures SET last_checked_at=? WHERE id=?",
                    (now(), row["id"]),
                )
            conn.commit()


def monthly_rescan() -> None:
    """Re-scan every active user once per month."""
    with standalone_connection() as conn:
        users = conn.execute(
            "SELECT id FROM users WHERE subscription_status IN ('active','trialing')"
        ).fetchall()
    for u in users:
        run_full_scan(u["id"])


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    sched = BackgroundScheduler(daemon=True)
    # Every minute: drain the removal queue (a few items each pass)
    sched.add_job(process_removal_queue, "interval", minutes=1, id="removals", max_instances=1)
    # Every 5 minutes: check whether submitted removals have completed
    sched.add_job(check_removal_statuses, "interval", minutes=5, id="status_checks", max_instances=1)
    # Daily at 4am: full re-scan of every active user
    sched.add_job(monthly_rescan, "cron", hour=4, minute=0, id="monthly_rescan", max_instances=1)
    sched.start()
    log.info("Background scheduler started")
    _scheduler = sched
    return sched
