from django.db import migrations, models


class Migration(migrations.Migration):
    """Готовые иконки лотов убраны (файлов не было в репозитории) — картинку загружает администратор."""

    dependencies = [
        ('auction', '0003_alter_auctionlot_end_date'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RenameField(
            model_name='auctionlot',
            old_name='custom_image',
            new_name='image',
        ),
        migrations.AlterField(
            model_name='auctionlot',
            name='image',
            field=models.ImageField(blank=True, help_text='Картинка предмета из игры. Без картинки на сайте будет значок аукциона', null=True, upload_to='auction/lots/', verbose_name='Картинка'),
        ),
        migrations.RemoveField(
            model_name='auctionlot',
            name='icon_choice',
        ),
        migrations.AlterField(
            model_name='auctionbid',
            name='bidder',
            field=models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='auction_bids', to='auth.user', verbose_name='Участник'),
        ),
        migrations.AlterField(
            model_name='auctionbid',
            name='lot',
            field=models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='bids', to='auction.auctionlot', verbose_name='Лот'),
        ),
    ]
