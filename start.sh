#!/bin/sh
# Migrate, THEN serve — in that order, every deploy (Step 10).
#
# If the migration fails, the server never starts and the deploy is
# marked failed with the migration error in the logs — the previous
# version keeps serving. Code and schema therefore cannot disagree in
# production: the window where new code meets an old schema is closed by
# construction.
set -e

echo "[start] applying database migrations..."
alembic upgrade head

echo "[start] starting the server..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
