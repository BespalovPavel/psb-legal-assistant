#!/bin/sh
set -e

echo "[ENTRYPOINT] Применение миграций БД (Alembic)..."
alembic upgrade head

exec uvicorn main:app --host 0.0.0.0 --port 8000
