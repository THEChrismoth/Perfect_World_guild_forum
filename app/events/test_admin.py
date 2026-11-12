from datetime import timedelta

from django.contrib import admin
from django.contrib.auth.models import Group, Permission, User
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.roles import GUILD_GROUP
from .admin import EventTypeForm
from .models import Event, EventNotification, EventType


@override_settings(SECURE_SSL_REDIRECT=False)
class EventAdminTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser('events-admin', password='test')
        self.member = User.objects.create_user('events-member')
        self.member.groups.add(Group.objects.get_or_create(name=GUILD_GROUP)[0])
        self.kind = EventType.objects.create(name='Тест админки', party_size=2)
        self.party = Event.objects.get(event_type=self.kind).parties.get()
        self.client.force_login(self.admin_user)

    def type_values(self):
        return {'name': self.kind.name, 'parties_count': 1, 'party_size': 2, 'icon': 'x', 'order': 0,
                'is_active': 'on', 'min_presence_minutes': 30, 'points_present': 0, 'points_absent': 0,
                'penalty_scope': 'promised', 'roster_notes': 'Постоянные примечания'}

    def test_menu_has_only_types_and_dates_in_workflow_order(self):
        request = RequestFactory().get('/admin/')
        request.user = self.admin_user
        models = admin.site.get_app_list(request, app_label='events')[0]['models']
        self.assertEqual([item['object_name'] for item in models], ['EventType', 'EventNotification'])

    def test_type_settings_and_notes_save_without_points_requirement(self):
        values = self.type_values()
        values['ts_channels'] = 'Гильдия / Тест'
        self.assertTrue(EventTypeForm(values, instance=self.kind).is_valid())
        url = reverse('admin:events_eventtype_change', args=[self.kind.pk])
        response = self.client.get(url)
        self.assertContains(response, 'Постоянные отряды')
        self.assertContains(response, 'Посещение и очки')
        response = self.client.post(url, {**values, '_continue': '1'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Event.objects.get(event_type=self.kind).notes, 'Постоянные примечания')

    def test_roster_page_and_validated_editor(self):
        roster_url = reverse('admin:events_eventtype_roster', args=[self.kind.pk])
        self.assertContains(self.client.get(roster_url), 'Отряд 1')
        url = reverse('admin:events_party_change', args=[self.party.pk])
        response = self.client.post(url, {'leader': self.member.pk, 'members': [self.member.pk]})
        self.assertContains(response, 'Лидер не должен повторяться')
        self.party.refresh_from_db()
        self.assertIsNone(self.party.leader_id)
        response = self.client.post(url, {'leader': self.member.pk})
        self.assertRedirects(response, roster_url)
        self.party.refresh_from_db()
        self.assertEqual(self.party.leader_id, self.member.pk)

    def test_staff_without_change_permission_cannot_save_roster(self):
        viewer = User.objects.create_user('roster-viewer', is_staff=True)
        viewer.user_permissions.add(Permission.objects.get(codename='view_party'))
        self.client.force_login(viewer)
        url = reverse('admin:events_party_change', args=[self.party.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {'leader': self.member.pk}).status_code, 403)

    def test_date_form_can_save_draft_then_send_once(self):
        url = reverse('admin:events_eventnotification_add')
        self.assertContains(self.client.get(url), 'Сохранить черновик')
        values = {'event_type': self.kind.pk, 'event_date': (timezone.localdate() + timedelta(days=1)).isoformat(),
                  'start_time': '20:00', 'duration_minutes': 60, 'subject': '', 'message': ''}
        self.assertEqual(self.client.post(url, {**values, '_continue': '1'}).status_code, 302)
        date = EventNotification.objects.get(event_type=self.kind)
        self.assertIsNone(date.sent_at)
        edit = reverse('admin:events_eventnotification_change', args=[date.pk])
        self.assertContains(self.client.get(edit), 'Сохранить и отправить')
        self.assertEqual(self.client.post(edit, {**values, '_send_notification': '1'}).status_code, 302)
        date.refresh_from_db()
        self.assertIsNotNone(date.sent_at)
        response = self.client.get(edit)
        self.assertContains(response, 'Ответы и явка')
        self.assertNotContains(response, 'name="_send_notification"')
        self.assertNotContains(response, 'name="event_date"')

    def test_legacy_member_editor_cannot_bypass_roster_validation(self):
        url = reverse('admin:events_partymember_add')
        self.assertEqual(self.client.get(url).status_code, 403)
