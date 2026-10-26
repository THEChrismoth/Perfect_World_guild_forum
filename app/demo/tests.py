import datetime
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from auction.models import AuctionLot
from events.models import EventNotification
from notifications.models import Notification
from reception.models import Application
from teamspeak.models import GUILD_GROUP

from .accounts import DEMO_ROLES, GUEST_GROUP
from . import limits
from .guests import create_guest


@override_settings(SECURE_SSL_REDIRECT=False, DEMO_MODE=False)
class DemoModeOffTests(TestCase):
    """Без DEMO_MODE сайт работает как обычно."""

    def test_no_banner_and_register_link_shown(self):
        response = self.client.get('/')
        self.assertNotContains(response, 'demo-banner')
        self.assertContains(response, reverse('register'))

    def test_demo_login_not_found(self):
        response = self.client.post(reverse('demo:login', args=['member']))
        self.assertEqual(response.status_code, 404)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertFalse(User.objects.exists())

    def test_register_open(self):
        self.assertEqual(self.client.get(reverse('register')).status_code, 200)


    def test_login_page_has_password_form(self):
        response = self.client.get(reverse('login'))
        self.assertContains(response, 'id_password')
        self.assertNotContains(response, 'demo-role-btn')

    def test_seed_refuses(self):
        User.objects.create_user('player')
        with self.assertRaises(CommandError):
            call_command('demo_seed')


@override_settings(SECURE_SSL_REDIRECT=False, DEMO_MODE=True)
class DemoModeOnTests(TestCase):
    def setUp(self):
        # Лимит аккаунтов с IP хранится в кэше — он общий для всех тестов.
        cache.clear()

    def test_banner_with_roles(self):
        response = self.client.get('/')
        self.assertContains(response, 'demo-banner')
        self.assertContains(response, reverse('demo:login', args=['admin']))
        self.assertNotContains(response, f'href="{reverse("register")}"')

    def test_login_page_shows_roles_instead_of_password(self):
        response = self.client.get(reverse('login'))
        self.assertContains(response, 'demo-role-btn')
        self.assertNotContains(response, 'id_password')

    def login(self, role, client=None):
        client = client or self.client
        response = client.post(reverse('demo:login', args=[role]))
        self.assertRedirects(response, '/', fetch_redirect_response=False)
        return User.objects.get(pk=client.session['_auth_user_id'])

    def test_demo_login_creates_personal_account(self):
        user = self.login('member')
        self.assertTrue(user.username.startswith('Гость_'))
        self.assertFalse(user.has_usable_password())
        self.assertTrue(user.groups.filter(name=GUILD_GROUP).exists())
        self.assertTrue(user.groups.filter(name=GUEST_GROUP).exists())
        self.assertFalse(user.is_staff)

    def test_same_browser_returns_to_same_account(self):
        member = self.login('member')
        admin = self.login('admin')
        self.assertNotEqual(member, admin)
        self.assertEqual(self.login('member'), member)

    def test_other_visitor_gets_other_account(self):
        self.assertNotEqual(self.login('member'), self.login('member', client=self.client_class()))

    def test_banner_shows_current_role(self):
        self.login('admin')
        response = self.client.get('/')
        self.assertContains(response, 'demo-role-btn current')

    def test_admin_link_in_menu_only_for_admin(self):
        self.login('member')
        self.assertNotContains(self.client.get('/'), 'class="admin-link"')
        self.login('admin')
        self.assertContains(self.client.get('/'), 'class="admin-link"')

    def test_stale_cookie_creates_new_account(self):
        user = self.login('member')
        user.delete()
        self.assertTrue(self.login('member').username.startswith('Гость_'))

    def test_cookie_does_not_log_into_other_players(self):
        User.objects.create_user('Северянка', is_staff=True)
        self.login('member')
        self.client.cookies['demo_guests'] = self.client.cookies['demo_guests'].value.replace('Гость', 'Север')
        self.assertNotEqual(self.login('member').username, 'Северянка')

    def test_admin_account(self):
        admin = self.login('admin')
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.has_perm('auction.change_auctionlot'))
        self.assertFalse(admin.has_perm('auth.change_user'))

    def test_candidate_account(self):
        candidate = self.login('candidate')
        self.assertFalse(candidate.groups.filter(name=GUILD_GROUP).exists())
        self.assertTrue(candidate.profile.player_class)

    def test_demo_login_get_not_allowed(self):
        self.assertEqual(self.client.get(reverse('demo:login', args=['member'])).status_code, 405)

    def test_unknown_role(self):
        self.assertEqual(self.client.post(reverse('demo:login', args=['superuser'])).status_code, 404)

    def test_register_blocked(self):
        response = self.client.get(reverse('register'))
        self.assertRedirects(response, '/', fetch_redirect_response=False)

    def test_blocked_referer_does_not_loop(self):
        response = self.client.get(reverse('register'), HTTP_REFERER='http://testserver' + reverse('register'))
        self.assertRedirects(response, '/', fetch_redirect_response=False)

    def test_admin_service_sections_blocked(self):
        self.client.force_login(User.objects.create_superuser('root'))
        for url in ['/admin/auth/user/', '/admin/core/', '/admin/backups/', reverse('admin:password_change')]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 302)

    def test_uploads_blocked(self):
        self.client.force_login(create_guest('member'))
        avatar = SimpleUploadedFile('a.png', b'fake', content_type='image/png')
        response = self.client.post(reverse('profile_edit'), {'avatar': avatar})
        self.assertRedirects(response, '/', fetch_redirect_response=False)


