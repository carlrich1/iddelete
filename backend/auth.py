"""Authentication: signup, login, logout, current-user, password reset.

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
from .security import rate_limit, verify_hcaptcha

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

SESSION_COOKIE = "ey_session"
SESSION_TTL_SECONDS = 30 * 24 * 3600  # 30 days
PASSWORD_RESET_TTL_SECONDS = 60 * 60  # 1 hour


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
        "SELECT u.* FROM users u JOIN sessions s ON s.user_id = u.id "
        "WHERE s.token = ? AND s.expires_at > ?",
        (token, now()),
    ).fetchone()
    return to_user_dict(row) if row else None


def current_user() -> Optional[dict]:
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


def _site_base_url() -> str:
    import os
    explicit = os.environ.get("EY_SITE_URL")
    if explicit:
        return explicit.rstrip("/")
    return request.url_root.rstrip("/")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.post("/signup")
@rate_limit(limit=5, window_seconds=15 * 60, key_prefix="signup")
def signup():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    name = (data.get("name") or "").strip()
    plan = (data.get("plan") or "family").strip()
    city = (data.get("city") or "").strip()
    state = (data.get("state") or "").strip()
    captcha_token = (data.get("captcha_token") or "").strip()

    if not email or "@" not in email:
        return jsonify(error="invalid_email"), 400
    if len(password) < 8:
        return jsonify(error="password_too_short"), 400
    if plan not in {"personal", "family", "pro"}:
        plan = "family"

    ok, why = verify_hcaptcha(captcha_token)
    if not ok:
        return jsonify(error=why or "captcha_failed"), 400

    db = get_db()
    if db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
        return jsonify(error="email_in_use"), 409

    t = now()
    cur = db.execute(
        "INSERT INTO users(email, password_hash, name, plan, city, state, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (email, generate_password_hash(password), name, plan, city, state, t, t),
    )
    user_id = cur.lastrowid
    db.commit()

    from .scanners import schedule_full_scan
    schedule_full_scan(user_id)

    try:
        from .mailer import notify, site_url
        notify(
            user_id=user_id, user_email=email, kind="welcome",
            short_body="Welcome to ID Delete!", template="welcome",
            context={"name": name, "dashboard_url": f"{site_url()}/dashboard.html"},
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("welcome notify failed")

    token = _issue_session(user_id)
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    resp = jsonify(user=to_user_dict(row))
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="Lax",
                    max_age=SESSION_TTL_SECONDS,
                    secure=current_app.config.get("COOKIE_SECURE", False))
    return resp, 201


@bp.post("/login")
@rate_limit(limit=10, window_seconds=15 * 60, key_prefix="login")
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
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="Lax",
                    max_age=SESSION_TTL_SECONDS,
                    secure=current_app.config.get("COOKIE_SECURE", False))
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


@bp.post("/forgot")
@rate_limit(limit=5, window_seconds=15 * 60, key_prefix="forgot")
def forgot():
    """Request a password reset. Always returns 200 so callers can't
    enumerate which emails are registered."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return jsonify(ok=True)

    db = get_db()
    user = db.execute(
        "SELECT id, email, name FROM users WHERE email = ?", (email,)
    ).fetchone()

    if user is not None:
        db.execute("DELETE FROM password_resets WHERE user_id = ?", (user["id"],))
        token = secrets.token_urlsafe(32)
        db.execute(
            "INSERT INTO password_resets(token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
            (token, user["id"], now(), now() + PASSWORD_RESET_TTL_SECONDS),
        )
        db.commit()
        try:
            from .mailer import send_template
            reset_url = f"{_site_base_url()}/reset-password.html?t={token}"
            send_template(
                to=user["email"], template="password_reset",
                context={"name": user["name"] or "", "reset_url": reset_url,
                         "expires_in_hours": PASSWORD_RESET_TTL_SECONDS // 3600},
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception("password reset email failed")

    return jsonify(ok=True)


@bp.post("/reset")
@rate_limit(limit=10, window_seconds=15 * 60, key_prefix="reset")
def reset():
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    new_password = data.get("password") or ""
    if not token:
        return jsonify(error="invalid_token"), 400
    if len(new_password) < 8:
        return jsonify(error="password_too_short"), 400
    db = get_db()
    row = db.execute(
        "SELECT pr.token, pr.user_id, pr.expires_at, pr.used_at "
        "FROM password_resets pr WHERE pr.token = ?",
        (token,),
    ).fetchone()
    if row is None:
        return jsonify(error="invalid_token"), 400
    if row["used_at"] is not None:
        return jsonify(error="token_already_used"), 400
    if row["expires_at"] < now():
        return jsonify(error="token_expired"), 400
    db.execute("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
               (generate_password_hash(new_password), now(), row["user_id"]))
    db.execute("UPDATE password_resets SET used_at = ? WHERE token = ?", (now(), token))
    db.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))
    db.commit()
    new_token = _issue_session(row["user_id"])
    user_row = db.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    resp = jsonify(ok=True, user=to_user_dict(user_row))
    resp.set_cookie(SESSION_COOKIE, new_token, httponly=True, samesite="Lax",
                    max_age=SESSION_TTL_SECONDS,
                    secure=current_app.config.get("COOKIE_SECURE", False))
    return resp
