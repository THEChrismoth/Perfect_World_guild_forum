from django.db import migrations

STAT_FIELDS = ('hp', 'bd', 'bu', 'pa', 'fa', 'ma', 'physical_pierce', 'magic_pierce',
               'pz', 'physical_defense', 'magic_defense')


def fill_gear_sets(apps, schema_editor):
    """Нынешние характеристики профиля становятся сетом ПА (основным), сет ПЗ — пустой, игрок заполнит."""
    User = apps.get_model('auth', 'User')
    Profile = apps.get_model('profiles', 'Profile')
    GearSet = apps.get_model('profiles', 'GearSet')
    profiles = {profile.user_id: profile for profile in Profile.objects.all()}
    sets = []
    for user_id in User.objects.values_list('id', flat=True):
        profile = profiles.get(user_id)
        stats = {field: getattr(profile, field) for field in STAT_FIELDS} if profile else {}
        sets.append(GearSet(user_id=user_id, kind='pa', **stats))
        sets.append(GearSet(user_id=user_id, kind='pz'))
    GearSet.objects.bulk_create(sets, ignore_conflicts=True)


class Migration(migrations.Migration):
    # Поля профиля удаляются отдельной миграцией: в PostgreSQL нельзя в одной транзакции
    # заполнить таблицу и сразу менять схему связанной таблицы.

    dependencies = [
        ('profiles', '0009_gear_sets'),
    ]

    operations = [
        migrations.RunPython(fill_gear_sets, migrations.RunPython.noop),
    ]
