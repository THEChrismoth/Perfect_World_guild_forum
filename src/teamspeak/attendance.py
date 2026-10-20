"""Очки активности за посещение ивентов по присутствию в каналах TeamSpeak.

1. Бот раз в минуту присылает, кто в каком канале (путь канала: ['Гильдия', 'МТВ / ГВГ', 'Пати 3']).
2. Для ивентов, идущих прямо сейчас, игрокам в каналах ивента (и их подканалах) добавляется минута.
3. После окончания ивента: набравшим min_presence_minutes — points_present, остальным
   по правилу penalty_scope — штраф points_absent.

Учитываются только игроки с подтверждённым TS3 ID (TsLink.verified) — иначе можно было бы
получать очки, вписав чужой ID.
"""
import datetime
import logging

from django.contrib.auth.models import Group, User
from django.db import transaction
from django.utils import timezone

from .models import GUILD_GROUP, EventPresence, TsLink

logger = logging.getLogger(__name__)
PATH_SEPARATOR = '/'


def parse_channels(text):
    """Каналы ивента из настройки типа: по одному пути на строку, например 'Гильдия / МТВ / ГВГ'.

    Имена каналов сами могут содержать «/» («МТВ / ГВГ»), поэтому путь не разбивается на части:
    сравнение идёт по склеенной строке — см. path_matches."""
    return [line.strip() for line in (text or '').splitlines() if line.strip()]


def _normalize(path_text):
    return ' / '.join(part.strip() for part in path_text.split(PATH_SEPARATOR) if part.strip())


def path_matches(client_path, channel_rules):
    """Канал клиента — один из каналов ивента или его подканал"""
    joined = _normalize(PATH_SEPARATOR.join(client_path))
    for rule in channel_rules:
        rule = _normalize(rule)
        if joined == rule or joined.startswith(rule + ' / '):
            return True
    return False


def _tracked_notifications():
    from events.models import EventNotification
    return (EventNotification.objects
            .filter(start_time__isnull=False, points_processed_at__isnull=True)
            .exclude(event_type__ts_channels='')
            .select_related('event_type'))


def active_sessions(now=None):
    now = now or timezone.now()
    today = timezone.localtime(now).date()
    # Ивент может начаться вчера и закончиться после полуночи
    candidates = _tracked_notifications().filter(event_date__gte=today - datetime.timedelta(days=1), event_date__lte=today)
    return [n for n in candidates if n.starts_at <= now < n.ends_at]


def record_presence(clients, now=None):
    """clients: [{'uid': '...', 'path': ['Гильдия', 'МТВ / ГВГ', 'Пати 1']}]. Возвращает число отметок."""
    now = now or timezone.now()
    sessions = active_sessions(now)
    if not sessions:
        return 0

    uids = {client.get('uid') for client in clients if client.get('uid')}
    users_by_uid = {link.uid: link.user_id for link in TsLink.objects.filter(status='verified', uid__in=uids)}
    minute = now.replace(second=0, microsecond=0)
    marks = 0

    for session in sessions:
        rules = parse_channels(session.event_type.ts_channels)
        present = {users_by_uid[c['uid']] for c in clients
                   if c.get('uid') in users_by_uid and path_matches(c.get('path') or [], rules)}
        for user_id in present:
            presence, _ = EventPresence.objects.get_or_create(notification=session, user_id=user_id)
            # Бот может прислать отчёт чаще раза в минуту — считаем каждую минуту один раз
            if presence.last_minute != minute:
                presence.minutes += 1
                presence.last_minute = minute
                presence.save(update_fields=['minutes', 'last_minute'])
                marks += 1
    return marks


def finalize_due(now=None):
    """Подводит итоги всех закончившихся ивентов. Вызывается при каждом обращении бота."""
    now = now or timezone.now()
    today = timezone.localtime(now).date()
    done = 0
    for notification in _tracked_notifications().filter(event_date__lte=today):
        if notification.ends_at <= now:
            if finalize(notification.pk, now):
                done += 1
    return done


def _invited_users(notification):
    users = list(notification.sent_to_users.all())
    if users:
        return users
    group = Group.objects.filter(name=GUILD_GROUP).first()
    return list(group.user_set.all()) if group else []


def finalize(notification_id, now=None):
    from auction.models import PointsTransaction
    from events.models import EventNotification
    from notifications.utils import send_notification

    now = now or timezone.now()
    with transaction.atomic():
        notification = (EventNotification.objects.select_for_update()
                         .select_related('event_type').get(pk=notification_id))
        if notification.points_processed_at:
            return False
        event_type = notification.event_type
        title = f'{event_type.icon} {event_type.name} {notification.event_date:%d.%m}'

        present_ids = set(EventPresence.objects.filter(
            notification=notification, minutes__gte=event_type.min_presence_minutes
        ).values_list('user_id', flat=True))

        statuses = dict(notification.attendances.values_list('user_id', 'status'))
        invited = _invited_users(notification)
        if event_type.penalty_scope == 'promised':
            candidates = [u for u in invited if statuses.get(u.pk) == 'yes']
            # Ответивший «Приду» мог не попасть в список рассылки (например, приглашение без рассылки)
            known = {u.pk for u in candidates}
            candidates += list(User.objects.filter(pk__in=[uid for uid, s in statuses.items()
                                                           if s == 'yes' and uid not in known]))
        elif event_type.penalty_scope == 'not_declined':
            candidates = [u for u in invited if statuses.get(u.pk) != 'no']
        else:
            candidates = invited
        absent = [u for u in candidates if u.pk not in present_ids]

        if event_type.points_present:
            for user in User.objects.filter(pk__in=present_ids).select_related('profile'):
                user.profile.add_points(event_type.points_present)
                PointsTransaction.objects.create(
                    user=user, amount=event_type.points_present, transaction_type='credit',
                    description=f'Участие в ивенте: {title}'[:255],
                )
                send_notification(user, '⭐ Очки за ивент',
                                  f'+{event_type.points_present} очков активности за участие: {title}',
                                  notification_type='success')

        if event_type.points_absent:
            for user in absent:
                profile = user.profile
                penalty = min(event_type.points_absent, profile.activity_points)
                profile.activity_points -= penalty
                profile.save()
                PointsTransaction.objects.create(
                    user=user, amount=penalty, transaction_type='debit',
                    description=f'Отсутствие на ивенте: {title}'[:255],
                )
                send_notification(user, '⚠️ Пропуск ивента',
                                  f'−{penalty} очков активности за отсутствие: {title}',
                                  notification_type='warning')

        notification.points_processed_at = now
        notification.save(update_fields=['points_processed_at'])

    logger.info('Ивент %s: участников %s, пропусков %s', notification, len(present_ids), len(absent))
    return True