@override_settings(SECURE_SSL_REDIRECT=False, DEMO_MODE=True)
class DemoSeedTests(TestCase):
    def test_seed(self):
        cache.clear()
        User.objects.create_superuser('real_admin')
        call_command('demo_seed', stdout=StringIO())

        # База стерта, под вымышленными игроками не войти.
        self.assertFalse(User.objects.filter(username='real_admin').exists())
        self.assertFalse(User.objects.filter(is_superuser=True).exists())
        self.assertFalse(any(user.has_usable_password() for user in User.objects.all()))

        self.assertTrue(AuctionLot.objects.filter(status='active').exists())
        self.assertTrue(AuctionLot.objects.filter(status='ended').exists())
        self.assertTrue(EventNotification.objects.filter(points_processed_at__isnull=False).exists())
        self.assertTrue(Application.objects.filter(status='voting').exists())

        # Гость-участник получил историю очков и приглашения на ближайшие ивенты.
        self.client.post(reverse('demo:login', args=['member']))
        guest = User.objects.get(pk=self.client.session['_auth_user_id'])
        self.assertGreater(guest.profile.activity_points, 100)
        self.assertTrue(Notification.objects.filter(user=guest, link__startswith='/events/vote/').exists())

        # Главные страницы открываются под каждой ролью.
        for role in DEMO_ROLES:
            self.client.post(reverse('demo:login', args=[role]))
            for url in ['/', '/koslist/', reverse('events:event_index'), reverse('auction:auction_index')]:
                if role == 'candidate' and url == reverse('auction:auction_index'):
                    continue
                with self.subTest(role=role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)


class AutoResetRuleTests(TestCase):
    def test_should_reset(self):
        from datetime import timedelta

        from .management.commands.demo_autoreset import should_reset

        hour = timedelta(hours=1)
        cases = [
            (timedelta(minutes=30), False, False),  # интервал не прошел
            (hour, False, True),                    # прошел, посетителей нет
            (hour, True, False),                    # прошел, но кто-то сидит — ждем
            (2 * hour, True, True),                 # двойной интервал — сбрасываем в любом случае
        ]
        for elapsed, active, expected in cases:
            with self.subTest(elapsed=elapsed, active=active):
                self.assertEqual(should_reset(elapsed, hour, active), expected)

    @override_settings(DEMO_MODE=True)
    def test_visitors_active_counts_only_guests(self):
        from datetime import timedelta

        from .management.commands.demo_autoreset import visitors_active

        User.objects.create_user('player')  # вымышленный игрок с «свежей» активностью — не посетитель
        self.assertFalse(visitors_active(timedelta(minutes=10)))
        create_guest('member')
        self.assertTrue(visitors_active(timedelta(minutes=10)))

    @override_settings(DEMO_MODE=False)
    def test_refuses_without_demo_mode(self):
        with self.assertRaises(CommandError):
            call_command('demo_autoreset')


@override_settings(SECURE_SSL_REDIRECT=False, DEMO_MODE=True)
class GuestLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    def login(self, ip='10.0.0.1'):
        """Вход новым посетителем (без cookie). Возвращает созданного пользователя или None."""
        client = self.client_class(REMOTE_ADDR=ip)
        client.post(reverse('demo:login', args=['member']))
        user_id = client.session.get('_auth_user_id')
        return User.objects.get(pk=user_id) if user_id else None

    def test_limit_per_ip(self):
        with mock.patch.object(limits, 'GUESTS_PER_IP', 2):
            self.assertIsNotNone(self.login())
            self.assertIsNotNone(self.login())
            self.assertIsNone(self.login())
            # Другой адрес — свой лимит.
            self.assertIsNotNone(self.login(ip='10.0.0.2'))
        self.assertEqual(User.objects.count(), 3)

    def test_returning_visitor_not_counted(self):
        with mock.patch.object(limits, 'GUESTS_PER_IP', 1):
            self.client.post(reverse('demo:login', args=['member']))
            for _ in range(3):
                self.client.post(reverse('demo:login', args=['member']))
        self.assertEqual(User.objects.count(), 1)

    def test_ip_behind_proxy(self):
        request = mock.Mock(META={'HTTP_X_FORWARDED_FOR': '1.1.1.1, 2.2.2.2', 'REMOTE_ADDR': '10.0.0.9'})
        self.assertEqual(limits.client_ip(request), '2.2.2.2')

    def test_full_demo_removes_oldest_inactive_guest(self):
        with mock.patch.object(limits, 'MAX_GUESTS', 2):
            old = self.login(ip='10.0.0.1')
            active = self.login(ip='10.0.0.2')
            old.profile.last_activity = timezone.now() - datetime.timedelta(hours=1)
            old.profile.save()
            new = self.login(ip='10.0.0.3')
        self.assertIsNotNone(new)
        self.assertFalse(User.objects.filter(pk=old.pk).exists())
        self.assertTrue(User.objects.filter(pk=active.pk).exists())

    def test_full_demo_with_active_guests_refuses(self):
        with mock.patch.object(limits, 'MAX_GUESTS', 2):
            self.login(ip='10.0.0.1')
            self.login(ip='10.0.0.2')
            self.assertIsNone(self.login(ip='10.0.0.3'))
        self.assertEqual(User.objects.count(), 2)
