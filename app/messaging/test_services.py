import uuid
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings

from notifications.models import Notification
from .crypto import MessageCryptoError
from .models import ContactBlock, Conversation, Message
from .selectors import dialog_rows, dialogs_for
from .services import (
    can_contact,
    contact_queryset,
    mark_read,
    send_message,
    set_block,
    unread_count,
)
from .test_crypto import TEST_KEY


@override_settings(PRIVATE_MESSAGES_KEYS=(TEST_KEY,))
class MessageServiceTests(TestCase):
    def setUp(self):
        self.first = User.objects.create_user('Первый')
        self.second = User.objects.create_user('Второй')
        self.candidate = User.objects.create_user('Кандидат')
        self.admin = User.objects.create_superuser('Админ')
        Group.objects.get_or_create(name='Член гильдии')[0].user_set.add(self.first, self.second)

    def send(self, sender=None, recipient=None, text='Личное сообщение', client_id=None):
        return send_message(
            sender or self.first, recipient or self.second, text, client_id or uuid.uuid4()
        )[0]

    def test_pair_policy_and_contact_search(self):
        self.assertTrue(can_contact(self.first, self.second))
        self.assertTrue(can_contact(self.candidate, self.admin))
        self.assertTrue(can_contact(self.admin, self.candidate))
        self.assertFalse(can_contact(self.candidate, self.first))
        self.assertFalse(can_contact(self.first, self.first))
        self.assertEqual(list(contact_queryset(self.candidate)), [self.admin])
        with self.assertRaises(PermissionDenied):
            self.send(self.candidate, self.first)
        self.second.is_active = False
        self.second.save()
        with self.assertRaises(PermissionDenied):
            self.send()

    def test_one_dialog_and_idempotent_encrypted_send(self):
        key = uuid.uuid4()
        first, created = send_message(self.first, self.second, 'Секрет', key)
        again, created_again = send_message(self.first, self.second, 'Секрет', key)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.pk, again.pk)
        self.send(self.second, self.first)
        self.assertEqual(Conversation.objects.count(), 1)
        self.assertNotIn('Секрет', first.ciphertext)
        with self.assertRaises(ValidationError):
            send_message(self.first, self.second, 'Другой текст', key)

    def test_notification_has_no_body_and_is_not_repeated_while_unread(self):
        first = self.send(text='Секретный текст')
        self.send(text='Второй секрет')
        notices = Notification.objects.filter(user=self.second)
        self.assertEqual(notices.count(), 1)
        self.assertNotIn('Секретный текст', notices.get().message)
        last = Message.objects.last()
        mark_read(first.conversation_id, self.second, last.pk)
        self.send()
        self.assertEqual(notices.count(), 2)

    def test_read_cursors_are_monotonic_and_bound_to_conversation(self):
        first = self.send()
        second = self.send()
        self.assertEqual(unread_count(self.second), 2)
        self.assertEqual(unread_count(self.first), 0)
        mark_read(first.conversation_id, self.second, second.pk)
        mark_read(first.conversation_id, self.second, first.pk)
        self.assertEqual(unread_count(self.second), 0)
        with self.assertRaises(Conversation.DoesNotExist):
            mark_read(first.conversation_id, self.admin, first.pk)
        with self.assertRaises(ValidationError):
            mark_read(first.conversation_id, self.second, 99999)

    def test_blocking_is_bidirectional_for_send_but_keeps_history(self):
        first = self.send()
        set_block(self.second, self.first, True)
        self.assertFalse(can_contact(self.first, self.second))
        self.assertFalse(can_contact(self.second, self.first))
        for sender, recipient in [(self.first, self.second), (self.second, self.first)]:
            with self.assertRaises(PermissionDenied):
                self.send(sender, recipient)
        self.assertEqual(first.text_for(self.first), 'Личное сообщение')
        set_block(self.second, self.first, False)
        self.send()
        self.assertFalse(ContactBlock.objects.exists())

    def test_validation_rate_limit_and_missing_key(self):
        for text in ['', '   ', 'я' * 4001]:
            with self.assertRaises(ValidationError):
                self.send(text=text)
        with patch('messaging.services.PER_MINUTE', 1):
            self.send()
            with self.assertRaises(ValidationError):
                self.send()
        count = Message.objects.count()
        with override_settings(PRIVATE_MESSAGES_KEYS=('invalid-key',)):
            with self.assertRaises(MessageCryptoError):
                self.send()
        self.assertEqual(Message.objects.count(), count)

    def test_selectors_unread_and_corrupt_ciphertext(self):
        message = self.send()
        rows = dialog_rows(self.second, dialogs_for(self.second))
        self.assertEqual(rows[0]['unread'], 1)
        self.assertEqual(rows[0]['preview'], 'Личное сообщение')
        self.assertEqual(list(dialogs_for(self.admin)), [])
        Message.objects.filter(pk=message.pk).update(ciphertext='broken')
        self.assertEqual(
            dialog_rows(self.second, dialogs_for(self.second))[0]['preview'], 'Сообщение недоступно'
        )
