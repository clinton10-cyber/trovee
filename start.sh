#!/bin/bash
# Trovee startup script for Render.com
set -e

# Initialise the database (safe to call on every deploy — uses IF NOT EXISTS)
python3 -c "
import sys
sys.path.insert(0, '.')
from backend.db import init_db
init_db()
print('Database ready.')
"

# Start the app with gunicorn
exec gunicorn backend.app:app \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers 2 \
  --timeout 60 \
  --log-level info
