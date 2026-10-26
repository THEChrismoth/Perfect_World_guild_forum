#!/bin/sh
# Подготовка демо-сайта: чистая база с вымышленной гильдией при каждом запуске.
set -e

# Хранить в демо нечего, поэтому ключ можно создавать заново при каждом запуске.
# Общий для всех процессов gunicorn, так как задается до их запуска.
if [ -z "$DJANGO_SECRET_KEY" ]; then
    DJANGO_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(50))')
    export DJANGO_SECRET_KEY
fi

echo "Применяю миграции..."
python manage.py migrate --noinput

echo "Заполняю демо-данные..."
python manage.py demo_seed

# Сброс к исходным данным по расписанию, в фоне. DEMO_RESET_HOURS=0 — не сбрасывать.
if [ "${DEMO_RESET_HOURS:-0}" != "0" ]; then
    python manage.py demo_autoreset --hours "$DEMO_RESET_HOURS" &
fi

exec "$@"
