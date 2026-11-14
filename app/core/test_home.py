from datetime import time, timedelta

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from auction.models import AuctionBid, AuctionLot
from events.models import EventAttendance, EventNotification, EventRosterEntry, EventType
from forum.models import Category, SubCategory, Topic
from reception.models import Application
from .home import recent_topics
from .roles import GUILD_GROUP


@override_settings(SECURE_SSL_REDIRECT=False)
class GuildHomeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('dashboard-player')
        self.group = Group.objects.get_or_create(name=GUILD_GROUP)[0]
        self.client.force_login(self.user)

    def make_member(self):
        self.user.groups.add(self.group)

    def test_home_and_forum_have_distinct_urls_and_navigation(self):
        self.assertEqual(reverse('home'), '/')
        self.assertEqual(reverse('index'), '/forum/')
        self.assertContains(self.client.get('/'), 'Добро пожаловать')
        self.assertTemplateUsed(self.client.get('/forum/'), 'forum/forum_index.html')

    def test_candidate_sees_own_application_without_member_data(self):
        own = Application.objects.create(user=self.user, player_class='Маг', development_plans='Personal', status='pending')
        other = User.objects.create_user('secret-candidate')
        Application.objects.create(user=other, player_class='Воин', development_plans='Private-plans-text')
        response = self.client.get('/')
        self.assertEqual(response.context['my_application'], own)
        self.assertNotContains(response, 'Идут торги')
        self.assertNotContains(response, 'Private-plans-text')
        self.assertNotContains(response, 'Создать лот')

    def test_member_invitation_and_answer_are_personal_and_drafts_are_hidden(self):
        self.make_member()
        kind = EventType.objects.create(name='Visible-event')
        tomorrow = timezone.localdate() + timedelta(days=1)
        sent = EventNotification.objects.create(event_type=kind, event_date=tomorrow, start_time=time(20), sent_at=timezone.now())
        sent.sent_to_users.add(self.user)
        EventRosterEntry.objects.create(notification=sent, user=self.user, party_number=2)
        EventNotification.objects.create(event_type=kind, event_date=tomorrow+timedelta(days=1), subject='Private-draft')
        response = self.client.get('/')
        self.assertEqual(response.context['featured_event'].pk, sent.pk)
        self.assertContains(response, 'Отряд 2')
        self.assertNotContains(response, 'Private-draft')
        self.assertEqual(response.context['unanswered_events'], 1)
        EventAttendance.objects.create(notification=sent, user=self.user, status='yes')
        response = self.client.get('/')
        self.assertEqual(response.context['unanswered_events'], 0)
        self.assertEqual(response.context['upcoming'][0].my_answer, 'yes')
        self.assertContains(response, 'notice-answer is-selected')

    def test_feed_checks_parent_and_child_permissions_before_limiting(self):
        hidden = Group.objects.create(name='Private officers')
        category = Category.objects.create(title='Private category', slug='hidden-cat')
        category.view_groups.add(hidden)
        section = SubCategory.objects.create(category=category, title='Open child', slug='open-child')
        Topic.objects.create(title='Secret parent topic', author=self.user, subcategory=section)
        public = Category.objects.create(title='Public', slug='public-cat')
        child = SubCategory.objects.create(category=public, title='Private child', slug='private-child')
        child.view_groups.add(hidden)
        Topic.objects.create(title='Secret child topic', author=self.user, subcategory=child)
        visible = SubCategory.objects.create(category=public, title='Chat', slug='chat-home')
        Topic.objects.create(title='Visible discussion', author=self.user, subcategory=visible)
        response = self.client.get('/')
        self.assertContains(response, 'Visible discussion')
        self.assertNotContains(response, 'Secret parent topic')
        self.assertNotContains(response, 'Secret child topic')

    def test_feed_query_count_does_not_grow_per_section(self):
        category = Category.objects.create(title='Public', slug='public-queries')
        for number in range(12):
            section = SubCategory.objects.create(category=category, title=f'Section {number}', slug=f'home-section-{number}')
            Topic.objects.create(title=f'Topic {number}', author=self.user, subcategory=section)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as queries:
            topics = list(recent_topics(User.objects.get(pk=self.user.pk)))
        self.assertEqual(len(topics), 6)
        self.assertLessEqual(len(queries), 6)

    def test_live_lots_exclude_expired_and_future_and_show_outbid(self):
        self.make_member()
        now = timezone.now()
        lot = AuctionLot.objects.create(name='Active-lot', initial_price=10, end_date=now+timedelta(days=1))
        AuctionLot.objects.create(name='Expired-secret', initial_price=10, end_date=now-timedelta(days=1))
        AuctionLot.objects.create(name='Future-secret', initial_price=10, start_date=now+timedelta(days=1), end_date=now+timedelta(days=2))
        other = User.objects.create_user('other-bidder')
        AuctionBid.objects.create(lot=lot, bidder=self.user, bid_amount=10)
        AuctionBid.objects.create(lot=lot, bidder=other, bid_amount=20, is_frozen=True)
        response = self.client.get('/')
        self.assertEqual(response.context['lots_total'], 1)
        self.assertEqual(response.context['outbid_count'], 1)
        self.assertNotContains(response, 'Expired-secret')
        self.assertNotContains(response, 'Future-secret')

    def test_admin_gets_management_actions_but_member_does_not(self):
        self.make_member()
        self.assertNotContains(self.client.get('/'), 'Создать лот')
        self.user.is_staff = True
        self.user.save()
        self.user.user_permissions.add(Permission.objects.get(codename='add_auctionlot'))
        self.assertContains(self.client.get('/'), 'Создать лот')
        self.assertNotContains(self.client.get('/'), 'Создать ивент')

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_staff_home_is_compact_and_actions_follow_permissions(self):
        self.make_member()
        self.user.is_staff = True
        self.user.save()
        self.user.user_permissions.add(Permission.objects.get(codename='add_auctionlot'))
        response = self.client.get('/')
        self.assertTemplateUsed(response, 'core/home_dashboard.html')
        self.assertContains(response, 'Быстрые действия')
        self.assertContains(response, 'Таблица активности')
        self.assertContains(response, 'Создать лот')
        self.assertNotContains(response, 'Пригласить на ивент')
        self.assertNotContains(response, 'Разделы форума')
        self.assertNotContains(response, 'Начать замес')
        self.assertNotContains(response, 'Последние обсуждения')
        self.assertNotContains(response, 'Последние операции')
        self.assertContains(response, 'hd-summary-grid')
        self.assertEqual(response.context['lots'], [])
        self.assertEqual(response.context['topics'], [])

    def test_manager_sees_sent_dates_without_being_a_recipient_but_not_drafts(self):
        self.make_member()
        self.user.is_staff = True
        self.user.save()
        self.user.user_permissions.add(Permission.objects.get(codename='view_eventnotification'))
        tomorrow = timezone.localdate() + timedelta(days=1)
        draft_kind = EventType.objects.create(name='Draft-only-event')
        EventNotification.objects.create(event_type=draft_kind, event_date=tomorrow)
        sent_kind = EventType.objects.create(name='Guild-event')
        session = EventNotification.objects.create(event_type=sent_kind, event_date=tomorrow,
                                                   start_time=time(20), sent_at=timezone.now())
        response = self.client.get('/')
        self.assertEqual(response.context['upcoming'][0], session)
        self.assertContains(response, 'Guild-event')
        self.assertNotContains(response, 'Draft-only-event')

    def test_restricted_staff_gets_no_private_management_data(self):
        self.make_member()
        self.user.is_staff = True
        self.user.save()
        kind = EventType.objects.create(name='Uninvited-event')
        EventNotification.objects.create(event_type=kind, event_date=timezone.localdate() + timedelta(days=1),
                                         sent_at=timezone.now())
        candidate = User.objects.create_user('restricted-candidate')
        Application.objects.create(user=candidate, player_class='Маг', development_plans='Private')
        response = self.client.get('/')
        self.assertEqual(response.context['upcoming'], [])
        self.assertNotContains(response, 'Новые заявки в гильдию')
        self.assertNotContains(response, 'Uninvited-event')

    def test_superuser_has_shared_overview_and_skirmish_controls(self):
        admin = User.objects.create_superuser('dashboard-admin')
        self.client.force_login(admin)
        response = self.client.get('/')
        self.assertContains(response, 'hd-summary-grid')
        self.assertContains(response, 'Предстоящие ивенты')
        self.assertContains(response, f'action="{reverse("skirmishes:start")}"')
        self.assertContains(response, 'Пригласить на ивент')
        self.assertContains(response, 'Разделы форума')
        from skirmishes.models import Skirmish
        active = Skirmish.objects.create(title='Active-skirmish', code='0123', ts_channel='Гильдия')
        response = self.client.get('/')
        self.assertContains(response, 'Active-skirmish')
        self.assertContains(response, active.get_absolute_url())
        self.assertNotContains(response, f'action="{reverse("skirmishes:start")}"')

    def test_member_has_shared_compact_overview_without_management_actions(self):
        self.make_member()
        response = self.client.get('/')
        self.assertTemplateUsed(response, 'core/home_dashboard.html')
        self.assertContains(response, 'hd-summary-grid')
        self.assertNotContains(response, 'Последние обсуждения')
        self.assertNotContains(response, 'Быстрые действия')

    def test_upcoming_total_includes_dates_beyond_two_cards(self):
        self.make_member()
        kind = EventType.objects.create(name='Three-dates')
        for offset in [1, 2, 3]:
            event = EventNotification.objects.create(event_type=kind,
                event_date=timezone.localdate() + timedelta(days=offset), sent_at=timezone.now())
            event.sent_to_users.add(self.user)
        response = self.client.get('/')
        self.assertEqual(len(response.context['upcoming']), 2)
        self.assertEqual(response.context['upcoming_total'], 3)
        self.assertEqual(response.context['unanswered_events'], 3)

    def test_online_metric_counts_only_active_guild_members(self):
        self.make_member()
        for name, active, member, online in [('online-guild', True, True, True),
                                            ('offline-guild', True, True, False),
                                            ('inactive-guild', False, True, True),
                                            ('online-outsider', True, False, True)]:
            user = User.objects.create_user(name, is_active=active)
            if member:
                user.groups.add(self.group)
            user.profile.last_activity = timezone.now() - timedelta(minutes=0 if online else 20)
            user.profile.save()
        response = self.client.get('/')
        self.assertEqual(response.context['guild_total'], 3)
        self.assertEqual(response.context['guild_online'], 2)

    def test_inline_response_preserves_comment_and_returns_home(self):
        self.make_member()
        kind = EventType.objects.create(name='Inline-event')
        event = EventNotification.objects.create(event_type=kind,
            event_date=timezone.localdate() + timedelta(days=1), sent_at=timezone.now())
        event.sent_to_users.add(self.user)
        comment = 'Буду позже\nПосле босса'
        entry = EventAttendance.objects.create(notification=event, user=self.user, status='maybe', comment=comment)
        page = self.client.get('/')
        self.assertContains(page, 'name="return_to" value="home"')
        response = self.client.post(reverse('events:vote_view', args=[event.pk]),
                                    {'status': 'yes', 'comment': 'Буду позже После босса', 'return_to': 'home'})
        self.assertRedirects(response, '/')
        entry.refresh_from_db()
        self.assertEqual((entry.status, entry.comment), ('yes', comment))
        response = self.client.post(reverse('events:vote_view', args=[event.pk]),
                                    {'status': 'no', 'return_to': 'https://example.com'})
        self.assertRedirects(response, reverse('events:vote_results', args=[event.pk]))

    def test_uninvited_manager_sees_event_but_no_inline_response_form(self):
        admin = User.objects.create_superuser('uninvited-dashboard-admin')
        self.client.force_login(admin)
        kind = EventType.objects.create(name='Not-invited-event')
        event = EventNotification.objects.create(event_type=kind,
            event_date=timezone.localdate() + timedelta(days=1), sent_at=timezone.now())
        response = self.client.get('/')
        self.assertContains(response, 'Not-invited-event')
        self.assertNotContains(response, 'name="return_to"')
        self.assertEqual(response.context['unanswered_events'], 0)
        self.client.post(reverse('events:vote_view', args=[event.pk]), {'status': 'yes', 'return_to': 'home'})
        self.assertFalse(EventAttendance.objects.filter(notification=event, user=admin).exists())
