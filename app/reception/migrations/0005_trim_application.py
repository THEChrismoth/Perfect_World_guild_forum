from django.db import migrations, models


class Migration(migrations.Migration):
    """Анкета без «игрового опыта» и поручителей; вместо пяти скриншотов — два: окно характеристик сетов ПА и ПЗ.
    Первые два прежних скриншота сохраняются как скриншоты сетов, остальные три удаляются."""

    dependencies = [
        ('reception', '0004_drop_personal_data'),
    ]

    operations = [
        migrations.RemoveField(model_name='application', name='previous_nicknames'),
        migrations.RemoveField(model_name='application', name='on_blacklist'),
        migrations.RemoveField(model_name='application', name='blacklist_details'),
        migrations.RemoveField(model_name='application', name='other_guilds'),
        migrations.RemoveField(model_name='application', name='guarantors'),
        migrations.RemoveField(model_name='application', name='screenshot3'),
        migrations.RemoveField(model_name='application', name='screenshot4'),
        migrations.RemoveField(model_name='application', name='screenshot5'),
        migrations.RenameField(model_name='application', old_name='screenshot1', new_name='screenshot_pa'),
        migrations.RenameField(model_name='application', old_name='screenshot2', new_name='screenshot_pz'),
        migrations.AlterField(
            model_name='application',
            name='screenshot_pa',
            field=models.ImageField(blank=True, null=True, upload_to='applications/screenshots/%Y/%m/%d/',
                                    verbose_name='Скриншот сета ПА'),
        ),
        migrations.AlterField(
            model_name='application',
            name='screenshot_pz',
            field=models.ImageField(blank=True, null=True, upload_to='applications/screenshots/%Y/%m/%d/',
                                    verbose_name='Скриншот сета ПЗ'),
        ),
    ]
