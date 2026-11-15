import io
import tempfile
import uuid
from pathlib import Path

from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings

from .crypto import MessageCryptoError, decrypt, encrypt
from .models import Conversation, Message

TEST_KEY = Fernet.generate_key().decode()


@override_settings(PRIVATE_MESSAGES_KEYS=(TEST_KEY,))
class EncryptionTests(TestCase):
    def setUp(self):
        self.first = User.objects.create_user('first')
        self.second = User.objects.create_user('second')
        self.dialog = Conversation.objects.create(low_user=self.first, high_user=self.second)
        self.client_id = uuid.uuid4()

    def message(self):
        return Message.objects.create(conversation=self.dialog, sender=self.first, client_id=self.client_id,
            ciphertext=encrypt('Приватный текст\nВторая строка', self.dialog.pk, self.first.pk, self.client_id))

    def test_ciphertext_and_context_and_django_key_independence(self):
        message = self.message()
        self.assertNotIn('Приватный', message.ciphertext)
        self.assertNotIn('Приватный', str(message))
        self.assertEqual(message.text_for(self.second), 'Приватный текст\nВторая строка')
        with override_settings(SECRET_KEY='another-django-key'):
            self.assertEqual(message.text_for(self.first), 'Приватный текст\nВторая строка')
        outsider = User.objects.create_superuser('outsider')
        with self.assertRaises(PermissionDenied):
            message.text_for(outsider)
        for conversation, sender, client in [(99, self.first.pk, self.client_id),
                                            (self.dialog.pk, self.second.pk, self.client_id),
                                            (self.dialog.pk, self.first.pk, uuid.uuid4())]:
            with self.assertRaises(MessageCryptoError):
                decrypt(message.ciphertext, conversation, sender, client)

    def test_wrong_key_and_rotation(self):
        message = self.message()
        new_key = Fernet.generate_key().decode()
        with override_settings(PRIVATE_MESSAGES_KEYS=(new_key,)):
            with self.assertRaises(MessageCryptoError):
                message.text_for(self.first)
        with override_settings(PRIVATE_MESSAGES_KEYS=(new_key, TEST_KEY)):
            call_command('reencrypt_messages', stdout=io.StringIO())
        message.refresh_from_db()
        with override_settings(PRIVATE_MESSAGES_KEYS=(new_key,)):
            self.assertEqual(message.text_for(self.first), 'Приватный текст\nВторая строка')

    def test_key_creation_keeps_existing_key_and_refuses_to_replace_lost_one(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(
                PRIVATE_MESSAGES_KEYS=(), PRIVATE_MESSAGES_KEY_FILE=str(Path(directory) / 'messages.keys')):
            output = io.StringIO()
            call_command('init_messages_key', stdout=output)
            key = Path(directory, 'messages.keys').read_bytes()
            self.assertNotIn(key.decode().strip(), output.getvalue())
            call_command('init_messages_key', stdout=output)
            self.assertEqual(Path(directory, 'messages.keys').read_bytes(), key)
            self.message()
            Path(directory, 'messages.keys').unlink()
            with self.assertRaises(CommandError):
                call_command('init_messages_key')
