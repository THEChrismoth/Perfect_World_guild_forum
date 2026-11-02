"""Роли на сайте.

Член гильдии — игрок в группе «Член гильдии»: ему открыты аукцион и ивенты, он голосует по заявкам.
Кто не в гильдии, видит форум и подаёт заявку на вступление.

Модератор ведет аукцион, прием заявок и ивенты, без настроек сайта, бэкапов и пользователей.
Администратор — суперпользователь, у него полная админ-панель. Модератор — игрок в группе
«Модератор»: группа создается сама при миграциях, а доступ в админ-панель (is_staff)
выдается и снимается вместе с группой.
"""
from functools import wraps

from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied

GUILD_GROUP = 'Член гильдии'


def is_guild_member(user):
    """Член гильдии; суперпользователю доступно всё, что и членам."""
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.groups.filter(name=GUILD_GROUP).exists()


def guild_member_required(view):
    """Страница только для членов гильдии (аукцион, ивенты). Вход проверяет LoginRequiredMiddleware."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not is_guild_member(request.user):
            raise PermissionDenied('Раздел доступен только членам гильдии')
        return view(request, *args, **kwargs)
    return wrapper

MODERATOR_GROUP = 'Модератор'
MODERATOR_APPS = ['auction', 'reception', 'events']
# Просмотр игроков нужен, чтобы выбирать участников отрядов в ивентах (поиск по игрокам).
MODERATOR_EXTRA_PERMISSIONS = [('auth', 'view_user')]


def moderator_permissions():
    permissions = Permission.objects.filter(content_type__app_label__in=MODERATOR_APPS)
    for app_label, codename in MODERATOR_EXTRA_PERMISSIONS:
        permissions |= Permission.objects.filter(content_type__app_label=app_label, codename=codename)
    return permissions


def ensure_moderator_group(**kwargs):
    """После миграций: группа есть и у нее права на все модели разделов модератора.

    Права только добавляются — то, что администратор выдал группе вручную, сохраняется.
    """
    group, _ = Group.objects.get_or_create(name=MODERATOR_GROUP)
    group.permissions.add(*moderator_permissions())
