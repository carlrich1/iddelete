"""Background worker — scheduled re-scans, removal queue, monthly digests."""

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


def process_removal_queue() -> None:
    scanners_by_slug = {c.slug: c for c in registered()}
    with standalone_connection() as conn:
        rows = conn.execute(
            "SELECT e.*, u.name as user_name, u.email as user_email, "
            "u.phone, u.dob, u.city, u.state "
            "FROM exposures e JOIN users u ON u.id = e.user_id "
            "WHERE e.status = 'found' LIMIT 100"
        ).fetchall()
        for row in rows:
            cls = scanners_by_slug.get(row["broker_slug"])
            if not cls:
                continue
            scanner = cls()
            name = row["user_name"] or ""
            parts = name.split(" ", 1)
            ident = {"name": name,
                     "first_name": parts[0] if parts else "",
                     "last_name": parts[1] if len(parts) > 1 else "",
                     "email": row["user_email"], "phone": row["phone"] or "",
                     "city": row["city"] or "", "state": row["state"] or "",
                     "dob": row["dob"] or ""}
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
                "INSERT INTO removal_requests(exposure_id, attempt_num, sent_at, "
                "status, response_body, reference) VALUES (?,?,?,?,?,?)",
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
            conn.commit()


def check_removal_statuses() -> None:
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
                "SELECT reference FROM removal_requests "
                "WHERE exposure_id = ? ORDER BY id DESC LIMIT 1",
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
                u = conn.execute(
                    "SELECT email FROM users WHERE id = ?", (row["user_id"],)
                ).fetchone()
                remaining = conn.execute(
                    "SELECT COUNT(*) FROM exposures WHERE user_id = ? AND status IN ('found','req','manual')",
                    (row["user_id"],),
                ).fetchone()[0]
                try:
                    exposed = json.loads(row["exposed_fields"]) if row["exposed_fields"] else []
                except Exception:
                    exposed = []
                try:
                    from .mailer import notify, site_url
                    notify(
                        user_id=row["user_id"], user_email=u["email"] if u else "",
                        kind="removed", short_body=f"Removed from {row['broker_name']}.",
                        template="removal_confirmed",
                        context={"broker_name": row["broker_name"],
                                 "exposed_fields": ", ".join(exposed),
                                 "remaining": remaining,
                                 "dashboard_url": f"{site_url()}/removals.html"},
                        conn=conn,
                    )
                except Exception:
                    log.exception("removal notify failed")
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


def send_monthly_digests() -> None:
    """Email each active user a one-page monthly privacy report."""
    thirty_days_ago = now() - (30 * 24 * 3600)
    with standalone_connection() as conn:
        users = conn.execute(
            "SELECT id, email, name FROM users "
            "WHERE subscription_status IN ('active','trialing')"
        ).fetchall()
        for u in users:
            removed = conn.execute(
                "SELECT COUNT(*) FROM exposures WHERE user_id = ? AND status = 'gone' AND removed_at >= ?",
                (u["id"], thirty_days_ago),
            ).fetchone()[0]
            in_progress = conn.execute(
                "SELECT COUNT(*) FROM exposures WHERE user_id = ? AND status IN ('found','req','manual')",
                (u["id"],),
            ).fetchone()[0]
            new_found = conn.execute(
                "SELECT COUNT(*) FROM exposures WHERE user_id = ? AND created_at >= ?",
                (u["id"], thirty_days_ago),
            ).fetchone()[0]
            brokers_scanned = conn.execute(
                "SELECT COALESCE(SUM(brokers_scanned), 0) FROM scan_runs WHERE user_id = ? AND started_at >= ?",
                (u["id"], thirty_days_ago),
            ).fetchone()[0]
            try:
                from .mailer import notify, site_url
                notify(
                    user_id=u["id"], user_email=u["email"], kind="monthly_summary",
                    short_body=f"Your monthly report: {removed} removed, {in_progress} in progress.",
                    template="monthly_summary",
                    context={"removed_count": removed, "in_progress_count": in_progress,
                             "new_count": new_found, "brokers_scanned": int(brokers_scanned),
                             "dashboard_url": f"{site_url()}/dashboard.html"},
                    conn=conn,
                )
                conn.commit()
            except Exception:
                log.exception("monthly digest failed for user %d", u["id"])


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    sched = BackgroundScheduler(daemon=True)
    sched.add_job(process_removal_queue, "interval", minutes=1, id="removals", max_instances=1)
    sched.add_job(check_removal_statuses, "interval", minutes=5, id="status_checks", max_instances=1)
    sched.add_job(monthly_rescan, "cron", hour=4, minute=0, id="monthly_rescan", max_instances=1)
    sched.add_job(send_monthly_digests, "cron", day=1, hour=9, minute=0, id="monthly_digests", max_instances=1)
    sched.start()
    log.info("Background scheduler started")
    _scheduler = sched
    return sched
