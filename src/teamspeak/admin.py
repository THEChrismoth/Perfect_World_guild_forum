from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import EventPresence, TeamSpeakSettings, TsLink, TsRoom, TsTask
from .tasks import revoke_link

MAX_LICENSE_SIZE = 64 * 1024


class SuperuserOnlyMixin:
    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser


class TeamSpeakSettingsForm(forms.ModelForm):
    license_upload = forms.FileField(
        label='Загрузить лицензию', required=False,
        help_text='Файл licensekey.dat, купленный у TeamSpeak. После сохранения бот установит его '
                  'и перезапустит сервер TeamSpeak (около минуты все будут отключены)',
    )

    class Meta:
        model = TeamSpeakSettings
        fields = ['server_address', 'rooms_per_member', 'max_clients']

    def clean_license_upload(self):
        upload = self.cleaned_data.get('license_upload')
        if upload and upload.size > MAX_LICENSE_SIZE:
            raise forms.ValidationError('Слишком большой файл — лицензия TeamSpeak весит несколько килобайт')
        return upload


@admin.register(TeamSpeakSettings)
class TeamSpeakSettingsAdmin(SuperuserOnlyMixin, admin.ModelAdmin):
    form = TeamSpeakSettingsForm
    readonly_fields = ('bot_status', 'license_status')
    fieldsets = (
        ('Бот', {
            'fields': ('bot_status',),
            'description': 'Бот TeamSpeak — отдельный контейнер tsbot. Он выдаёт группу «Член гильдии», создаёт '
                           'комнаты и считает присутствие на ивентах. Как включить — в docs/GUIDE.md, раздел «TeamSpeak».',
        }),
        ('Сервер', {'fields': ('server_address', 'rooms_per_member')}),
        ('Лицензия', {
            'fields': ('license_status', 'license_upload', 'max_clients'),
            'description': 'Без лицензии TeamSpeak 3 работает на 32 слота. Купленный файл лицензии загрузите здесь.',
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        return redirect(reverse('admin:teamspeak_teamspeaksettings_change', args=[TeamSpeakSettings.load().pk]))

    @admin.display(description='Состояние')
    def bot_status(self, obj):
        if obj.bot_online:
            return format_html('<strong style="color:#16a34a">{}</strong>', '🟢 на связи')
        if obj.bot_last_seen:
            return format_html('<strong style="color:#dc2626">{}</strong> {}', '🔴 не отвечает',
                               f'(последний раз {timezone.localtime(obj.bot_last_seen):%d.%m.%Y %H:%M})')
        return 'ещё не подключался'

    @admin.display(description='Лицензия')
    def license_status(self, obj):
        if not obj.license_name:
            return 'не загружена (32 слота)'
        installed = (f'установлена {timezone.localtime(obj.license_installed_at):%d.%m.%Y %H:%M}'
                     if obj.license_installed_at else 'ожидает установки ботом')
        return f'{obj.license_name} — {installed}'

    def save_model(self, request, obj, form, change):
        upload = form.cleaned_data.get('license_upload')
        if upload:
            obj.license_name = upload.name
            obj.license_data = upload.read()
            obj.license_uploaded_at = timezone.now()
            obj.license_installed_at = None
        super().save_model(request, obj, form, change)
        if upload:
            TsTask.enqueue('install_license', user=request.user, max_clients=obj.max_clients)
            messages.info(request, 'Лицензия загружена — бот установит её и перезапустит сервер TeamSpeak')


@admin.register(TsTask)
class TsTaskAdmin(SuperuserOnlyMixin, admin.ModelAdmin):
    list_display = ('created_at', 'type', 'status_display', 'user', 'error_short')
    list_filter = ('status', 'type')
    readonly_fields = ('type', 'status', 'user', 'payload', 'result', 'error', 'created_at', 'started_at', 'finished_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description='Статус', ordering='status')
    def status_display(self, obj):
        colors = {'done': '#16a34a', 'failed': '#dc2626', 'running': '#0ea5e9'}
        return format_html('<strong style="color:{}">{}</strong>', colors.get(obj.status, '#64748b'), obj.get_status_display())

    @admin.display(description='Ошибка')
    def error_short(self, obj):
        return (obj.error[:80] + '…') if len(obj.error) > 80 else obj.error


@admin.register(TsLink)
class TsLinkAdmin(SuperuserOnlyMixin, admin.ModelAdmin):
    list_display = ('user', 'uid', 'status', 'requested_at', 'verified_at')
    list_filter = ('status',)
    search_fields = ('user__username', 'uid')
    readonly_fields = ('user', 'uid', 'status', 'requested_at', 'verified_at')
    actions = ['revoke']

    def has_add_permission(self, request):
        return False

    @admin.action(description='Отозвать доступ (снять группу в TeamSpeak и удалить привязку)')
    def revoke(self, request, queryset):
        count = 0
        for link in queryset:
            revoke_link(link)
            count += 1
        self.message_user(request, f'Отозвано привязок: {count}')

    def delete_model(self, request, obj):
        revoke_link(obj)

    def delete_queryset(self, request, queryset):
        for link in queryset:
            revoke_link(link)


@admin.register(TsRoom)
class TsRoomAdmin(SuperuserOnlyMixin, admin.ModelAdmin):
    list_display = ('name', 'owner', 'status', 'channel_id', 'created_at')
    list_filter = ('status',)
    search_fields = ('name', 'owner__username')
    readonly_fields = ('owner', 'name', 'channel_id', 'status', 'error', 'created_at')
    actions = ['delete_rooms']

    def has_add_permission(self, request):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions

    @admin.action(description='Удалить комнаты в TeamSpeak')
    def delete_rooms(self, request, queryset):
        for room in queryset:
            if room.channel_id and room.status == 'active':
                room.status = 'deleting'
                room.save(update_fields=['status'])
                TsTask.enqueue('delete_room', user=room.owner, room_id=room.pk, cid=room.channel_id)
            else:
                room.delete()
        self.message_user(request, 'Комнаты удаляются')


@admin.register(EventPresence)
class EventPresenceAdmin(SuperuserOnlyMixin, admin.ModelAdmin):
    list_display = ('notification', 'user', 'minutes', 'last_minute')
    list_filter = ('notification__event_type',)
    search_fields = ('user__username',)
    readonly_fields = ('notification', 'user', 'minutes', 'last_minute')

    def has_add_permission(self, request):
        return False
