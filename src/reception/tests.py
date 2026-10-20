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
class ApplicationFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('candidate', password='pass')
        self.client.force_login(self.user)

    def test_empty_profile_redirects_to_profile_edit(self):
        response = self.client.get(reverse('reception:application_form'), follow=True)

        # Раньше здесь был редирект на несуществующий /profile/edit/ и страница 404
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

        # Снимок: изменение профиля не меняет уже поданную заявку
        profile.real_name = 'Другое имя'
        profile.save()
        application.refresh_from_db()
        self.assertEqual(application.real_name, 'Даниил')
