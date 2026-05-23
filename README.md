# ID Delete

A privacy removal SaaS. We scan the internet's data brokers for your personal
information and force them to delete you — continuously, on autopilot.

* **Live:** https://iddelete.com (deploys from `main` branch)
* **Stack:** Flask + SQLite + APScheduler, vanilla HTML/CSS/JS frontend
* **Architecture details:** see [backend/README.md](backend/README.md)

## Run locally

```bash
# From the project root
backend/run.bat        # Windows
./backend/run.sh       # macOS / Linux
```

Then visit http://127.0.0.1:5000.

## Deploy

Pushes to `main` auto-deploy to Railway. Environment variables live in the
Railway dashboard. See `backend/.env.example` for the full list.
