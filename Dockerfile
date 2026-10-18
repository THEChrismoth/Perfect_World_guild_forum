FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Зависимости ставим отдельным слоем, чтобы при правке кода они не пересобирались
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Работаем не от root. Папки static и media создаем заранее с нужным владельцем —
# Docker скопирует эти права в тома при первом запуске
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/static /app/media \
    && chown -R app:app /app \
    && chmod +x /app/docker/entrypoint.sh
USER app

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["sh", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-3} --timeout 60 --access-logfile -"]
