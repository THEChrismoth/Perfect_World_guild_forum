import io
import json
import re
import smtplib
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.mail import get_connection
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import SiteSettings
from notifications.models import Notification


@override_settings(SECURE_SSL_REDIRECT=False)
class ActivityMenuTests(TestCase):
    def test_menu_item_opens_activity_page(self):
        admin = User.objects.create_superuser('admin', password='pass')
        self.client.force_login(admin)

        response = self.client.get(reverse('admin:profiles_dummymodel_changelist'))

        self.assertRedirects(response, reverse('admin:activity_management'))


def locmem_connection(*args, **kwargs):
    """Письма складываются в django.core.mail.outbox вместо отправки по SMTP."""
    return get_connection('django.core.mail.backends.locmem.EmailBackend')


def captcha_response(payload):
    response = mock.MagicMock()
    response.read.return_value = json.dumps(payload).encode()
    response.__enter__.return_value = response
    return response


@override_settings(SECURE_SSL_REDIRECT=False)
class RegistrationTests(TestCase):
    FORM = {
        'username': 'newbie',
        'email': 'newbie@example.com',
        'password1': 'Very-Strong-Pass-42',
        'password2': 'Very-Strong-Pass-42',
    }

    def configure(self, **fields):
        site = SiteSettings.load()
        for name, value in fields.items():
            setattr(site, name, value)
        site.save()

    def register(self, **extra):
        return self.client.post(reverse('register'), {**self.FORM, **extra})

    def test_without_verification_user_active_and_logged_in(self):
        response = self.register()

        self.assertRedirects(response, '/')
        user = User.objects.get(username='newbie')
        self.assertTrue(user.is_active)
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    @mock.patch('core.mail.get_mail_connection', locmem_connection)
    def test_with_verification_email_sent_and_link_activates(self):
        self.configure(email_verification=True, email_host='smtp.example.com', email_from='Гильдия <noreply@example.com>')

        response = self.register()

        self.assertRedirects(response, reverse('login'))
        user = User.objects.get(username='newbie')
        self.assertFalse(user.is_active)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['newbie@example.com'])
        self.assertEqual(mail.outbox[0].from_email, 'Гильдия <noreply@example.com>')

        link = re.search(r'https?://\S+', mail.outbox[0].body).group(0)
        self.client.get(link)
        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_mail_failure_does_not_leave_dead_account(self):
        User.objects.create_superuser('admin', password='pass')
        self.configure(email_verification=True, email_host='smtp.example.com')

        with mock.patch('profiles.views.send_site_mail', side_effect=smtplib.SMTPException('connection refused')):
            response = self.register()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Не удалось отправить письмо')
        self.assertFalse(User.objects.filter(username='newbie').exists())
        self.assertTrue(Notification.objects.filter(user__username='admin', notification_type='error').exists())

    def test_duplicate_email_rejected(self):
        User.objects.create_user('old', email='Newbie@Example.com', password='pass')

        response = self.register()

        self.assertContains(response, 'уже зарегистрирован')
        self.assertFalse(User.objects.filter(username='newbie').exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class RegistrationCaptchaTests(TestCase):
    def setUp(self):
        site = SiteSettings.load()
        site.captcha_enabled = True
        site.captcha_site_key = 'site-key-123'
        site.captcha_private_key = 'private-key-456'
        site.save()

    def register(self, **extra):
        return self.client.post(reverse('register'), {**RegistrationTests.FORM, **extra})

    def test_widget_on_page(self):
        response = self.client.get(reverse('register'))

        self.assertContains(response, 'data-sitekey="site-key-123"')
        self.assertContains(response, 'captcha.ddos-guard.net/static/api.js')
        self.assertNotContains(response, 'private-key-456')

    def test_without_token_rejected(self):
        with mock.patch('core.captcha.urllib.request.urlopen') as urlopen:
            response = self.register()

        urlopen.assert_not_called()
        self.assertContains(response, 'Пройдите проверку')
        self.assertFalse(User.objects.filter(username='newbie').exists())

    def test_valid_token_accepted_and_private_key_sent(self):
        with mock.patch('core.captcha.urllib.request.urlopen',
                        return_value=captcha_response({'success': True, 'error-codes': []})) as urlopen:
            response = self.register(**{'ddg-captcha-token': 'token-from-widget'})

        self.assertRedirects(response, '/')
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, 'https://captcha.ddos-guard.net/siteverify')
        self.assertEqual(json.loads(request.data), {'response': 'token-from-widget', 'private_key': 'private-key-456'})

    def test_expired_token_message(self):
        with mock.patch('core.captcha.urllib.request.urlopen',
                        return_value=captcha_response({'success': False, 'error-codes': ['timeout-or-duplicate']})):
            response = self.register(**{'ddg-captcha-token': 'old'})

        self.assertContains(response, 'Проверка устарела')
        self.assertFalse(User.objects.filter(username='newbie').exists())

    def test_service_down_blocks_registration(self):
        import urllib.error
        with mock.patch('core.captcha.urllib.request.urlopen', side_effect=urllib.error.URLError('timed out')):
            response = self.register(**{'ddg-captcha-token': 'token'})

        self.assertContains(response, 'временно недоступен')
        self.assertFalse(User.objects.filter(username='newbie').exists())

    def test_token_not_spent_on_invalid_form(self):
        with mock.patch('core.captcha.urllib.request.urlopen') as urlopen:
            self.register(password2='different', **{'ddg-captcha-token': 'token'})

        urlopen.assert_not_called()
