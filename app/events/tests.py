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
