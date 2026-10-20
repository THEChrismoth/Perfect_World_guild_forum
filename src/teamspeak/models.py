"""Связь сайта с ботом TeamSpeak (tsbot/).

Бот — отдельный сервис. Он опрашивает API сайта (teamspeak/api.py): забирает задачи из очереди
TsTask, выполняет их в TeamSpeak и сообщает результат, а также присылает, кто в каких каналах
находится — по этим данным начисляются очки активности за ивенты.
"""
import datetime
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

GUILD_GROUP = 'Член гильдии'
BOT_ONLINE_TIMEOUT = datetime.timedelta(minutes=2)


class TeamSpeakSettings(models.Model):
    """Настройки TeamSpeak. Хранится единственная запись (pk=1)."""

    server_address = models.CharField(
        'Адрес сервера TeamSpeak', max_length=255, blank=True,
        help_text='Что вводить в клиенте TeamSpeak, например myguild.ru. Если пусто — домен сайта'
    )
    rooms_per_member = models.PositiveSmallIntegerField(
        'Комнат на члена гильдии', default=1,
        help_text='Сколько комнат в разделе «Комнаты членов гильдии» может создать один игрок через сайт'
    )
    max_clients = models.PositiveIntegerField(
        'Слотов на сервере', null=True, blank=True,
        help_text='После установки лицензии бот выставит это число слотов. Пусто — не менять'
    )

    # Лицензия хранится в базе, а не в media: файлы media доступны из интернета
    license_name = models.CharField('Файл лицензии', max_length=255, blank=True, editable=False)
    license_data = models.BinaryField('Лицензия', null=True, blank=True, editable=False)
    license_uploaded_at = models.DateTimeField('Лицензия загружена', null=True, blank=True, editable=False)
    license_installed_at = models.DateTimeField('Лицензия установлена', null=True, blank=True, editable=False)

    bot_last_seen = models.DateTimeField('Бот был на связи', null=True, blank=True, editable=False)

    class Meta:
        verbose_name = 'Настройки TeamSpeak'
        verbose_name_plural = 'Настройки TeamSpeak'

    def __str__(self):
        return 'Настройки TeamSpeak'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def bot_online(self):
        return bool(self.bot_last_seen) and timezone.now() - self.bot_last_seen < BOT_ONLINE_TIMEOUT

    def display_address(self, request=None):
        if self.server_address:
            return self.server_address
        if request is not None:
            return request.get_host().split(':')[0]
        hosts = [h for h in settings.ALLOWED_HOSTS if h not in ('*', 'web')]
        return hosts[0] if hosts else ''


class TsLink(models.Model):
    """Привязка аккаунта сайта к клиенту TeamSpeak (по уникальному ID клиента)"""

    STATUS_CHOICES = [
        ('pending', 'Ждёт подтверждения в TeamSpeak'),
        ('verified', 'Подтверждена'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ts_link')
    uid = models.CharField('TS3 ID', max_length=64)
    status = models.CharField('Статус', max_length=10, choices=STATUS_CHOICES, default='pending')
    token = models.CharField(max_length=64, unique=True, editable=False)
    requested_at = models.DateTimeField('Запрошена', auto_now_add=True)
    verified_at = models.DateTimeField('Подтверждена', null=True, blank=True)

    class Meta:
        verbose_name = 'Привязка TeamSpeak'
        verbose_name_plural = 'Привязки TeamSpeak'

    def __str__(self):
        return f'{self.user} → {self.uid}'

    @staticmethod
    def new_token():
        return secrets.token_urlsafe(24)

    @property
    def verified(self):
        return self.status == 'verified'


class TsTask(models.Model):
    """Очередь задач для бота"""

    TYPE_CHOICES = [
        ('verify_link', 'Подтверждение TS3 ID'),
        ('grant_guild', 'Выдать группу гильдии'),
        ('revoke_guild', 'Снять группу гильдии'),
        ('create_room', 'Создать комнату'),
        ('delete_room', 'Удалить комнату'),
        ('install_license', 'Установить лицензию'),
    ]
    STATUS_CHOICES = [
        ('pending', 'В очереди'),
        ('running', 'Выполняется'),
        ('done', 'Выполнено'),
        ('failed', 'Ошибка'),
    ]

    type = models.CharField('Задача', max_length=20, choices=TYPE_CHOICES)
    payload = models.JSONField('Параметры', default=dict)
    status = models.CharField('Статус', max_length=10, choices=STATUS_CHOICES, default='pending')
    result = models.JSONField('Результат', null=True, blank=True)
    error = models.TextField('Ошибка', blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='ts_tasks', verbose_name='Пользователь')
    created_at = models.DateTimeField('Создана', auto_now_add=True)
    started_at = models.DateTimeField('Взята ботом', null=True, blank=True)
    finished_at = models.DateTimeField('Завершена', null=True, blank=True)

    class Meta:
        verbose_name = 'Задача бота'
        verbose_name_plural = 'Задачи бота'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_type_display()} #{self.pk}'

    @classmethod
    def enqueue(cls, task_type, user=None, **payload):
        return cls.objects.create(type=task_type, payload=payload, user=user)


class TsRoom(models.Model):
    """Комната члена гильдии в разделе «Комнаты членов гильдии»"""

    STATUS_CHOICES = [
        ('creating', 'Создаётся'),
        ('active', 'Создана'),
        ('deleting', 'Удаляется'),
        ('failed', 'Ошибка'),
    ]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ts_rooms',
                              verbose_name='Владелец')
    name = models.CharField('Название', max_length=40)
    channel_id = models.PositiveIntegerField('ID канала', null=True, blank=True)
    status = models.CharField('Статус', max_length=10, choices=STATUS_CHOICES, default='creating')
    error = models.TextField('Ошибка', blank=True)
    created_at = models.DateTimeField('Создана', auto_now_add=True)

    class Meta:
        verbose_name = 'Комната'
        verbose_name_plural = 'Комнаты членов гильдии'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class EventPresence(models.Model):
    """Сколько минут игрок провёл в каналах ивента во время его проведения"""

    notification = models.ForeignKey('events.EventNotification', on_delete=models.CASCADE,
                                     related_name='ts_presence', verbose_name='Ивент')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ts_presence',
                             verbose_name='Игрок')
    minutes = models.PositiveIntegerField('Минут в канале', default=0)
    last_minute = models.DateTimeField('Последняя отметка', null=True, blank=True)

    class Meta:
        verbose_name = 'Присутствие на ивенте'
        verbose_name_plural = 'Присутствие на ивентах'
        unique_together = ['notification', 'user']

    def __str__(self):
        return f'{self.user} — {self.notification}: {self.minutes} мин'
