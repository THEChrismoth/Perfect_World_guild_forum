from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('forum', '0005_remove_special_subcategories'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='subcategory',
            name='is_auction',
        ),
        migrations.RemoveField(
            model_name='subcategory',
            name='is_events',
        ),
        migrations.RemoveField(
            model_name='subcategory',
            name='is_reception',
        ),
        migrations.RemoveField(
            model_name='subcategory',
            name='is_reception_view',
        ),
    ]
