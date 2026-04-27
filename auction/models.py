from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse
from django.core.validators import MinValueValidator
from django.templatetags.static import static
from uuslug import uuslug
from notifications.utils import send_notification


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
    slug = models.SlugField(unique=True, max_length=200, blank=True)
    description = models.TextField('Описание', blank=True)
    
    # Выбор иконки или своей картинки
    icon_choice = models.CharField(
        'Выбор иконки', 
        max_length=30, 
        choices=ICON_CHOICES, 
        default='custom',
        help_text='Выберите иконку или "Своя картинка" для загрузки своего изображения'
    )
    
    # Своя картинка
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
    
    # Временные параметры
    start_date = models.DateTimeField('Дата начала', default=timezone.now)
    end_date = models.DateTimeField('Дата окончания (план)', null=True, blank=True, 
                                     help_text='Плановая дата окончания. После этой даты ставки будут запрещены до завершения админом')
    
    # Статус
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default='active')
    
    # Кто завершил аукцион
    ended_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='ended_auctions',
        verbose_name='Завершил'
    )
    ended_at = models.DateTimeField('Дата завершения', null=True, blank=True)
    
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
        
        if not self.slug:
            self.slug = uuslug(self.name, instance=self, max_length=200)
        
        super().save(*args, **kwargs)
    
    def get_absolute_url(self):
        return reverse('auction:lot_detail', args=[self.slug])
    
    def get_image_url(self):
        """Возвращает URL изображения"""
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
        """Проверяет, активен ли аукцион (только по статусу)"""
        return self.status == 'active'
    
    @property
    def can_bid(self):
        """Может ли пользователь делать ставки (активен И время не истекло)"""
        if self.status != 'active':
            return False
        if self.end_date and timezone.now() >= self.end_date:
            return False
        return True
    
    @property
    def is_time_expired(self):
        """Проверяет, истекло ли плановое время (но админ еще не завершил)"""
        return self.status == 'active' and self.end_date and timezone.now() >= self.end_date
    
    @property
    def winners_count(self):
        return 1 if self.bids.filter(is_winner=True).exists() else 0
    
    @property
    def total_bids_count(self):
        return self.bids.count()
    
    def get_winner_bids(self):
        return self.bids.filter(is_winner=True).order_by('-bid_amount')
    
    def get_current_leader(self):
        return self.bids.filter(is_frozen=True).order_by('-bid_amount').first()
    
    def process_auction_end(self, ended_by_user=None, force_winner_id=None):
        """Обрабатывает завершение аукциона администратором"""
        if self.status != 'active':
            return False, "Аукцион уже завершен или отменен"
        
        leader = None
        if force_winner_id:
            try:
                leader = self.bids.filter(bidder_id=force_winner_id, is_frozen=True).first()
                if not leader:
                    leader = self.bids.filter(bidder_id=force_winner_id).order_by('-bid_amount').first()
            except:
                pass
        
        if not leader:
            leader = self.get_current_leader()
        
        if leader:
            # Победитель
            leader.is_winner = True
            leader.status = 'won'
            leader.is_frozen = False
            leader.save()
            
            # Списываем очки
            profile = leader.bidder.profile
            if hasattr(profile, 'spend_points_auction'):
                profile.spend_points_auction(leader.bid_amount)
            
            PointsTransaction.objects.create(
                user=leader.bidder,
                lot=self,
                amount=leader.bid_amount,
                transaction_type='debit',
                description=f'Выигрыш в аукционе: {self.name}'
            )
            
            try:
                send_notification(
                    user=leader.bidder,
                    title='🏆 ВЫ ВЫИГРАЛИ АУКЦИОН!',
                    message=f'Поздравляем! Вы выиграли лот "{self.name}" со ставкой {leader.bid_amount} ⭐\n\nОчки списаны с вашего баланса.',
                    notification_type='auction_win',
                    link=reverse('auction:lot_detail', args=[self.slug])
                )
            except:
                pass
            
            # Все остальные замороженные ставки размораживаем
            other_bids = self.bids.filter(is_frozen=True).exclude(id=leader.id)
            for bid in other_bids:
                bid.is_frozen = False
                bid.status = 'lost'
                bid.save()
                
                PointsTransaction.objects.create(
                    user=bid.bidder,
                    lot=self,
                    amount=bid.bid_amount,
                    transaction_type='unfreeze',
                    description=f'Возврат замороженных очков после завершения аукциона: {self.name}'
                )
                
                try:
                    send_notification(
                        user=bid.bidder,
                        title='❌ Аукцион завершен',
                        message=f'Аукцион "{self.name}" завершен. Ваша ставка {bid.bid_amount} ⭐ была перебита. Очки разморожены.',
                        notification_type='auction_lost',
                        link=reverse('auction:lot_detail', args=[self.slug])
                    )
                except:
                    pass
        else:
            try:
                send_notification(
                    user=ended_by_user,
                    title='ℹ️ Аукцион завершен без победителя',
                    message=f'Аукцион "{self.name}" завершен. Не было сделано ни одной ставки.',
                    notification_type='auction_info',
                    link=reverse('auction:lot_detail', args=[self.slug])
                )
            except:
                pass
        
        self.status = 'ended'
        self.ended_by = ended_by_user
        self.ended_at = timezone.now()
        self.save()
        
        return True, "Аукцион успешно завершен"
    
    def cancel_auction(self, cancelled_by_user=None):
        """Отмена аукциона с возвратом всех очков"""
        if self.status != 'active':
            return False, "Можно отменить только активный аукцион"
        
        frozen_bids = self.bids.filter(is_frozen=True)
        for bid in frozen_bids:
            bid.is_frozen = False
            bid.status = 'cancelled'
            bid.save()
            
            PointsTransaction.objects.create(
                user=bid.bidder,
                lot=self,
                amount=bid.bid_amount,
                transaction_type='unfreeze',
                description=f'Возврат очков при отмене аукциона: {self.name}'
            )
            
            try:
                send_notification(
                    user=bid.bidder,
                    title='⚠️ Аукцион отменен',
                    message=f'Аукцион "{self.name}" был отменен администратором. Ваша ставка {bid.bid_amount} ⭐ разморожена.',
                    notification_type='auction_cancelled',
                    link=reverse('auction:lot_detail', args=[self.slug])
                )
            except:
                pass
        
        self.status = 'cancelled'
        self.ended_by = cancelled_by_user
        self.ended_at = timezone.now()
        self.save()
        
        return True, "Аукцион отменен, все очки возвращены"


class AuctionBid(models.Model):
    """Модель ставки"""
    BID_STATUS = [
        ('active', 'Активна'),
        ('frozen', 'Заморожена'),
        ('won', 'Выиграна'),
        ('lost', 'Проиграна'),
        ('outbid', 'Перебита'),
        ('cancelled', 'Отменена'),
    ]
    
    lot = models.ForeignKey(AuctionLot, on_delete=models.CASCADE, related_name='bids')
    bidder = models.ForeignKey(User, on_delete=models.CASCADE, related_name='auction_bids')
    bid_amount = models.IntegerField('Сумма ставки', validators=[MinValueValidator(1)])
    created_at = models.DateTimeField('Время ставки', auto_now_add=True)
    is_winner = models.BooleanField('Победитель', default=False)
    is_frozen = models.BooleanField('Очки заморожены', default=False)
    status = models.CharField('Статус ставки', max_length=10, choices=BID_STATUS, default='active')
    
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
        ('freeze', 'Заморозка'),
        ('unfreeze', 'Разморозка'),
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
