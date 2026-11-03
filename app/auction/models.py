from datetime import timedelta

from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse
from django.core.validators import MinValueValidator
from uuslug import uuslug
from notifications.utils import send_notification

# Ставка, сделанная меньше чем за это время до конца, продлевает торги на столько же...
ANTI_SNIPE = timedelta(minutes=5)
# ...но не дальше этого предела сверх назначенного времени окончания: потом торги заканчиваются в любом случае.
ANTI_SNIPE_LIMIT = timedelta(minutes=30)


class AuctionLot(models.Model):
    STATUS_CHOICES = [
        ('active', 'Активен'),
        ('ended', 'Завершен'),
        ('cancelled', 'Отменен'),
    ]
    
    # Основная информация.
    name = models.CharField('Название лота', max_length=200)
    slug = models.SlugField(unique=True, max_length=200, blank=True)
    description = models.TextField('Описание', blank=True)
    image = models.ImageField(
        'Картинка',
        upload_to='auction/lots/',
        blank=True,
        null=True,
        help_text='Картинка предмета из игры. Без картинки на сайте будет значок аукциона'
    )

    # Аукционные параметры.
    initial_price = models.IntegerField('Начальная цена', validators=[MinValueValidator(1)])
    current_price = models.IntegerField('Текущая цена', default=0)
    min_step = models.IntegerField('Минимальный шаг ставки', default=1, validators=[MinValueValidator(1)])
    
    # Временные параметры.
    start_date = models.DateTimeField('Дата начала', default=timezone.now)
    end_date = models.DateTimeField(
        'Окончание торгов', null=True, blank=True,
        help_text='Когда время выйдет, лот завершится сам: лидер платит, остальным очки возвращаются. '
                  'Ставка в последние 5 минут продлевает торги на 5 минут, всего не больше чем на 30 минут'
    )
    # Назначенное время окончания до продлений — от него считается предел продления.
    # Пусто, пока торги не продлевали; сбрасывается, когда администратор меняет окончание.
    original_end_date = models.DateTimeField('Окончание до продлений', null=True, blank=True, editable=False)
    
    # Статус.
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default='active')
    
    # Кто завершил аукцион.
    ended_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='ended_auctions',
        verbose_name='Завершил'
    )
    ended_at = models.DateTimeField('Дата завершения', null=True, blank=True)
    
    # Мета.
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
        """URL картинки лота или пустая строка, если её не загрузили."""
        return self.image.url if self.image else ''

    @property
    def is_active(self):
        """Проверяет, активен ли аукцион (только по статусу)."""
        return self.status == 'active'
    
    @property
    def can_bid(self):
        """Может ли пользователь делать ставки (активен и время не истекло)."""
        if self.status != 'active':
            return False
        if self.end_date and timezone.now() >= self.end_date:
            return False
        return True
    
    @property
    def is_time_expired(self):
        """Проверяет, истекло ли плановое время (но админ еще не завершил)."""
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
        """Обрабатывает завершение аукциона администратором."""
        from profiles.models import Profile

        with transaction.atomic():
            # Перечитываем лот с блокировкой, чтобы аукцион нельзя было
            # завершить дважды (два админа, двойной клик, cron).
            lot = AuctionLot.objects.select_for_update().get(pk=self.pk)
            if lot.status != 'active':
                return False, "Аукцион уже завершен или отменен"

            leader = None
            if force_winner_id:
                leader = lot.bids.filter(bidder_id=force_winner_id, is_frozen=True).first()
                if not leader:
                    leader = lot.bids.filter(bidder_id=force_winner_id).order_by('-bid_amount').first()

            if not leader:
                leader = lot.get_current_leader()

            if leader:
                profile = Profile.objects.select_for_update().get(user=leader.bidder)

                # Снимаем заморозку перед списанием, иначе ставка
                # не учитывается в доступных очках.
                leader.is_frozen = False
                leader.save(update_fields=['is_frozen'])

                # Победителем ставка становится только после успешного списания.
                # Если очков не хватает — откатываем всё, аукцион остается активным.
                if not profile.spend_points_auction(leader.bid_amount):
                    transaction.set_rollback(True)
                    return False, (
                        f'У {leader.bidder.username} недостаточно очков для оплаты ставки '
                        f'{leader.bid_amount} ⭐. Выберите другого победителя или скорректируйте баланс'
                    )

                leader.is_winner = True
                leader.status = 'won'
                leader.save(update_fields=['is_winner', 'status'])

                PointsTransaction.objects.create(
                    user=leader.bidder,
                    lot=lot,
                    amount=leader.bid_amount,
                    transaction_type='debit',
                    description=f'Выигрыш в аукционе: {lot.name}'
                )

                send_notification(
                    user=leader.bidder,
                    title='🏆 ВЫ ВЫИГРАЛИ АУКЦИОН!',
                    message=f'Поздравляем! Вы выиграли лот "{lot.name}" со ставкой {leader.bid_amount} ⭐\n\nОчки списаны с вашего баланса.',
                    notification_type='auction_win',
                    link=reverse('auction:lot_detail', args=[lot.slug])
                )

                # Все остальные замороженные ставки размораживаем.
                other_bids = lot.bids.filter(is_frozen=True).exclude(id=leader.id)
                for bid in other_bids:
                    bid.is_frozen = False
                    bid.status = 'lost'
                    bid.save()

                    PointsTransaction.objects.create(
                        user=bid.bidder,
                        lot=lot,
                        amount=bid.bid_amount,
                        transaction_type='unfreeze',
                        description=f'Возврат замороженных очков после завершения аукциона: {lot.name}'
                    )

                    send_notification(
                        user=bid.bidder,
                        title='❌ Аукцион завершен',
                        message=f'Аукцион "{lot.name}" завершен. Ваша ставка {bid.bid_amount} ⭐ была перебита. Очки разморожены.',
                        notification_type='auction_lost',
                        link=reverse('auction:lot_detail', args=[lot.slug])
                    )
            elif ended_by_user:
                send_notification(
                    user=ended_by_user,
                    title='ℹ️ Аукцион завершен без победителя',
                    message=f'Аукцион "{lot.name}" завершен. Не было сделано ни одной ставки.',
                    notification_type='auction_info',
                    link=reverse('auction:lot_detail', args=[lot.slug])
                )

            lot.status = 'ended'
            lot.ended_by = ended_by_user
            lot.ended_at = timezone.now()
            lot.save()

        self.refresh_from_db()
        return True, "Аукцион успешно завершен"

    def cancel_auction(self, cancelled_by_user=None):
        """Отмена аукциона с возвратом всех очков."""
        with transaction.atomic():
            lot = AuctionLot.objects.select_for_update().get(pk=self.pk)
            if lot.status != 'active':
                return False, "Можно отменить только активный аукцион"

            frozen_bids = lot.bids.filter(is_frozen=True)
            for bid in frozen_bids:
                bid.is_frozen = False
                bid.status = 'cancelled'
                bid.save()

                PointsTransaction.objects.create(
                    user=bid.bidder,
                    lot=lot,
                    amount=bid.bid_amount,
                    transaction_type='unfreeze',
                    description=f'Возврат очков при отмене аукциона: {lot.name}'
                )

                send_notification(
                    user=bid.bidder,
                    title='⚠️ Аукцион отменен',
                    message=f'Аукцион "{lot.name}" был отменен администратором. Ваша ставка {bid.bid_amount} ⭐ разморожена.',
                    notification_type='auction_cancelled',
                    link=reverse('auction:lot_detail', args=[lot.slug])
                )

            lot.status = 'cancelled'
            lot.ended_by = cancelled_by_user
            lot.ended_at = timezone.now()
            lot.save()

        self.refresh_from_db()
        return True, "Аукцион отменен, все очки возвращены"


class AuctionBid(models.Model):
    """Модель ставки."""
    BID_STATUS = [
        ('active', 'Активна'),
        ('frozen', 'Заморожена'),
        ('won', 'Выиграна'),
        ('lost', 'Проиграна'),
        ('outbid', 'Перебита'),
        ('cancelled', 'Отменена'),
    ]
    
    lot = models.ForeignKey(AuctionLot, on_delete=models.CASCADE, related_name='bids', verbose_name='Лот')
    bidder = models.ForeignKey(User, on_delete=models.CASCADE, related_name='auction_bids', verbose_name='Участник')
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
    """Модель транзакций очков активности."""
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
