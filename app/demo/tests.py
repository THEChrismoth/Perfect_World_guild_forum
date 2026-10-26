from io import StringIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from auction.models import AuctionLot
from events.models import EventNotification
from reception.models import Application

from .accounts import DEMO_ROLES


def create_demo_accounts():
    for role in DEMO_ROLES.values():
        User.objects.create_user(role['username'])


@override_settings(SECURE_SSL_REDIRECT=False, DEMO_MODE=False)
class DemoModeOffTests(TestCase):
    """Без DEMO_MODE сайт работает как обычно."""

    def setUp(self):
        create_demo_accounts()

    def test_no_banner_and_register_link_shown(self):
        response = self.client.get('/')
        self.assertNotContains(response, 'demo-banner')
        self.assertContains(response, reverse('register'))

    def test_demo_login_not_found(self):
        response = self.client.post(reverse('demo:login', args=['member']))
        self.assertEqual(response.status_code, 404)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_register_open(self):
        self.assertEqual(self.client.get(reverse('register')).status_code, 200)

    def test_login_page_has_password_form(self):
        response = self.client.get(reverse('login'))
        self.assertContains(response, 'id_password')
        self.assertNotContains(response, 'demo-role-btn')

    def test_seed_refuses(self):
        with self.assertRaises(CommandError):
            call_command('demo_seed')
        self.assertTrue(User.objects.exists())


@override_settings(SECURE_SSL_REDIRECT=False, DEMO_MODE=True)
class DemoModeOnTests(TestCase):
    def setUp(self):
        create_demo_accounts()

    def test_banner_with_roles(self):
        response = self.client.get('/')
        self.assertContains(response, 'demo-banner')
        self.assertContains(response, reverse('demo:login', args=['admin']))
        self.assertNotContains(response, f'href="{reverse("register")}"')

    def test_login_page_shows_roles_instead_of_password(self):
        response = self.client.get(reverse('login'))
        self.assertContains(response, 'demo-role-btn')
        self.assertNotContains(response, 'id_password')

    def test_demo_login(self):
        response = self.client.post(reverse('demo:login', args=['member']))
        self.assertRedirects(response, '/', fetch_redirect_response=False)
        user = User.objects.get(username=DEMO_ROLES['member']['username'])
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

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
        self.client.force_login(User.objects.get(username=DEMO_ROLES['member']['username']))
        avatar = SimpleUploadedFile('a.png', b'fake', content_type='image/png')
        response = self.client.post(reverse('profile_edit'), {'avatar': avatar})
        self.assertRedirects(response, '/', fetch_redirect_response=False)


@override_settings(SECURE_SSL_REDIRECT=False, DEMO_MODE=True)
class DemoSeedTests(TestCase):
    def test_seed(self):
        User.objects.create_superuser('real_admin')
        call_command('demo_seed', stdout=StringIO())

        # База стерта, созданы демо-аккаунты без пароля.
        self.assertFalse(User.objects.filter(username='real_admin').exists())
        self.assertFalse(User.objects.filter(is_superuser=True).exists())
        for role in DEMO_ROLES.values():
            self.assertFalse(User.objects.get(username=role['username']).has_usable_password())

        admin = User.objects.get(username=DEMO_ROLES['admin']['username'])
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.has_perm('auction.change_auctionlot'))
        self.assertFalse(admin.has_perm('auth.change_user'))

        self.assertTrue(AuctionLot.objects.filter(status='active').exists())
        self.assertTrue(AuctionLot.objects.filter(status='ended').exists())
        self.assertTrue(EventNotification.objects.filter(points_processed_at__isnull=False).exists())
        self.assertTrue(Application.objects.filter(status='voting').exists())

        # Главные страницы открываются под каждой ролью.
        for role in DEMO_ROLES:
            self.client.post(reverse('demo:login', args=[role]))
            for url in ['/', '/koslist/', reverse('events:event_index'), reverse('auction:auction_index')]:
                if role == 'candidate' and url == reverse('auction:auction_index'):
                    continue
                with self.subTest(role=role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)
