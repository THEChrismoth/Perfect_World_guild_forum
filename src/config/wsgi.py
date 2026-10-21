"""Точка входа WSGI для сайта.

Объект WSGI-приложения доступен как переменная модуля ``application``.
Подробнее: https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_wsgi_application()
