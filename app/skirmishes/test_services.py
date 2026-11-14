from datetime import timedelta

from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import SiteSettings
from core.roles import GUILD_GROUP
from .models import AttendanceCorrection, CodeAttempt, Participant, Skirmish
from .services import confirm_results, correct_attendance, finish_skirmish, join_by_code, start_skirmish


class ServiceTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_user('Офицер')
        self.member = User.objects.create_user('Игрок')
        group = Group.objects.get_or_create(name=GUILD_GROUP)[0]
        group.user_set.add(self.actor, self.member)
        self.actor.user_permissions.add(Permission.objects.get(codename='manage_skirmish'))
        self.outsider = User.objects.create_user('Гость')
        SiteSettings.objects.update_or_create(pk=1, defaults={'skirmish_ts_channel': 'Гильдия / Сбор'})

    def start(self):
        return start_skirmish(self.actor)[0]

    def test_start_is_idempotent_and_snapshots_settings(self):
        session, created = start_skirmish(self.actor)
        self.assertTrue(created)
        self.assertEqual(len(session.code), 4)
        self.assertTrue(session.code.isdigit())
        config = SiteSettings.load()
        config.skirmish_ts_channel = 'Другой'
        config.save()
        again, created = start_skirmish(self.actor, 'Другое имя')
        self.assertFalse(created)
        self.assertEqual(again.pk, session.pk)
        self.assertEqual(again.ts_channel, 'Гильдия / Сбор')

    def test_missing_channel_and_no_permission(self):
        SiteSettings.objects.update(skirmish_ts_channel='')
        with self.assertRaises(ValidationError):
            self.start()
        with self.assertRaises(PermissionDenied):
            start_skirmish(self.member)

    def test_code_is_not_attendance_and_repeat_keeps_join_time(self):
        session = self.start()
        first = join_by_code(self.member, session.code)
        again = join_by_code(self.member, session.code)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(first.joined_at, again.joined_at)
        self.assertFalse(first.attended)
        self.assertEqual(first.minutes, 0)
        with self.assertRaises(PermissionDenied):
            join_by_code(self.outsider, session.code)

    def test_wrong_code_is_rate_limited_and_recovers(self):
        session = self.start()
        for _ in range(10):
            with self.assertRaises(ValidationError):
                join_by_code(self.member, 'wrong')
        with self.assertRaisesMessage(ValidationError, 'Слишком много попыток'):
            join_by_code(self.member, session.code)
        CodeAttempt.objects.filter(user=self.member).update(window_started_at=timezone.now() - timedelta(minutes=2))
        self.assertIsNotNone(join_by_code(self.member, session.code))

    def test_finished_code_is_closed_and_new_start_allowed(self):
        session = self.start()
        finished = finish_skirmish(session.pk, self.actor)
        self.assertEqual(finish_skirmish(session.pk, self.actor).ended_at, finished.ended_at)
        with self.assertRaises(ValidationError):
            join_by_code(self.member, session.code)
        self.assertNotEqual(self.start().pk, session.pk)

    def test_correction_requires_reason_and_preserves_ts_minutes(self):
        session = self.start()
        entry = Participant.objects.create(skirmish=session, user=self.member, minutes=3)
        with self.assertRaises(ValidationError):
            correct_attendance(session.pk, self.actor, self.member, True, 'Вылет')
        finish_skirmish(session.pk, self.actor)
        with self.assertRaises(ValidationError):
            correct_attendance(session.pk, self.actor, self.member, True, '')
        entry = correct_attendance(session.pk, self.actor, self.member, True, 'Вылет из TS')
        self.assertTrue(entry.attended)
        self.assertEqual(entry.minutes, 3)
        correction = AttendanceCorrection.objects.get(participant=entry)
        self.assertEqual(correction.actor, self.actor)
        self.assertEqual(correction.reason, 'Вылет из TS')
        self.assertIsNone(correction.previous_value)
        entry = correct_attendance(session.pk, self.actor, self.member, None, 'Вернуть учёт TS')
        self.assertFalse(entry.attended)
        self.assertEqual(entry.corrections.count(), 2)

    def test_review_locks_results_and_is_idempotent(self):
        session = self.start()
        with self.assertRaises(ValidationError):
            confirm_results(session.pk, self.actor)
        finish_skirmish(session.pk, self.actor)
        result = confirm_results(session.pk, self.actor)
        self.assertEqual(confirm_results(session.pk, self.actor).reviewed_at, result.reviewed_at)
        with self.assertRaises(ValidationError):
            correct_attendance(session.pk, self.actor, self.member, True, 'Поздняя правка')

    def test_manager_can_add_missed_member_but_not_outsider(self):
        session = self.start()
        finish_skirmish(session.pk, self.actor)
        entry = correct_attendance(session.pk, self.actor, self.member, True, 'Был в игре, TS не работал')
        self.assertTrue(entry.attended)
        with self.assertRaises(ValidationError):
            correct_attendance(session.pk, self.actor, self.outsider, True, 'Гость')

    def test_all_management_operations_check_permissions(self):
        session = self.start()
        for operation in [lambda: finish_skirmish(session.pk, self.member),
                          lambda: confirm_results(session.pk, self.member),
                          lambda: correct_attendance(session.pk, self.member, self.member, True, 'Причина')]:
            with self.assertRaises(PermissionDenied):
                operation()
