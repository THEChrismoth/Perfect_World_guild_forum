from django.contrib.auth.models import User, Group
from django.utils import timezone
from django.db import transaction
from notifications.utils import VOTE_BUTTON, build_message_html
from notifications.models import Notification
from .models import EventNotification, EventRosterEntry, Party


def get_recipient_users(notification):
    """Возвращает список пользователей-получателей на основе выбранных групп.

    Аргументы:
        notification: объект EventNotification.
    """
    groups = notification.recipient_groups.all()
    
    if groups.exists():
        # Если выбраны группы — берем пользователей из этих групп.
        users = User.objects.filter(groups__in=groups, is_active=True).distinct()
    else:
        # Если группы не выбраны — берем всех членов группы "Член гильдии".
        try:
            guild_group = Group.objects.get(name='Член гильдии')
            users = guild_group.user_set.filter(is_active=True)
        except Group.DoesNotExist:
            users = User.objects.none()
    
    return users


@transaction.atomic
def send_event_notification(notification_id):
    """Отправляет уведомление выбранным группам пользователей через модуль notifications.

    Аргументы:
        notification_id: ID уведомления.
    """
    
    try:
        notification = EventNotification.objects.select_for_update(of=('self',)).select_related('event_type').get(id=notification_id)
    except EventNotification.DoesNotExist:
        return 0
    
    if notification.sent_at:
        return 0

    event_type = notification.event_type
    if (not event_type.is_active or notification.event_date < timezone.localdate()
            or (notification.ends_at and notification.ends_at <= timezone.now())):
        return 0
    event_date = notification.event_date
    event_date_str = event_date.strftime('%d.%m.%Y')
    weekday = get_weekday_name(event_date)
    
    # Получаем пользователей для отправки.
    users = list(get_recipient_users(notification))
    if not users:
        return 0
    
    # Ссылка для голосования.
    vote_url = f"/events/vote/{notification.id}/"
    
    # Формируем сообщение без текстовой ссылки (только кнопка добавится в notifications/utils.py).
    full_message = f"""{notification.message}

📅 Дата: {weekday}, {event_date_str}
🎯 Ивент: {event_type.icon} {event_type.name}"""
    
    Notification.objects.bulk_create([
        Notification(user=user, title=notification.subject,
                     message=build_message_html(full_message, vote_url, VOTE_BUTTON),
                     notification_type='warning', link=vote_url)
        for user in users
    ])
    notification.sent_to_users.set(users)
    sent_count = len(users)

    # Состав фиксируется один раз: последующее редактирование не меняет историю.
    from .models import Event
    Event.objects.select_for_update().get(event_type=event_type)
    invited_ids = {user.pk for user in users}
    entries = {}
    for party in Party.objects.filter(event__event_type=event_type).prefetch_related('members'):
        if party.leader_id in invited_ids:
            entries.setdefault(party.leader_id, (party.number, True))
        for member in party.members.all():
            if member.user_id in invited_ids:
                entries.setdefault(member.user_id, (party.number, False))
    EventRosterEntry.objects.bulk_create([
        EventRosterEntry(notification=notification, user_id=user_id, party_number=number, is_leader=leader)
        for user_id, (number, leader) in entries.items()
    ])

    # Обновляем время отправки.
    notification.sent_at = timezone.now()
    notification.save()
    
    return sent_count


def get_attendance_stats(notification_id):
    """Возвращает статистику ответов на уведомление.

    Аргументы:
        notification_id: ID уведомления.
    """
    
    try:
        notification = EventNotification.objects.get(id=notification_id)
    except EventNotification.DoesNotExist:
        return {
            'yes_count': 0,
            'no_count': 0,
            'maybe_count': 0,
            'total_count': 0,
            'yes_users': [],
            'no_users': [],
            'maybe_users': [],
            'notification': None
        }
    
    attendances = notification.attendances.select_related('user__profile')
    
    yes_users = [a for a in attendances if a.status == 'yes']
    no_users = [a for a in attendances if a.status == 'no']
    maybe_users = [a for a in attendances if a.status == 'maybe']
    
    return {
        'yes_count': len(yes_users),
        'no_count': len(no_users),
        'maybe_count': len(maybe_users),
        'total_count': attendances.count(),
        'yes_users': yes_users,
        'no_users': no_users,
        'maybe_users': maybe_users,
        'notification': notification
    }


def get_weekday_name(date_obj):
    """Возвращает русское название дня недели."""
    weekdays = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
    return weekdays[date_obj.weekday()]


def get_presence_report(notification):
    """Сопоставляет приглашение, ответ и фактическое посещение на одну дату."""
    from teamspeak.models import EventPresence
    responses = {item.user_id: item for item in notification.attendances.select_related('user')}
    presence = {item.user_id: item for item in EventPresence.objects.filter(notification=notification).select_related('user')}
    slots = {item.user_id: item for item in notification.roster_entries.all()}
    users = {user.pk: user for user in notification.sent_to_users.all()}
    for item in [*responses.values(), *presence.values()]:
        users[item.user_id] = item.user
    rows = []
    for user in sorted(users.values(), key=lambda user: user.username.casefold()):
        answer = responses.get(user.pk)
        mark = presence.get(user.pk)
        minutes = mark.minutes if mark else 0
        slot = slots.get(user.pk)
        present = bool(mark) and minutes >= notification.event_type.min_presence_minutes
        if not notification.event_type.ts_channels.strip() or not notification.start_time:
            label = 'Учёт не настроен'
        elif present:
            label = 'Присутствовал'
        elif notification.ends_at <= timezone.now():
            label = 'Недостаточно минут' if mark else 'Не отмечен в TeamSpeak'
        elif notification.starts_at <= timezone.now():
            label = 'Учёт идёт'
        else:
            label = 'Ожидается'
        rows.append({'user': user, 'answer': answer, 'minutes': minutes, 'slot': slot,
                     'present': present, 'presence_label': label})
    return rows
