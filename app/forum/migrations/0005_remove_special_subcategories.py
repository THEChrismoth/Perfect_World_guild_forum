from django.db import migrations
from django.db.models import Q


def delete_empty_special_subcategories(apps, schema_editor):
    # Аукцион, ивенты и заявки теперь — отдельные разделы в меню слева, подкатегории-ссылки на них не нужны.
    # Удаляем те, в которых нет тем; если темы есть, подкатегория остаётся обычной и темы не пропадают.
    SubCategory = apps.get_model('forum', 'SubCategory')
    special = Q(is_auction=True) | Q(is_events=True) | Q(is_reception=True) | Q(is_reception_view=True)
    SubCategory.objects.filter(special, topics__isnull=True).delete()


class Migration(migrations.Migration):
    # Поля флагов удаляет следующая миграция: PostgreSQL не даёт менять таблицу в той же транзакции,
    # где из неё удаляли строки со связями.

    dependencies = [
        ('forum', '0004_field_labels'),
    ]

    operations = [
        migrations.RunPython(delete_empty_special_subcategories, migrations.RunPython.noop),
    ]
