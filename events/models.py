from django.db import models
from django.contrib.auth.models import User, Group
from django.urls import reverse
from django.utils.text import slugify


class EventType(models.Model):
    """Тип ивента (шаблон отрядов)"""
    name = models.CharField('Название типа ивента', max_length=100)
    slug = models.SlugField('Слаг', unique=True, blank=True, editable=False)
    description = models.TextField('Описание', blank=True)
    
    # Количество отрядов
    parties_count = models.PositiveIntegerField(
        'Количество отрядов',
        default=1,
        help_text='Сколько отрядов в ивенте'
    )
    
    # Размер отряда
    party_size = models.PositiveIntegerField(
        'Размер отряда',
        default=10,
        help_text='Количество участников в отряде (включая лидера)'
    )
    
    # Иконка
    icon = models.CharField('Иконка', max_length=10, default='⚔️')
    
    # Активен ли тип
    is_active = models.BooleanField('Активен', default=True)
    
    # Порядок сортировки
    order = models.IntegerField('Порядок', default=0)
    
    # Связь с подкатегорией форума (опционально)
    forum_subcategory = models.ForeignKey(
        'forum.SubCategory',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='event_types',
        verbose_name='Подкатегория форума'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Тип ивента'
        verbose_name_plural = 'Типы ивентов'
        ordering = ['order', 'name']
    
    def __str__(self):
        return f"{self.icon} {self.name}"
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
    
    def get_absolute_url(self):
        return reverse('events:event_detail', kwargs={'event_type_slug': self.slug})
    
    @property
    def total_slots(self):
        """Общее количество слотов в ивенте этого типа"""
        return self.parties_count * self.party_size


class Event(models.Model):
    """Ивент - создается на основе EventType, отряды заполняются вручную"""
    
    event_type = models.ForeignKey(
        EventType,
        on_delete=models.PROTECT,
        related_name='events',
        verbose_name='Тип ивента'
    )
    
    notes = models.TextField('Примечания', blank=True, help_text='Особенности на эту неделю')
    is_active = models.BooleanField('Активен', default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Ивент'
        verbose_name_plural = 'Ивенты'
    
    def __str__(self):
        return f"{self.event_type.icon} {self.event_type.name}"
    
    def get_absolute_url(self):
        return reverse('events:event_detail', kwargs={'event_type_slug': self.event_type.slug})


class Party(models.Model):
    """Отряд в ивенте"""
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='parties')
    number = models.PositiveIntegerField('Номер отряда')
    leader = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='led_parties',
        verbose_name='Лидер отряда'
    )
    
    class Meta:
        verbose_name = 'Отряд'
        verbose_name_plural = 'Отряды'
        ordering = ['event', 'number']
        unique_together = ['event', 'number']
    
    def __str__(self):
        leader_name = self.leader.username if self.leader else "Не назначен"
        return f"{self.event} - Отряд {self.number} (Лидер: {leader_name})"
    
    @property
    def members_count(self):
        return self.members.count() + (1 if self.leader else 0)
    
    @property
    def is_full(self):
        return self.members_count >= self.event.event_type.party_size
    
    @property
    def available_slots(self):
        return self.event.event_type.party_size - self.members_count


class PartyMember(models.Model):
    """Участник отряда (не лидер)"""
    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='event_memberships')
    joined_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Участник отряда'
        verbose_name_plural = 'Участники отрядов'
        unique_together = ['party', 'user']
    
    def __str__(self):
        return f"{self.user.username} - отряд {self.party.number}"


class EventNotification(models.Model):
    """Уведомление о проведении ивента на конкретную дату"""
    
    event_type = models.ForeignKey(
        EventType,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name='Тип ивента'
    )
    
    event_date = models.DateField('Дата проведения')
    subject = models.CharField('Тема', max_length=200)
    message = models.TextField('Сообщение')
    
    # Группы получателей (можно выбрать несколько)
    recipient_groups = models.ManyToManyField(
        Group,
        blank=True,
        verbose_name='Группы получателей',
        help_text='Выберите группы пользователей, которые получат уведомление. Если не выбрано - отправляется всем членам гильдии'
    )
    
    sent_at = models.DateTimeField('Отправлено', auto_now_add=True, null=True, blank=True)
    sent_to_users = models.ManyToManyField(
        User,
        related_name='event_notifications',
        verbose_name='Отправлено пользователям',
        blank=True
    )
    
    class Meta:
        verbose_name = 'Уведомление об ивенте'
        verbose_name_plural = 'Уведомления об ивентах'
        ordering = ['-event_date', '-sent_at']
        unique_together = ['event_type', 'event_date']
    
    def __str__(self):
        return f"{self.event_type.name} - {self.event_date}"


class EventAttendance(models.Model):
    """Ответы пользователей на уведомление (кто придет/не придет)"""
    
    STATUS_CHOICES = [
        ('yes', '✅ Приду'),
        ('no', '❌ Не приду'),
        ('maybe', '🤔 Возможно'),
    ]
    
    notification = models.ForeignKey(
        EventNotification,
        on_delete=models.CASCADE,
        related_name='attendances',
        verbose_name='Уведомление'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='event_attendances',
        verbose_name='Пользователь'
    )
    status = models.CharField('Статус', max_length=10, choices=STATUS_CHOICES)
    comment = models.TextField('Комментарий', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Ответ на уведомление'
        verbose_name_plural = 'Ответы на уведомления'
        unique_together = ['notification', 'user']
    
    def __str__(self):
        return f"{self.user.username} - {self.notification.event_type.name} ({self.notification.event_date}): {self.get_status_display()}"


# ========== СИГНАЛЫ ДЛЯ АВТОМАТИЧЕСКОГО СОЗДАНИЯ ОТРЯДОВ ==========

from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=EventType)
def create_event_and_parties(sender, instance, created, **kwargs):
    """При создании типа ивента автоматически создаем Event и отряды"""
    if created:
        # Создаем ивент
        event = Event.objects.create(
            event_type=instance,
            is_active=True
        )
        
        # Создаем отряды
        for i in range(instance.parties_count):
            Party.objects.create(
                event=event,
                number=i + 1
            )


@receiver(post_save, sender=EventType)
def update_parties_count(sender, instance, **kwargs):
    """При изменении количества отрядов в EventType обновляем отряды в Event"""
    if not instance.pk:
        return
    
    try:
        event = Event.objects.get(event_type=instance)
    except Event.DoesNotExist:
        return
    
    current_parties = event.parties.count()
    
    # Если нужно добавить отряды
    if instance.parties_count > current_parties:
        for i in range(current_parties + 1, instance.parties_count + 1):
            Party.objects.create(event=event, number=i)
    
    # Если нужно удалить отряды (только пустые)
    elif instance.parties_count < current_parties:
        parties_to_remove = event.parties.filter(number__gt=instance.parties_count)
        for party in parties_to_remove:
            if party.members.count() == 0 and not party.leader:
                party.delete()
