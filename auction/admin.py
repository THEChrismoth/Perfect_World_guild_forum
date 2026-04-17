from django.contrib import admin
from django.utils import timezone
from .models import AuctionLot, AuctionBid, PointsTransaction

class AuctionBidInline(admin.TabularInline):
    model = AuctionBid
    extra = 0
    readonly_fields = ('bidder', 'bid_amount', 'created_at', 'is_winner', 'is_frozen', 'status')
    fields = ('bidder', 'bid_amount', 'created_at', 'is_winner', 'is_frozen', 'status')
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False

@admin.register(AuctionLot)
class AuctionLotAdmin(admin.ModelAdmin):
    list_display = ('name', 'icon_choice', 'initial_price', 'current_price', 'status', 'end_date')
    list_filter = ('status', 'icon_choice', 'created_at')
    search_fields = ('name', 'slug', 'description')
    readonly_fields = ('current_price',)
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'description', 'icon_choice', 'custom_image')
        }),
        ('Аукционные параметры', {
            'fields': ('initial_price', 'min_step', 'start_date', 'end_date')
        }),
        ('Статус', {
            'fields': ('status', 'current_price')
        }),
    )
    actions = ['force_end_auction']
    inlines = [AuctionBidInline]
    
    def force_end_auction(self, request, queryset):
        for lot in queryset:
            lot.process_auction_end()
        self.message_user(request, f'Аукционы завершены')
    force_end_auction.short_description = 'Принудительно завершить выбранные аукционы'
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.current_price = obj.initial_price
        super().save_model(request, obj, form, change)

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
