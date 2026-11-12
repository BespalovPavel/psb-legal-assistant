FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT="/opt/venv" \
    PATH="/opt/venv/bin:$PATH" \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Системные зависимости для сборки C-расширений и работы с PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Копируем бинарник uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Создаём виртуальное окружение и ставим зависимости из requirements.txt + пакеты для БД/конфига
COPY requirements.txt ./
RUN uv venv /opt/venv && \
    uv pip install -r requirements.txt pydantic-settings asyncpg jinja2 alembic

# Копируем исходный код проекта
COPY . /app

# Защита от Windows-переносов строк (CRLF) и права на выполнение entrypoint.sh
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]