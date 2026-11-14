"""Учёт минут TS без начисления баллов и без доверия к входу по коду."""
from collections import Counter

from django.db import transaction
from django.utils import timezone

from core.roles import GUILD_GROUP
from teamspeak.attendance import path_matches
from teamspeak.models import TsLink
from .models import Participant, Skirmish, UnidentifiedPresence


def record_presence(clients, session_id, now=None):
    """Учитывает минуту один раз; отчёт от предыдущего замеса не попадает в новый."""
    if session_id is None:
        return 0
    now = now or timezone.now()
    with transaction.atomic():
        session = (Skirmish.objects.select_for_update()
                   .filter(pk=session_id, ended_at__isnull=True, started_at__lte=now).first())
        if not session or (session.last_report_at and session.last_report_at >= now):
            return 0
        minute = now.replace(second=0, microsecond=0)
        present = {client['uid']: client for client in clients
                   if path_matches(client.get('path') or [], [session.ts_channel], session.include_children)}
        links = list(TsLink.objects.filter(status='verified', uid__in=present,
                     user__is_active=True, user__groups__name=GUILD_GROUP).values_list('uid', 'user_id').distinct())
        counts = Counter(uid for uid, _ in links)
        users = {uid: user_id for uid, user_id in links if counts[uid] == 1}
        marks = 0
        for uid, client in present.items():
            if uid in users:
                entry, _ = Participant.objects.get_or_create(skirmish=session, user_id=users[uid])
                if entry.first_seen_at is None:
                    entry.first_seen_at = now
            else:
                entry, _ = UnidentifiedPresence.objects.get_or_create(skirmish=session, uid=uid, defaults={
                    'nickname': client.get('nickname', ''), 'first_seen_at': now,
                    'last_seen_at': now, 'last_minute': minute,
                })
                entry.nickname = client.get('nickname', '')
            # Новый неопознанный клиент создаётся с текущей минутой и нулём отметок.
            if entry.last_minute != minute or entry.minutes == 0:
                entry.minutes += 1
                entry.last_minute = minute
                marks += 1
            entry.last_seen_at = now
            entry.save()
        session.last_report_at = now
        session.save(update_fields=['last_report_at'])
        return marks
