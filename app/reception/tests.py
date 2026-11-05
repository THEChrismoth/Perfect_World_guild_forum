
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Application, ApplicationVote


@override_settings(SECURE_SSL_REDIRECT=False)
class ApplicationAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('boss', 'boss@example.com', 'pass')
        self.candidate = User.objects.create_user('candidate')
        self.application = Application.objects.create(user=self.candidate, player_class='Маг', development_plans='Расти')
        self.client.force_login(self.admin)

    def decide(self, decision, **data):
        return self.client.post(reverse('admin:reception_application_decision', args=[self.application.pk]),
                                {'decision': decision, **data})

    def test_no_add_and_no_votes_section(self):
        self.assertEqual(self.client.get(reverse('admin:reception_application_add')).status_code, 403)
        with self.assertRaises(Exception):
            reverse('admin:reception_applicationvote_changelist')

    def test_card_shows_application_and_escaped_comments(self):
        voter = User.objects.create_user('voter')
        ApplicationVote.objects.create(application=self.application, voter=voter, vote='for',
                                       comment='<script>alert(1)</script>')

        response = self.client.get(reverse('admin:reception_application_change', args=[self.application.pk]))

        self.assertContains(response, 'Расти')
        self.assertContains(response, 'Вынести на голосование')
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')

    def test_decisions_follow_status(self):
        from django.contrib.auth.models import Group
        from notifications.models import Notification

        # Одобрить можно только после голосования.
        self.decide('approve')
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'pending')

        self.decide('voting')
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'voting')
        self.assertIsNotNone(self.application.approved_at)

        self.decide('approve', add_to_guild='1')
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'approved')
        self.assertTrue(self.candidate.groups.filter(name='Член гильдии').exists())
        self.assertEqual(Notification.objects.filter(user=self.candidate).count(), 2)

    def test_reject_requires_reason(self):
        self.decide('reject', reason='  ')
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'pending')

        self.decide('reject', reason='Нет скриншотов')
        self.application.refresh_from_db()
        self.assertEqual((self.application.status, self.application.admin_comment), ('rejected', 'Нет скриншотов'))


@override_settings(SECURE_SSL_REDIRECT=False)
@override_settings(SECURE_SSL_REDIRECT=False)
class GuildMemberReceptionTests(TestCase):
    def test_member_votes_instead_of_applying(self):
        from django.contrib.auth.models import Group

        member = User.objects.create_user('member', password='pass')
        member.groups.add(Group.objects.create(name='Член гильдии'))
        self.client.force_login(member)

        response = self.client.get(reverse('reception:application_form'))

        self.assertRedirects(response, reverse('reception:application_list'))


