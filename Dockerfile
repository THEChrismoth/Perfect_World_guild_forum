FROM python:3.13-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# pg_dump и pg_restore для резервных копий. В Debian trixie это PostgreSQL 17 —
# версия должна быть не ниже версии базы в docker-compose.yml. gpg — шифрование копий
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client gpg gpg-agent \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Зависимости ставим отдельным слоем, чтобы при правке кода они не пересобирались
COPY requirements.txt .
RUN pip install -r requirements.txt

# Структура как в репозитории: код в /app/src, данные (static, media) в /app
COPY docker/ docker/
COPY src/ src/

# Работаем не от root. Папки static, media и backups создаем заранее с нужным владельцем —
# Docker скопирует эти права в тома при первом запуске
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/static /app/media /app/backups \
    && chown -R app:app /app \
    && chmod +x /app/docker/entrypoint.sh
USER app

WORKDIR /app/src

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["sh", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-3} --timeout 60 --access-logfile -"]
