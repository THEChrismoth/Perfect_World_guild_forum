from django.contrib import admin
from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'title', 'notification_type', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read', 'created_at')
    search_fields = ('user__username', 'title', 'message')
    readonly_fields = ('created_at',)

    fieldsets = (
        ('Получатель', {'fields': ('user',)}),
        ('Содержание', {'fields': ('title', 'message', 'notification_type', 'link')}),
        ('Статус', {'fields': ('is_read', 'created_at')}),
    )