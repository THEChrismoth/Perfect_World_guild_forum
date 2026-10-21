import datetime
import json

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from auction.models import PointsTransaction
from events.models import EventAttendance, EventNotification, EventType
from profiles.forms import ProfileForm
from . import attendance
from .models import GUILD_GROUP, EventPresence, TeamSpeakSettings, TsLink, TsRoom, TsTask

TOKEN = 'test-bot-token'
UID_A = 'A' * 27 + '='
UID_B = 'B' * 27 + '='
UID_C = 'C' * 27 + '='


def bot_headers():
    return {'HTTP_AUTHORIZATION': f'Bearer {TOKEN}'}


def make_member(username, uid=None, verified=False):
    user = User.objects.create_user(username, password='pass')
    user.groups.add(Group.objects.get_or_create(name=GUILD_GROUP)[0])
    if uid:
        user.profile.ts3_id = uid
        user.profile.save()
    if verified:
        TsLink.objects.create(user=user, uid=uid, status='verified', token=TsLink.new_token(), verified_at=timezone.now())
    return user


def bot_online():
    TeamSpeakSettings.objects.update_or_create(pk=1, defaults={'bot_last_seen': timezone.now()})


@override_settings(TSBOT_API_TOKEN=TOKEN, SECURE_SSL_REDIRECT=False)
class BotApiTests(TestCase):
    def test_token_required(self):
        self.assertEqual(self.client.get(reverse('tsbot_api:state')).status_code, 403)
        self.assertEqual(self.client.get(reverse('tsbot_api:state'), HTTP_AUTHORIZATION='Bearer wrong').status_code, 403)
        with override_settings(TSBOT_API_TOKEN=''):
            self.assertEqual(self.client.get(reverse('tsbot_api:state'), **bot_headers()).status_code, 403)

    def test_state_hands_out_tasks_once(self):
        task = TsTask.enqueue('grant_guild', uid=UID_A)

        data = self.client.get(reverse('tsbot_api:state'), **bot_headers()).json()

        self.assertEqual([t['id'] for t in data['tasks']], [task.pk])
        self.assertEqual(data['tasks'][0]['payload'], {'uid': UID_A})
        self.assertTrue(TeamSpeakSettings.load().bot_online)
        task.refresh_from_db()
        self.assertEqual(task.status, 'running')
        # Второй опрос не выдаёт ту же задачу повторно.
        self.assertEqual(self.client.get(reverse('tsbot_api:state'), **bot_headers()).json()['tasks'], [])

    def test_stale_running_task_requeued(self):
        task = TsTask.enqueue('grant_guild', uid=UID_A)
        TsTask.objects.filter(pk=task.pk).update(status='running', started_at=timezone.now() - datetime.timedelta(minutes=30))

        data = self.client.get(reverse('tsbot_api:state'), **bot_headers()).json()

        self.assertEqual([t['id'] for t in data['tasks']], [task.pk])

    def test_task_result(self):
        task = TsTask.enqueue('grant_guild', uid=UID_A)
        url = reverse('tsbot_api:task_result', args=[task.pk])

        response = self.client.post(url, json.dumps({'ok': False, 'error': 'клиент не найден'}),
                                    content_type='application/json', **bot_headers())

        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.status, 'failed')
        self.assertEqual(task.error, 'клиент не найден')

    def test_license_download(self):
        TeamSpeakSettings.objects.update_or_create(pk=1, defaults={'license_data': b'LICENSE-BYTES', 'license_name': 'licensekey.dat'})

        response = self.client.get(reverse('tsbot_api:license'), **bot_headers())

        self.assertEqual(response.content, b'LICENSE-BYTES')


