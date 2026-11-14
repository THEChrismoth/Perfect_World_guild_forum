"""Быстрые действия администраторов и модераторов на общем дашборде."""
from django.conf import settings
from django.urls import reverse


def management_data(user):
    """Возвращает разрешённые быстрые действия для общего дашборда."""
    actions = [{'label': 'Таблица активности', 'icon': 'table', 'url': reverse('admin:activity_management')}]
    for permission, label, icon, route in [
        ('auction.add_auctionlot', 'Создать лот', 'gavel', 'admin:auction_auctionlot_add'),
        ('events.add_eventnotification', 'Пригласить на ивент', 'megaphone', 'admin:events_eventnotification_add'),
    ]:
        if user.has_perm(permission):
            actions.append({'label': label, 'icon': icon, 'url': reverse(route)})
    if any(user.has_perm(f'forum.{action}_subcategory') for action in ('view', 'change')):
        actions.append({'label': 'Разделы форума', 'icon': 'folder', 'url': reverse('admin:forum_subcategory_changelist')})
    actions.append({'label': 'Панель управления', 'icon': 'settings', 'url': reverse('admin:index')})
    if settings.DEMO_MODE:
        actions.append({'label': 'Демонстрация TeamSpeak', 'icon': 'headphones', 'url': reverse('demo:teamspeak')})

    return {'quick_actions': actions}
