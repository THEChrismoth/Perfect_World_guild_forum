import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings

from .models import Conversation, Message
from .services import send_message, set_block
from .test_crypto import TEST_KEY


@skipUnless(connection.vendor == 'postgresql', 'Блокировки строк проверяются на PostgreSQL.')
@override_settings(PRIVATE_MESSAGES_KEYS=(TEST_KEY,))
class MessageConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.first = User.objects.create_user('Первый')
        self.second = User.objects.create_user('Второй')
        Group.objects.get_or_create(name='Член гильдии')[0].user_set.add(self.first, self.second)

    def parallel(self, actions):
        barrier = Barrier(len(actions))

        def run(action):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return action()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            return list(pool.map(run, actions))

    def test_parallel_retry_creates_one_message(self):
        key = uuid.uuid4()
        results = self.parallel([lambda: send_message(self.first, self.second, 'Текст', key)] * 2)
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(sorted(created for message, created in results), [False, True])

    def test_opposite_sends_share_dialog_without_deadlock(self):
        self.parallel(
            [
                lambda: send_message(self.first, self.second, 'Первый', uuid.uuid4()),
                lambda: send_message(self.second, self.first, 'Второй', uuid.uuid4()),
            ]
        )
        self.assertEqual(Conversation.objects.count(), 1)
        self.assertEqual(Message.objects.count(), 2)

    def test_block_serializes_with_send(self):
        def send():
            try:
                send_message(self.first, self.second, 'Текст', uuid.uuid4())
            except PermissionDenied:
                pass

        self.parallel([send, lambda: set_block(self.second, self.first, True)])
        before = Message.objects.count()
        with self.assertRaises(PermissionDenied):
            send_message(self.first, self.second, 'После блокировки', uuid.uuid4())
        self.assertEqual(Message.objects.count(), before)
