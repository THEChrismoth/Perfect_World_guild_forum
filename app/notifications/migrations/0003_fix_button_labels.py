from django.db import migrations

OLD_BUTTON = '🗳️ Проголосовать</a>'
NEW_BUTTON = 'Подробнее →</a>'


def fix_button_labels(apps, schema_editor):
    # Раньше кнопка «Проголосовать» добавлялась к любому уведомлению со ссылкой (TeamSpeak, аукцион, заявки).
    # Она хранится в тексте уведомления — у тех, что ведут не на ответ по ивенту, меняем её на «Подробнее».
    Notification = apps.get_model('notifications', 'Notification')
    for notification in Notification.objects.filter(message__contains=OLD_BUTTON).exclude(link__startswith='/events/vote/'):
        notification.message = notification.message.replace(OLD_BUTTON, NEW_BUTTON)
        notification.save(update_fields=['message'])


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0002_field_labels'),
    ]

    operations = [
        migrations.RunPython(fix_button_labels, migrations.RunPython.noop),
    ]
