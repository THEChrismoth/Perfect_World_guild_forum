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
        self.assertContains(response, 'Вы будете')

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
