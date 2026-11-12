#!/bin/sh
set -e

echo "[ENTRYPOINT] Запуск сервиса ПСБ Юридический ИИ-ассистент..."
echo "[ENTRYPOINT] База данных: ${DB_HOST:-localhost}:${DB_PORT:-5432}/${DB_NAME:-psb_assistant}"
echo "[ENTRYPOINT] LLM модель : ${LLM_MODEL:-deepseek/deepseek-v4.1-flash}"

# Создаём необходимые директории, если их нет
mkdir -p /app/static /app/templates /app/data

echo "[ENTRYPOINT] Применение миграций БД (Alembic)..."
alembic upgrade head

exec "$@"