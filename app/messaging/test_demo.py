from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings

from demo.guests import create_guest
from .models import Message
from .services import own_conversations
from .test_crypto import TEST_KEY


@override_settings(DEMO_MODE=True, PRIVATE_MESSAGES_KEYS=(TEST_KEY,))
class DemoMessageTests(TestCase):
    def test_seed_and_guests_have_separate_encrypted_dialogs(self):
        call_command('demo_seed', stdout=StringIO())
        self.assertTrue(Message.objects.exists())
        member = create_guest('member')
        candidate = create_guest('candidate')
        first = own_conversations(member).get()
        second = own_conversations(candidate).get()
        self.assertNotEqual(first.pk, second.pk)
        text = first.last_message.text_for(member)
        self.assertIn('пример личной переписки', text)
        self.assertNotIn('пример личной переписки', first.last_message.ciphertext)
        self.assertEqual(first.other(member), User.objects.get(username='Северянка'))
