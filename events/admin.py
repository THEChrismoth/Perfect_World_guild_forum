from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.shortcuts import redirect
from django.contrib import messages
from django import forms
from django.contrib.auth.models import Group
from .models import EventType, Event, Party, PartyMember, EventNotification, EventAttendance


class PartyMemberInline(admin.TabularInline):
    model = PartyMember
    extra = 1
    raw_id_fields = ['user']
    autocomplete_fields = ['user']
    fields = ['user', 'joined_at']
    readonly_fields = ['joined_at']
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'user':
            kwargs['widget'] = forms.Select(attrs={
                'style': 'min-width: 250px; width: auto; padding: 5px;'
            })
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = ['event_link', 'number', 'leader_link', 'members_count_display', 'is_full_display', 'edit_link']
    list_filter = ['event__event_type', 'event']
    search_fields = ['leader__username', 'event__event_type__name']
    raw_id_fields = ['leader']
    autocomplete_fields = ['leader']
    inlines = [PartyMemberInline]
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'leader':
            kwargs['widget'] = forms.Select(attrs={
                'style': 'min-width: 300px; width: auto; padding: 8px; border: 1px solid #ccc; border-radius: 4px;'
            })
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
    
    def event_link(self, obj):
        url = reverse('admin:events_event_change', args=[obj.event.id])
        return format_html('<a href="{}">{}</a>', url, obj.event)
    event_link.short_description = 'Ивент'
    
    def leader_link(self, obj):
        if obj.leader:
            url = reverse('admin:auth_user_change', args=[obj.leader.id])
            return format_html('<a href="{}" target="_blank">{}</a>', url, obj.leader.username)
        return '—'
    leader_link.short_description = 'Лидер'
    
    def members_count_display(self, obj):
        party_size = obj.event.event_type.party_size
        return f"{obj.members_count}/{party_size}"
    members_count_display.short_description = 'Участников'
    
    def is_full_display(self, obj):
        if obj.is_full:
            return format_html('<span style="color: green;">✅ Полный</span>')
        return format_html('<span style="color: orange;">❌ {}/{} мест</span>', obj.available_slots, obj.event.event_type.party_size)
    is_full_display.short_description = 'Статус'
    
    def edit_link(self, obj):
        url = reverse('admin:events_party_change', args=[obj.id])
        return format_html('<a href="{}" style="background: #417690; color: white; padding: 4px 8px; border-radius: 4px; text-decoration: none;">✏️ Редактировать отряд</a>', url)
    edit_link.short_description = 'Действие'


@admin.register(EventType)
class EventTypeAdmin(admin.ModelAdmin):
    list_display = ['icon', 'name', 'parties_count', 'party_size', 'is_active', 'order', 'view_parties_link']
    list_filter = ['is_active']
    search_fields = ['name', 'description']
    list_editable = ['order', 'is_active']
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'icon', 'description', 'is_active', 'order')
        }),
        ('Структура ивента', {
            'fields': ('parties_count', 'party_size'),
            'description': 'Количество отрядов и размер каждого отряда (включая лидера)'
        }),
        ('Связь с форумом', {
            'fields': ('forum_subcategory',),
        }),
    )
    readonly_fields = ['slug']
    
    def view_parties_link(self, obj):
        try:
            event = Event.objects.get(event_type=obj)
            url = reverse('admin:events_party_changelist') + f'?event__id__exact={event.id}'
            return format_html('<a href="{}" style="background: #417690; color: white; padding: 4px 8px; border-radius: 4px; text-decoration: none;">📋 Управление отрядами</a>', url)
        except Event.DoesNotExist:
            return '—'
    view_parties_link.short_description = 'Отряды'


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'event_type_link', 'is_active', 'parties_info_short', 'manage_parties_link']
    list_filter = ['event_type', 'is_active']
    search_fields = ['event_type__name', 'notes']
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('event_type', 'is_active', 'notes')
        }),
    )
    
    def event_type_link(self, obj):
        url = reverse('admin:events_eventtype_change', args=[obj.event_type.id])
        return format_html('<a href="{}">{}</a>', url, obj.event_type.name)
    event_type_link.short_description = 'Тип ивента'
    
    def parties_info_short(self, obj):
        parties = obj.parties.all()
        total_members = sum(p.members_count for p in parties)
        party_size = obj.event_type.party_size
        total_slots = len(parties) * party_size
        return f"{total_members}/{total_slots} мест"
    parties_info_short.short_description = 'Заполнение'
    
    def manage_parties_link(self, obj):
        url = reverse('admin:events_party_changelist') + f'?event__id__exact={obj.id}'
        return format_html('<a href="{}" style="background: #417690; color: white; padding: 4px 8px; border-radius: 4px; text-decoration: none;">📋 Управление отрядами</a>', url)
    manage_parties_link.short_description = 'Действие'


