# ID Delete — Backend

Flask + SQLite backend that powers the privacy-removal SaaS. The static
frontend in the parent directory is served by the same Flask app, so once
this is running you visit a single URL (default `http://127.0.0.1:5000`)
and the whole product works end-to-end.

## What you get out of the box

* **Real signup / login** — passwords hashed (PBKDF2), session cookies (HttpOnly).
* **SQLite database** — file-based, zero config. Schema is migrated on startup.
* **Scanner framework** — abstract `BaseScanner` plus deterministic mock
  scanners for ~45 broker brands. Real-broker scaffolds (WhitePages,
  Spokeo, BeenVerified) are included but default to dry-run.
* **Removal queue + scheduler** — APScheduler background jobs file opt-out
  requests, poll for removal confirmation, and re-scan every active user.
* **Stripe integration** — Checkout + Customer Portal + webhook receiver.
  Disabled by default; set `STRIPE_SECRET_KEY` to turn it on.
* **REST API** under `/api/*` consumed by the existing HTML/CSS/JS frontend.

## Quick start

```bash
cd privacy1/backend
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m backend.app          # run from privacy1/, NOT from backend/
```

Then visit **http://127.0.0.1:5000**.

> ⚠️ Run the command from the `privacy1/` directory (one level up from
> `backend/`), so that the `backend` package is importable. On Windows
> the included `run.bat` does this automatically.

## Configuration

Copy `backend/.env.example` to `backend/.env` and edit. The important
toggles:

| Variable | Effect |
|----------|--------|
| `FLASK_SECRET_KEY` | Required for safe session cookies. Set to 32 random bytes. |
| `EY_COOKIE_SECURE=1` | Mark cookies Secure (turn on behind HTTPS). |
| `EY_DB_PATH` | Override SQLite file path. |
| `EY_REAL_SCANNERS=1` | Load production-pattern scanner modules in addition to mocks. |
| `EY_LIVE_REQUESTS=1` | Fire real HTTP opt-out requests. Leave **off** in dev. |
| `STRIPE_SECRET_KEY` + `STRIPE_PRICE_*` | Turn on real billing. |

## API surface

All routes are JSON. Session is a cookie (`ey_session`).

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/auth/signup` | Create user + session, fire initial scan |
| POST | `/api/auth/login` | Email + password → session |
| POST | `/api/auth/logout` | Revoke session |
| GET  | `/api/auth/me` | Current user (or null) |
| GET  | `/api/scan` | All exposures + summary |
| POST | `/api/scan/run` | Kick a fresh scan |
| GET  | `/api/removals` | Removal log |
| PATCH | `/api/profile` | Update identifiers |
| DELETE | `/api/account` | Cancel + delete |
| GET  | `/api/brokers` | Catalogue of registered scanners |
| GET  | `/api/health` | Liveness probe (used by the frontend to detect API mode) |
| GET  | `/api/billing/config` | Public key + which prices are configured |
| POST | `/api/billing/checkout` | Start Stripe Checkout session |
| POST | `/api/billing/portal` | Open Stripe Customer Portal |
| POST | `/api/billing/webhook` | Stripe webhook receiver |

## How the frontend detects backend

`js/api.js` probes `/api/health` on every page load. If it answers,
`window.eyBackend.mode === 'api'` and every call (`signup`, `getScan`, …)
goes over fetch. If not, it falls back to `localStorage`. This means the
static site keeps working with no backend, and turns into a real app the
moment you start Flask.

## Adding a new broker scanner

1. Create `backend/scanners/yourbroker.py`.
2. Subclass `BaseScanner`, declare `slug`, `name`, `homepage`, `removal_url`.
3. Implement `search`, `submit_removal`, `check_removal_status`.
4. Decorate the class with `@register` (imported from `backend.scanners`).
5. Add the import to `backend/scanners/__init__.py` (inside the
   `EY_REAL_SCANNERS` block, or unconditionally if it has no external
   dependencies).

## Productionisation checklist

This codebase is a working foundation, not a hardened production deploy.
Before paying customers depend on it:

- [ ] Move from SQLite to Postgres (the schema is portable; swap the
      `sqlite3` calls for `psycopg`).
- [ ] Move the scheduler out of process (RQ/Celery/Dramatiq + Redis).
- [ ] Add residential proxy pool + CAPTCHA solver for real scrapers.
- [ ] Email service (Postmark or SES) for transactional mail.
- [ ] Rate-limit signup/login endpoints (e.g., Flask-Limiter).
- [ ] Turn on `EY_COOKIE_SECURE=1` behind HTTPS, add HSTS.
- [ ] Set a proper `FLASK_SECRET_KEY`.
- [ ] Add structured logging + error reporting (Sentry).
- [ ] Stripe webhook signature verification (already wired — just set
      `STRIPE_WEBHOOK_SECRET`).
- [ ] Legal review of opt-out request templates per broker.
- [ ] Privacy / security audit.

## Important honesty note about scrapers

Real data broker websites are protected by Cloudflare-style anti-bot
measures, CAPTCHAs, and Terms of Service that prohibit automated access.
Building production-grade scrapers requires:

1. Residential proxy pools (e.g., Bright Data, Oxylabs)
2. CAPTCHA-solving service (e.g., 2Captcha)
3. A human-in-the-loop queue for the brokers that require photo ID,
   notarized affidavits, or fax-only submission
4. Legal counsel on compliance with each broker's ToS in your jurisdiction

The `whitepages.py`, `spokeo.py`, and `beenverified.py` scanners ship
with `search()` deliberately returning empty results and `submit_removal()`
running in dry-mode unless `EY_LIVE_REQUESTS=1`. They show the structure
of the integration — they are not a turn-key scraping fleet.
