import re
import shutil
import smtplib
import tempfile
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.templatetags.static import static
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .models import SiteSettings
from .secrets import SECRET_PREFIX


@override_settings(SECURE_SSL_REDIRECT=False)
class DashboardTests(TestCase):
    def setUp(self):
        from datetime import timedelta

        from django.contrib.auth.models import Group
        from django.utils import timezone

        from auction.models import AuctionLot
        from reception.models import Application

        self.admin = User.objects.create_superuser('admin', password='pass')
        guild = Group.objects.create(name='Член гильдии')
        member = User.objects.create_user('member', password='pass')
        member.groups.add(guild)
        candidate = User.objects.create_user('candidate', password='pass')
        Application.objects.create(user=candidate, player_class='Маг', development_plans='Расти')
        AuctionLot.objects.create(name='Старый лот', initial_price=10, end_date=timezone.now() - timedelta(hours=1))

    def test_superuser_dashboard(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('admin:index'))

        self.assertEqual(response.status_code, 200)
        dashboard = response.context['dashboard']
        labels = {stat['label']: stat['value'] for stat in dashboard['stats']}
        self.assertEqual(labels['Заявки на рассмотрении'], 1)
        self.assertEqual(labels['Члены гильдии'], 1)
        alert_texts = ' '.join(alert['text'] for alert in dashboard['alerts'])
        self.assertIn('заявки', alert_texts)
        self.assertIn('ждут завершения', alert_texts)
        self.assertIn('копии выключены', alert_texts)
        self.assertIsNotNone(dashboard['backup'])
        self.assertContains(response, 'Требует внимания')
        self.assertContains(response, 'candidate')

    def test_all_dashboard_links_open(self):
        self.client.force_login(self.admin)
        dashboard = self.client.get(reverse('admin:index')).context['dashboard']

        urls = [stat['url'] for stat in dashboard['stats'] if stat['url']]
        urls += [alert['url'] for alert in dashboard['alerts'] if alert['url']]
        urls += [action['url'] for action in dashboard['actions'] if not action.get('post') and not action.get('external')]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url, follow=True)
                self.assertEqual(response.status_code, 200)

    def test_staff_without_permissions_sees_no_system_blocks(self):
        staff = User.objects.create_user('officer', password='pass', is_staff=True)
        self.client.force_login(staff)

        response = self.client.get(reverse('admin:index'))

        self.assertEqual(response.status_code, 200)
        dashboard = response.context['dashboard']
        self.assertIsNone(dashboard['backup'])
        self.assertEqual(dashboard['alerts'], [])
        self.assertNotIn('Пользователи', [stat['label'] for stat in dashboard['stats']])

    def test_site_name_in_admin_header(self):
        site = SiteSettings.load()
        site.site_name = 'Ermitage'
        site.save()
        self.client.force_login(self.admin)

        response = self.client.get(reverse('admin:index'))

        self.assertContains(response, '<span class="brand-text">Ermitage</span>', html=True)

    def test_cancel_auction_page_renders(self):
        from auction.models import AuctionLot

        lot = AuctionLot.objects.get(name='Старый лот')
        self.client.force_login(self.admin)

        response = self.client.get(reverse('admin:auction_cancel_auction', args=[lot.pk]))

        self.assertContains(response, 'Что произойдёт')
        self.assertContains(response, 'Отменить аукцион')


