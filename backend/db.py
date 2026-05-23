"""SQLite database layer for ID Delete.

Migrations are forward-only via the ``MIGRATIONS`` list. The connection
is opened lazily per request (Flask's ``g``).
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Optional

from flask import g, current_app

DB_PATH_ENV = "EY_DB_PATH"
DEFAULT_DB_NAME = "iddelete.sqlite3"


def _db_path() -> str:
    p = os.environ.get(DB_PATH_ENV)
    if p:
        return p
    here = Path(__file__).resolve().parent
    return str(here / DEFAULT_DB_NAME)


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(_db_path())
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        g.db = conn
    return g.db


def close_db(error: Optional[BaseException] = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def standalone_connection():
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Migrations (forward-only)
# ---------------------------------------------------------------------------

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            name TEXT, phone TEXT, dob TEXT, city TEXT, state TEXT,
            prev_addresses TEXT, aliases TEXT,
            plan TEXT NOT NULL DEFAULT 'family',
            stripe_customer_id TEXT, stripe_subscription_id TEXT,
            subscription_status TEXT NOT NULL DEFAULT 'trialing',
            created_at REAL NOT NULL, updated_at REAL NOT NULL
        );
        CREATE TABLE sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at REAL NOT NULL, expires_at REAL NOT NULL
        );
        CREATE INDEX idx_sessions_user ON sessions(user_id);
        CREATE TABLE exposures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            broker_slug TEXT NOT NULL, broker_name TEXT NOT NULL,
            profile_url TEXT, exposed_fields TEXT NOT NULL,
            match_confidence REAL NOT NULL DEFAULT 1.0,
            status TEXT NOT NULL DEFAULT 'found',
            requested_at REAL, removed_at REAL,
            last_checked_at REAL NOT NULL, created_at REAL NOT NULL,
            UNIQUE(user_id, broker_slug, profile_url)
        );
        CREATE INDEX idx_exposures_user_status ON exposures(user_id, status);
        CREATE TABLE removal_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exposure_id INTEGER NOT NULL REFERENCES exposures(id) ON DELETE CASCADE,
            attempt_num INTEGER NOT NULL DEFAULT 1,
            sent_at REAL NOT NULL, response_at REAL,
            status TEXT NOT NULL, response_body TEXT, reference TEXT
        );
        CREATE INDEX idx_removal_requests_exposure ON removal_requests(exposure_id);
        CREATE TABLE notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind TEXT NOT NULL, body TEXT NOT NULL,
            read_at REAL, created_at REAL NOT NULL
        );
        CREATE INDEX idx_notifications_user ON notifications(user_id);
        CREATE TABLE scan_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            started_at REAL NOT NULL, finished_at REAL,
            brokers_scanned INTEGER NOT NULL DEFAULT 0,
            new_exposures INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'running'
        );
        CREATE INDEX idx_scan_runs_user ON scan_runs(user_id);
    """),
    (2, """
        CREATE TABLE password_resets (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at REAL NOT NULL, expires_at REAL NOT NULL, used_at REAL
        );
        CREATE INDEX idx_password_resets_user ON password_resets(user_id);
    """),
]


def migrate(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
    cur.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
    current = cur.fetchone()[0]
    for version, sql in MIGRATIONS:
        if version <= current:
            continue
        conn.executescript(sql)
        cur.execute("INSERT OR REPLACE INTO schema_version(version) VALUES (?)", (version,))
        conn.commit()


def init_db() -> None:
    with standalone_connection() as conn:
        migrate(conn)


def row_to_dict(row):
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def now() -> float:
    return time.time()


def to_user_dict(row):
    d = row_to_dict(row) or {}
    d.pop("password_hash", None)
    for k in ("prev_addresses", "aliases"):
        v = d.get(k)
        if isinstance(v, str) and v.startswith("["):
            try:
                d[k] = json.loads(v)
            except Exception:
                pass
    return d
