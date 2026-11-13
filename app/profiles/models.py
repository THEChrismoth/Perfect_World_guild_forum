from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.templatetags.static import static
from django.utils import timezone

from core.accents import ACCENT_CHOICES

# Тип атаки определяется классом персонажа.
MAGIC_CLASSES = frozenset({'mag', 'zhrec', 'dru', 'sham', 'mist', 'zhnec', 'bard'})


def damage_type(player_class):
    """Возвращает тип атаки и пробива для класса персонажа."""
    return 'magic' if player_class in MAGIC_CLASSES else 'physical'


# Иконки классов персонажей (static_src/class_icon/).
CLASS_ICONS = {
    'var': 'class_icon/var.png',
    'mag': 'class_icon/mag.png',
    'luk': 'class_icon/luk.png',
    'zhrec': 'class_icon/priest.png',
    'obor': 'class_icon/tank.png',
    'dru': 'class_icon/dru.png',
    'sin': 'class_icon/sin.png',
    'sham': 'class_icon/sham.png',
    'mist': 'class_icon/mist.png',
    'strazh': 'class_icon/sik.png',
    'pal': 'class_icon/pal.png',
    'strel': 'class_icon/gun.png',
    'priz': 'class_icon/gost.png',
    'zhnec': 'class_icon/koas.png',
    'makaka': 'class_icon/mk.png',
    'bard': 'class_icon/bard.png',
    'dk': 'class_icon/dk.png',
}


def class_icon_url(player_class):
    path = CLASS_ICONS.get(player_class)
    return static(path) if path else ''


# Пустое значение — «как у гильдии» (цвет по умолчанию из настроек сайта).
PROFILE_ACCENT_CHOICES = [('', 'Как у гильдии')] + ACCENT_CHOICES


