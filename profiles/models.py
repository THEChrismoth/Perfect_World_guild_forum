from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from datetime import date
from django.templatetags.static import static

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
    birth_date = models.DateField('Дата рождения', blank=True, null=True)
    city = models.CharField('Город', max_length=100, blank=True, null=True)
    player_class = models.CharField('Класс персонажа', max_length=20, choices=CLASS_CHOICES, blank=True, null=True)
    
    # Характеристики (заполняются пользователем)
    hp = models.IntegerField(default=0, verbose_name='❤️ HP')
    mp = models.IntegerField(default=0, verbose_name='💧 MP')
    pa = models.IntegerField(default=0, verbose_name='ПА - Показатель Атаки')
    fa = models.IntegerField(default=0, verbose_name='ФА - Физическая атака')
    ma = models.IntegerField(default=0, verbose_name='МА - Магическая атака')
    pz = models.IntegerField(default=0, verbose_name='ПЗ - Показатель защиты')
    bd = models.IntegerField(default=0, verbose_name='БД - Боевой дух')
    bu = models.IntegerField(default=0, verbose_name='БУ - Бонус уровня')
    physical_defense = models.IntegerField(default=0, verbose_name='Физическая защита')
    magic_defense = models.IntegerField(default=0, verbose_name='Магическая защита')
    physical_pierce = models.IntegerField(default=0, verbose_name='Физический пробив')
    magic_pierce = models.IntegerField(default=0, verbose_name='Магический пробив')
    crit_damage = models.IntegerField(default=0, verbose_name='Крит. урон')
    crit_chance = models.IntegerField(default=0, verbose_name='Крит. шанс')
    accuracy = models.IntegerField(default=0, verbose_name='Меткость')
    dodge = models.IntegerField(default=0, verbose_name='Уклонение')
    
    # Очки активности (только для админа)
    activity_points = models.IntegerField('Очки активности', default=0, help_text='Изменяется только в админ-панели')
    activity_points = models.IntegerField('Очки активности', default=0, help_text='Изменяется только в админ-панели')
    spent_points = models.IntegerField('Потрачено очков активности', default=0, help_text='Общее количество потраченных очков')

    last_activity = models.DateTimeField('Последняя активность', auto_now=True, null=True, blank=True)

    def update_points(self, total_earned=None, spent=None):
        """Обновляет очки активности"""
        if total_earned is not None:
            # total_earned = activity_points + spent_points
            # activity_points = total_earned - spent_points
            new_activity = total_earned - self.spent_points
            if new_activity >= 0:
                self.activity_points = new_activity

        if spent is not None:
            # Если меняем потраченные, пересчитываем текущие
            if spent != self.spent_points:
                old_spent = self.spent_points
                self.spent_points = spent
                # Корректируем текущие очки
                self.activity_points = self.activity_points - (spent - old_spent)
                if self.activity_points < 0:
                    self.activity_points = 0

        self.save()

    @property
    def total_earned_points(self):
        """Всего начислено очков активности"""
        return self.activity_points + self.spent_points

    class Meta:
        verbose_name = 'редактировать профиль'
        verbose_name_plural = 'редактировать профили'
    
    def __str__(self):
        return f"Профиль {self.user.username}"
    
    def get_icon_url(self):
        """Возвращает URL иконки для класса персонажа"""
        icons = {
            'var': 'class_icon/voin.png',
            'mag': 'class_icon/mag.png',
            'luk': 'class_icon/luk.png',
            'zhrec': 'class_icon/zhrec.png',
            'obor': 'class_icon/obor.png',
            'dru': 'class_icon/dru.png',
            'sin': 'class_icon/sin.png',
            'sham': 'class_icon/sham.png',
            'mist': 'class_icon/mist.png',
            'strazh': 'class_icon/strazh.png',
            'pal': 'class_icon/pal.png',
            'strel': 'class_icon/strel.png',
            'priz': 'class_icon/priz.png',
            'zhnec': 'class_icon/zhnec.png',
            'makaka': 'class_icon/makaka.png',
            'bard': 'class_icon/bard1.png',
            'dk': 'class_icon/dk.png',
        }
        icon_path = icons.get(self.player_class, '')
        if icon_path:
            return static(icon_path)
        return ''
    
    def age(self):
        """Возвращает возраст пользователя"""
        if self.birth_date:
            today = date.today()
            return today.year - self.birth_date.year - ((today.month, today.day) < (self.birth_date.month, self.birth_date.day))
        return None

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Создает профиль только когда пользователь создается"""
    if created:
        Profile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Сохраняет профиль, только если он существует"""
    if hasattr(instance, 'profile'):  # Проверяем наличие профиля
        instance.profile.save()
