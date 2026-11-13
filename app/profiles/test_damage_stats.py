from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import GearSetForm
from .models import MAGIC_CLASSES, Profile


@override_settings(SECURE_SSL_REDIRECT=False)
class ClassDamageStatsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('damage-player')
        self.gear = self.user.gear_sets.get(kind='pa')
        self.gear.fa, self.gear.ma = 111, 222
        self.gear.physical_pierce, self.gear.magic_pierce = 11, 22
        self.gear.hp = 1000
        self.gear.save()
        self.client.force_login(self.user)

    def test_all_classes_use_requested_damage_type(self):
        expected_magic = {'mag', 'zhrec', 'dru', 'sham', 'mist', 'zhnec', 'bard'}
        self.assertEqual(MAGIC_CLASSES, expected_magic)
        for code, _ in Profile.CLASS_CHOICES:
            with self.subTest(player_class=code):
                form = GearSetForm(instance=self.gear, player_class=code)
                self.assertEqual(form.fields['attack'].label, 'Маг. атака' if code in expected_magic else 'Физ. атака')
                self.assertEqual(form.initial['attack'], 222 if code in expected_magic else 111)
                self.assertEqual(form.initial['pierce'], 22 if code in expected_magic else 11)
                self.assertNotIn('fa', form.fields)
                self.assertNotIn('ma', form.fields)

    def test_saving_selected_type_preserves_other_type_and_ignores_injected_fields(self):
        for code, expected in [('zhnec', (111, 900, 11, 90)), ('var', (900, 222, 90, 22))]:
            with self.subTest(player_class=code):
                self.gear.refresh_from_db()
                self.gear.fa, self.gear.ma = 111, 222
                self.gear.physical_pierce, self.gear.magic_pierce = 11, 22
                data = {name: 0 for name in GearSetForm.Meta.fields}
                data.update(attack=900, pierce=90, fa=777, ma=777, physical_pierce=777, magic_pierce=777)
                form = GearSetForm(data, instance=self.gear, player_class=code)
                self.assertTrue(form.is_valid(), form.errors)
                form.save()
                self.gear.refresh_from_db()
                self.assertEqual((self.gear.fa, self.gear.ma, self.gear.physical_pierce, self.gear.magic_pierce), expected)

    def test_class_change_and_both_sets_save_in_one_submission(self):
        data = {'username': self.user.username, 'player_class': 'zhnec', 'main_set': 'pz', 'ts3_id': ''}
        for kind in ('pa', 'pz'):
            for name in GearSetForm.Meta.fields:
                data[f'{kind}-{name}'] = 0
            data[f'{kind}-attack'] = 5000
            data[f'{kind}-pierce'] = 50
        response = self.client.post(reverse('profile_edit'), data)
        self.assertEqual(response.status_code, 302)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.player_class, 'zhnec')
        self.assertEqual(self.user.profile.main_set, 'pz')
        for gear in self.user.gear_sets.all():
            self.assertEqual((gear.ma, gear.magic_pierce), (5000, 50))
        self.gear.refresh_from_db()
        self.assertEqual((self.gear.fa, self.gear.physical_pierce), (111, 11))

    def test_profile_and_shared_application_stats_show_only_selected_type(self):
        from django.template.loader import render_to_string
        for code, label, value, hidden in [('mag', 'Маг. атака', '222', 'Физ. атака'),
                                           ('var', 'Физ. атака', '111', 'Маг. атака')]:
            with self.subTest(player_class=code):
                self.user.profile.player_class = code
                self.user.profile.save()
                response = self.client.get(reverse('profile_view', args=[self.user.username]))
                self.assertContains(response, label)
                self.assertContains(response, value)
                self.assertNotContains(response, hidden)
                html = render_to_string('profiles/includes/gear_sets.html', {'profile': self.user.profile})
                self.assertIn(label, html)
                self.assertNotIn(hidden, html)

    def test_admin_inline_uses_same_damage_fields(self):
        self.user.is_superuser = self.user.is_staff = True
        self.user.save()
        self.user.profile.player_class = 'mag'
        self.user.profile.save()
        response = self.client.get(reverse('admin:auth_user_change', args=[self.user.pk]))
        self.assertContains(response, 'name="gear_sets-0-attack"')
        self.assertNotContains(response, 'name="gear_sets-0-fa"')
        self.assertContains(response, 'Маг. пробив')
