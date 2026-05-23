"""Flask application entry point.

Serves the static frontend (``../*.html``, ``../css``, ``../js``) and the
REST API under ``/api``. Starts the background scheduler in-process.

Run:

    python -m backend.app

or

    flask --app backend.app run --port 5000
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, send_from_directory

from .auth import bp as auth_bp
from .api import bp as api_bp
from .stripe_billing import bp as billing_bp
from .db import close_db, init_db
from .worker import start_scheduler

ROOT = Path(__file__).resolve().parent.parent   # privacy1/


def create_app() -> Flask:
    logging.basicConfig(
        level=os.environ.get("EY_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    )
    app = Flask(__name__, static_folder=None)
    app.config["COOKIE_SECURE"] = os.environ.get("EY_COOKIE_SECURE") == "1"
    app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

    init_db()

    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(billing_bp)
    app.teardown_appcontext(close_db)

    # ----- static frontend ---------------------------------------------------

    @app.get("/")
    def root():
        return send_from_directory(ROOT, "index.html")

    @app.get("/<path:path>")
    def static_files(path: str):
        # Map clean URLs ("/pricing") to "pricing.html"
        candidate = ROOT / path
        if candidate.is_file():
            return send_from_directory(ROOT, path)
        html = ROOT / f"{path}.html"
        if html.is_file():
            return send_from_directory(ROOT, f"{path}.html")
        # Fallback: 404
        return ("Not found", 404)

    # Skip the background worker when running under the Flask reloader's
    # parent process or under tests.
    if os.environ.get("EY_NO_SCHEDULER") != "1":
        try:
            start_scheduler()
        except Exception as e:
            logging.warning("Scheduler did not start: %s", e)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port, debug=False)
