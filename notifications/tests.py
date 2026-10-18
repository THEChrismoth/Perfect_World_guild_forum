from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Notification
from .utils import send_notification


class NotificationHtmlTests(TestCase):
    def test_message_is_escaped(self):
        user = User.objects.create_user('alice')

        notification = send_notification(user, 'Тест', 'Причина: <script>alert(1)</script>\nвторая строка', link='/events/vote/1/')

        self.assertNotIn('<script>', notification.message)
        self.assertIn('&lt;script&gt;', notification.message)
        self.assertIn('<br>вторая строка', notification.message)
        self.assertIn('href="/events/vote/1/"', notification.message)


@override_settings(SECURE_SSL_REDIRECT=False)
class NotificationViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('alice', password='pass')
        self.notification = Notification.objects.create(user=self.user, title='Тест', message='Текст')
        self.client.force_login(self.user)

    def test_external_next_is_ignored(self):
        url = reverse('notifications:mark_as_read', args=[self.notification.id])
        response = self.client.get(url, {'next': 'https://evil.example/'})

        self.assertRedirects(response, reverse('notifications:notification_list'))

    def test_internal_next_is_used(self):
        url = reverse('notifications:mark_as_read', args=[self.notification.id])
        response = self.client.get(url, {'next': '/auction/'}, follow=False)

        self.assertEqual(response.url, '/auction/')

    def test_delete_requires_post(self):
        url = reverse('notifications:delete_notification', args=[self.notification.id])

        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertTrue(Notification.objects.filter(pk=self.notification.pk).exists())

        self.client.post(url)
        self.assertFalse(Notification.objects.filter(pk=self.notification.pk).exists())