@override_settings(TSBOT_API_TOKEN=TOKEN, SECURE_SSL_REDIRECT=False)
class LinkFlowTests(TestCase):
    def setUp(self):
        self.user = make_member('Аквилон', uid=UID_A)
        self.client.force_login(self.user)
        bot_online()

    def test_request_confirm_grant(self):
        self.client.post(reverse('teamspeak:request_access'))

        link = TsLink.objects.get(user=self.user)
        self.assertEqual(link.status, 'pending')
        verify = TsTask.objects.get(type='verify_link')
        self.assertEqual(verify.payload['uid'], UID_A)
        self.assertIn(reverse('teamspeak:confirm', args=[link.token]), verify.payload['url'])
        self.assertTrue(verify.payload['url'].startswith('http'))

        # Чужой аккаунт не может подтвердить ссылку.
        stranger = make_member('Чужой')
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(reverse('teamspeak:confirm', args=[link.token])).status_code, 404)

        self.client.force_login(self.user)
        self.client.get(reverse('teamspeak:confirm', args=[link.token]))
        link.refresh_from_db()
        self.assertTrue(link.verified)
        self.assertTrue(TsTask.objects.filter(type='grant_guild', payload__uid=UID_A).exists())

    def test_not_guild_member_rejected(self):
        outsider = User.objects.create_user('Гость', password='pass')
        outsider.profile.ts3_id = UID_B
        outsider.profile.save()
        self.client.force_login(outsider)

        self.client.post(reverse('teamspeak:request_access'))

        self.assertFalse(TsTask.objects.exists())

    def test_bot_offline_rejected(self):
        TeamSpeakSettings.objects.filter(pk=1).update(bot_last_seen=timezone.now() - datetime.timedelta(hours=1))

        self.client.post(reverse('teamspeak:request_access'))

        self.assertFalse(TsTask.objects.exists())

    def test_profile_card_shown_to_owner(self):
        response = self.client.get(reverse('profile_view', args=[self.user.username]))

        self.assertContains(response, 'Получить доступ в TS3')
        self.assertContains(response, 'локальный')
        self.assertContains(response, UID_A)  # Свой ID — уже в поле ввода

        other = make_member('Другой')
        self.client.force_login(other)
        response = self.client.get(reverse('profile_view', args=[self.user.username]))
        self.assertNotContains(response, 'Получить доступ в TS3')
        self.assertNotContains(response, UID_A)

    def test_entered_uid_saved_to_profile_after_confirm(self):
        self.user.profile.ts3_id = None
        self.user.profile.save()

        self.client.post(reverse('teamspeak:request_access'), {'uid': UID_C})
        link = TsLink.objects.get(user=self.user)
        self.assertEqual(TsTask.objects.get(type='verify_link').payload['uid'], UID_C)

        self.client.get(reverse('teamspeak:confirm', args=[link.token]))
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.ts3_id, UID_C)  # ID сохранился в профиле
        link.refresh_from_db()
        self.assertTrue(link.verified)  # Сохранение ID в профиль не сбросило привязку

    def test_uid_linked_to_other_account_rejected(self):
        other = make_member('Другой', uid=UID_B, verified=True)

        self.client.post(reverse('teamspeak:request_access'), {'uid': UID_B})

        self.assertFalse(TsLink.objects.filter(user=self.user).exists())
        self.assertTrue(TsLink.objects.filter(user=other, status='verified').exists())

    def test_manual_uid_validated(self):
        self.client.post(reverse('teamspeak:request_access'), {'uid': 'мой ник'})
        self.assertFalse(TsTask.objects.exists())

        self.client.post(reverse('teamspeak:request_access'), {'uid': UID_C})
        self.assertEqual(TsTask.objects.get(type='verify_link').payload['uid'], UID_C)


