# Бот TeamSpeak — отдельный сервис, только стандартная библиотека Python.
FROM python:3.13-alpine

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY tsbot/ tsbot/
# Конфиг по умолчанию; в docker-compose.yml поверх него монтируется tsbot/channels.json,
# чтобы правки применялись без пересборки образа.
COPY channels.json channels.json

CMD ["python", "-m", "tsbot", "run"]
