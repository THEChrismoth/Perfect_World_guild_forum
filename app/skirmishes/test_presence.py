import json
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.roles import GUILD_GROUP
from teamspeak.models import TsLink
from .models import Participant, Skirmish, UnidentifiedPresence
from .presence import record_presence


@override_settings(SECURE_SSL_REDIRECT=False, TSBOT_API_TOKEN='test-token')
class PresenceTests(TestCase):
    def setUp(self):
        self.now = timezone.now().replace(second=5, microsecond=0)
        self.session = Skirmish.objects.create(title='Сбор', code='0123', ts_channel='Гильдия / Замесы',
                                               started_at=self.now - timedelta(seconds=1), min_minutes=2)
        self.user = User.objects.create_user('Игрок')
        self.user.groups.add(Group.objects.get_or_create(name=GUILD_GROUP)[0])
        TsLink.objects.create(user=self.user, uid='verified-id', status='verified', token=TsLink.new_token())
        self.clients = [{'uid': 'verified-id', 'path': ['Гильдия', 'Замесы', 'Пати 1'], 'nickname': 'Игрок'}]

    def report(self, offset=0, clients=None):
        return record_presence(self.clients if clients is None else clients, self.session.pk,
                               self.now + timedelta(seconds=offset))

    def test_auto_attendance_without_code_and_no_duplicate_minute(self):
        self.assertEqual(self.report(), 1)
        self.assertEqual(self.report(10), 0)
        self.assertEqual(self.report(60), 1)
        entry = Participant.objects.get(skirmish=self.session, user=self.user)
        self.assertIsNone(entry.joined_at)
        self.assertEqual(entry.minutes, 2)
        self.assertTrue(entry.attended)

    def test_leaving_and_returning_accumulates_only_observed_minutes(self):
        self.report()
        self.report(60, [])
        self.report(120, [])
        self.report(180)
        self.assertEqual(Participant.objects.get(user=self.user).minutes, 2)

    def test_exact_channel_and_outside_channel(self):
        self.session.include_children = False
        self.session.save()
        self.assertEqual(self.report(), 0)
        self.assertEqual(self.report(60, [{'uid': 'verified-id', 'path': ['Гильдия', 'Замесы']}]), 1)
        self.assertEqual(self.report(120, [{'uid': 'verified-id', 'path': ['Гильдия', 'Замесы чужие']}]), 0)

    def test_pending_outsider_and_ambiguous_links_stay_unidentified(self):
        pending = User.objects.create_user('Не подтверждён')
        pending.groups.add(Group.objects.get(name=GUILD_GROUP))
        TsLink.objects.create(user=pending, uid='pending-id', status='pending', token=TsLink.new_token())
        guest = User.objects.create_user('Гость')
        TsLink.objects.create(user=guest, uid='guest-id', status='verified', token=TsLink.new_token())
        duplicate = User.objects.create_user('Дубликат')
        duplicate.groups.add(Group.objects.get(name=GUILD_GROUP))
        TsLink.objects.create(user=duplicate, uid='verified-id', status='verified', token=TsLink.new_token())
        clients = [{'uid': uid, 'path': ['Гильдия', 'Замесы'], 'nickname': uid}
                   for uid in ['pending-id', 'guest-id', 'verified-id', 'unknown-id']]
        self.assertEqual(self.report(clients=clients), 4)
        self.assertEqual(self.report(5, clients), 0)
        self.assertFalse(Participant.objects.exists())
        self.assertEqual(UnidentifiedPresence.objects.count(), 4)

    def test_closed_old_and_out_of_order_reports_ignored(self):
        self.report(60)
        self.assertEqual(self.report(0), 0)
        self.session.ended_at = self.now + timedelta(seconds=120)
        self.session.save(update_fields=['ended_at'])
        self.assertEqual(self.report(180), 0)
        new_session = Skirmish.objects.create(title='Новый', code='3210', ts_channel=self.session.ts_channel)
        self.assertEqual(self.report(240), 0)
        self.assertFalse(new_session.participants.exists())

    def test_api_tracks_skirmish_and_accepts_empty_report(self):
        headers = {'HTTP_AUTHORIZATION': 'Bearer test-token'}
        state = self.client.get(reverse('tsbot_api:state'), **headers).json()
        self.assertTrue(state['track_presence'])
        self.assertEqual(state['active_skirmish_id'], self.session.pk)
        response = self.client.post(reverse('tsbot_api:presence'), json.dumps({
            'clients': self.clients, 'skirmish_id': self.session.pk}), content_type='application/json', **headers)
        self.assertEqual(response.json()['skirmish_marks'], 1)
        self.assertEqual(response.json()['marks'], 0)
        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.last_report_at)

    def test_api_rejects_malformed_reports(self):
        for payload in [[], {'clients': [None]}, {'clients': [{'uid': 'a', 'path': [2]}]},
                        {'clients': [], 'skirmish_id': True}]:
            response = self.client.post(reverse('tsbot_api:presence'), json.dumps(payload),
                content_type='application/json', HTTP_AUTHORIZATION='Bearer test-token')
            self.assertEqual(response.status_code, 400)
