"""Ограничения на создание гостевых аккаунтов, чтобы боты не раздули базу демо.

1. С одного IP — не больше GUESTS_PER_IP новых аккаунтов в час.
2. Всего — не больше MAX_GUESTS. Когда места нет, удаляются самые старые гости,
   неактивные дольше INACTIVE_MINUTES. Если таких нет, новый аккаунт не создается.
"""
import datetime

from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils import timezone

from .accounts import GUEST_GROUP

GUESTS_PER_IP = 10
IP_WINDOW_SECONDS = 3600
MAX_GUESTS = 300
INACTIVE_MINUTES = 30


def client_ip(request):
    """IP посетителя. За прокси хостинга берем последний адрес X-Forwarded-For —
    его дописывает сам прокси, а первые адреса посетитель может подставить любые."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[-1].strip()
    return request.META.get('REMOTE_ADDR', '')


def take_ip_slot(request):
    """Учитывает новый аккаунт с IP посетителя. False — лимит на этот час исчерпан."""
    key = f'demo-guests-ip:{client_ip(request)}'
    # add создает счетчик с окном в час только если его еще нет.
    cache.add(key, 0, IP_WINDOW_SECONDS)
    try:
        count = cache.incr(key)
    except ValueError:
        # Счетчик истек между add и incr — начинаем новое окно.
        cache.set(key, 1, IP_WINDOW_SECONDS)
        count = 1
    return count <= GUESTS_PER_IP


def make_room():
    """Освобождает место под новый аккаунт. False — все места заняты активными посетителями."""
    guests = User.objects.filter(groups__name=GUEST_GROUP)
    excess = guests.count() - MAX_GUESTS + 1
    if excess <= 0:
        return True
    inactive_since = timezone.now() - datetime.timedelta(minutes=INACTIVE_MINUTES)
    stale = list(guests.filter(profile__last_activity__lt=inactive_since)
                 .order_by('date_joined').values_list('pk', flat=True)[:excess])
    User.objects.filter(pk__in=stale).delete()
    return len(stale) == excess
