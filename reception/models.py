from django.db import models
from django.contrib.auth.models import User, Group
from django.utils import timezone
from django.urls import reverse

class Application(models.Model):
    """Модель заявки на вступление в гильдию"""
    
    STATUS_CHOICES = [
        ('pending', 'На рассмотрении'),
        ('approved', 'Одобрена'),
        ('rejected', 'Отклонена'),
        ('voting', 'Голосование'),
    ]
    
    VOTE_CHOICES = [
        ('for', 'За'),
        ('against', 'Против'),
        ('abstain', 'Воздержался'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='applications')
    player_class = models.CharField('Класс персонажа', max_length=20)
    
    previous_nicknames = models.TextField('Прошлые никнеймы', blank=True)
    timezone = models.CharField('Часовой пояс', max_length=50, default='UTC+3')
    real_name = models.CharField('Имя', max_length=100, blank=True)
    age = models.PositiveIntegerField('Возраст', null=True, blank=True)
    on_blacklist = models.BooleanField('Нахождение в ЧС других гильдий', default=False)
    blacklist_details = models.TextField('Пояснение по ЧС', blank=True)
    other_guilds = models.TextField('Гильдии в которых состоит', blank=True)
    development_plans = models.TextField('Планы на развитие персонажа на 2 месяца')
    guarantors = models.TextField('Поручители', blank=True)
    
    screenshot1 = models.ImageField('Скриншот 1', upload_to='applications/screenshots/%Y/%m/%d/', blank=True, null=True)
    screenshot2 = models.ImageField('Скриншот 2', upload_to='applications/screenshots/%Y/%m/%d/', blank=True, null=True)
    screenshot3 = models.ImageField('Скриншот 3', upload_to='applications/screenshots/%Y/%m/%d/', blank=True, null=True)
    screenshot4 = models.ImageField('Скриншот 4', upload_to='applications/screenshots/%Y/%m/%d/', blank=True, null=True)
    screenshot5 = models.ImageField('Скриншот 5', upload_to='applications/screenshots/%Y/%m/%d/', blank=True, null=True)
    
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default='pending')
    admin_comment = models.TextField('Комментарий администратора', blank=True)
    
    created_at = models.DateTimeField('Дата подачи', auto_now_add=True)
    updated_at = models.DateTimeField('Дата обновления', auto_now=True)
    approved_at = models.DateTimeField('Дата одобрения', null=True, blank=True)
    
    reviewed_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='reviewed_applications',
        verbose_name='Проверил'
    )
    
    class Meta:
        verbose_name = 'Заявку'
        verbose_name_plural = 'Заявки'
        ordering = ['-created_at']
    
    def __str__(self):
        return f'Заявка от {self.user.username} ({self.get_status_display()})'
    
    def get_absolute_url(self):
        return reverse('reception:application_detail', args=[self.id])
    
    def approve_by_admin(self, admin_user):
        self.status = 'voting'
        self.approved_at = timezone.now()
        self.reviewed_by = admin_user
        self.save()
    
    def reject_by_admin(self, admin_user, comment=''):
        self.status = 'rejected'
        self.admin_comment = comment
        self.reviewed_by = admin_user
        self.save()
    
    def final_approve(self):
        """Окончательное одобрение после голосования - выдача группы"""
        self.status = 'approved'
        self.save()
        
        # Выдаем группу "Член гильдии"
        try:
            guild_group = Group.objects.get(name='Член гильдии')
            self.user.groups.add(guild_group)
        except Group.DoesNotExist:
            # Создаем группу если не существует
            guild_group = Group.objects.create(name='Член гильдии')
            self.user.groups.add(guild_group)
    
    def final_reject(self):
        self.status = 'rejected'
        self.save()
    
    def can_vote(self, user):
        if self.status != 'voting':
            return False
        return user.groups.filter(name='Член гильдии').exists()
    
    def has_voted(self, user):
        return self.votes.filter(voter=user).exists()
    
    def get_vote_stats(self):
        votes_for = self.votes.filter(vote='for').count()
        votes_against = self.votes.filter(vote='against').count()
        votes_abstain = self.votes.filter(vote='abstain').count()
        total = self.votes.count()
        
        return {
            'for': votes_for,
            'against': votes_against,
            'abstain': votes_abstain,
            'total': total,
        }


class ApplicationVote(models.Model):
    VOTE_CHOICES = [
        ('for', 'За'),
        ('against', 'Против'),
        ('abstain', 'Воздержался'),
    ]
    
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='votes')
    voter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='application_votes')
    vote = models.CharField('Голос', max_length=10, choices=VOTE_CHOICES)
    comment = models.TextField('Комментарий', blank=True)
    created_at = models.DateTimeField('Дата голосования', auto_now_add=True)
    
    class Meta:
        verbose_name = 'Голос'
        verbose_name_plural = 'Голоса'
        unique_together = ['application', 'voter']
    
    def __str__(self):
        return f'{self.voter.username} - {self.get_vote_display()}'


class ApplicationNotification(models.Model):
    """Уведомления о заявках"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='application_notifications')
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f'Уведомление для {self.user.username}'
