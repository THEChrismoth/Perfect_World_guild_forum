from django.db import models
from django.contrib.auth.models import User, Group
from django.utils import timezone
from django.urls import reverse


class Application(models.Model):
    """Модель заявки на вступление в гильдию."""

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

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='applications', verbose_name='Кандидат')
    player_class = models.CharField('Класс персонажа', max_length=20)

    development_plans = models.TextField('Планы на развитие персонажа на 2 месяца')

    # Скриншоты окна характеристик из игры — по ним администратор сверяет статы сетов из анкеты.
    screenshot_pa = models.ImageField('Скриншот сета ПА', upload_to='applications/screenshots/%Y/%m/%d/',
                                      blank=True, null=True)
    screenshot_pz = models.ImageField('Скриншот сета ПЗ', upload_to='applications/screenshots/%Y/%m/%d/',
                                      blank=True, null=True)

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
        return vote_stats(votes_for, votes_against, votes_abstain)


def vote_stats(votes_for, votes_against, votes_abstain):
    """Голоса и проценты «за» и «против» (воздержавшиеся в процент не входят)."""
    decided = votes_for + votes_against
    percent_for = round(votes_for * 100 / decided) if decided else 0
    return {
        'for': votes_for,
        'against': votes_against,
        'abstain': votes_abstain,
        'total': decided + votes_abstain,
        'percent_for': percent_for,
        'percent_against': 100 - percent_for if decided else 0,
    }


class ApplicationVote(models.Model):
    VOTE_CHOICES = [
        ('for', 'За'),
        ('against', 'Против'),
        ('abstain', 'Воздержался'),
    ]

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='votes', verbose_name='Заявка')
    voter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='application_votes', verbose_name='Голосующий')
    vote = models.CharField('Голос', max_length=10, choices=VOTE_CHOICES)
    comment = models.TextField('Комментарий', blank=True)
    created_at = models.DateTimeField('Дата голосования', auto_now_add=True)

    class Meta:
        verbose_name = 'Голос'
        verbose_name_plural = 'Голоса'
        unique_together = ['application', 'voter']

    def __str__(self):
        return f'{self.voter.username} - {self.get_vote_display()}'


class ApplicationComment(models.Model):
    """Комментарий в обсуждении заявки — отдельно от голоса, писать можно сколько угодно."""

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='comments', verbose_name='Заявка')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='application_comments', verbose_name='Автор')
    text = models.TextField('Комментарий')
    created_at = models.DateTimeField('Дата', auto_now_add=True)

    class Meta:
        verbose_name = 'Комментарий к заявке'
        verbose_name_plural = 'Комментарии к заявкам'
        ordering = ['created_at']

    def __str__(self):
        return f'{self.author.username}: {self.text[:40]}'