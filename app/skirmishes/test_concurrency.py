from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth.models import Group, User
from django.db import connection, connections
from django.test import TransactionTestCase
from django.utils import timezone

from core.models import SiteSettings
from core.roles import GUILD_GROUP
from teamspeak.models import TsLink
from .models import Participant, Skirmish
from .presence import record_presence
from .services import join_by_code, start_skirmish


@skipUnless(connection.vendor == 'postgresql', 'Проверка блокировок требует PostgreSQL')
class ConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.actor = User.objects.create_superuser('Офицер')
        self.member = User.objects.create_user('Игрок')
        self.member.groups.add(Group.objects.get_or_create(name=GUILD_GROUP)[0])
        SiteSettings.objects.update_or_create(pk=1, defaults={'skirmish_ts_channel': 'Гильдия / Замесы'})

    def concurrently(self, operation):
        barrier = Barrier(2)

        def worker():
            try:
                barrier.wait(timeout=10)
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            return [future.result(timeout=30) for future in futures]

    def test_two_organizers_get_the_same_active_session(self):
        def start():
            session, created = start_skirmish(User.objects.get(pk=self.actor.pk))
            return session.pk, created

        results = self.concurrently(start)
        self.assertEqual(len({pk for pk, _ in results}), 1)
        self.assertEqual(sum(created for _, created in results), 1)
        self.assertEqual(Skirmish.objects.count(), 1)

    def test_parallel_join_creates_one_participant(self):
        session = start_skirmish(self.actor)[0]
        results = self.concurrently(lambda: join_by_code(User.objects.get(pk=self.member.pk), session.code).pk)
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(Participant.objects.count(), 1)

    def test_parallel_presence_does_not_double_minutes(self):
        session = start_skirmish(self.actor)[0]
        TsLink.objects.create(user=self.member, uid='verified', status='verified', token=TsLink.new_token())
        now = timezone.now()
        results = self.concurrently(lambda: record_presence(
            [{'uid': 'verified', 'path': ['Гильдия', 'Замесы']}], session.pk, now))
        self.assertEqual(sum(results), 1)
        self.assertEqual(Participant.objects.get(user=self.member).minutes, 1)