@override_settings(TSBOT_API_TOKEN=TOKEN, SECURE_SSL_REDIRECT=False)
class RoomTests(TestCase):
    def setUp(self):
        self.user = make_member('Аквилон', uid=UID_A, verified=True)
        self.client.force_login(self.user)
        bot_online()

    def test_create_and_delete_room(self):
        self.client.post(reverse('teamspeak:room_create'), {'name': '  Комната   Аквилона '})

        room = TsRoom.objects.get(owner=self.user)
        self.assertEqual(room.name, 'Комната Аквилона')
        task = TsTask.objects.get(type='create_room')
        self.assertEqual(task.payload, {'room_id': room.pk, 'name': 'Комната Аквилона', 'owner_uid': UID_A})

        self.client.post(reverse('tsbot_api:task_result', args=[task.pk]),
                         json.dumps({'ok': True, 'data': {'cid': 42}}), content_type='application/json', **bot_headers())
        room.refresh_from_db()
        self.assertEqual((room.status, room.channel_id), ('active', 42))

        self.client.post(reverse('teamspeak:room_delete', args=[room.pk]))
        delete_task = TsTask.objects.get(type='delete_room')
        self.assertEqual(delete_task.payload['cid'], 42)
        self.client.post(reverse('tsbot_api:task_result', args=[delete_task.pk]),
                         json.dumps({'ok': True}), content_type='application/json', **bot_headers())
        self.assertFalse(TsRoom.objects.exists())

    def test_room_limit(self):
        self.client.post(reverse('teamspeak:room_create'), {'name': 'Первая'})
        self.client.post(reverse('teamspeak:room_create'), {'name': 'Вторая'})

        self.assertEqual(TsRoom.objects.count(), 1)

    def test_unverified_cannot_create(self):
        TsLink.objects.filter(user=self.user).update(status='pending')

        self.client.post(reverse('teamspeak:room_create'), {'name': 'Комната'})

        self.assertFalse(TsRoom.objects.exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class SyncSignalTests(TestCase):
    def test_removed_from_guild_revokes(self):
        user = make_member('Аквилон', uid=UID_A, verified=True)

        user.groups.remove(Group.objects.get(name=GUILD_GROUP))

        self.assertTrue(TsTask.objects.filter(type='revoke_guild', payload__uid=UID_A).exists())

    def test_added_to_guild_grants(self):
        user = User.objects.create_user('Новичок')
        TsLink.objects.create(user=user, uid=UID_B, status='verified', token=TsLink.new_token())

        user.groups.add(Group.objects.get_or_create(name=GUILD_GROUP)[0])

        self.assertTrue(TsTask.objects.filter(type='grant_guild', payload__uid=UID_B).exists())

    def test_changed_ts3_id_revokes_old(self):
        user = make_member('Аквилон', uid=UID_A, verified=True)

        user.profile.ts3_id = UID_B
        user.profile.save()

        self.assertFalse(TsLink.objects.filter(user=user).exists())
        self.assertTrue(TsTask.objects.filter(type='revoke_guild', payload__uid=UID_A).exists())


class TsIdValidationTests(TestCase):
    def test_format(self):
        user = User.objects.create_user('x')
        base = {'timezone': 'UTC+3', **{f: 0 for f in ['hp', 'mp', 'bd', 'pa', 'fa', 'ma', 'crit_damage', 'crit_chance',
                                                       'bu', 'accuracy', 'pz', 'physical_defense', 'magic_defense',
                                                       'physical_pierce', 'magic_pierce', 'dodge']}}
        self.assertTrue(ProfileForm({**base, 'ts3_id': UID_A}, instance=user.profile).is_valid())
        form = ProfileForm({**base, 'ts3_id': 'мой ник в тс'}, instance=user.profile)
        self.assertFalse(form.is_valid())
        self.assertIn('Идентификаторы', str(form.errors['ts3_id']))


@override_settings(SECURE_SSL_REDIRECT=False)
class AttendanceTests(TestCase):
    def setUp(self):
        self.present = make_member('Пришёл', uid=UID_A, verified=True)
        self.promised = make_member('Обещал', uid=UID_B, verified=True)
        self.silent = make_member('Молчал', uid=UID_C, verified=True)
        for user in (self.present, self.promised, self.silent):
            user.profile.activity_points = 20
            user.profile.save()

        self.event_type = EventType.objects.create(
            name='МТВ', ts_channels='Гильдия / МТВ / ГВГ', points_present=10, points_absent=5, min_presence_minutes=2,
        )
        self.start = timezone.now().replace(second=0, microsecond=0) - datetime.timedelta(minutes=30)
        local = timezone.localtime(self.start)
        self.notification = EventNotification.objects.create(
            event_type=self.event_type, event_date=local.date(), start_time=local.time(), duration_minutes=60,
            subject='МТВ', message='Сбор',
        )
        self.notification.sent_to_users.set([self.present, self.promised, self.silent])
        EventAttendance.objects.create(notification=self.notification, user=self.promised, status='yes')
        EventAttendance.objects.create(notification=self.notification, user=self.present, status='yes')

    def report(self, minutes_after_start, path):
        now = self.start + datetime.timedelta(minutes=minutes_after_start)
        return attendance.record_presence([{'uid': UID_A, 'path': path}], now)

    def test_path_matching(self):
        rules = ['Гильдия / МТВ / ГВГ']
        self.assertTrue(attendance.path_matches(['Гильдия', 'МТВ / ГВГ'], rules))
        self.assertTrue(attendance.path_matches(['Гильдия', 'МТВ / ГВГ', 'Пати 3'], rules))
        self.assertFalse(attendance.path_matches(['Гильдия', 'КХ', 'Пати 3'], rules))
        self.assertFalse(attendance.path_matches(['Гостиная'], rules))

    def test_minutes_counted_once_per_minute(self):
        path = ['Гильдия', 'МТВ / ГВГ', 'Пати 2']
        self.report(5, path)
        attendance.record_presence([{'uid': UID_A, 'path': path}], self.start + datetime.timedelta(minutes=5, seconds=30))
        self.report(6, path)
        self.report(7, ['Гостиная'])  # Вышел из каналов ивента — не считается

        self.assertEqual(EventPresence.objects.get(user=self.present).minutes, 2)

    def test_no_presence_outside_event(self):
        self.assertEqual(self.report(120, ['Гильдия', 'МТВ / ГВГ']), 0)

    def finish(self):
        return attendance.finalize_due(self.start + datetime.timedelta(minutes=61))

    def test_points_and_penalty_for_promised(self):
        self.report(1, ['Гильдия', 'МТВ / ГВГ', 'Пати 1'])
        self.report(2, ['Гильдия', 'МТВ / ГВГ', 'Пати 1'])

        self.assertEqual(self.finish(), 1)

        points = {u.username: User.objects.get(pk=u.pk).profile.activity_points
                  for u in (self.present, self.promised, self.silent)}
        self.assertEqual(points, {'Пришёл': 30, 'Обещал': 15, 'Молчал': 20})
        self.assertTrue(PointsTransaction.objects.filter(user=self.present, transaction_type='credit', amount=10).exists())
        self.assertTrue(PointsTransaction.objects.filter(user=self.promised, transaction_type='debit', amount=5).exists())
        # Повторно не начисляется.
        self.assertEqual(self.finish(), 0)
        self.assertEqual(User.objects.get(pk=self.present.pk).profile.activity_points, 30)

    def test_scope_all_invited(self):
        EventAttendance.objects.create(notification=self.notification, user=self.silent, status='no')
        self.event_type.penalty_scope = 'all'
        self.event_type.save()
        self.finish()
        all_points = {u.username: User.objects.get(pk=u.pk).profile.activity_points for u in (self.promised, self.silent)}
        self.assertEqual(all_points, {'Обещал': 15, 'Молчал': 15})

    def test_scope_not_declined_skips_declined(self):
        EventAttendance.objects.create(notification=self.notification, user=self.silent, status='no')
        self.event_type.penalty_scope = 'not_declined'
        self.event_type.save()
        self.finish()
        self.assertEqual(User.objects.get(pk=self.silent.pk).profile.activity_points, 20)
        self.assertEqual(User.objects.get(pk=self.promised.pk).profile.activity_points, 15)

    def test_penalty_not_below_zero(self):
        self.promised.profile.activity_points = 2
        self.promised.profile.save()
        self.finish()
        self.assertEqual(User.objects.get(pk=self.promised.pk).profile.activity_points, 0)

    def test_presence_api(self):
        with override_settings(TSBOT_API_TOKEN=TOKEN):
            response = self.client.post(reverse('tsbot_api:presence'),
                                        json.dumps({'clients': [{'uid': UID_A, 'path': ['Гильдия', 'МТВ / ГВГ']}]}),
                                        content_type='application/json', **bot_headers())
        self.assertEqual(response.json()['marks'], 1)


@override_settings(SECURE_SSL_REDIRECT=False)
class LicenseAdminTests(TestCase):
    def test_upload_creates_install_task(self):
        admin = User.objects.create_superuser('admin', password='pass')
        self.client.force_login(admin)
        url = reverse('admin:teamspeak_teamspeaksettings_change', args=[TeamSpeakSettings.load().pk])

        self.client.post(url, {
            'server_address': 'myguild.ru', 'rooms_per_member': '1', 'max_clients': '64',
            'license_upload': SimpleUploadedFile('licensekey.dat', b'KEY-DATA'),
        })

        settings_obj = TeamSpeakSettings.load()
        self.assertEqual(bytes(settings_obj.license_data), b'KEY-DATA')
        task = TsTask.objects.get(type='install_license')
        self.assertEqual(task.payload, {'max_clients': 64})
