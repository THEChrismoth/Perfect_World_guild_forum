from django import forms
from django.contrib import admin
from django.utils import timezone
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import path, reverse
from django.template.response import TemplateResponse
from django.http import HttpResponseRedirect
from django.utils.html import format_html

from core.admin_mixins import NoRelatedPopupsMixin
from .models import AuctionLot, AuctionBid, PointsTransaction


class AuctionLotForm(forms.ModelForm):
    class Meta:
        model = AuctionLot
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('icon_choice') == 'custom' and not cleaned_data.get('custom_image'):
            self.add_error('custom_image', 'Загрузите картинку или выберите готовую иконку')
        start, end = cleaned_data.get('start_date'), cleaned_data.get('end_date')
        if start and end and end <= start:
            self.add_error('end_date', 'Окончание должно быть позже начала')
        if not self.instance.pk and end and end <= timezone.now():
            self.add_error('end_date', 'Дата окончания уже прошла — ставки по лоту сразу будут закрыты')
        initial_price, min_step = cleaned_data.get('initial_price'), cleaned_data.get('min_step')
        if initial_price and min_step and min_step > initial_price:
            self.add_error('min_step', 'Шаг ставки больше начальной цены — проверьте числа')
        return cleaned_data


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
class AuctionLotAdmin(NoRelatedPopupsMixin, admin.ModelAdmin):
    form = AuctionLotForm
    list_display = ('name', 'icon_choice', 'initial_price', 'current_price', 'status', 'ended_at', 'total_bids')
    list_filter = ('status', 'icon_choice', 'created_at', 'ended_at')
    search_fields = ('name', 'slug', 'description')
    readonly_fields = ('icon_preview', 'current_price', 'ended_at', 'ended_by')

    main_fieldsets = (
        ('Лот', {
            'fields': ('name', 'description', 'icon_choice', 'custom_image', 'icon_preview'),
            'description': 'Так лот будет выглядеть на странице аукциона. Готовые иконки — предметы из игры; '
                           'для другого предмета выберите «Своя картинка» и загрузите изображение.',
        }),
        ('Ставки', {
            'fields': ('initial_price', 'min_step', 'start_date', 'end_date'),
            'description': 'Цены — в очках активности. После даты окончания ставки закрываются, а победителя '
                           'выбирает администратор кнопкой «Завершить аукцион» вверху страницы лота.',
        }),
    )
    status_fieldset = ('Состояние торгов', {
        'fields': ('status', 'current_price', 'ended_by', 'ended_at'),
        'description': 'Завершайте и отменяйте лот кнопками вверху страницы: тогда очки списываются и возвращаются '
                       'участникам автоматически. Ручная смена статуса очки не трогает.',
    })

    def get_fieldsets(self, request, obj=None):
        # Новый лот всегда начинается активным — состояние торгов показываем только у созданных.
        return self.main_fieldsets + ((self.status_fieldset,) if obj else ())

    @admin.display(description='Как выглядит')
    def icon_preview(self, obj):
        url = obj.get_image_url() if obj and obj.pk else ''
        if not url:
            return 'появится после сохранения'
        return format_html('<img class="ga-lot-preview" src="{}" alt="">', url)

    actions = ['force_end_auction', 'cancel_selected_auctions']
    inlines = [AuctionBidInline]
    
    def total_bids(self, obj):
        return obj.total_bids_count
    total_bids.short_description = 'Всего ставок'
    
    def force_end_auction(self, request, queryset):
        """Массовое завершение аукционов."""
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
        """Отмена выбранных аукционов."""
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
        """Индивидуальное завершение аукциона с выбором победителя."""
        lot = self.get_object(request, lot_id)
        
        if not lot:
            self.message_user(request, 'Лот не найден', level=messages.ERROR)
            return HttpResponseRedirect(reverse('admin:auction_auctionlot_changelist'))
        
        if lot.status != 'active':
            self.message_user(request, 'Этот аукцион уже завершен или отменен', level=messages.ERROR)
            return HttpResponseRedirect(reverse('admin:auction_auctionlot_change', args=[lot_id]))
        
        # Получаем все замороженные ставки.
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
                # Завершаем без победителя.
                success, message = lot.process_auction_end(ended_by_user=request.user)
                if success:
                    self.message_user(request, message, level=messages.SUCCESS)
                    return HttpResponseRedirect(reverse('admin:auction_auctionlot_change', args=[lot_id]))
                else:
                    self.message_user(request, message, level=messages.ERROR)
            else:
                self.message_user(request, 'Пожалуйста, выберите победителя', level=messages.ERROR)
        
        context = {
            # Шапка, меню и название сайта как на остальных страницах админки.
            **self.admin_site.each_context(request),
            'title': f'Завершение аукциона: {lot.name}',
            'lot': lot,
            'frozen_bids': frozen_bids,
            'opts': self.model._meta,
            'has_change_permission': self.has_change_permission(request),
            'original': lot,
        }
        return TemplateResponse(request, 'admin/auction/end_auction_confirmation.html', context)
    
    def cancel_auction_view(self, request, lot_id):
        """Отмена аукциона."""
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
            # Шапка, меню и название сайта как на остальных страницах админки.
            **self.admin_site.each_context(request),
            'title': f'Отмена аукциона: {lot.name}',
            'lot': lot,
            'active_bids': lot.bids.filter(is_frozen=True),
            'opts': self.model._meta,
            'has_change_permission': self.has_change_permission(request),
            'original': lot,
        }
        return TemplateResponse(request, 'admin/auction/cancel_auction_confirmation.html', context)


@admin.register(AuctionBid)
class AuctionBidAdmin(NoRelatedPopupsMixin, admin.ModelAdmin):
    list_display = ('lot', 'bidder', 'bid_amount', 'created_at', 'is_winner', 'is_frozen', 'status')
    list_filter = ('is_winner', 'is_frozen', 'status', 'created_at')
    search_fields = ('bidder__username', 'lot__name')
    readonly_fields = ('lot', 'bidder', 'bid_amount', 'created_at', 'is_winner', 'is_frozen', 'status')
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PointsTransaction)
class PointsTransactionAdmin(NoRelatedPopupsMixin, admin.ModelAdmin):
    list_display = ('user', 'amount', 'transaction_type', 'description', 'created_at')
    list_filter = ('transaction_type', 'created_at')
    search_fields = ('user__username', 'description')
    readonly_fields = ('user', 'lot', 'amount', 'transaction_type', 'description', 'created_at')
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
