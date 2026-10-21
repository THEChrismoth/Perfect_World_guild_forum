"""Точка входа ASGI для сайта.

Объект ASGI-приложения доступен как переменная модуля ``application``.
Подробнее: https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_asgi_application()
