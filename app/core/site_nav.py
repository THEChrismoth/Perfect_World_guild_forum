"""Боковое меню сайта (templates/includes/site_sidebar.html). Иконки — имена из core/templatetags/ga_admin.py."""
from django.urls import reverse

GUILD_GROUP = 'Член гильдии'


def _item(label, icon, url, module, current_module, badge=0):
    return {'label': label, 'icon': icon, 'url': url, 'badge': badge, 'current': module == current_module}


def build_site_nav(request, unread_notifications=0):
    """Группы меню с отметкой раздела, в котором сейчас находимся. Только для вошедших пользователей."""
    user = request.user
    match = getattr(request, 'resolver_match', None)
    # Раздел — приложение, чья страница сейчас открыта: forum, events, auction, reception…
    current = match.func.__module__.split('.')[0] if match else ''

    # Приём: участник гильдии голосует по заявкам, кандидат смотрит свои.
    if user.groups.filter(name=GUILD_GROUP).exists():
        reception_url = reverse('reception:application_list')
    else:
        reception_url = reverse('reception:my_applications')

    from auction.views import check_auction_access

    guild_items = [
        _item('Форум', 'message', reverse('index'), 'forum', current),
        _item('Ивенты', 'swords', reverse('events:event_index'), 'events', current),
    ]
    # Аукцион доступен не всем (видимость его раздела форума) — без доступа пункта нет, а не ошибка.
    if check_auction_access(user):
        guild_items.append(_item('Аукцион', 'gavel', reverse('auction:auction_index'), 'auction', current))
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
