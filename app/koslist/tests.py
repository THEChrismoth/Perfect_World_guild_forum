from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.test import TestCase, override_settings

from profiles.models import CLASS_ICONS, Profile
from .models import Player


class ClassIconTests(TestCase):
    def test_every_class_has_existing_icon(self):
        for choices in (Player.CLASS_CHOICES, Profile.CLASS_CHOICES):
            for value, label in choices:
                with self.subTest(player_class=value):
                    self.assertIn(value, CLASS_ICONS)
                    self.assertIsNotNone(finders.find(CLASS_ICONS[value]), f'нет файла {CLASS_ICONS[value]}')


@override_settings(SECURE_SSL_REDIRECT=False)
class KosListPageTests(TestCase):
    def test_page_shows_icons_of_all_classes_and_players(self):
        Player.objects.create(name='Злодей', player_class='zhrec')
        self.client.force_login(User.objects.create_user('member', password='pass'))

        response = self.client.get('/koslist/')

        self.assertContains(response, 'class_icon/priest.png', count=2)
        self.assertContains(response, 'title = "Дух крови"')
        self.assertNotContains(response, 'voin.png')
