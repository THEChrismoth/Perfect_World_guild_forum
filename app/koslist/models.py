from django.db import models

from profiles.models import class_icon_url

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
        """Возвращает URL иконки для класса персонажа (иконки общие с профилями)."""
        return class_icon_url(self.player_class)




