from django.contrib.auth.models import Group, User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.roles import GUILD_GROUP
from skirmishes.models import Participant, Skirmish
from teamspeak.models import TsLink, TsRoom, TsTask


@override_settings(DEMO_MODE=True, SECURE_SSL_REDIRECT=False)
class TeamSpeakPreviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('Посетитель')
        self.user.groups.add(Group.objects.get_or_create(name=GUILD_GROUP)[0])
        self.client.force_login(self.user)
        self.url = reverse('demo:teamspeak')
        self.action = reverse('demo:teamspeak_action')
        self.presence = reverse('demo:skirmish_presence')

    def test_demo_features_visible_on_home_and_own_profile(self):
        for url in ['/', reverse('profile_view', args=[self.user.username]), self.url]:
            response = self.client.get(url)
            self.assertContains(response, 'Демонстрация')
            self.assertContains(response, 'TeamSpeak')
        self.assertContains(self.client.get(self.url), 'Показать привязку аккаунта')

    def test_link_and_room_are_session_only(self):
        self.client.post(self.action, {'action': 'link'})
        self.client.post(self.action, {'action': 'create_room', 'name': 'Моя комната'})
        self.assertContains(self.client.get(self.url), 'Моя комната')
        other = Client()
        other.force_login(self.user)
        self.assertNotContains(other.get(self.url), 'Моя комната')
        self.assertFalse(TsLink.objects.exists())
        self.assertFalse(TsRoom.objects.exists())
        self.assertFalse(TsTask.objects.exists())
        self.client.post(self.action, {'action': 'delete_room'})
        self.assertNotIn('demo_ts_room', self.client.session)

    def test_room_requires_demo_link_and_escapes_name(self):
        self.client.post(self.action, {'action': 'create_room', 'name': 'Комната'})
        self.assertNotIn('demo_ts_room', self.client.session)
        self.client.post(self.action, {'action': 'link'})
        self.client.post(self.action, {'action': 'create_room', 'name': '<script>bad()</script>'})
        response = self.client.get(self.url)
        self.assertNotContains(response, '<script>bad()</script>')
        self.assertContains(response, '&lt;script&gt;bad()&lt;/script&gt;')

    def test_presence_requires_link_and_only_changes_own_active_record(self):
        session = Skirmish.objects.create(title='Пример', code='1234', ts_channel='Гильдия', min_minutes=5)
        self.client.post(self.presence)
        self.assertFalse(Participant.objects.exists())
        self.client.post(self.action, {'action': 'link'})
        self.client.post(self.presence)
        self.client.post(self.presence)
        entry = Participant.objects.get()
        self.assertEqual(entry.user, self.user)
        self.assertEqual(entry.minutes, 5)
        self.assertTrue(entry.attended)
        self.assertIsNone(entry.joined_at)
        from django.utils import timezone
        session.ended_at = timezone.now()
        session.save()
        self.client.post(self.presence)
        entry.refresh_from_db()
        self.assertEqual(entry.minutes, 5)
        self.assertFalse(TsTask.objects.exists())

    def test_real_ts_routes_stay_blocked(self):
        self.client.post(reverse('teamspeak:request_access'), {'uid': 'A' * 27 + '='})
        self.assertFalse(TsTask.objects.exists())

    def test_non_demo_rejects_all_preview_endpoints(self):
        with override_settings(DEMO_MODE=False):
            self.assertEqual(self.client.get(self.url).status_code, 404)
            self.assertEqual(self.client.post(self.action, {'action': 'link'}).status_code, 404)
            self.assertEqual(self.client.post(self.presence).status_code, 404)
        self.assertNotIn('demo_ts_linked', self.client.session)

    def test_candidate_and_csrf_cannot_mutate_demo_state(self):
        self.user.groups.clear()
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.action, {'action': 'link'}).status_code, 403)
        self.assertEqual(self.client.post(self.presence).status_code, 403)
        self.user.groups.add(Group.objects.get(name=GUILD_GROUP))
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(self.action, {'action': 'link'}).status_code, 403)
