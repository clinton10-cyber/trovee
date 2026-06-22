#!/bin/bash
# Trovee startup script.
# In production use gunicorn. In dev use flask directly.

set -e
cd "$(dirname "$0")/backend"

# Load .env if it exists
if [ -f ../.env ]; then
  export $(grep -v '^#' ../.env | xargs)
fi

# Initialise the database on first run (safe to call repeatedly).
python3 db.py

# Production: pip install gunicorn, then use:
#   gunicorn app:app --bind 0.0.0.0:8000 --workers 2
# Dev:
python3 app.py
