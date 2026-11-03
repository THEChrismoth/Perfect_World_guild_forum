import base64

from django import forms
from django.contrib import admin
from django.utils import timezone
from django.contrib import messages
from django.urls import path, reverse
from django.template.response import TemplateResponse
from django.http import HttpResponseRedirect
from django.utils.html import format_html
from django.views.decorators.http import require_POST

from core.admin_mixins import NoRelatedPopupsMixin
from core.templatetags.ga_admin import ga_icon
from core.widgets import DateTimeLocalInput, datetime_local_field
from .models import AuctionLot, AuctionBid, PointsTransaction

PREVIEW_IMAGE_LIMIT = 5 * 1024 * 1024


class AuctionLotForm(forms.ModelForm):
    # Дата и время одним полем с календарём браузера и быстрыми кнопками.
    start_date = datetime_local_field(
        label='Начало торгов', initial=timezone.now,
        widget=DateTimeLocalInput(quick=[('now', 'Сейчас')]),
    )
    end_date = datetime_local_field(
        label='Окончание торгов', required=False,
        help_text='После этого времени ставки закрываются, победителя выбирает администратор. '
                  'Кнопки «+N дн.» считают от начала торгов',
        widget=DateTimeLocalInput(quick=[('+1', '+1 дн.'), ('+3', '+3 дн.'), ('+7', '+7 дн.')],
                                  from_field='start_date'),
    )

    class Meta:
        model = AuctionLot
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
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
    list_display = ('image_thumb', 'name', 'initial_price', 'current_price', 'status', 'end_date', 'total_bids')
    list_display_links = ('image_thumb', 'name')
    list_filter = ('status', 'created_at', 'ended_at')
    search_fields = ('name', 'slug', 'description')
    readonly_fields = ('current_price', 'ended_at', 'ended_by')

    main_fieldsets = (
        ('Лот', {
            'fields': ('name', 'description', 'image'),
            'description': 'Как лот будет выглядеть на сайте, покажет кнопка «Предпросмотр» внизу страницы — '
                           'без сохранения.',
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

    @admin.display(description='')
    def image_thumb(self, obj):
        url = obj.get_image_url()
        if not url:
            return format_html('<span class="ga-lot-thumb ga-lot-thumb-empty">{}</span>', ga_icon('gavel'))
        return format_html('<img class="ga-lot-thumb" src="{}" alt="">', url)

    actions = ['force_end_auction', 'cancel_selected_auctions']

    def get_inlines(self, request, obj):
        # Таблица ставок нужна только у лота, по которому уже торгуются.
        return [AuctionBidInline] if obj and obj.bids.exists() else []
    
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
            path('preview/', self.admin_site.admin_view(require_POST(self.preview_view)), name='auction_lot_preview'),
        ]
        return custom_urls + urls
    
    def preview_view(self, request):
        """Карточка лота как на сайте — из того, что сейчас введено в форме, без сохранения."""
        data = request.POST

        def number(name, default):
            try:
                return max(int(data.get(name, '')), 0)
            except ValueError:
                return default

        lot = AuctionLot(
            name=data.get('name', '').strip() or 'Без названия',
            description=data.get('description', ''),
            initial_price=number('initial_price', 0),
            min_step=number('min_step', 1),
        )
        lot.current_price = lot.initial_price
        try:
            lot.end_date = datetime_local_field(required=False).clean(data.get('end_date', ''))
        except forms.ValidationError:
            lot.end_date = None

        # Новая картинка ещё не сохранена — встраиваем её прямо в страницу предпросмотра.
        image_url = ''
        bids_count = 0
        upload = request.FILES.get('image')
        if upload and upload.size <= PREVIEW_IMAGE_LIMIT and (upload.content_type or '').startswith('image/'):
            image_url = f'data:{upload.content_type};base64,{base64.b64encode(upload.read()).decode()}'
        saved = AuctionLot.objects.filter(pk=data['object_id']).first() if data.get('object_id') else None
        if saved:
            lot.current_price = max(saved.current_price, lot.initial_price)
            bids_count = saved.total_bids_count
            if not image_url and not data.get('image-clear'):
                image_url = saved.get_image_url()

        return TemplateResponse(request, 'admin/auction/lot_preview.html', {
            'lot': lot,
            'image_url': image_url,
            'bids_count': bids_count,
            'theme': 'dark' if data.get('theme') == 'dark' else 'light',
            'accent': data.get('accent', 'indigo'),
        })

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
