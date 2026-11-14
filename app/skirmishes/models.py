"""Внеплановые сборы, фактическая явка и история проверки результатов."""
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Skirmish(models.Model):
    title = models.CharField('Название', max_length=120)
    code = models.CharField('Код входа', max_length=4)
    organizer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                  null=True, related_name='organized_skirmishes', verbose_name='Организатор')
    started_at = models.DateTimeField('Начат', default=timezone.now)
    ended_at = models.DateTimeField('Завершён', null=True, blank=True)
    reviewed_at = models.DateTimeField('Результат подтверждён', null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='+', verbose_name='Проверил')
    ts_channel = models.CharField('TS-канал', max_length=255)
    include_children = models.BooleanField('Учитывать подканалы', default=True)
    min_minutes = models.PositiveSmallIntegerField('Минимум минут', default=10)
    last_report_at = models.DateTimeField('Последний отчёт TS', null=True, blank=True)

    class Meta:
        verbose_name = 'Замес'
        verbose_name_plural = 'Замесы'
        ordering = ['-started_at', '-pk']
        permissions = [('manage_skirmish', 'Может начинать замесы и проверять участие')]
        constraints = [
            models.UniqueConstraint(models.Value(1), condition=models.Q(ended_at__isnull=True),
                                    name='one_active_skirmish'),
            models.CheckConstraint(condition=models.Q(ended_at__isnull=True) | models.Q(ended_at__gte=models.F('started_at')),
                                   name='skirmish_end_after_start'),
            models.CheckConstraint(condition=models.Q(reviewed_at__isnull=True) | models.Q(ended_at__isnull=False),
                                   name='skirmish_review_after_end'),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('skirmishes:detail', args=[self.pk])

    @property
    def active(self):
        return self.ended_at is None

    @property
    def status_label(self):
        if self.active:
            return 'Идёт сбор'
        return 'Итоги подтверждены' if self.reviewed_at else 'Ожидает проверки'


class Participant(models.Model):
    skirmish = models.ForeignKey(Skirmish, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='skirmish_participations')
    joined_at = models.DateTimeField('Вход по коду', null=True, blank=True)
    minutes = models.PositiveIntegerField('Минут в TS', default=0)
    first_seen_at = models.DateTimeField('Впервые в TS', null=True, blank=True)
    last_seen_at = models.DateTimeField('Последний раз в TS', null=True, blank=True)
    last_minute = models.DateTimeField('Учтённая минута', null=True, blank=True)
    attendance_override = models.BooleanField('Участие подтверждено вручную', null=True, blank=True)

    class Meta:
        verbose_name = 'Участник замеса'
        verbose_name_plural = 'Участники замесов'
        constraints = [models.UniqueConstraint(fields=['skirmish', 'user'], name='unique_skirmish_participant')]

    @property
    def attended(self):
        if self.attendance_override is not None:
            return self.attendance_override
        return self.minutes >= self.skirmish.min_minutes


class UnidentifiedPresence(models.Model):
    skirmish = models.ForeignKey(Skirmish, on_delete=models.CASCADE, related_name='unidentified')
    uid = models.CharField('TS3 ID', max_length=64)
    nickname = models.CharField('Ник в TS', max_length=128, blank=True)
    minutes = models.PositiveIntegerField('Минут в TS', default=0)
    first_seen_at = models.DateTimeField('Первая отметка')
    last_seen_at = models.DateTimeField('Последняя отметка')
    last_minute = models.DateTimeField('Учтённая минута')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['skirmish', 'uid'], name='unique_skirmish_unknown')]


class AttendanceCorrection(models.Model):
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name='corrections')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    previous_value = models.BooleanField(null=True)
    new_value = models.BooleanField(null=True)
    reason = models.CharField('Причина', max_length=500)

    class Meta:
        ordering = ['-created_at', '-pk']


class CodeAttempt(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    window_started_at = models.DateTimeField()
    count = models.PositiveSmallIntegerField(default=0)
