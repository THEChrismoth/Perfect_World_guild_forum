from datetime import date

from django.contrib import admin
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .admin import ApplicationAdmin
from .models import Application, ApplicationVote


class ApplicationAdminTests(TestCase):
    def test_vote_comment_is_escaped(self):
        applicant = User.objects.create_user('applicant')
        voter = User.objects.create_user('voter')
        application = Application.objects.create(user=applicant, player_class='Маг', development_plans='Расти')
        ApplicationVote.objects.create(application=application, voter=voter, vote='for', comment='<script>alert(1)</script>')

        html = ApplicationAdmin(Application, admin.site).votes_detail(application)

        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)


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

    def test_personal_data_taken_from_profile(self):
        profile = self.user.profile
        profile.player_class = 'mag'
        profile.real_name = 'Даниил'
        profile.birth_date = date(2000, 1, 15)
        profile.timezone = 'UTC+5'
        profile.save()

        page = self.client.get(reverse('reception:application_form'))
        self.assertNotContains(page, 'name="real_name"')
        self.assertNotContains(page, 'name="age"')
        self.assertContains(page, 'Даниил')
        self.assertContains(page, 'Изменить в профиле')

        response = self.client.post(reverse('reception:application_form'), {
            'previous_nicknames': '', 'other_guilds': '', 'development_plans': 'Качаться', 'guarantors': '',
        })

        self.assertRedirects(response, reverse('reception:application_success'))
        application = Application.objects.get(user=self.user)
        self.assertEqual(application.real_name, 'Даниил')
        self.assertEqual(application.age, profile.age())
        self.assertEqual(application.timezone, 'UTC+5')
        self.assertEqual(application.player_class, 'Маг')

        # Снимок: изменение профиля не меняет уже поданную заявку.
        profile.real_name = 'Другое имя'
        profile.save()
        application.refresh_from_db()
        self.assertEqual(application.real_name, 'Даниил')
