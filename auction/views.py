from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from .models import AuctionLot, AuctionBid, PointsTransaction

def check_auction_access(user):
    """Проверяет, имеет ли пользователь доступ к аукциону"""
    from forum.models import SubCategory
    
    if user.is_superuser:
        return True
    
    try:
        auction_subcategory = SubCategory.objects.get(is_auction=True)
        return auction_subcategory.is_visible_to_user(user)
    except SubCategory.DoesNotExist:
        return False
    except Exception:
        return False

def auction_index(request):
    """Главная страница аукциона"""
    if not check_auction_access(request.user):
        raise PermissionDenied("У вас нет доступа к аукциону")
    
    active_lots = AuctionLot.objects.filter(
        status='active',
        end_date__gt=timezone.now()
    ).order_by('end_date')
    
    ended_lots = AuctionLot.objects.filter(
        status='ended'
    ).order_by('-end_date')[:10]
    
    stats = {
        'active_count': active_lots.count(),
        'total_lots': AuctionLot.objects.count(),
        'total_bids': AuctionBid.objects.count(),
    }
    
    from django.core.paginator import Paginator
    paginator = Paginator(active_lots, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'active_lots': page_obj,
        'ended_lots': ended_lots,
        'stats': stats,
    }
    return render(request, 'auction/auction_index.html', context)

@login_required
def lot_detail(request, slug):
    """Детальная страница лота"""
    if not check_auction_access(request.user):
        raise PermissionDenied("У вас нет доступа к аукциону")
    
    lot = get_object_or_404(AuctionLot, slug=slug)
    
    # Проверяем и обновляем статус если нужно
    if lot.status == 'active' and timezone.now() >= lot.end_date:
        lot.process_auction_end()
        lot.refresh_from_db()
    
    # Обработка формы ставки (только если аукцион активен)
    if request.method == 'POST' and lot.is_active:
        bid_amount = request.POST.get('bid_amount')
        
        if bid_amount:
            try:
                bid_amount = int(bid_amount)
                min_bid = lot.current_price + lot.min_step
                
                # Проверяем минимальную ставку
                if bid_amount < min_bid:
                    messages.error(request, f'Минимальная ставка: {min_bid} ⭐')
                else:
                    # Проверяем, не делал ли пользователь уже ставку-лидера (замороженную)
                    existing_frozen_bid = lot.bids.filter(bidder=request.user, is_frozen=True).first()
                    if existing_frozen_bid:
                        messages.error(request, 'Вы уже являетесь лидером на этом аукционе! Ваша ставка активна и очки заморожены.')
                        return redirect('auction:lot_detail', slug=lot.slug)
                    
                    # Проверяем доступные очки с учетом заморозки
                    available_points = request.user.profile.get_available_points()
                    
                    if available_points < bid_amount:
                        messages.error(request, f'Недостаточно доступных очков. Доступно: {available_points} ⭐ (Всего: {request.user.profile.activity_points} ⭐)')
                    else:
                        # Находим текущего лидера (замороженную ставку)
                        current_leader = lot.get_current_leader()
                        
                        if current_leader:
                            # Размораживаем очки предыдущего лидера
                            current_leader.is_frozen = False
                            current_leader.status = 'outbid'
                            current_leader.save()
                            
                            # Создаем транзакцию разморозки
                            PointsTransaction.objects.create(
                                user=current_leader.bidder,
                                lot=lot,
                                amount=current_leader.bid_amount,
                                transaction_type='unfreeze',
                                description=f'Разморозка очков - ставка перебита в аукционе: {lot.name}'
                            )
                            
                            messages.info(request, f'Ставка {current_leader.bid_amount} ⭐ была перебита! Очки разморожены.')
                        
                        # Создаем новую ставку (сразу замороженную)
                        bid = AuctionBid.objects.create(
                            lot=lot,
                            bidder=request.user,
                            bid_amount=bid_amount,
                            status='frozen',
                            is_frozen=True,
                            is_winner=False
                        )
                        
                        # Обновляем текущую цену лота
                        lot.current_price = bid_amount
                        lot.save()
                        
                        # Создаем транзакцию заморозки
                        PointsTransaction.objects.create(
                            user=request.user,
                            lot=lot,
                            amount=bid_amount,
                            transaction_type='freeze',
                            description=f'Заморозка очков по ставке на лот: {lot.name}'
                        )
                        
                        messages.success(request, f'Ставка {bid_amount} ⭐ успешно сделана! Вы теперь лидер. Очки заморожены.')
            except ValueError:
                messages.error(request, 'Введите корректную сумму')
        else:
            messages.error(request, 'Введите сумму ставки')
        
        return redirect('auction:lot_detail', slug=lot.slug)
    
    # ПОКАЗЫВАЕМ ВСЕ СТАВКИ для истории
    all_bids = lot.bids.all().order_by('-bid_amount', 'created_at')
    
    # Проверяем, есть ли у пользователя ЗАМОРОЖЕННАЯ ставка на этот лот (он лидер)
    user_frozen_bid = None
    user_available_points = 0
    
    if request.user.is_authenticated:
        user_frozen_bid = lot.bids.filter(bidder=request.user, is_frozen=True).first()
        user_available_points = request.user.profile.get_available_points()
    
    winners = lot.get_winner_bids() if lot.status == 'ended' else []
    end_timestamp = int(lot.end_date.timestamp() * 1000) if lot.end_date and lot.is_active else 0
    
    # Находим текущего лидера
    current_leader = lot.get_current_leader()
    
    # Может ли пользователь сделать ставку
    can_bid = lot.is_active and request.user.is_authenticated and not user_frozen_bid
    
    context = {
        'lot': lot,
        'bids': all_bids,
        'can_bid': can_bid,
        'winners': winners,
        'user_balance': request.user.profile.activity_points if request.user.is_authenticated else 0,
        'available_points': user_available_points,
        'min_bid': lot.current_price + lot.min_step if lot.is_active else 0,
        'end_timestamp': end_timestamp,
        'user_frozen_bid': user_frozen_bid,
        'current_leader': current_leader,
    }
    return render(request, 'auction/lot_detail.html', context)

@login_required
def my_bids(request):
    """Мои ставки"""
    if not check_auction_access(request.user):
        raise PermissionDenied("У вас нет доступа к аукциону")
    
    my_bids = AuctionBid.objects.filter(bidder=request.user).select_related('lot').order_by('-created_at')
    
    active_bids = []
    won_bids = []
    lost_bids = []
    frozen_bids = []
    outbid_bids = []
    
    for bid in my_bids:
        if bid.is_winner:
            won_bids.append(bid)
        elif bid.is_frozen:
            frozen_bids.append(bid)
        elif bid.status == 'outbid':
            outbid_bids.append(bid)
        elif bid.status == 'lost':
            lost_bids.append(bid)
        elif bid.lot.is_active:
            active_bids.append(bid)
        else:
            lost_bids.append(bid)
    
    context = {
        'active_bids': active_bids,
        'won_bids': won_bids,
        'lost_bids': lost_bids,
        'frozen_bids': frozen_bids,
        'outbid_bids': outbid_bids,
    }
    return render(request, 'auction/my_bids.html', context)
