#!/usr/bin/env bash
# Convenience launcher (macOS / Linux).
set -e
cd "$(dirname "$0")/.."        # cd into privacy1/
if [ ! -d backend/.venv ]; then
    python3 -m venv backend/.venv
    backend/.venv/bin/pip install -U pip
    backend/.venv/bin/pip install -r backend/requirements.txt
fi
# Load .env if present
if [ -f backend/.env ]; then
    set -a
    . backend/.env
    set +a
fi
exec backend/.venv/bin/python -m backend.app
