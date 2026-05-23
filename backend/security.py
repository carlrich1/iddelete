"""Security middleware: rate limiting and CAPTCHA verification.

Kept tiny on purpose — no Redis, no external services unless configured.
For higher scale or multi-process deploys, swap ``_BUCKETS`` for a
shared store (Redis, Memcached, or a Werkzeug ProxyFix-aware backend).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from functools import wraps
from typing import Callable

import requests
from flask import jsonify, request

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

# bucket key (route + ip) -> deque[float timestamps]
_BUCKETS: dict[str, deque] = {}
_BUCKETS_LOCK = threading.Lock()


def _client_ip() -> str:
    """Best-effort client IP, honoring X-Forwarded-For when behind a proxy
    (Railway puts the real IP first in this header)."""
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"


def rate_limit(
    limit: int = 5,
    window_seconds: int = 15 * 60,
    key_prefix: str | None = None,
) -> Callable:
    """Decorator: at most ``limit`` requests per ``window_seconds`` per IP.

    Returns 429 with a JSON body when exceeded. Designed for auth endpoints
    (login, signup, forgot, reset).
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if os.environ.get("EY_RATE_LIMIT_DISABLED") == "1":
                return fn(*args, **kwargs)
            ip = _client_ip()
            prefix = key_prefix or fn.__name__
            key = f"{prefix}:{ip}"
            cutoff = time.time() - window_seconds
            with _BUCKETS_LOCK:
                dq = _BUCKETS.get(key)
                if dq is None:
                    dq = deque()
                    _BUCKETS[key] = dq
                # Drop expired entries
                while dq and dq[0] < cutoff:
                    dq.popleft()
                if len(dq) >= limit:
                    retry_after = int(window_seconds - (time.time() - dq[0]))
                    resp = jsonify(
                        error="rate_limited",
                        retry_after_seconds=max(retry_after, 1),
                    )
                    resp.status_code = 429
                    resp.headers["Retry-After"] = str(max(retry_after, 1))
                    log.info("rate limit hit: key=%s count=%d", key, len(dq))
                    return resp
                dq.append(time.time())
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def reset_rate_limit_buckets() -> None:
    """Test helper — clears all buckets."""
    with _BUCKETS_LOCK:
        _BUCKETS.clear()


# ---------------------------------------------------------------------------
# hCaptcha verification (server-side)
#
# Free, privacy-friendly CAPTCHA. Sign up at https://hcaptcha.com and set
# HCAPTCHA_SITEKEY (public, exposed via /api/config) and HCAPTCHA_SECRET
# (server-only). If either is missing, captcha verification is skipped —
# convenient for local dev and gives you a kill switch in production.
# ---------------------------------------------------------------------------

HCAPTCHA_VERIFY_URL = "https://api.hcaptcha.com/siteverify"


def is_captcha_enabled() -> bool:
    return bool(
        os.environ.get("HCAPTCHA_SITEKEY") and os.environ.get("HCAPTCHA_SECRET")
    )


def verify_hcaptcha(token: str) -> tuple[bool, str | None]:
    """Returns (ok, error_code). When captcha is disabled, returns (True, None)
    so callers can use ``if not verify_hcaptcha(t)[0]: ...`` unconditionally."""
    if not is_captcha_enabled():
        return True, None
    if not token:
        return False, "captcha_missing"
    secret = os.environ.get("HCAPTCHA_SECRET", "")
    try:
        resp = requests.post(
            HCAPTCHA_VERIFY_URL,
            data={
                "secret": secret,
                "response": token,
                "remoteip": _client_ip(),
            },
            timeout=10,
        )
        body = resp.json() if resp.ok else {}
    except Exception as e:
        log.warning("hCaptcha verification request failed: %s", e)
        return False, "captcha_unreachable"
    if body.get("success"):
        return True, None
    codes = body.get("error-codes") or []
    return False, "captcha_invalid:" + ",".join(codes) if codes else "captcha_invalid"
