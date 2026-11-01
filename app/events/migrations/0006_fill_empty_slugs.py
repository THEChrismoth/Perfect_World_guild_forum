from django.db import migrations
from uuslug import uuslug


def fill_empty_slugs(apps, schema_editor):
    # Раньше адрес делался через slugify, а он выбрасывает кириллицу: у типа «МТВ» адрес был пустой,
    # и страница ивентов падала. Даём таким типам адрес латиницей, как теперь в EventType.save.
    EventType = apps.get_model('events', 'EventType')
    for event_type in EventType.objects.filter(slug=''):
        event_type.slug = uuslug(event_type.name, instance=event_type, max_length=50)
        event_type.save(update_fields=['slug'])


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0005_field_labels'),
    ]

    operations = [
        migrations.RunPython(fill_empty_slugs, migrations.RunPython.noop),
    ]