@admin.register(PartyMember)
class PartyMemberAdmin(admin.ModelAdmin):
    list_display = ['user_link', 'party_link', 'joined_at', 'delete_link']
    list_filter = ['party__event__event_type', 'party__event']
    search_fields = ['user__username', 'party__event__event_type__name']
    raw_id_fields = ['user']
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'user':
            kwargs['widget'] = forms.Select(attrs={
                'style': 'min-width: 300px; width: auto; padding: 8px; border: 1px solid #ccc; border-radius: 4px;'
            })
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
    
    def user_link(self, obj):
        url = reverse('admin:auth_user_change', args=[obj.user.id])
        return format_html('<a href="{}" target="_blank">{}</a>', url, obj.user.username)
    user_link.short_description = 'Пользователь'
    
    def party_link(self, obj):
        url = reverse('admin:events_party_change', args=[obj.party.id])
        return format_html('<a href="{}">{} - Отряд {}</a>', url, obj.party.event, obj.party.number)
    party_link.short_description = 'Отряд'
    
    def delete_link(self, obj):
        url = reverse('admin:events_partymember_delete', args=[obj.id])
        return format_html('<a href="{}" style="color: #ba2121;" onclick="return confirm(\'Удалить участника?\')">🗑️ Удалить</a>', url)
    delete_link.short_description = 'Действие'


@admin.register(EventNotification)
class EventNotificationAdmin(admin.ModelAdmin):
    list_display = ['event_type', 'event_date', 'subject', 'send_status', 'recipient_groups_display', 'sent_at']
    list_filter = ['event_type', 'event_date', 'recipient_groups']
    search_fields = ['subject', 'message']
    readonly_fields = ['sent_at', 'responses_count']
    filter_horizontal = ['recipient_groups']  # Убрали sent_to_users отсюда
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('event_type', 'event_date', 'subject', 'message')
        }),
        ('Получатели', {
            'fields': ('recipient_groups',),
            'description': 'Выберите группы пользователей, которые получат уведомление. Если не выбрано - отправляется всем членам гильдии'
        }),
        ('Статистика', {
            'fields': ('sent_at', 'responses_count'),
            'classes': ('collapse',)
        }),
    )
    
    def responses_count(self, obj):
        return obj.attendances.count()
    responses_count.short_description = 'Ответов'
    
    def recipient_groups_display(self, obj):
        groups = obj.recipient_groups.all()
        if groups:
            return ", ".join([g.name for g in groups])
        return "Все члены гильдии"
    recipient_groups_display.short_description = 'Получатели'
    
    def send_status(self, obj):
        if obj.sent_at:
            sent_count = obj.sent_to_users.count()
            return format_html('<span style="color: green;">✅ Отправлено {} ({})</span>', 
                             obj.sent_at.strftime('%d.%m.%Y %H:%M'), sent_count)
        return format_html('<span style="color: orange;">⏳ Не отправлено</span>')
    send_status.short_description = 'Статус'
    
    actions = ['send_selected_notifications']
    
    def send_selected_notifications(self, request, queryset):
        """Отправить выбранные уведомления"""
        from .utils import send_event_notification
        
        sent_count = 0
        for notification in queryset:
            result = send_event_notification(notification.id)
            if result > 0:
                sent_count += 1
                self.message_user(request, f'✓ Уведомление для "{notification.event_type.name}" на {notification.event_date} отправлено ({result} пользователей)')
            else:
                self.message_user(request, f'✗ Ошибка при отправке "{notification.event_type.name}"', level='ERROR')
        
        if sent_count > 0:
            self.message_user(request, f'Отправлено {sent_count} уведомлений')
    send_selected_notifications.short_description = '📢 Отправить выбранные уведомления'
    
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
    
    def response_add(self, request, obj, post_url_continue=None):
        """При создании - предлагаем отправить"""
        if '_send_notification' in request.POST:
            from .utils import send_event_notification
            result = send_event_notification(obj.id)
            if result > 0:
                self.message_user(request, f'✅ Уведомление для "{obj.event_type.name}" на {obj.event_date} успешно отправлено {result} пользователям!')
            else:
                self.message_user(request, f'⚠️ Уведомление создано, но не отправлено (нет получателей)', level='WARNING')
            return redirect('admin:events_eventnotification_changelist')
        return super().response_add(request, obj, post_url_continue)
    
    def response_change(self, request, obj):
        """При изменении - предлагаем отправить"""
        if '_send_notification' in request.POST:
            from .utils import send_event_notification
            result = send_event_notification(obj.id)
            if result > 0:
                self.message_user(request, f'✅ Уведомление для "{obj.event_type.name}" на {obj.event_date} успешно отправлено {result} пользователям!')
            else:
                self.message_user(request, f'⚠️ Уведомление обновлено, но не отправлено (нет получателей)', level='WARNING')
            return redirect('admin:events_eventnotification_changelist')
        return super().response_change(request, obj)
    
    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        extra_context = extra_context or {}
        extra_context['show_send_button'] = True
        
        # Добавляем статистику голосования если уведомление уже существует
        if object_id:
            from .utils import get_attendance_stats
            stats = get_attendance_stats(object_id)
            extra_context['attendance_stats'] = stats
        
        return super().changeform_view(request, object_id, form_url, extra_context)


@admin.register(EventAttendance)
class EventAttendanceAdmin(admin.ModelAdmin):
    list_display = ['user', 'notification_link', 'status', 'updated_at']
    list_filter = ['status', 'notification__event_type', 'notification__event_date']
    search_fields = ['user__username', 'comment']
    raw_id_fields = ['user']
    readonly_fields = ['created_at', 'updated_at']
    
    def notification_link(self, obj):
        url = reverse('admin:events_eventnotification_change', args=[obj.notification.id])
        return format_html('<a href="{}">{}</a>', url, obj.notification)
    notification_link.short_description = 'Уведомление'
