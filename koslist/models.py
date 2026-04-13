from django.db import models
#from django.utils import choices
from django.templatetags.static import static

class Guild(models.Model):
    name = models.CharField('Название гильдии', max_length = 100)
    url_obs = models.URLField('Ссылка на гильдию', blank = True, null = False)

    class Meta:
        ordering = ('name',)
        verbose_name = 'Гильдию'
        verbose_name_plural = 'Гильдии'

    def __str__(self):
        return self.name

class Player(models.Model):
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

    name = models.CharField('Ник персонажа', max_length = 20)
    player_class = models.CharField('Класс персонажа', max_length = 20, choices = CLASS_CHOICES)
    url_obs = models.CharField('Ссылка на персонажа', blank =True, null = False)

    class Meta:
        ordering = ('name',)
        verbose_name = 'Игрока'
        verbose_name_plural = 'Игроки'

    def __str__(self):
        return self.name

    def get_icon_url(self):
        """Возвращаем URL иконки для класса персонажа"""
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
        }
        icon_path = icons.get(self.player_class, '')
        if icon_path:
            return static(icon_path)
        return ''




