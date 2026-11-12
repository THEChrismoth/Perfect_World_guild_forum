from django.contrib.auth.models import Group, User
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import resolve, reverse

from core.roles import GUILD_GROUP
from . import views
from .models import EventType


@override_settings(SECURE_SSL_REDIRECT=False)
class CyrillicEventTypeTests(TestCase):
    def test_russian_names_get_unique_latin_slugs_and_pages_open(self):
        first = EventType.objects.create(name='МТВ')
        second = EventType.objects.create(name='МТВ')

        self.assertTrue(first.slug)
        self.assertNotEqual(first.slug, second.slug)

        member = User.objects.create_user('member', password='pass')
        member.groups.add(Group.objects.create(name=GUILD_GROUP))
        self.client.force_login(member)
        self.assertEqual(self.client.get(reverse('events:event_index')).status_code, 200)
        self.assertEqual(self.client.get(first.get_absolute_url()).status_code, 200)


@override_settings(SECURE_SSL_REDIRECT=False)
class EventAccessTests(TestCase):
    def test_only_guild_members(self):
        self.client.force_login(User.objects.create_user('outsider', password='pass'))
        for url in [reverse('events:event_index'), reverse('events:my_votes')]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)


class EventUrlTests(SimpleTestCase):
    def test_my_votes_not_taken_as_event_slug(self):
        self.assertEqual(resolve('/events/my-votes/').func, views.my_votes)

    def test_event_slug_still_works(self):
        self.assertEqual(resolve('/events/some-event/').func, views.event_detail)

