import uuid

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import Message
from .services import send_message, unread_count
from .test_crypto import TEST_KEY


@override_settings(PRIVATE_MESSAGES_KEYS=(TEST_KEY,))
class MessageViewTests(TestCase):
    def setUp(self):
        self.first = User.objects.create_user('Первый')
        self.second = User.objects.create_user('Второй')
        self.admin = User.objects.create_superuser('Админ')
        self.candidate = User.objects.create_user('Кандидат')
        Group.objects.get_or_create(name='Член гильдии')[0].user_set.add(self.first, self.second)
        self.message = send_message(
            self.first, self.second, '<script>alert(1)</script>', uuid.uuid4()
        )[0]
        self.dialog = self.message.conversation
        self.client.force_login(self.second)

    def url(self, name):
        return reverse('messaging:' + name, args=[self.dialog.pk])

    def test_private_pages_escape_text_and_get_does_not_mark_read(self):
        for path in [reverse('messaging:inbox'), self.url('conversation')]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, '&lt;script&gt;')
            self.assertNotContains(response, '<script>alert(1)</script>')
            self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(unread_count(self.second), 1)
        self.client.force_login(self.admin)
        for name in ['conversation', 'updates', 'send', 'read', 'block']:
            response = (
                self.client.get(self.url(name))
                if name in ['conversation', 'updates']
                else self.client.post(self.url(name))
            )
            self.assertEqual(response.status_code, 404)
        self.assertNotContains(self.client.get(reverse('messaging:inbox')), '&lt;script&gt;')

    def test_send_retry_and_read_api(self):
        payload = {'body': 'Ответ', 'client_id': str(uuid.uuid4())}
        for status in [201, 200]:
            response = self.client.post(self.url('send'), payload, HTTP_ACCEPT='application/json')
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()['message']['text'], 'Ответ')
        self.assertEqual(Message.objects.count(), 2)
        response = self.client.get(self.url('updates'), {'after': self.message.pk})
        self.assertEqual(len(response.json()['messages']), 1)
        self.assertEqual(self.client.get(self.url('read')).status_code, 405)
        self.assertEqual(self.client.post(self.url('read'), {'up_to': 999999}).status_code, 400)
        response = self.client.post(
            self.url('read'), {'up_to': self.message.pk}, HTTP_ACCEPT='application/json'
        )
        self.assertEqual(response.json()['unread'], 0)

    def test_csrf_block_and_draft_survives_failure(self):
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.second)
        self.assertEqual(secure.post(self.url('send'), {'body': 'Текст'}).status_code, 403)
        response = self.client.post(self.url('send'), {'body': 'Черновик', 'client_id': 'invalid'})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'Черновик', status_code=400)
        self.client.post(self.url('block'), {'action': 'block'})
        response = self.client.post(
            self.url('send'),
            {'body': 'Текст', 'client_id': str(uuid.uuid4())},
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(self.client.get(self.url('conversation')).status_code, 200)

    def test_candidate_contacts_and_missing_key(self):
        self.client.force_login(self.candidate)
        self.assertEqual(
            self.client.get(reverse('messaging:compose', args=[self.first.pk])).status_code, 404
        )
        self.assertEqual(
            self.client.get(reverse('messaging:compose', args=[self.admin.pk])).status_code, 200
        )
        self.client.force_login(self.second)
        with override_settings(PRIVATE_MESSAGES_KEYS=('invalid',)):
            response = self.client.get(self.url('conversation'))
            self.assertContains(response, 'Сообщение недоступно')
            response = self.client.post(
                self.url('send'),
                {'body': 'Секрет', 'client_id': str(uuid.uuid4())},
                HTTP_ACCEPT='application/json',
            )
            self.assertEqual(response.status_code, 503)
            self.assertNotContains(response, 'Секрет', status_code=503)
        self.assertEqual(Message.objects.count(), 1)

    def test_history_and_updates_are_bounded_and_keep_cursor(self):
        from unittest.mock import patch

        with patch('messaging.services.PER_MINUTE', 100):
            for index in range(52):
                send_message(self.first, self.second, f'Сообщение {index}', uuid.uuid4())
        response = self.client.get(self.url('conversation'))
        self.assertEqual(len(response.context['message_rows']), 50)
        self.assertIsNotNone(response.context['older_before'])
        older = self.client.get(
            self.url('conversation'), {'before': response.context['older_before']}
        )
        self.assertEqual(len(older.context['message_rows']), 3)
        self.assertTrue(older.context['history'])
        updates = self.client.get(self.url('updates')).json()
        self.assertEqual(len(updates['messages']), 50)
        self.assertTrue(updates['more'])
        rest = self.client.get(self.url('updates'), {'after': updates['messages'][-1]['id']}).json()
        self.assertEqual(len(rest['messages']), 3)
        self.assertFalse(rest['more'])
        self.assertEqual(unread_count(self.second), 53)
