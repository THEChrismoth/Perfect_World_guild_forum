"""Боковое меню сайта (templates/includes/site_sidebar.html). Иконки — имена из core/templatetags/ga_admin.py."""
from django.urls import reverse
from django.conf import settings

from .roles import is_guild_member


def _item(label, icon, url, module, current_module, badge=0):
    return {'label': label, 'icon': icon, 'url': url, 'badge': badge, 'current': module == current_module}


def online_summary():
    """Блок «Онлайн» внизу меню: кто был на сайте последние 5 минут и сколько всего игроков."""
    from django.contrib.auth.models import User
    from forum.models import get_online_users

    users = list(get_online_users().order_by('username').only('username'))
    return {'users': users, 'count': len(users), 'total': User.objects.filter(is_active=True).count()}


def build_site_nav(request, unread_notifications=0):
    """Группы меню с отметкой раздела, в котором сейчас находимся. Только для вошедших пользователей."""
    user = request.user
    match = getattr(request, 'resolver_match', None)
    # Раздел — приложение, чья страница сейчас открыта: forum, events, auction, reception…
    current = match.func.__module__.split('.')[0] if match else ''

    member = is_guild_member(user)
    guild_items = [
        _item('Главная', 'dashboard', reverse('home'), 'core', current),
        _item('Форум', 'message', reverse('index'), 'forum', current),
    ]
    # Ивенты и аукцион — только для членов гильдии: остальным пункта нет, а не ошибка доступа.
    if member:
        guild_items += [
            _item('Ивенты', 'swords', reverse('events:event_index'), 'events', current),
            _item('Замесы', 'zap', reverse('skirmishes:index'), 'skirmishes', current),
            _item('Аукцион', 'gavel', reverse('auction:auction_index'), 'auction', current),
        ]
        if settings.DEMO_MODE:
            guild_items.append(_item('TeamSpeak', 'headphones', reverse('demo:teamspeak'), 'demo', current))
    # Приём: член гильдии голосует по заявкам, остальные подают заявку и следят за своими.
    reception_url = reverse('reception:application_list' if member else 'reception:my_applications')
    guild_items += [
        _item('Приём в гильдию', 'file-text', reception_url, 'reception', current),
        _item('Кос-лист', 'skull', reverse('koslist'), 'koslist', current),
    ]

    groups = [
        {'title': '', 'items': guild_items},
        {'title': 'Личное', 'items': [
            _item('Уведомления', 'bell', reverse('notifications:notification_list'), 'notifications', current,
                  badge=unread_notifications),
        ]},
    ]
    if user.is_staff:
        groups.append({'title': 'Управление', 'items': [
            _item('Панель управления', 'dashboard', reverse('admin:index'), 'admin', current),
        ]})
    return groups
