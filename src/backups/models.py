import datetime

from django.core.validators import MinValueValidator
from django.db import models


class BackupSettings(models.Model):
    """Настройки резервного копирования. Хранится единственная запись (pk=1)."""

    FREQUENCY_CHOICES = [
        ('daily', 'Каждый день'),
        ('weekly', 'Раз в неделю'),
    ]
    WEEKDAY_CHOICES = [
        (0, 'Понедельник'),
        (1, 'Вторник'),
        (2, 'Среда'),
        (3, 'Четверг'),
        (4, 'Пятница'),
        (5, 'Суббота'),
        (6, 'Воскресенье'),
    ]

    # Расписание
    enabled = models.BooleanField(
        'Автоматические копии',
        default=False,
        help_text='Создавать резервные копии по расписанию'
    )
    frequency = models.CharField('Как часто', max_length=10, choices=FREQUENCY_CHOICES, default='daily')
    weekday = models.PositiveSmallIntegerField(
        'День недели',
        choices=WEEKDAY_CHOICES,
        default=0,
        help_text='Для копий раз в неделю'
    )
    run_time = models.TimeField('Время', default=datetime.time(4, 0), help_text='По времени сервера (Москва)')

    # Что сохранять
    include_media = models.BooleanField(
        'Сохранять загруженные файлы',
        default=True,
        help_text='Аватары, картинки постов, скриншоты заявок. Без них копия меньше, но картинки не восстановятся'
    )

    # Локальное хранение
    keep_local = models.PositiveIntegerField(
        'Хранить копий на сервере',
        default=7,
        validators=[MinValueValidator(1)],
        help_text='Более старые копии удаляются с сервера автоматически'
    )

    # Яндекс Диск
    yandex_enabled = models.BooleanField(
        'Загружать на Яндекс Диск',
        default=False,
        help_text='Только для зашифрованных копий: задайте BACKUP_ENCRYPTION_PASSWORD в .env'
    )
    # Хранится зашифрованным (см. backups/crypto.py). Читать — get_yandex_token()
    yandex_token = models.CharField(
        'OAuth-токен Яндекса',
        max_length=500,
        blank=True,
        help_text='Как получить токен — в README, раздел «Резервные копии». Оставьте поле пустым, чтобы не менять сохраненный токен'
    )
    yandex_folder = models.CharField(
        'Папка на Диске',
        max_length=255,
        default='app:/backups',
        help_text='app:/backups — папка приложения (Приложения → название приложения → backups). '
                  'Если у токена полный доступ к Диску, можно указать, например, disk:/Бэкапы гильдии'
    )
    keep_yandex = models.PositiveIntegerField(
        'Хранить копий на Яндекс Диске',
        default=30,
        validators=[MinValueValidator(1)],
        help_text='Более старые копии удаляются с Диска автоматически'
    )

    # Служебное: когда в последний раз сработало расписание
    last_scheduled_run = models.DateTimeField('Последний запуск по расписанию', null=True, blank=True, editable=False)

    class Meta:
        verbose_name = 'Настройки резервных копий'
        verbose_name_plural = 'Настройки резервных копий'

    def __str__(self):
        return 'Настройки резервных копий'

    def save(self, *args, **kwargs):
        from .crypto import SECRET_PREFIX, encrypt_secret

        self.pk = 1
        # Токен никогда не записывается в базу открытым текстом
        if self.yandex_token and not self.yandex_token.startswith(SECRET_PREFIX):
            self.yandex_token = encrypt_secret(self.yandex_token)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Настройки не удаляются
        pass

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def get_yandex_token(self):
        """Расшифрованный токен или пустая строка"""
        from .crypto import decrypt_secret
        return decrypt_secret(self.yandex_token) or ''

    @property
    def yandex_token_unreadable(self):
        """Токен сохранен, но не расшифровывается — обычно после смены DJANGO_SECRET_KEY"""
        return bool(self.yandex_token) and not self.get_yandex_token()

    @property
    def yandex_configured(self):
        return self.yandex_enabled and bool(self.get_yandex_token())


class Backup(models.Model):
    """Журнал резервных копий"""

    STATUS_CHOICES = [
        ('pending', 'В очереди'),
        ('running', 'Выполняется'),
        ('success', 'Готово'),
        ('warning', 'Готово с замечаниями'),
        ('failed', 'Ошибка'),
    ]
    # Статусы, при которых архив создан и пригоден для восстановления
    COMPLETED_STATUSES = ('success', 'warning')
    TRIGGER_CHOICES = [
        ('schedule', 'По расписанию'),
        ('manual', 'Вручную'),
    ]
    YANDEX_STATUS_CHOICES = [
        ('off', 'Не настроено'),
        ('uploaded', 'Загружено'),
        ('failed', 'Ошибка загрузки'),
        ('deleted', 'Удалено с Диска'),
    ]

    created_at = models.DateTimeField('Создано', auto_now_add=True)
    started_at = models.DateTimeField('Начато', null=True, blank=True)
    finished_at = models.DateTimeField('Завершено', null=True, blank=True)
    status = models.CharField('Статус', max_length=10, choices=STATUS_CHOICES, default='pending')
    trigger = models.CharField('Запуск', max_length=10, choices=TRIGGER_CHOICES, default='manual')
    requested_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Запустил'
    )

    file_name = models.CharField('Файл', max_length=255, blank=True)
    size = models.BigIntegerField('Размер, байт', null=True, blank=True)
    includes_media = models.BooleanField('С загруженными файлами', default=True)
    encrypted = models.BooleanField('Зашифрована', default=False)
    local_deleted = models.BooleanField('Удалено с сервера', default=False)

    yandex_status = models.CharField('Яндекс Диск', max_length=10, choices=YANDEX_STATUS_CHOICES, default='off')
    yandex_path = models.CharField('Путь на Диске', max_length=500, blank=True)

    error = models.TextField('Ошибка', blank=True)

    class Meta:
        verbose_name = 'Резервная копия'
        verbose_name_plural = 'Журнал резервных копий'
        ordering = ['-created_at']

    def __str__(self):
        return self.file_name or f'Копия #{self.pk}'

    @property
    def duration(self):
        if self.started_at and self.finished_at:
            return self.finished_at - self.started_at
        return None

    @property
    def local_path(self):
        from .services import backup_dir
        if not self.file_name:
            return None
        return backup_dir() / self.file_name

    @property
    def local_available(self):
        path = self.local_path
        return bool(path) and not self.local_deleted and path.exists()
