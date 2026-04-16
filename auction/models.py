from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse
from django.core.validators import MinValueValidator

class AuctionLot(models.Model):
    STATUS_CHOICES = [
        ('active', 'Активен'),
        ('ended', 'Завершен'),
        ('cancelled', 'Отменен'),
    ]
    
    # Основная информация
    name = models.CharField('Название лота', max_length=200)
    slug = models.SlugField(unique=True, max_length=200)
    description = models.TextField('Описание', blank=True)
    image = models.ImageField('Изображение лота', upload_to='auction/lots/', blank=True, null=True)
    
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
        
        # Получаем все ставки, отсортированные по убыванию суммы
        all_bids = self.bids.filter(is_winner=False).order_by('-bid_amount', 'created_at')
        
        # Определяем победителей (первые max_winners)
        winners = []
        seen_users = set()
        
        for bid in all_bids:
            if len(winners) >= self.max_winners:
                break
            
            # Пользователь может выиграть только один раз в этом лоте
            if bid.bidder.id not in seen_users:
                bid.is_winner = True
                bid.save()
                winners.append(bid)
                seen_users.add(bid.bidder.id)
                
                # Списание очков активности у победителя
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
