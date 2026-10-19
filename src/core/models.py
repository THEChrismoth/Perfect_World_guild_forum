from django.core.validators import FileExtensionValidator
from django.db import models


class SiteSettings(models.Model):
    """Настройки сайта. Хранится единственная запись (pk=1), редактируется в админ-панели."""

    site_name = models.CharField(
        'Название сайта',
        max_length=100,
        default='Гильдия',
        help_text='Отображается в заголовке вкладки браузера и в шапке сайта'
    )
    favicon = models.FileField(
        'Иконка сайта (favicon)',
        upload_to='site/',
        blank=True,
        validators=[FileExtensionValidator(['ico', 'png'])],
        help_text='Файл .ico или .png, лучше квадратный (32×32 или 64×64). Если не загружен — используется стандартная иконка'
    )

    class Meta:
        verbose_name = 'Настройки сайта'
        verbose_name_plural = 'Настройки сайта'

    def __str__(self):
        return 'Настройки сайта'

    def save(self, *args, **kwargs):
        self.pk = 1
        # При замене иконки удаляем старый файл, чтобы не копился мусор в media
        old = SiteSettings.objects.filter(pk=1).first()
        if old and old.favicon and old.favicon != self.favicon:
            old.favicon.delete(save=False)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Настройки не удаляются
        pass

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
