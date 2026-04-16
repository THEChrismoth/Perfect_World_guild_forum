from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from .models import AuctionLot, AuctionBid
from .forms import BidForm

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
    
    if lot.status == 'active' and timezone.now() >= lot.end_date:
        lot.process_auction_end()
        lot.refresh_from_db()
    
    # Обработка формы ставки
    if request.method == 'POST':
        if not lot.is_active:
            messages.error(request, 'Аукцион уже завершен')
            return redirect('auction:lot_detail', slug=lot.slug)
        
        bid_amount = request.POST.get('bid_amount')
        
        if bid_amount:
            try:
                bid_amount = int(bid_amount)
                # Минимальная ставка - от начальной цены, а не от текущей!
                min_bid = lot.initial_price + lot.min_step
                user_balance = request.user.profile.activity_points
                
                if bid_amount < min_bid:
                    messages.error(request, f'Минимальная ставка: {min_bid} ⭐')
                elif user_balance < bid_amount:
                    messages.error(request, f'Недостаточно очков активности! Ваш баланс: {user_balance} ⭐')
                else:
                    AuctionBid.objects.create(
                        lot=lot,
                        bidder=request.user,
                        bid_amount=bid_amount
                    )
                    # Обновляем текущую цену только если ставка больше текущей
                    if bid_amount > lot.current_price:
                        lot.current_price = bid_amount
                        lot.save()
                    messages.success(request, f'Ставка {bid_amount} ⭐ успешно сделана!')
            except ValueError:
                messages.error(request, 'Введите корректную сумму')
        else:
            messages.error(request, 'Введите сумму ставки')
        
        return redirect('auction:lot_detail', slug=lot.slug)
    
    bids = lot.bids.all().order_by('-bid_amount', 'created_at')[:20]
    winners = lot.get_winner_bids() if lot.status == 'ended' else []
    end_timestamp = int(lot.end_date.timestamp() * 1000) if lot.end_date else 0
    
    # Минимальная ставка для отображения - от начальной цены
    min_bid_display = lot.initial_price + lot.min_step
    
    context = {
        'lot': lot,
        'bids': bids,
        'can_bid': lot.is_active and request.user.is_authenticated,
        'winners': winners,
        'user_balance': request.user.profile.activity_points if request.user.is_authenticated else 0,
        'min_bid': min_bid_display,  # Минимальная ставка от начальной цены
        'end_timestamp': end_timestamp,
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
    
    for bid in my_bids:
        if bid.is_winner:
            won_bids.append(bid)
        elif bid.lot.is_active:
            active_bids.append(bid)
        else:
            lost_bids.append(bid)
    
    context = {
        'active_bids': active_bids,
        'won_bids': won_bids,
        'lost_bids': lost_bids,
    }
    return render(request, 'auction/my_bids.html', context)