@override_settings(SECURE_SSL_REDIRECT=False)
class PermanentRosterTests(TestCase):
    def setUp(self):
        from .models import Event
        self.kind = EventType.objects.create(name='Постоянный', parties_count=2, party_size=2)
        self.roster = Event.objects.get(event_type=self.kind)
        self.first, self.second = list(self.roster.parties.all())
        self.group = Group.objects.get_or_create(name=GUILD_GROUP)[0]
        self.users = [User.objects.create_user(f'roster-{number}') for number in range(3)]
        for user in self.users:
            user.groups.add(self.group)

    def test_roster_persists_when_type_changes_and_gaps_are_repaired(self):
        from .models import Event, Party
        from .services import save_party_roster
        save_party_roster(self.first, self.users[0], [self.users[1]])
        self.second.delete()
        self.kind.parties_count = 3
        self.kind.save()
        self.assertEqual(Event.objects.filter(event_type=self.kind).count(), 1)
        self.assertEqual(list(Party.objects.filter(event=self.roster).values_list('number', flat=True)), [1, 2, 3])
        self.first.refresh_from_db()
        self.assertEqual(self.first.leader_id, self.users[0].pk)
        self.assertEqual(self.first.members.get().user_id, self.users[1].pk)

    def test_rejects_duplicate_leader_overflow_and_other_party_assignment(self):
        from django.core.exceptions import ValidationError
        from .services import save_party_roster
        save_party_roster(self.first, self.users[0], [self.users[1]])
        for party, leader, members in [(self.first, self.users[0], [self.users[0]]),
                                       (self.first, self.users[0], self.users[1:]),
                                       (self.second, self.users[2], [self.users[1]])]:
            with self.subTest(party=party.pk, members=members), self.assertRaises(ValidationError):
                save_party_roster(party, leader, members)
        self.assertEqual(self.first.members.count(), 1)

    def test_edit_requires_permission_and_saves_valid_roster(self):
        from django.contrib.auth.models import Permission
        self.client.force_login(self.users[0])
        url = reverse('events:party_edit', args=[self.first.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.users[0].user_permissions.add(Permission.objects.get(codename='change_party'))
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {'leader': self.users[0].pk, 'members': [self.users[1].pk]})
        self.assertRedirects(response, self.kind.get_absolute_url())
        self.first.refresh_from_db()
        self.assertEqual(self.first.leader_id, self.users[0].pk)

    def test_type_form_does_not_discard_occupied_party_or_shrink_below_members(self):
        from .admin import EventTypeForm
        from .services import save_party_roster
        save_party_roster(self.second, self.users[0], [self.users[1]])
        values = {'name': self.kind.name, 'parties_count': 1, 'party_size': 1, 'icon': 'x',
                  'order': 0, 'min_presence_minutes': 30, 'penalty_scope': 'promised',
                  'points_present': 0, 'points_absent': 0}
        form = EventTypeForm(values, instance=self.kind)
        self.assertFalse(form.is_valid())
        self.assertIn('parties_count', form.errors)
        self.assertIn('party_size', form.errors)

@override_settings(SECURE_SSL_REDIRECT=False)
class DatedInvitationTests(TestCase):
    def setUp(self):
        from datetime import timedelta, time
        from django.utils import timezone
        from .models import EventNotification, Event
        self.kind = EventType.objects.create(name='Дата', ts_channels='Гильдия / Дата')
        self.user = User.objects.create_user('invited')
        self.user.groups.add(Group.objects.get_or_create(name=GUILD_GROUP)[0])
        self.invitation = EventNotification.objects.create(event_type=self.kind,
            event_date=timezone.localdate() + timedelta(days=1), start_time=time(20))
        self.party = Event.objects.get(event_type=self.kind).parties.get()
        self.party.leader = self.user
        self.party.save()

    def test_draft_send_is_idempotent_and_snapshots_roster(self):
        from notifications.models import Notification
        from .utils import send_event_notification
        self.assertIsNone(self.invitation.sent_at)
        self.assertEqual(send_event_notification(self.invitation.pk), 1)
        self.assertEqual(send_event_notification(self.invitation.pk), 0)
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)
        slot = self.invitation.roster_entries.get()
        self.assertEqual(slot.user_id, self.user.pk)
        self.assertTrue(slot.is_leader)
        self.party.leader = None
        self.party.save()
        self.assertTrue(self.invitation.roster_entries.get().is_leader)

    def test_draft_is_private_and_uninvited_cannot_answer(self):
        self.client.force_login(self.user)
        url = reverse('events:vote_view', args=[self.invitation.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        from .utils import send_event_notification
        send_event_notification(self.invitation.pk)
        self.assertEqual(self.client.get(url).status_code, 200)
        outsider = User.objects.create_user('not-invited')
        outsider.groups.add(Group.objects.get(name=GUILD_GROUP))
        self.client.force_login(outsider)
        self.assertEqual(self.client.post(url, {'status': 'yes'}).status_code, 404)

    def test_closed_invitation_rejects_answers(self):
        from django.utils import timezone
        from .utils import send_event_notification
        send_event_notification(self.invitation.pk)
        self.invitation.refresh_from_db()
        self.invitation.points_processed_at = timezone.now()
        self.invitation.save()
        self.client.force_login(self.user)
        response = self.client.post(reverse('events:vote_view', args=[self.invitation.pk]), {'status': 'yes'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.invitation.attendances.exists())

    def test_report_keeps_promises_separate_from_presence(self):
        from .models import EventAttendance
        from .utils import send_event_notification, get_presence_report
        from teamspeak.models import EventPresence
        send_event_notification(self.invitation.pk)
        EventAttendance.objects.create(notification=self.invitation, user=self.user, status='yes')
        self.assertFalse(get_presence_report(self.invitation)[0]['present'])
        EventPresence.objects.create(notification=self.invitation, user=self.user, minutes=30)
        self.assertTrue(get_presence_report(self.invitation)[0]['present'])

    def test_no_guild_recipients_does_not_broadcast_to_everyone(self):
        from .utils import send_event_notification
        self.user.groups.clear()
        self.assertEqual(send_event_notification(self.invitation.pk), 0)
        self.invitation.refresh_from_db()
        self.assertIsNone(self.invitation.sent_at)

    def test_date_creation_requires_permission_and_send_requires_post(self):
        from django.contrib.auth.models import Permission
        from django.utils import timezone
        self.client.force_login(self.user)
        url = reverse('events:invitation_create', args=[self.kind.slug])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.user.user_permissions.add(Permission.objects.get(codename='add_eventnotification'))
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(reverse('events:invitation_send', args=[self.invitation.pk])).status_code, 405)
        response = self.client.post(url, {'event_date': timezone.localdate().isoformat(), 'start_time': '20:00',
            'duration_minutes': 60, 'send': 'no'})
        self.assertEqual(response.status_code, 302)

    def test_duplicate_date_and_invalid_duration_return_form_errors(self):
        from .forms import InvitationForm
        data = {'event_date': self.invitation.event_date.isoformat(), 'start_time': '20:00', 'duration_minutes': 60}
        form = InvitationForm(data, event_type=self.kind)
        self.assertFalse(form.is_valid())
        self.assertIn('event_date', form.errors)
        data['duration_minutes'] = 'invalid'
        self.assertFalse(InvitationForm(data, event_type=self.kind).is_valid())

    def test_response_can_change_without_duplicates_and_comment_is_escaped(self):
        from .utils import send_event_notification
        send_event_notification(self.invitation.pk)
        self.client.force_login(self.user)
        url = reverse('events:vote_view', args=[self.invitation.pk])
        self.client.post(url, {'status': 'yes', 'comment': 'First'})
        self.client.post(url, {'status': 'maybe', 'comment': '<script>alert(1)</script>'})
        self.assertEqual(self.invitation.attendances.count(), 1)
        self.assertEqual(self.invitation.attendances.get().status, 'maybe')
        result = self.client.get(reverse('events:vote_results', args=[self.invitation.pk]))
        self.assertNotContains(result, '<script>alert(1)</script>')
        self.assertContains(result, '&lt;script&gt;')

    def test_selected_groups_are_respected(self):
        from .utils import send_event_notification
        selected = Group.objects.create(name='Invite-selected')
        self.invitation.recipient_groups.add(selected)
        self.assertEqual(send_event_notification(self.invitation.pk), 0)
        self.user.groups.add(selected)
        self.assertEqual(send_event_notification(self.invitation.pk), 1)

    def test_other_date_does_not_reuse_answers_or_presence(self):
        from datetime import timedelta
        from .models import EventNotification, EventAttendance
        from .utils import send_event_notification, get_presence_report
        from teamspeak.models import EventPresence
        send_event_notification(self.invitation.pk)
        EventAttendance.objects.create(notification=self.invitation, user=self.user, status='yes')
        EventPresence.objects.create(notification=self.invitation, user=self.user, minutes=30)
        other = EventNotification.objects.create(event_type=self.kind, event_date=self.invitation.event_date + timedelta(days=1))
        send_event_notification(other.pk)
        row = get_presence_report(other)[0]
        self.assertIsNone(row['answer'])
        self.assertFalse(row['present'])
