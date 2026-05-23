"""Public REST API for the dashboard.

All routes here require an authenticated session (see ``auth.py``). Output
shape mirrors what the existing static frontend expects from ``app.js``.
"""

from __future__ import annotations

import json
import time
from typing import Any

from flask import Blueprint, g, jsonify, request

from .auth import login_required, current_user
from .db import get_db, now
from .scanners import list_scanners, schedule_full_scan

bp = Blueprint("api", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FRONTEND_STATUS = {
    # backend status -> frontend pill (matches static-only build)
    "found":  "found",
    "req":    "req",
    "gone":   "gone",
    "manual": "req",   # show as in-progress; specialist will pick up
}


def _exposure_to_dict(row) -> dict:
    return {
        "id":          row["id"],
        "broker":      row["broker_name"],
        "broker_slug": row["broker_slug"],
        "profileUrl":  row["profile_url"],
        "exposed":     json.loads(row["exposed_fields"] or "[]"),
        "confidence":  row["match_confidence"],
        "status":      _FRONTEND_STATUS.get(row["status"], row["status"]),
        "requestedAt": _ts(row["requested_at"]),
        "removedAt":   _ts(row["removed_at"]),
    }


def _ts(v) -> str | None:
    if not v:
        return None
    return time.strftime("%Y-%m-%d", time.gmtime(float(v)))


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@bp.patch("/profile")
@login_required
def update_profile():
    data = request.get_json(silent=True) or {}
    fields = ["name", "phone", "dob", "city", "state", "prev_addresses", "aliases"]
    updates = []
    args: list[Any] = []
    for f in fields:
        if f in data:
            updates.append(f"{f} = ?")
            args.append(data[f])
    if not updates:
        return jsonify(error="no_fields"), 400
    args.extend([now(), g.user["id"]])
    db = get_db()
    db.execute(f"UPDATE users SET {', '.join(updates)}, updated_at = ? WHERE id = ?", args)
    db.commit()
    return jsonify(ok=True)


@bp.delete("/account")
@login_required
def delete_account():
    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (g.user["id"],))
    db.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Scan / exposures
# ---------------------------------------------------------------------------

@bp.get("/scan")
@login_required
def list_exposures():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM exposures WHERE user_id = ? ORDER BY status, broker_name",
        (g.user["id"],),
    ).fetchall()
    return jsonify(
        exposures=[_exposure_to_dict(r) for r in rows],
        summary=_summary(rows),
    )


def _summary(rows) -> dict:
    out = {"total": len(rows), "found": 0, "req": 0, "gone": 0}
    for r in rows:
        s = _FRONTEND_STATUS.get(r["status"], r["status"])
        if s in out:
            out[s] += 1
    return out


@bp.post("/scan/run")
@login_required
def run_scan():
    schedule_full_scan(g.user["id"])
    return jsonify(ok=True, message="Scan kicked off; refresh in ~30s.")


# ---------------------------------------------------------------------------
# Removals
# ---------------------------------------------------------------------------

@bp.get("/removals")
@login_required
def list_removals():
    db = get_db()
    rows = db.execute(
        """
        SELECT e.*, (
            SELECT r.status FROM removal_requests r
            WHERE r.exposure_id = e.id ORDER BY r.id DESC LIMIT 1
        ) as last_request_status
        FROM exposures e
        WHERE e.user_id = ? AND e.status IN ('req','gone','found','manual')
        ORDER BY
            CASE e.status WHEN 'req' THEN 0 WHEN 'manual' THEN 1
                          WHEN 'found' THEN 2 ELSE 3 END,
            e.broker_name
        """,
        (g.user["id"],),
    ).fetchall()
    out = []
    for r in rows:
        d = _exposure_to_dict(r)
        d["lastRequestStatus"] = r["last_request_status"]
        out.append(d)
    return jsonify(removals=out)


# ---------------------------------------------------------------------------
# Brokers catalogue
# ---------------------------------------------------------------------------

@bp.get("/brokers")
def brokers():
    return jsonify(brokers=list_scanners())


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@bp.get("/health")
def health():
    db = get_db()
    n_users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    n_exposures = db.execute("SELECT COUNT(*) FROM exposures").fetchone()[0]
    return jsonify(ok=True, users=n_users, exposures=n_exposures,
                   scanners=len(list_scanners()))
