from django.test import TestCase, override_settings

from .models import SiteSettings


@override_settings(SECURE_SSL_REDIRECT=False)
class SiteSettingsTests(TestCase):
    def test_default_name_shown(self):
        response = self.client.get('/')

        self.assertContains(response, '<title>Гильдия</title>', html=True)

    def test_changed_name_shown(self):
        settings = SiteSettings.load()
        settings.site_name = 'Ermitage'
        settings.save()

        response = self.client.get('/')

        self.assertContains(response, '<title>Ermitage</title>', html=True)
        self.assertContains(response, '<a href="/">Ermitage</a>', html=True)

    def test_only_one_record(self):
        SiteSettings(site_name='Первая').save()
        SiteSettings(site_name='Вторая').save()

        self.assertEqual(SiteSettings.objects.count(), 1)
        self.assertEqual(SiteSettings.load().site_name, 'Вторая')
