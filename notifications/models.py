from django.db import models
from django.contrib.auth.models import User, Group
from django.urls import reverse


class Notification(models.Model):
    """Универсальная модель уведомлений для всего сайта"""

    NOTIFICATION_TYPES = [
        ('info', 'ℹ️ Информация'),
        ('success', '✅ Успех'),
        ('warning', '⚠️ Предупреждение'),
        ('error', '❌ Ошибка'),
        ('application', '📝 Заявка'),
        ('auction', '🎯 Аукцион'),
        ('forum', '💬 Форум'),
        ('system', '⚙️ Система'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField('Заголовок', max_length=200)
    message = models.TextField('Сообщение')
    notification_type = models.CharField('Тип', max_length=20, choices=NOTIFICATION_TYPES, default='info')
    link = models.CharField('Ссылка', max_length=500, blank=True, null=True)
    is_read = models.BooleanField('Прочитано', default=False)
    created_at = models.DateTimeField('Создано', auto_now_add=True)

    class Meta:
        verbose_name = 'Уведомление'
        verbose_name_plural = 'Уведомления'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_notification_type_display()}: {self.title} - {self.user.username}'

    def mark_as_read(self):
        """Пометить как прочитанное"""
        self.is_read = True
        self.save()

    def get_icon(self):
        """Получить иконку для типа уведомления"""
        icons = {
            'info': 'ℹ️',
            'success': '✅',
            'warning': '⚠️',
            'error': '❌',
            'application': '📝',
            'auction': '🎯',
            'forum': '💬',
            'system': '⚙️',
        }
        return icons.get(self.notification_type, '🔔')