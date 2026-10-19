from django.contrib import admin
from django.utils import timezone
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import path, reverse
from django.template.response import TemplateResponse
from django.http import HttpResponseRedirect
from .models import AuctionLot, AuctionBid, PointsTransaction


class AuctionBidInline(admin.TabularInline):
    model = AuctionBid
    extra = 0
    readonly_fields = ('bidder', 'bid_amount', 'created_at', 'is_winner', 'is_frozen', 'status')
    fields = ('bidder', 'bid_amount', 'created_at', 'is_winner', 'is_frozen', 'status')
    can_delete = False
    ordering = ('-bid_amount',)
    
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(AuctionLot)
class AuctionLotAdmin(admin.ModelAdmin):
    list_display = ('name', 'icon_choice', 'initial_price', 'current_price', 'status', 'ended_at', 'total_bids')
    list_filter = ('status', 'icon_choice', 'created_at', 'ended_at')
    search_fields = ('name', 'slug', 'description')
    readonly_fields = ('current_price', 'ended_at', 'ended_by')
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'description', 'icon_choice', 'custom_image')
        }),
        ('Аукционные параметры', {
            'fields': ('initial_price', 'min_step', 'start_date', 'end_date')
        }),
        ('Статус', {
            'fields': ('status', 'current_price', 'ended_by', 'ended_at')
        }),
    )
    
    actions = ['force_end_auction', 'cancel_selected_auctions']
    inlines = [AuctionBidInline]
    # Временно убираем кастомный шаблон, пока не настроим его правильно
    # change_form_template = 'admin/auction/auctionlot/change_form.html'
    
    def total_bids(self, obj):
        return obj.total_bids_count
    total_bids.short_description = 'Всего ставок'
    
    def force_end_auction(self, request, queryset):
        """Массовое завершение аукционов"""
        ended_count = 0
        errors = []
        
        for lot in queryset:
            success, message = lot.process_auction_end(ended_by_user=request.user)
            if success:
                ended_count += 1
                self.message_user(request, f'✅ {message}', level=messages.SUCCESS)
            else:
                errors.append(f'{lot.name}: {message}')
        
        if ended_count > 0:
            self.message_user(request, f'Успешно завершено аукционов: {ended_count}', level=messages.SUCCESS)
        if errors:
            self.message_user(request, f'Ошибки: {" | ".join(errors)}', level=messages.WARNING)
    
    force_end_auction.short_description = 'Завершить выбранные аукционы'
    
    def cancel_selected_auctions(self, request, queryset):
        """Отмена выбранных аукционов"""
        cancelled_count = 0
        errors = []
        
        for lot in queryset:
            success, message = lot.cancel_auction(cancelled_by_user=request.user)
            if success:
                cancelled_count += 1
                self.message_user(request, f'✅ {message}', level=messages.SUCCESS)
            else:
                errors.append(f'{lot.name}: {message}')
        
        if cancelled_count > 0:
            self.message_user(request, f'Успешно отменено аукционов: {cancelled_count}', level=messages.SUCCESS)
        if errors:
            self.message_user(request, f'Ошибки: {" | ".join(errors)}', level=messages.WARNING)
    
    cancel_selected_auctions.short_description = 'Отменить выбранные аукционы (с возвратом очков)'
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:lot_id>/end-auction/',
                self.admin_site.admin_view(self.end_auction_view),
                name='auction_end_auction',
            ),
            path(
                '<int:lot_id>/cancel-auction/',
                self.admin_site.admin_view(self.cancel_auction_view),
                name='auction_cancel_auction',
            ),
        ]
        return custom_urls + urls
    
    def end_auction_view(self, request, lot_id):
        """Индивидуальное завершение аукциона с выбором победителя"""
        lot = self.get_object(request, lot_id)
        
        if not lot:
            self.message_user(request, 'Лот не найден', level=messages.ERROR)
            return HttpResponseRedirect(reverse('admin:auction_auctionlot_changelist'))
        
        if lot.status != 'active':
            self.message_user(request, 'Этот аукцион уже завершен или отменен', level=messages.ERROR)
            return HttpResponseRedirect(reverse('admin:auction_auctionlot_change', args=[lot_id]))
        
        # Получаем все замороженные ставки
        frozen_bids = lot.bids.filter(is_frozen=True).order_by('-bid_amount')
        
        if request.method == 'POST':
            winner_id = request.POST.get('winner_id')
            
            if winner_id and winner_id != '':
                success, message = lot.process_auction_end(
                    ended_by_user=request.user,
                    force_winner_id=int(winner_id)
                )
                if success:
                    self.message_user(request, message, level=messages.SUCCESS)
                    return HttpResponseRedirect(reverse('admin:auction_auctionlot_change', args=[lot_id]))
                else:
                    self.message_user(request, message, level=messages.ERROR)
            elif winner_id == '':
                # Завершаем без победителя
                success, message = lot.process_auction_end(ended_by_user=request.user)
                if success:
                    self.message_user(request, message, level=messages.SUCCESS)
                    return HttpResponseRedirect(reverse('admin:auction_auctionlot_change', args=[lot_id]))
                else:
                    self.message_user(request, message, level=messages.ERROR)
            else:
                self.message_user(request, 'Пожалуйста, выберите победителя', level=messages.ERROR)
        
        context = {
            'title': f'Завершение аукциона: {lot.name}',
            'lot': lot,
            'frozen_bids': frozen_bids,
            'opts': self.model._meta,
            'has_change_permission': self.has_change_permission(request),
            'original': lot,
        }
        return TemplateResponse(request, 'admin/auction/end_auction_confirmation.html', context)
    
    def cancel_auction_view(self, request, lot_id):
        """Отмена аукциона"""
        lot = self.get_object(request, lot_id)
        
        if not lot:
            self.message_user(request, 'Лот не найден', level=messages.ERROR)
            return HttpResponseRedirect(reverse('admin:auction_auctionlot_changelist'))
        
        if lot.status != 'active':
            self.message_user(request, 'Этот аукцион уже завершен или отменен', level=messages.ERROR)
            return HttpResponseRedirect(reverse('admin:auction_auctionlot_change', args=[lot_id]))
        
        if request.method == 'POST':
            success, message = lot.cancel_auction(cancelled_by_user=request.user)
            if success:
                self.message_user(request, message, level=messages.SUCCESS)
                return HttpResponseRedirect(reverse('admin:auction_auctionlot_change', args=[lot_id]))
            else:
                self.message_user(request, message, level=messages.ERROR)
        
        context = {
            'title': f'Отмена аукциона: {lot.name}',
            'lot': lot,
            'active_bids': lot.bids.filter(is_frozen=True),
            'opts': self.model._meta,
            'has_change_permission': self.has_change_permission(request),
            'original': lot,
        }
        return TemplateResponse(request, 'admin/auction/cancel_auction_confirmation.html', context)


@admin.register(AuctionBid)
class AuctionBidAdmin(admin.ModelAdmin):
    list_display = ('lot', 'bidder', 'bid_amount', 'created_at', 'is_winner', 'is_frozen', 'status')
    list_filter = ('is_winner', 'is_frozen', 'status', 'created_at')
    search_fields = ('bidder__username', 'lot__name')
    readonly_fields = ('lot', 'bidder', 'bid_amount', 'created_at', 'is_winner', 'is_frozen', 'status')
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PointsTransaction)
class PointsTransactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount', 'transaction_type', 'description', 'created_at')
    list_filter = ('transaction_type', 'created_at')
    search_fields = ('user__username', 'description')
    readonly_fields = ('user', 'lot', 'amount', 'transaction_type', 'description', 'created_at')
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
