"""Личные аккаунты посетителей демо-сайта.

По кнопке роли создается новый игрок (Гость_4821 и т.п.). Какие аккаунты уже выданы этому
браузеру, хранится в подписанной cookie: повторный вход в ту же роль возвращает в тот же аккаунт.
"""
import datetime
import json
import random

from django.contrib.auth.models import Group, Permission, User
from django.urls import reverse
from django.utils import timezone

from auction.models import PointsTransaction
from events.models import EventAttendance, EventNotification
from notifications.utils import send_notification
from teamspeak.models import GUILD_GROUP

from .accounts import ADMIN_APPS, ADMIN_GROUP, DEMO_ROLES, GUEST_GROUP

COOKIE = 'demo_guests'
COOKIE_MAX_AGE = 30 * 24 * 3600
GUEST_START_POINTS = 100
# Сколько прошедших ивентов засчитать гостю, чтобы у него была история очков.
GUEST_PAST_EVENTS = 2

MAGIC_CLASSES = {'mag', 'zhrec', 'dru', 'sham', 'mist', 'bard'}
GUEST_CLASSES = ['var', 'mag', 'luk', 'zhrec', 'obor', 'dru', 'sin', 'sham', 'strazh', 'strel']
CITIES = ['Москва', 'Санкт-Петербург', 'Новосибирск', 'Екатеринбург', 'Казань', 'Минск', 'Самара', 'Краснодар']


def fill_profile(user, player_class, rng):
    """Класс и правдоподобные характеристики персонажа."""
    magic = player_class in MAGIC_CLASSES
    profile = user.profile
    profile.player_class = player_class
    profile.city = rng.choice(CITIES)
    profile.birth_date = datetime.date(rng.randint(1985, 2005), rng.randint(1, 12), rng.randint(1, 28))
    profile.hp = rng.randint(18, 45) * 1000
    profile.mp = rng.randint(8, 25) * 1000
    profile.pa = rng.randint(150, 260)
    profile.pz = rng.randint(150, 260)
    profile.fa = 0 if magic else rng.randint(9, 24) * 1000
    profile.ma = rng.randint(9, 24) * 1000 if magic else 0
    profile.bd = rng.randint(60, 150)
    profile.bu = rng.randint(5, 30)
    profile.physical_defense = rng.randint(20, 60) * 1000
    profile.magic_defense = rng.randint(20, 60) * 1000
    profile.physical_pierce = 0 if magic else rng.randint(10, 60)
    profile.magic_pierce = rng.randint(10, 60) if magic else 0
    profile.crit_damage = rng.randint(200, 350)
    profile.crit_chance = rng.randint(5, 40)
    profile.accuracy = rng.randint(3, 15) * 1000
    profile.dodge = rng.randint(2, 10) * 1000
    profile.save()


def admin_group():
    group, created = Group.objects.get_or_create(name=ADMIN_GROUP)
    if created:
        # Просмотр игроков — для выбора участников отрядов в ивентах; сами разделы пользователей закрыты в демо.
        group.permissions.set(Permission.objects.filter(content_type__app_label__in=ADMIN_APPS)
                              | Permission.objects.filter(content_type__app_label='auth', codename='view_user'))
    return group


# ===== Cookie с выданными аккаунтами =====

def read_guests(request):
    """{роль: имя пользователя} из cookie этого браузера."""
    try:
        data = json.loads(request.get_signed_cookie(COOKIE, default='{}', salt=COOKIE))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def remember_guest(request, response, role, user):
    guests = read_guests(request)
    guests[role] = user.username
    response.set_signed_cookie(COOKIE, json.dumps(guests), salt=COOKIE, max_age=COOKIE_MAX_AGE,
                               httponly=True, samesite='Lax', secure=request.is_secure())


def find_guest(role, username):
    """Ранее выданный аккаунт роли. После сброса демо его уже нет — тогда None."""
    if not username or not username.startswith(DEMO_ROLES[role]['prefix'] + '_'):
        return None
    return User.objects.filter(username=username, is_active=True, groups__name=GUEST_GROUP).first()


def current_role(request):
    username = request.user.get_username()
    return next((role for role, name in read_guests(request).items() if name and name == username), None)


# ===== Создание =====

def create_guest(role, rng=None):
    rng = rng or random.Random()
    prefix = DEMO_ROLES[role]['prefix']
    while True:
        username = f'{prefix}_{rng.randint(1000, 9999)}'
        if not User.objects.filter(username=username).exists():
            break

    user = User.objects.create(username=username)
    # Пароля нет: войти можно только кнопкой роли.
    user.set_unusable_password()
    user.save()
    user.groups.add(Group.objects.get_or_create(name=GUEST_GROUP)[0])
    fill_profile(user, rng.choice(GUEST_CLASSES), rng)

    if role in ('member', 'admin'):
        _join_guild(user)
    if role == 'admin':
        user.is_staff = True
        user.save(update_fields=['is_staff'])
        user.groups.add(admin_group())

    send_notification(user, '👋 Добро пожаловать в демо!',
                      f'Это ваш личный аккаунт {username}: очки, ставки и голоса только ваши. '
                      'Данные демо периодически сбрасываются.',
                      notification_type='info')
    return user


def _join_guild(user):
    user.groups.add(Group.objects.get_or_create(name=GUILD_GROUP)[0])
    profile = user.profile
    profile.add_points(GUEST_START_POINTS)
    PointsTransaction.objects.create(user=user, amount=GUEST_START_POINTS, transaction_type='credit',
                                     description='Стартовые очки')

    # История: гость «был» на последних ивентах и получил за них очки.
    past = (EventNotification.objects.filter(points_processed_at__isnull=False)
            .select_related('event_type').order_by('-event_date')[:GUEST_PAST_EVENTS])
    for notification in past:
        event_type = notification.event_type
        notification.sent_to_users.add(user)
        EventAttendance.objects.create(notification=notification, user=user, status='yes')
        if event_type.points_present:
            profile.add_points(event_type.points_present)
            PointsTransaction.objects.create(
                user=user, amount=event_type.points_present, transaction_type='credit',
                description=f'Участие в ивенте: {event_type.icon} {event_type.name} {notification.event_date:%d.%m}',
            )

    # Приглашения на ближайшие ивенты — как рассылка из админ-панели.
    upcoming = EventNotification.objects.filter(event_date__gte=timezone.localdate()).order_by('event_date')
    for notification in upcoming:
        notification.sent_to_users.add(user)
        send_notification(user, notification.subject, notification.message, notification_type='warning',
                          link=reverse('events:vote_view', args=[notification.id]))
