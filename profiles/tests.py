from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(SECURE_SSL_REDIRECT=False)
class ActivityMenuTests(TestCase):
    def test_menu_item_opens_activity_page(self):
        admin = User.objects.create_superuser('admin', password='pass')
        self.client.force_login(admin)

        response = self.client.get(reverse('admin:profiles_dummymodel_changelist'))

        self.assertRedirects(response, reverse('admin:activity_management'))
