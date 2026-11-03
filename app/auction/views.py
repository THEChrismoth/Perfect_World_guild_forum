from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count
from django.http import JsonResponse
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from core.roles import is_guild_member
from notifications.utils import send_notification
from profiles.models import Profile
from .models import ANTI_SNIPE, ANTI_SNIPE_LIMIT, AuctionLot, AuctionBid, PointsTransaction

def check_auction_access(user):
    """Аукцион открыт только членам гильдии (и суперпользователю)."""
    return is_guild_member(user)

def _points(user):
    """Баланс, доступные и замороженные в ставках очки игрока."""
    profile = user.profile
    available = profile.get_available_points()
    return {'balance': profile.activity_points, 'available': available, 'frozen': profile.activity_points - available}


def auction_index(request):
    """Главная страница аукциона: идущие торги карточками, завершённые — списком."""
    if not check_auction_access(request.user):
        raise PermissionDenied("У вас нет доступа к аукциону")

    active_lots = AuctionLot.objects.filter(status='active').annotate(bids_num=Count('bids')).order_by('end_date')
    ended_lots = (AuctionLot.objects.filter(status='ended').order_by('-ended_at')
                  .prefetch_related('bids__bidder')[:10])
    for lot in ended_lots:
        lot.winner = next((bid for bid in lot.bids.all() if bid.is_winner), None)

    page_obj = Paginator(active_lots, 12).get_page(request.GET.get('page'))

    context = {
        'active_lots': page_obj,
        'ended_lots': ended_lots,
        'points': _points(request.user),
        # Лоты, где игрок сейчас лидер, — на карточке метка «Вы лидер».
        'leading_ids': set(AuctionBid.objects.filter(bidder=request.user, is_frozen=True)
                           .values_list('lot_id', flat=True)),
    }
    return render(request, 'auction/auction_index.html', context)


def place_bid(request, lot_id, bid_amount):
    """Делает ставку на лот.

    Вся операция атомарна: лот и профиль блокируются, чтобы параллельные ставки
    не прошли проверки одновременно.
    """
    with transaction.atomic():
        lot = AuctionLot.objects.select_for_update().get(id=lot_id)
        # Блокируем профиль, чтобы одновременные ставки на разные лоты
        # не потратили одни и те же доступные очки.
        profile = Profile.objects.select_for_update().get(user=request.user)

        # Статус и время проверяем повторно уже под блокировкой.
        if not lot.can_bid:
            messages.error(request, 'Прием ставок на этот лот завершен')
            return

        min_bid = lot.current_price + lot.min_step
        if bid_amount < min_bid:
            messages.error(request, f'Минимальная ставка: {min_bid} ⭐')
            return

        # Проверяем, не делал ли пользователь уже ставку-лидера (замороженную).
        if lot.bids.filter(bidder=request.user, is_frozen=True).exists():
            messages.error(request, 'Вы уже являетесь лидером на этом аукционе! Ваша ставка активна и очки заморожены.')
            return

        # Проверяем доступные очки с учетом заморозки.
        available_points = profile.get_available_points()
        if available_points < bid_amount:
            messages.error(request, f'Недостаточно доступных очков. Доступно: {available_points} ⭐ (Всего: {profile.activity_points} ⭐)')
            return

        # Ставка в последние минуты продлевает торги, чтобы перебитый успел ответить,
        # но не дальше предела от назначенного времени — иначе торги могли бы тянуться бесконечно.
        extended = False
        now = timezone.now()
        if lot.end_date and lot.end_date - now < ANTI_SNIPE:
            planned_end = lot.original_end_date or lot.end_date
            new_end = min(now + ANTI_SNIPE, planned_end + ANTI_SNIPE_LIMIT)
            if new_end > lot.end_date:
                lot.original_end_date = planned_end
                lot.end_date = new_end
                extended = True

        # Находим текущего лидера (замороженную ставку).
        current_leader = lot.get_current_leader()

        if current_leader:
            # Размораживаем очки предыдущего лидера.
            current_leader.is_frozen = False
            current_leader.status = 'outbid'
            current_leader.save()

            # Создаем транзакцию разморозки.
            PointsTransaction.objects.create(
                user=current_leader.bidder,
                lot=lot,
                amount=current_leader.bid_amount,
                transaction_type='unfreeze',
                description=f'Разморозка очков - ставка перебита в аукционе: {lot.name}'
            )

            # Перебитый узнаёт сразу — особенно важно, когда игрок торгуется за несколько лотов.
            extended_text = f' Торги продлены до {timezone.localtime(lot.end_date):%H:%M}.' if extended else ''
            send_notification(
                user=current_leader.bidder,
                title='⚠️ Вашу ставку перебили',
                message=f'Ставку {current_leader.bid_amount} ⭐ на лот «{lot.name}» перебили: теперь {bid_amount} ⭐. '
                        f'Очки снова доступны — можно сделать новую ставку.{extended_text}',
                notification_type='auction',
                link=reverse('auction:lot_detail', args=[lot.slug]),
            )

        # Создаем новую ставку (сразу замороженную).
        AuctionBid.objects.create(
            lot=lot,
            bidder=request.user,
            bid_amount=bid_amount,
            status='frozen',
            is_frozen=True,
            is_winner=False
        )

        # Обновляем текущую цену лота (и время окончания, если торги продлены).
        lot.current_price = bid_amount
        lot.save(update_fields=['current_price', 'end_date', 'original_end_date', 'updated_at'])

        # Создаем транзакцию заморозки.
        PointsTransaction.objects.create(
            user=request.user,
            lot=lot,
            amount=bid_amount,
            transaction_type='freeze',
            description=f'Заморозка очков по ставке на лот: {lot.name}'
        )

    messages.success(request, f'Ставка {bid_amount} ⭐ успешно сделана! Вы теперь лидер. Очки заморожены.')
    if extended:
        messages.info(request, f'Ставка в последние минуты — торги продлены до {timezone.localtime(lot.end_date):%H:%M}.')


