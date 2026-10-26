"""Ограничения демо-сайта — все в одном месте.

При выключенном DEMO_MODE прослойка пропускает запросы без изменений.
В демо закрыто то, что ломает сайт для других посетителей или требует внешних сервисов:
регистрация, смена пароля, служебные разделы админки, TeamSpeak и загрузка файлов.
"""
from urllib.parse import urlparse

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

UPLOADS_DISABLED = 'В демо загрузка файлов отключена.'


def _blocked_prefixes():
    """(начало адреса, сообщение) для закрытых в демо разделов."""
    def admin_app(label):
        return reverse('admin:app_list', kwargs={'app_label': label})

    return [
        (reverse('register'), 'Регистрация в демо отключена — войдите одной из демо-ролей.'),
        (reverse('admin:password_change'), 'Смена пароля в демо отключена.'),
        (admin_app('auth'), 'Пользователи и группы в демо недоступны.'),
        (admin_app('core'), 'Настройки сайта в демо недоступны.'),
        (admin_app('backups'), 'Резервные копии в демо недоступны.'),
        (admin_app('teamspeak'), 'TeamSpeak в демо не подключён.'),
        ('/teamspeak/', 'TeamSpeak в демо не подключён.'),
    ]


def _blocked_message(path, blocked):
    return next((message for prefix, message in blocked if path.startswith(prefix)), None)


class DemoModeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.DEMO_MODE:
            blocked = _blocked_prefixes()
            message = _blocked_message(request.path, blocked)
            if message:
                return self._refuse(request, message, blocked)
            if request.method == 'POST' and request.FILES:
                return self._refuse(request, UPLOADS_DISABLED, blocked)
        return self.get_response(request)

    @staticmethod
    def _refuse(request, message, blocked):
        messages.warning(request, message)
        back = request.META.get('HTTP_REFERER', '')
        safe = url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()},
                                               require_https=request.is_secure())
        # Возвращаем на предыдущую страницу, но не на закрытую — иначе будет цикл.
        if not safe or _blocked_message(urlparse(back).path, blocked):
            back = '/'
        return redirect(back)
