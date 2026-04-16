from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse
from django.core.validators import MinValueValidator
from django.templatetags.static import static

class AuctionLot(models.Model):
    STATUS_CHOICES = [
        ('active', 'Активен'),
        ('ended', 'Завершен'),
        ('cancelled', 'Отменен'),
    ]
    
    # Типы иконок
    ICON_CHOICES = [
        ('wheel_of_fate', 'Колесо Судьбы'),
        ('stone_of_universe', 'Камень мироздания'),
        ('opal', 'Опал Лунной Кошки'),
        ('divinity_stone', 'Камень божества'),
        ('great_meteorite', 'Великий метеорит'),
        ('rune_set_7', 'Набор рун (7ур)'),
        ('time_yarn', 'Пряжа времени'),
        ('rune_set_9', 'Набор рун 9 ур'),
        ('absolute_stones', 'Камни абсолюта'),
        ('custom', 'Своя картинка'),
    ]
    
    # Основная информация
    name = models.CharField('Название лота', max_length=200)
    slug = models.SlugField(unique=True, max_length=200)
    description = models.TextField('Описание', blank=True)
    
    # Выбор иконки или своей картинки
    icon_choice = models.CharField(
        'Выбор иконки', 
        max_length=30, 
        choices=ICON_CHOICES, 
        default='custom',
        help_text='Выберите иконку или "Своя картинка" для загрузки своего изображения'
    )
    
    # Своя картинка (показывается только если выбрано custom)
    custom_image = models.ImageField(
        'Своя картинка', 
        upload_to='auction/lots/', 
        blank=True, 
        null=True,
        help_text='Загрузите свою картинку (только если выбрано "Своя картинка")'
    )
    
    # Аукционные параметры
    initial_price = models.IntegerField('Начальная цена', validators=[MinValueValidator(1)])
    current_price = models.IntegerField('Текущая цена', default=0)
    min_step = models.IntegerField('Минимальный шаг ставки', default=1, validators=[MinValueValidator(1)])
    
    # Количество победителей
    max_winners = models.IntegerField('Максимум победителей', default=1, validators=[MinValueValidator(1)])
    
    # Временные параметры
    start_date = models.DateTimeField('Дата начала', default=timezone.now)
    end_date = models.DateTimeField('Дата окончания')
    
    # Статус
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default='active')
    
    # Мета
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлен', auto_now=True)
    
    class Meta:
        verbose_name = 'Аукционный лот'
        verbose_name_plural = 'Аукционные лоты'
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if self.current_price == 0:
            self.current_price = self.initial_price
        super().save(*args, **kwargs)
    
    def get_absolute_url(self):
        return reverse('auction:lot_detail', args=[self.slug])
    
    def get_image_url(self):
        """Возвращает URL изображения (иконку или загруженную картинку)"""
        if self.icon_choice == 'custom' and self.custom_image:
            return self.custom_image.url
        
        icons = {
            'wheel_of_fate': 'auction_icons/wheel_of_fate.png',
            'stone_of_universe': 'auction_icons/stone_of_universe.png',
            'opal': 'auction_icons/opal.png',
            'divinity_stone': 'auction_icons/divinity_stone.png',
            'great_meteorite': 'auction_icons/great_meteorite.png',
            'rune_set_7': 'auction_icons/rune_set_7.png',
            'time_yarn': 'auction_icons/time_yarn.png',
            'rune_set_9': 'auction_icons/rune_set_9.png',
            'absolute_stones': 'auction_icons/absolute_stones.png',
        }
        icon_path = icons.get(self.icon_choice, '')
        if icon_path:
            return static(icon_path)
        return ''
    
    @property
    def is_active(self):
        """Проверяет, активен ли аукцион"""
        return self.status == 'active' and timezone.now() < self.end_date
    
    @property
    def time_left(self):
        """Возвращает оставшееся время в секундах"""
        if timezone.now() >= self.end_date:
            return 0
        return (self.end_date - timezone.now()).total_seconds()
    
    @property
    def winners_count(self):
        """Количество победителей"""
        return self.bids.filter(is_winner=True).count()
    
    @property
    def total_bids_count(self):
        """Общее количество ставок"""
        return self.bids.count()
    
    def get_winner_bids(self):
        """Возвращает ставки победителей"""
        return self.bids.filter(is_winner=True).order_by('-bid_amount')
    
    def process_auction_end(self):
        """Обрабатывает завершение аукциона"""
        if self.status != 'active' or timezone.now() < self.end_date:
            return False
        
        all_bids = self.bids.filter(is_winner=False).order_by('-bid_amount', 'created_at')
        
        winners = []
        seen_users = set()
        
        for bid in all_bids:
            if len(winners) >= self.max_winners:
                break
            
            if bid.bidder.id not in seen_users:
                bid.is_winner = True
                bid.save()
                winners.append(bid)
                seen_users.add(bid.bidder.id)
                
                profile = bid.bidder.profile
                if profile.spend_points(bid.bid_amount):
                    PointsTransaction.objects.create(
                        user=bid.bidder,
                        lot=self,
                        amount=bid.bid_amount,
                        transaction_type='debit',
                        description=f'Выигрыш в аукционе: {self.name}'
                    )
        
        self.status = 'ended'
        self.save()
        
        return True


class AuctionBid(models.Model):
    """Модель ставки"""
    lot = models.ForeignKey(AuctionLot, on_delete=models.CASCADE, related_name='bids')
    bidder = models.ForeignKey(User, on_delete=models.CASCADE, related_name='auction_bids')
    bid_amount = models.IntegerField('Сумма ставки', validators=[MinValueValidator(1)])
    created_at = models.DateTimeField('Время ставки', auto_now_add=True)
    is_winner = models.BooleanField('Победитель', default=False)
    
    class Meta:
        verbose_name = 'Ставка'
        verbose_name_plural = 'Ставки'
        ordering = ['-bid_amount', 'created_at']
    
    def __str__(self):
        return f'{self.bidder.username} - {self.bid_amount} - {self.lot.name}'


class PointsTransaction(models.Model):
    """Модель транзакций очков активности"""
    TRANSACTION_TYPES = [
        ('credit', 'Начисление'),
        ('debit', 'Списание'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='points_transactions')
    lot = models.ForeignKey(AuctionLot, on_delete=models.CASCADE, related_name='transactions', null=True, blank=True)
    amount = models.IntegerField('Сумма')
    transaction_type = models.CharField('Тип', max_length=10, choices=TRANSACTION_TYPES)
    description = models.CharField('Описание', max_length=255)
    created_at = models.DateTimeField('Время операции', auto_now_add=True)
    
    class Meta:
        verbose_name = 'Транзакция'
        verbose_name_plural = 'Транзакции'
        ordering = ['-created_at']
    
    def __str__(self):
        return f'{self.user.username} - {self.amount} - {self.description}'