@login_required
def lot_detail(request, slug):
    """Детальная страница лота."""
    if not check_auction_access(request.user):
        raise PermissionDenied("У вас нет доступа к аукциону")

    lot = get_object_or_404(AuctionLot, slug=slug)

    # Проверяем, разрешены ли ставки (активен и время не истекло).
    bidding_allowed = lot.can_bid
    time_expired = lot.is_time_expired

    # Обработка формы ставки (только если разрешены ставки).
    if request.method == 'POST' and bidding_allowed:
        bid_amount = request.POST.get('bid_amount')

        if bid_amount:
            try:
                bid_amount = int(bid_amount)
            except ValueError:
                messages.error(request, 'Введите корректную сумму')
            else:
                place_bid(request, lot.id, bid_amount)
        else:
            messages.error(request, 'Введите сумму ставки')

        return redirect('auction:lot_detail', slug=lot.slug)

    bids = lot.bids.select_related('bidder').order_by('-bid_amount', 'created_at')
    user_frozen_bid = next((bid for bid in bids if bid.bidder_id == request.user.id and bid.is_frozen), None)
    points = _points(request.user)
    min_bid = lot.current_price + lot.min_step

    context = {
        'lot': lot,
        'bids': bids,
        'bidding_allowed': bidding_allowed,
        'time_expired': time_expired,
        'can_bid': bidding_allowed and not user_frozen_bid and points['available'] >= min_bid,
        'user_frozen_bid': user_frozen_bid,
        'winner': next((bid for bid in bids if bid.is_winner), None),
        'points': points,
        'min_bid': min_bid,
        # Быстрые суммы: минимальная, +2 и +5 шагов — если хватает очков.
        'quick_bids': [amount for amount in (min_bid, min_bid + lot.min_step * 2, min_bid + lot.min_step * 5)
                       if amount <= points['available']],
    }
    return render(request, 'auction/lot_detail.html', context)


@login_required
def lot_state(request, slug):
    """Состояние торгов для страницы лота: она опрашивает его и подхватывает продление и новые ставки."""
    if not check_auction_access(request.user):
        raise PermissionDenied("У вас нет доступа к аукциону")
    lot = get_object_or_404(AuctionLot, slug=slug)
    return JsonResponse({
        'status': lot.status,
        'end': int(lot.end_date.timestamp() * 1000) if lot.end_date else None,
        'price': lot.current_price,
        'bids': lot.bids.count(),
    })


@login_required
def my_bids(request):
    """Мои лоты: по каждому лоту — моя лучшая ставка и чем всё кончилось (или идёт)."""
    if not check_auction_access(request.user):
        raise PermissionDenied("У вас нет доступа к аукциону")

    by_lot = {}
    for bid in AuctionBid.objects.filter(bidder=request.user).select_related('lot').order_by('-bid_amount'):
        by_lot.setdefault(bid.lot_id, bid)  # первая — самая крупная ставка игрока на этом лоте
    for bid in AuctionBid.objects.filter(bidder=request.user, is_frozen=True):
        by_lot[bid.lot_id] = bid

    active, finished = [], []
    for bid in sorted(by_lot.values(), key=lambda bid: bid.created_at, reverse=True):
        lot = bid.lot
        if lot.status == 'active':
            bid.state = 'leading' if bid.is_frozen else 'outbid'
            active.append(bid)
        else:
            bid.state = 'won' if bid.is_winner else ('cancelled' if lot.status == 'cancelled' else 'lost')
            finished.append(bid)

    context = {
        'active': active,
        'finished': finished,
        'points': _points(request.user),
        'counts': {
            'leading': sum(bid.state == 'leading' for bid in active),
            'outbid': sum(bid.state == 'outbid' for bid in active),
            'won': sum(bid.state == 'won' for bid in finished),
        },
    }
    return render(request, 'auction/my_bids.html', context)
