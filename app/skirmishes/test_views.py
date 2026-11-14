from datetime import timedelta

from django.contrib.auth.models import Group, Permission, User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import SiteSettings
from core.roles import GUILD_GROUP
from .models import Participant, Skirmish, UnidentifiedPresence


@override_settings(SECURE_SSL_REDIRECT=False)
class ViewTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_user('Офицер')
        self.member = User.objects.create_user('Игрок')
        Group.objects.get_or_create(name=GUILD_GROUP)[0].user_set.add(self.actor, self.member)
        self.actor.user_permissions.add(Permission.objects.get(codename='manage_skirmish'))
        SiteSettings.objects.update_or_create(pk=1, defaults={'skirmish_ts_channel': 'Гильдия / Замесы'})
        self.client.force_login(self.actor)

    def start(self):
        self.client.post(reverse('skirmishes:start'))
        return Skirmish.objects.get(ended_at__isnull=True)

    def test_complete_flow_without_admin_staff_access(self):
        self.assertFalse(self.actor.is_staff)
        self.assertContains(self.client.get(reverse('skirmishes:index')), 'Начать замес')
        session = self.start()
        self.assertContains(self.client.get(session.get_absolute_url()), session.code)
        self.client.post(reverse('skirmishes:start'))
        self.assertEqual(Skirmish.objects.count(), 1)
        self.client.force_login(self.member)
        self.client.post(reverse('skirmishes:join'), {'code': session.code})
        self.assertTrue(Participant.objects.filter(skirmish=session, user=self.member).exists())
        self.assertNotContains(self.client.get(session.get_absolute_url()), 'Завершить замес')
        self.client.force_login(self.actor)
        finish_url = reverse('skirmishes:finish', args=[session.pk])
        self.client.get(finish_url)
        session.refresh_from_db()
        self.assertTrue(session.active)
        self.client.post(finish_url)
        self.assertContains(self.client.get(session.get_absolute_url()), 'Корректировка участия')
        self.client.post(reverse('skirmishes:correct', args=[session.pk]), {
            'user': self.member.pk, 'result': 'yes', 'reason': 'Вылет из TS'})
        self.assertTrue(Participant.objects.get(user=self.member).attended)
        self.client.post(reverse('skirmishes:confirm', args=[session.pk]))
        self.assertNotContains(self.client.get(session.get_absolute_url()), 'Корректировка участия')

    def test_member_cannot_manage_and_outsider_cannot_read(self):
        session = self.start()
        self.client.force_login(self.member)
        for route in ['start', 'finish', 'confirm', 'correct']:
            url = reverse(f'skirmishes:{route}', args=[] if route == 'start' else [session.pk])
            self.assertEqual(self.client.post(url).status_code, 403)
        outsider = User.objects.create_user('Гость')
        self.client.force_login(outsider)
        for url in [reverse('skirmishes:index'), session.get_absolute_url()]:
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertNotContains(self.client.get('/'), 'sk-widget')

    def test_unknown_uids_and_correction_reasons_are_manager_only(self):
        session = self.start()
        UnidentifiedPresence.objects.create(skirmish=session, uid='private-uid', nickname='Незнакомец',
            first_seen_at=timezone.now(), last_seen_at=timezone.now(), last_minute=timezone.now())
        self.assertContains(self.client.get(session.get_absolute_url()), 'private-uid')
        self.client.force_login(self.member)
        self.assertNotContains(self.client.get(session.get_absolute_url()), 'private-uid')

    def test_csrf_and_post_required(self):
        self.assertEqual(self.client.get(reverse('skirmishes:start')).status_code, 405)
        self.assertEqual(self.client.get(reverse('skirmishes:join')).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.actor)
        self.assertEqual(csrf_client.post(reverse('skirmishes:start')).status_code, 403)
        self.assertFalse(Skirmish.objects.exists())

    def test_home_widget_and_code_link(self):
        session = self.start()
        self.client.force_login(self.member)
        self.assertContains(self.client.get('/'), 'sk-widget')
        self.assertContains(self.client.get('/'), session.title)
        response = self.client.get(reverse('skirmishes:index'), {'code': '0012'})
        self.assertContains(response, 'value="0012"')
        self.assertFalse(Participant.objects.exists())

    def test_history_pagination_mine_and_counts(self):
        for number in range(22):
            session = Skirmish.objects.create(title=f'Сбор {number}', code='0001', ts_channel='Гильдия',
                started_at=timezone.now() - timedelta(days=number + 1), ended_at=timezone.now())
            if number == 0:
                Participant.objects.create(skirmish=session, user=self.member)
                Participant.objects.create(skirmish=session, user=self.actor)
        self.assertEqual(len(self.client.get(reverse('skirmishes:index')).context['page']), 20)
        page = self.client.get(reverse('skirmishes:index'), {'filter': 'mine'}).context['page']
        self.assertEqual(len(page), 1)
        self.assertEqual(page[0].total, 2)

    def test_missing_channel_and_invalid_correction_show_errors(self):
        SiteSettings.objects.update(skirmish_ts_channel='')
        self.assertContains(self.client.get(reverse('skirmishes:index')), 'задать TS-канал')
        response = self.client.post(reverse('skirmishes:start'), follow=True)
        self.assertContains(response, 'Сначала задайте TS-канал')
        SiteSettings.objects.update(skirmish_ts_channel='Гильдия')
        session = self.start()
        self.client.post(reverse('skirmishes:finish', args=[session.pk]))
        response = self.client.post(reverse('skirmishes:correct', args=[session.pk]), {
            'user': self.member.pk, 'result': 'yes', 'reason': ''})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(session.participants.exists())

    def test_titles_and_reasons_are_escaped(self):
        self.client.post(reverse('skirmishes:start'), {'title': '<script>alert(1)</script>'})
        session = Skirmish.objects.get()
        response = self.client.get(session.get_absolute_url())
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')
