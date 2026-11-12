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