@override_settings(SECURE_SSL_REDIRECT=False)
class SiteSettingsAdminTests(TestCase):
    FORM = {
        'site_name': 'Гильдия', 'email_port': '587', 'email_security': 'tls',
        'email_host': '', 'email_host_user': '', 'email_host_password': '', 'email_from': '',
        'captcha_site_key': '', 'captcha_private_key': '',
    }

    def setUp(self):
        self.admin = User.objects.create_superuser('admin', email='admin@example.com', password='pass')
        self.client.force_login(self.admin)
        self.url = reverse('admin:core_sitesettings_change', args=[SiteSettings.load().pk])

    def post(self, **fields):
        return self.client.post(self.url, {**self.FORM, **fields})

    def test_secrets_encrypted_and_kept_when_left_empty(self):
        self.post(email_host='smtp.example.com', email_host_password='mail-pass', captcha_private_key='captcha-secret')
        site = SiteSettings.load()
        self.assertTrue(site.email_host_password.startswith(SECRET_PREFIX))
        self.assertNotIn('captcha-secret', site.captcha_private_key)

        response = self.client.get(self.url)
        self.assertNotContains(response, 'mail-pass')
        self.assertNotContains(response, 'captcha-secret')

        # Повторное сохранение с пустыми полями не стирает секреты
        self.post(email_host='smtp.example.com', site_name='Ermitage')
        site = SiteSettings.load()
        self.assertEqual(site.get_email_password(), 'mail-pass')
        self.assertEqual(site.get_captcha_private_key(), 'captcha-secret')
        self.assertEqual(site.site_name, 'Ermitage')

    def test_verification_requires_mail(self):
        response = self.post(email_verification='on')

        self.assertContains(response, 'Сначала настройте почту')
        self.assertFalse(SiteSettings.load().email_verification)

    def test_captcha_requires_keys(self):
        response = self.post(captcha_enabled='on')

        self.assertContains(response, 'Укажите Site key')
        self.assertContains(response, 'Укажите Private key')
        self.assertFalse(SiteSettings.load().captcha_enabled)

    def test_only_superuser(self):
        staff = User.objects.create_user('officer', password='pass', is_staff=True)
        self.client.force_login(staff)

        self.assertNotEqual(self.client.get(self.url).status_code, 200)

    def test_test_email_button(self):
        self.post(email_host='smtp.example.com', email_host_password='p')

        with mock.patch('core.admin.send_site_mail') as send:
            response = self.client.post(reverse('admin:core_send_test_email'), follow=True)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[2], ['admin@example.com'])
        self.assertContains(response, 'Тестовое письмо отправлено')

        with mock.patch('core.admin.send_site_mail', side_effect=smtplib.SMTPAuthenticationError(535, b'bad')):
            response = self.client.post(reverse('admin:core_send_test_email'), follow=True)
        self.assertContains(response, 'пароль приложения')


class HashedStaticTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.static_root = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, cls.static_root, ignore_errors=True)
        cls.overrides = override_settings(STATIC_ROOT=cls.static_root, DEBUG=False)
        cls.overrides.enable()
        cls.addClassCleanup(cls.overrides.disable)
        call_command('collectstatic', interactive=False, verbosity=0)

    def test_hash_in_file_name(self):
        self.assertRegex(static('css/style.css'), r'^/static/css/style\.[0-9a-f]{12}\.css$')

    def test_name_changes_with_content(self):
        # Имя зависит от содержимого: так браузер узнаёт о новой версии файла
        url = static('forum/css/style.css')
        other = static('css/style.css')
        self.assertNotEqual(re.search(r'\.([0-9a-f]{12})\.', url).group(1), re.search(r'\.([0-9a-f]{12})\.', other).group(1))

    def test_missing_file_does_not_break_page(self):
        self.assertEqual(static('auction_icons/not-uploaded.png'), '/static/auction_icons/not-uploaded.png')


@override_settings(SECURE_SSL_REDIRECT=False)
class SiteSettingsTests(TestCase):
    def test_default_name_shown(self):
        response = self.client.get('/')

        self.assertContains(response, '<title>Гильдия</title>', html=True)

    def test_changed_name_shown(self):
        settings = SiteSettings.load()
        settings.site_name = 'Ermitage'
        settings.save()

        response = self.client.get('/')

        self.assertContains(response, '<title>Ermitage</title>', html=True)
        self.assertContains(response, '<a href="/">Ermitage</a>', html=True)

    def test_only_one_record(self):
        SiteSettings(site_name='Первая').save()
        SiteSettings(site_name='Вторая').save()

        self.assertEqual(SiteSettings.objects.count(), 1)
        self.assertEqual(SiteSettings.load().site_name, 'Вторая')
