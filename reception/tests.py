from django.contrib import admin
from django.contrib.auth.models import User
from django.test import TestCase

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
