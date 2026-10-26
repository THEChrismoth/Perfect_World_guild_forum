# Демо-сайт: один контейнер с вымышленной гильдией, без PostgreSQL, TeamSpeak и Caddy.
# Подходит для бесплатных хостингов (Render, Koyeb и т.п.). Собирается из корня репозитория:
#   docker build -f docker/demo/Dockerfile -t guild-demo .
#   docker run --rm -p 8000:8000 -e USE_HTTPS=False guild-demo
# База (SQLite) заполняется при каждом запуске контейнера заново — перезапуск сбрасывает демо.
# Работающее демо само сбрасывается раз в DEMO_RESET_HOURS часов, когда нет посетителей (0 — не сбрасывать).
FROM python:3.13-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# WhiteNoise нужен только демо: на обычном сервере статику раздает Caddy.
COPY requirements.txt .
RUN pip install -r requirements.txt whitenoise==6.11.0

COPY docker/demo/entrypoint.sh docker/demo/entrypoint.sh
COPY app/ app/

# HTTPS на хостинге обеспечивает их прокси. Локально запускайте с -e USE_HTTPS=False.
ENV DEMO_MODE=True \
    USE_HTTPS=True \
    ALLOWED_HOSTS=* \
    GUNICORN_WORKERS=2 \
    DEMO_RESET_HOURS=6

RUN useradd --create-home --uid 1000 app \
    && cd app && DJANGO_SECRET_KEY=build python manage.py collectstatic --noinput \
    && chown -R app:app /app \
    && chmod +x /app/docker/demo/entrypoint.sh
USER app

WORKDIR /app/app

EXPOSE 8000

ENTRYPOINT ["/app/docker/demo/entrypoint.sh"]
# PORT задают хостинги (Render, Koyeb), по умолчанию 8000.
CMD ["sh", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${GUNICORN_WORKERS} --timeout 60 --access-logfile -"]
