"""Authentication: signup, login, logout, current-user.

Uses session cookies backed by the ``sessions`` table. Passwords are hashed
with PBKDF2 via ``werkzeug.security``. Cookies are HttpOnly and SameSite=Lax;
mark them Secure in production behind HTTPS.
"""

from __future__ import annotations

import secrets
import time
from typing import Optional

from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db, now, to_user_dict

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

SESSION_COOKIE = "ey_session"
SESSION_TTL_SECONDS = 30 * 24 * 3600  # 30 days


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def _issue_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db = get_db()
    db.execute(
        "INSERT INTO sessions(token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
        (token, user_id, now(), now() + SESSION_TTL_SECONDS),
    )
    db.commit()
    return token


def _revoke_session(token: str) -> None:
    db = get_db()
    db.execute("DELETE FROM sessions WHERE token = ?", (token,))
    db.commit()


def _lookup_user_by_session(token: str) -> Optional[dict]:
    db = get_db()
    row = db.execute(
        """
        SELECT u.* FROM users u
        JOIN sessions s ON s.user_id = u.id
        WHERE s.token = ? AND s.expires_at > ?
        """,
        (token, now()),
    ).fetchone()
    return to_user_dict(row) if row else None


def current_user() -> Optional[dict]:
    """Return the authenticated user dict or None."""
    if hasattr(g, "user_cache"):
        return g.user_cache
    token = request.cookies.get(SESSION_COOKIE)
    user = _lookup_user_by_session(token) if token else None
    g.user_cache = user
    return user


def login_required(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        u = current_user()
        if not u:
            return jsonify(error="auth_required"), 401
        g.user = u
        return fn(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.post("/signup")
def signup():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    name = (data.get("name") or "").strip()
    plan = (data.get("plan") or "family").strip()
    city = (data.get("city") or "").strip()
    state = (data.get("state") or "").strip()

    if not email or "@" not in email:
        return jsonify(error="invalid_email"), 400
    if len(password) < 8:
        return jsonify(error="password_too_short"), 400
    if plan not in {"personal", "family", "pro"}:
        plan = "family"

    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        return jsonify(error="email_in_use"), 409

    t = now()
    cur = db.execute(
        """
        INSERT INTO users(email, password_hash, name, plan, city, state, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (email, generate_password_hash(password), name, plan, city, state, t, t),
    )
    user_id = cur.lastrowid
    db.commit()

    # Kick off the initial scan asynchronously
    from .scanners import schedule_full_scan
    schedule_full_scan(user_id)

    token = _issue_session(user_id)
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    resp = jsonify(user=to_user_dict(row))
    resp.set_cookie(
        SESSION_COOKIE, token,
        httponly=True, samesite="Lax",
        max_age=SESSION_TTL_SECONDS,
        secure=current_app.config.get("COOKIE_SECURE", False),
    )
    return resp, 201


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    db = get_db()
    row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password):
        return jsonify(error="invalid_credentials"), 401

    token = _issue_session(row["id"])
    resp = jsonify(user=to_user_dict(row))
    resp.set_cookie(
        SESSION_COOKIE, token,
        httponly=True, samesite="Lax",
        max_age=SESSION_TTL_SECONDS,
        secure=current_app.config.get("COOKIE_SECURE", False),
    )
    return resp


@bp.post("/logout")
def logout():
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        _revoke_session(token)
    resp = jsonify(ok=True)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@bp.get("/me")
def me():
    u = current_user()
    if not u:
        return jsonify(user=None), 200
    return jsonify(user=u)
