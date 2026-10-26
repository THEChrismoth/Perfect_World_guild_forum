"""Роль модератора: ведет аукцион, прием заявок и ивенты, без настроек сайта, бэкапов и пользователей.

Администратор — суперпользователь, у него полная админ-панель. Модератор — игрок в группе
«Модератор»: группа создается сама при миграциях, а доступ в админ-панель (is_staff)
выдается и снимается вместе с группой.
"""
from django.contrib.auth.models import Group, Permission

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
