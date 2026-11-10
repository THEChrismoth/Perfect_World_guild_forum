"""Цвета оформления. Палитры — в static_src/css/accents.css (общие для сайта, админ-панели и входа).

Цвет по умолчанию задаётся в настройках сайта; в профиле пустое значение означает «как у гильдии».
Выбор цвета есть в меню пользователя и в админ-панели, и на сайте — оба сохраняют его через handle_accent_post.
"""
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

ACCENT_CHOICES = [
    ('indigo', 'Индиго'),
    ('blue', 'Синий'),
    ('teal', 'Бирюзовый'),
    ('pink', 'Розовый'),
    ('orange', 'Оранжевый'),
]
ACCENT_NAMES = dict(ACCENT_CHOICES)
DEFAULT_ACCENT = 'indigo'

# Значение формы «Цвет гильдии» в меню выбора: в профиль записывается пустая строка.
GUILD_ACCENT = 'guild'


def guild_accent():
    from .models import SiteSettings

    return SiteSettings.load().accent_color or DEFAULT_ACCENT


def _own_accent(user):
    profile = getattr(user, 'profile', None) if user.is_authenticated else None
    own = profile.accent_color if profile else ''
    return own if own in ACCENT_NAMES else ''


def user_accent(user, guild=None):
    """Цвет, которым показывать сайт пользователю: свой из профиля или цвет гильдии."""
    return _own_accent(user) or guild or guild_accent()


def accent_menu(user, guild=None):
    """Данные для меню выбора цвета: кружок «Цвет гильдии», пять цветов и что сейчас выбрано."""
    guild = guild or guild_accent()
    own = _own_accent(user)
    return {
        'accent': own or guild,
        'choice': own or GUILD_ACCENT,
        'guild': guild,
        'guild_name': ACCENT_NAMES.get(guild, '').lower(),
        'guild_value': GUILD_ACCENT,
        'choices': ACCENT_CHOICES,
    }


def handle_accent_post(request, fallback_url):
    """Сохраняет выбранный цвет в профиль. Меню шлёт запрос фоном (204, без перезагрузки),
    без JavaScript — обычной формой, тогда возвращаем на страницу, с которой её отправили."""
    from profiles.models import Profile

    color = request.POST.get('accent')
    if color != GUILD_ACCENT and color not in ACCENT_NAMES:
        return HttpResponseBadRequest('Неизвестный цвет')
    # «Цвет гильдии» хранится пустой строкой: тогда цвет меняется вместе с настройкой сайта.
    Profile.objects.update_or_create(user=request.user,
                                     defaults={'accent_color': '' if color == GUILD_ACCENT else color})
    if request.headers.get('X-Requested-With') == 'fetch':
        return HttpResponse(status=204)
    next_url = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}, require_https=request.is_secure()):
        next_url = fallback_url
    return redirect(next_url)
