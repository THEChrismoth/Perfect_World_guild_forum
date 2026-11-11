from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Notification
from .utils import send_notification


class NotificationHtmlTests(TestCase):
    def test_message_is_escaped(self):
        user = User.objects.create_user('alice')

        notification = send_notification(user, 'Тест', 'Причина: <script>alert(1)</script>\nвторая строка', link='/events/vote/1/')

        self.assertNotIn('<script>', notification.message)
        self.assertIn('&lt;script&gt;', notification.message)
        self.assertIn('<br>вторая строка', notification.message)
        self.assertIn('href="/events/vote/1/"', notification.message)

    def test_vote_button_only_for_event_invitations(self):
        from django.contrib.auth.models import Group
        from django.utils import timezone

        from events.models import EventNotification, EventType
        from events.utils import send_event_notification

        user = User.objects.create_user('alice')
        # Уведомление со ссылкой, но не голосование (например, от бота TeamSpeak) — кнопка «Подробнее».
        other = send_notification(user, '⚠️ TeamSpeak', 'Клиент не найден', link='/profiles/alice/')
        self.assertIn('Подробнее →', other.message)
        self.assertNotIn('Проголосовать', other.message)

        # Приглашение на ивент — «Проголосовать».
        user.groups.add(Group.objects.create(name='Член гильдии'))
        event_type = EventType.objects.create(name='МТВ')
        invitation = EventNotification.objects.create(event_type=event_type, event_date=timezone.localdate(),
                                                      subject='МТВ сегодня', message='Сбор в 20:00')
        send_event_notification(invitation.id)
        self.assertIn('Проголосовать', Notification.objects.get(user=user, title='МТВ сегодня').message)

    def test_migration_fixes_old_buttons(self):
        from importlib import import_module

        from django.apps import apps

        migration = import_module('notifications.migrations.0003_fix_button_labels')
        user = User.objects.create_user('alice')
        old_html = 'Текст<br><br><a href="{}" class="btn-vote-notify">🗳️ Проголосовать</a>'
        teamspeak = Notification.objects.create(user=user, title='TS', link='/profiles/alice/',
                                                message=old_html.format('/profiles/alice/'))
        vote = Notification.objects.create(user=user, title='Ивент', link='/events/vote/1/',
                                           message=old_html.format('/events/vote/1/'))

        migration.fix_button_labels(apps, None)

        teamspeak.refresh_from_db()
        vote.refresh_from_db()
        self.assertIn('Подробнее →', teamspeak.message)
        self.assertIn('Проголосовать', vote.message)


@override_settings(SECURE_SSL_REDIRECT=False)
class NotificationViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('alice', password='pass')
        self.notification = Notification.objects.create(user=self.user, title='Тест', message='Текст')
        self.client.force_login(self.user)

    def test_external_next_is_ignored(self):
        url = reverse('notifications:mark_as_read', args=[self.notification.id])
        response = self.client.get(url, {'next': 'https://evil.example/'})

        self.assertRedirects(response, reverse('notifications:notification_list'))

    def test_internal_next_is_used(self):
        url = reverse('notifications:mark_as_read', args=[self.notification.id])
        response = self.client.get(url, {'next': '/auction/'}, follow=False)

        self.assertEqual(response.url, '/auction/')

    def test_delete_requires_post(self):
        url = reverse('notifications:delete_notification', args=[self.notification.id])

        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertTrue(Notification.objects.filter(pk=self.notification.pk).exists())

        self.client.post(url)
        self.assertFalse(Notification.objects.filter(pk=self.notification.pk).exists())

@override_settings(SECURE_SSL_REDIRECT=False)
class NotificationCardTests(TestCase):
    def test_details_link_is_a_button_outside_message(self):
        from .presentation import prepare_notifications

        user = User.objects.create_user('details-user')
        notification = send_notification(user, 'Title', 'First line\nSecond line', link='/auction/')
        prepared = prepare_notifications([notification], user)
        self.assertEqual(prepared[0].card_message, 'First line\nSecond line')
        self.client.force_login(user)
        response = self.client.get(reverse('notifications:notification_list'))
        self.assertContains(response, 'class="ui-btn ui-btn-secondary ui-btn-sm"')
        self.assertContains(response, 'aria-label="Удалить уведомление"')
        self.assertNotContains(response, 'Second lineПодробнее')

    def test_event_card_shows_schedule_and_saved_response(self):
        from datetime import time
        from django.utils import timezone
        from events.models import EventType, EventNotification, EventAttendance

        user = User.objects.create_user('card-user')
        event_type = EventType.objects.create(name='MTB')
        event = EventNotification.objects.create(
            event_type=event_type, event_date=timezone.localdate(),
            start_time=time(20), subject='Event', message='Details')
        EventAttendance.objects.create(notification=event, user=user, status='maybe', comment='Saved comment')
        send_notification(user, 'Event', 'Details', link=reverse('events:vote_view', args=[event.pk]))
        self.client.force_login(user)
        response = self.client.get(reverse('notifications:notification_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '20:00')
        self.assertContains(response, 'notice-tag')
        self.assertContains(response, 'name="comment" value="Saved comment"')
        self.assertContains(response, 'name="status" value="maybe" class="ui-btn ui-btn-secondary ui-btn-sm notice-answer is-selected"')
        self.assertContains(response, 'name="status"', count=6)