class Profile(models.Model):
    CLASS_CHOICES = [
        ('var', 'Воин'),
        ('mag', 'Маг'),
        ('luk', 'Лучник'),
        ('zhrec', 'Жрец'),
        ('obor', 'Оборотень'),
        ('dru', 'Друид'),
        ('sin', 'Син'),
        ('sham', 'Шаман'),
        ('mist', 'Мистик'),
        ('strazh', 'Страж'),
        ('pal', 'Паладин'),
        ('strel', 'Стрелок'),
        ('priz', 'Призрак'),
        ('zhnec', 'Жнец'),
        ('makaka', 'Странник'),
        ('bard', 'Бард'),
        ('dk', 'Дух крови')
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    avatar = models.ImageField('Аватар', upload_to='avatars/', blank=True, null=True)
    ts3_id = models.CharField('TS3 ID', max_length=100, blank=True, null=True)
    player_class = models.CharField('Класс персонажа', max_length=20, choices=CLASS_CHOICES, blank=True, null=True)
    # Какой из двух комплектов брони показывать первым (характеристики — в GearSet).
    main_set = models.CharField('Основной сет', max_length=2, default='pa',
                                choices=[('pa', 'Сет ПА'), ('pz', 'Сет ПЗ')])

    # Очки активности (только для админа).
    activity_points = models.IntegerField('Очки активности', default=0, help_text='Изменяется только в админ-панели')
    spent_points = models.IntegerField('Потрачено очков активности', default=0, help_text='Общее количество потраченных очков')
    earned_points = models.IntegerField('Начислено очков активности', default=0, help_text='Общее количество начисленных очков')

    last_activity = models.DateTimeField('Последняя активность', default=timezone.now, null=True, blank=True)

    # Цвет оформления (пока — в админ-панели), список цветов — core/accents.py.
    accent_color = models.CharField('Цвет оформления', max_length=10, choices=PROFILE_ACCENT_CHOICES,
                                    blank=True, default='')

    def save(self, *args, **kwargs):
        # Автоматически поддерживаем консистентность при сохранении.
        if self.earned_points != self.activity_points + self.spent_points:
            self.earned_points = self.activity_points + self.spent_points
        super().save(*args, **kwargs)

    def add_points(self, points):
        """Начисление очков."""
        if points > 0:
            self.earned_points += points
            self.activity_points += points
            self.save()
    
    def spend_points(self, points):
        """Списание очков."""
        if points > 0 and points <= self.activity_points:
            self.spent_points += points
            self.activity_points -= points
            self.save()
            return True
        return False 

    def set_balance(self, new_balance):
        """Установка нового баланса (для администратора)."""
        if new_balance >= 0:
            # Корректируем earned_points чтобы баланс сходился.
            self.earned_points = new_balance + self.spent_points
            self.activity_points = new_balance
            self.save()

    @property
    def total_earned_points(self):
        """Всего начислено очков активности."""
        return self.earned_points

    # ========== МЕТОДЫ ДЛЯ АУКЦИОНА ==========
    
    def get_available_points(self):
        """Возвращает доступные очки (не замороженные)."""
        from auction.models import AuctionBid
        
        # Сумма всех замороженных ставок.
        frozen_amount = AuctionBid.objects.filter(
            bidder=self.user,
            is_frozen=True
        ).aggregate(total=models.Sum('bid_amount'))['total'] or 0
        
        return self.activity_points - frozen_amount

    def spend_points_auction(self, amount):
        """Списание очков для аукциона (только доступных, не замороженных)."""
        if amount <= 0:
            return False
        
        # Проверяем что достаточно доступных очков.
        available = self.get_available_points()
        if available >= amount and self.activity_points >= amount:
            self.activity_points -= amount
            self.spent_points += amount
            self.save()
            return True
        return False

    # ========================================

    class Meta:
        verbose_name = 'редактировать профиль'
        verbose_name_plural = 'редактировать профили'
    
    def __str__(self):
        return f"Профиль {self.user.username}"
    
    def get_icon_url(self):
        """Возвращает URL иконки для класса персонажа."""
        return class_icon_url(self.player_class)

    def gear_sets(self):
        """Оба комплекта: основной первым. Создаются вместе с пользователем, но старые аккаунты — на всякий случай."""
        sets = {gear.kind: gear for gear in self.user.gear_sets.all()}
        for kind in GearSet.KINDS:
            if kind not in sets:
                sets[kind] = GearSet.objects.create(user=self.user, kind=kind)
        return sorted(sets.values(), key=lambda gear: gear.kind != self.main_set)

    def main_gear(self):
        return self.gear_sets()[0]


class GearSet(models.Model):
    """Комплект брони. В игре их два — на атаку (ПА) и на защиту (ПЗ), меняются одной кнопкой в бою,
    поэтому у игрока два набора характеристик. Какой основной — Profile.main_set."""

    KIND_CHOICES = [('pa', 'Сет ПА'), ('pz', 'Сет ПЗ')]
    KINDS = [kind for kind, _ in KIND_CHOICES]
    # Характеристики сета — порядок для форм и копирования.
    STAT_FIELDS = ('hp', 'bd', 'bu', 'pa', 'fa', 'ma', 'physical_pierce', 'magic_pierce',
                   'pz', 'physical_defense', 'magic_defense')

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='gear_sets', verbose_name='Игрок')
    kind = models.CharField('Сет', max_length=2, choices=KIND_CHOICES)

    # Оба типа хранятся для сохранности данных; форма и профиль показывают тип по классу.
    hp = models.IntegerField(default=0, verbose_name='HP')
    bd = models.IntegerField(default=0, verbose_name='Боевой дух (БД)')
    bu = models.IntegerField(default=0, verbose_name='Бонус уровня (БУ)')
    pa = models.IntegerField(default=0, verbose_name='Показатель атаки (ПА)')
    fa = models.IntegerField(default=0, verbose_name='Физ. атака')
    ma = models.IntegerField(default=0, verbose_name='Маг. атака')
    physical_pierce = models.IntegerField(default=0, verbose_name='Физ. пробив')
    magic_pierce = models.IntegerField(default=0, verbose_name='Маг. пробив')
    pz = models.IntegerField(default=0, verbose_name='Показатель защиты (ПЗ)')
    physical_defense = models.IntegerField(default=0, verbose_name='Физ. защита')
    magic_defense = models.IntegerField(default=0, verbose_name='Маг. защита')

    class Meta:
        verbose_name = 'Сет брони'
        verbose_name_plural = 'Сеты брони'
        ordering = ['kind']
        constraints = [models.UniqueConstraint(fields=['user', 'kind'], name='unique_gear_set_per_user')]

    def __str__(self):
        return f'{self.get_kind_display()} — {self.user.username}'

    @property
    def attack_stats(self):
        """Возвращает атаку и пробив только своего типа для класса игрока."""
        magic = damage_type(self.user.profile.player_class) == 'magic'
        return [
            {'label': 'Маг. атака' if magic else 'Физ. атака', 'value': self.ma if magic else self.fa},
            {'label': 'Маг. пробив' if magic else 'Физ. пробив',
             'value': self.magic_pierce if magic else self.physical_pierce},
        ]

    def is_empty(self):
        return not any(getattr(self, field) for field in self.STAT_FIELDS)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Создает профиль и оба сета брони только когда пользователь создается."""
    if created:
        Profile.objects.create(user=instance)
        GearSet.objects.bulk_create([GearSet(user=instance, kind=kind) for kind in GearSet.KINDS])