@override_settings(SECURE_SSL_REDIRECT=False)
class VotingPageTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group
        from django.utils import timezone

        self.member = User.objects.create_user('member', password='pass')
        self.member.groups.add(Group.objects.create(name='Член гильдии'))
        self.candidate = User.objects.create_user('candidate', password='pass')
        self.voting = Application.objects.create(user=self.candidate, player_class='Маг', development_plans='Расти',
                                                 status='voting', approved_at=timezone.now())
        self.client.force_login(self.member)

    def test_tabs_show_history(self):
        from django.utils import timezone
        other = User.objects.create_user('old')
        Application.objects.create(user=other, player_class='Жрец', development_plans='-', status='rejected',
                                   approved_at=timezone.now())
        # Отклонена на проверке, до голосования не дошла — в истории её нет.
        Application.objects.create(user=User.objects.create_user('early'), player_class='Жрец',
                                   development_plans='-', status='rejected')

        open_page = self.client.get(reverse('reception:application_list'))
        rejected = self.client.get(reverse('reception:application_list'), {'tab': 'rejected'})
        everything = self.client.get(reverse('reception:application_list'), {'tab': 'all', 'q': 'old'})

        self.assertEqual([a.user.username for a in open_page.context['page']], ['candidate'])
        self.assertEqual([a.user.username for a in rejected.context['page']], ['old'])
        self.assertEqual([a.user.username for a in everything.context['page']], ['old'])

    def test_percent_from_for_and_against(self):
        for i, vote in enumerate(['for', 'for', 'for', 'against', 'abstain']):
            ApplicationVote.objects.create(application=self.voting, voter=User.objects.create_user(f'v{i}'), vote=vote)

        stats = self.client.get(reverse('reception:application_list')).context['page'][0].stats

        self.assertEqual((stats['percent_for'], stats['percent_against'], stats['total']), (75, 25, 5))

    def test_vote_once_and_comment_separately(self):
        vote_url = reverse('reception:application_vote', args=[self.voting.id])
        self.client.post(vote_url, {'vote': 'for', 'comment': ''})
        self.client.post(vote_url, {'vote': 'against'})
        response = self.client.post(reverse('reception:application_comment', args=[self.voting.id]),
                                    {'text': 'Знаю его, норм'}, HTTP_X_REQUESTED_WITH='fetch')

        self.assertEqual(list(self.voting.votes.values_list('vote', flat=True)), ['for'])
        self.assertEqual(self.voting.comments.get().text, 'Знаю его, норм')
        # Из окна обсуждения возвращается только содержимое окна, без каркаса сайта.
        self.assertContains(response, 'Знаю его, норм')
        self.assertNotContains(response, '<html')

    def test_site_feed_shows_only_texts(self):
        ApplicationVote.objects.create(application=self.voting, voter=User.objects.create_user('Molchun'), vote='for')
        ApplicationVote.objects.create(application=self.voting, voter=User.objects.create_user('Govorun'),
                                       vote='against', comment='Мало урона')

        items = self.client.get(reverse('reception:application_detail', args=[self.voting.id]),
                                {'modal': 1}).context['items']

        self.assertEqual([(item['author'].username, item['text']) for item in items], [('Govorun', 'Мало урона')])

    def test_comment_saved_with_vote(self):
        self.client.post(reverse('reception:application_vote', args=[self.voting.id]),
                         {'vote': 'against', 'comment': 'Был в ЧС'})

        vote = self.voting.votes.get()
        self.assertEqual((vote.vote, vote.comment), ('against', 'Был в ЧС'))

    def test_candidate_sees_own_application_without_names(self):
        voter = User.objects.create_user('ZloyGolos')
        ApplicationVote.objects.create(application=self.voting, voter=voter, vote='against', comment='Нет')
        self.client.force_login(self.candidate)

        # Содержимое заявки без каркаса: в списке «Онлайн» в меню имя голосовавшего есть всегда.
        response = self.client.get(reverse('reception:application_detail', args=[self.voting.id]), {'modal': 1})

        self.assertContains(response, 'Против · 1')
        self.assertNotContains(response, 'ZloyGolos')
        self.assertEqual(self.client.post(reverse('reception:application_comment', args=[self.voting.id]),
                                          {'text': 'Я'}).status_code, 403)


class ApplicationFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('candidate', password='pass')
        self.client.force_login(self.user)

    def test_empty_profile_redirects_to_profile_edit(self):
        response = self.client.get(reverse('reception:application_form'), follow=True)

        # Раньше здесь был редирект на несуществующий /profile/edit/ и страница 404.
        self.assertRedirects(response, reverse('profile_edit'))
        self.assertContains(response, 'заполните профиль')

    def test_class_and_stats_taken_from_profile(self):
        profile = self.user.profile
        profile.player_class = 'mag'
        profile.save()
        self.user.gear_sets.filter(kind='pa').update(ma=15000)

        page = self.client.get(reverse('reception:application_form'))
        self.assertContains(page, 'Сет ПЗ')
        self.assertContains(page, '0 / 15000')
        self.assertContains(page, 'Изменить в профиле')

        response = self.client.post(reverse('reception:application_form'), {
            'previous_nicknames': '', 'other_guilds': '', 'development_plans': 'Качаться', 'guarantors': '',
        })

        self.assertRedirects(response, reverse('reception:application_success'))
        application = Application.objects.get(user=self.user)
        self.assertEqual(application.player_class, 'Маг')

        # Снимок: смена класса в профиле не меняет уже поданную заявку.
        profile.player_class = 'var'
        profile.save()
        application.refresh_from_db()
        self.assertEqual(application.player_class, 'Маг')
