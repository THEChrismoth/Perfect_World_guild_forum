#!/bin/sh
# Подготовка контейнера web перед запуском gunicorn.
set -e

# Вспомогательные контейнеры (scheduler) запускают команду сразу — подготовкой занимается web.
if [ -n "$SKIP_SETUP" ]; then
    exec "$@"
fi

echo "Применяю миграции..."
python manage.py migrate --noinput

echo "Собираю статику..."
python manage.py collectstatic --noinput

# Первый администратор создается автоматически, если в .env заданы
# DJANGO_SUPERUSER_USERNAME и DJANGO_SUPERUSER_PASSWORD (и нет пользователя с таким именем).
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    python manage.py shell -c "
from django.contrib.auth.models import User
import os
username = os.environ['DJANGO_SUPERUSER_USERNAME']
if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username, os.environ.get('DJANGO_SUPERUSER_EMAIL', ''), os.environ['DJANGO_SUPERUSER_PASSWORD'])
    print(f'Создан администратор {username}')
"
fi

exec "$@"
