from django import forms
from django.contrib import admin, messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.template.defaultfilters import filesizeformat
from django.urls import path, reverse
from django.utils.html import format_html

from .crypto import encryption_enabled
from .models import Backup, BackupSettings
from .yandex import YandexDisk, YandexDiskError


class SuperuserOnlyMixin:
    """Копии содержат все данные сайта, поэтому раздел доступен только суперпользователям"""

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser


class BackupSettingsForm(forms.ModelForm):
    yandex_token = forms.CharField(
        label='OAuth-токен Яндекса',
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={'autocomplete': 'new-password', 'size': 60}),
        help_text=BackupSettings._meta.get_field('yandex_token').help_text,
    )
    clear_yandex_token = forms.BooleanField(label='Удалить сохраненный токен', required=False)

    class Meta:
        model = BackupSettings
        fields = '__all__'

    def clean_yandex_token(self):
        token = self.cleaned_data.get('yandex_token', '').strip()
        # Пустое поле — оставляем сохраненный (зашифрованный) токен
        return token or self.instance.yandex_token

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('clear_yandex_token'):
            cleaned_data['yandex_token'] = ''
        if cleaned_data.get('yandex_enabled'):
            if not encryption_enabled():
                self.add_error('yandex_enabled', 'Загрузка на Яндекс Диск доступна только для зашифрованных копий. '
                                                 'Задайте BACKUP_ENCRYPTION_PASSWORD в .env и перезапустите контейнеры')
            token = cleaned_data.get('yandex_token')
            if not token or (token == self.instance.yandex_token and self.instance.yandex_token_unreadable):
                self.add_error('yandex_token', 'Укажите токен, чтобы загружать копии на Яндекс Диск')
        folder = cleaned_data.get('yandex_folder', '')
        if folder and not (folder.startswith('app:/') or folder.startswith('disk:/')):
            self.add_error('yandex_folder', 'Путь должен начинаться с app:/ или disk:/')
        return cleaned_data


@admin.register(BackupSettings)
class BackupSettingsAdmin(SuperuserOnlyMixin, admin.ModelAdmin):
    form = BackupSettingsForm
    change_form_template = 'admin/backups/backupsettings/change_form.html'
    readonly_fields = ('encryption_status', 'token_status', 'last_scheduled_run')
    fieldsets = (
        ('Расписание', {
            'fields': ('enabled', 'frequency', 'weekday', 'run_time', 'last_scheduled_run'),
            'description': 'Копии по расписанию создает контейнер scheduler. Сделать копию вручную можно в «Журнале резервных копий».',
        }),
        ('Шифрование', {
            'fields': ('encryption_status',),
            'description': 'Пароль шифрования задается в .env (BACKUP_ENCRYPTION_PASSWORD) и не хранится в базе. '
                           'Сохраните его в надежном месте: без него зашифрованные копии восстановить невозможно.',
        }),
        ('Что сохранять', {'fields': ('include_media',)}),
        ('Хранение на сервере', {'fields': ('keep_local',)}),
        ('Яндекс Диск', {
            'fields': ('yandex_enabled', 'token_status', 'yandex_token', 'clear_yandex_token', 'yandex_folder', 'keep_yandex'),
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Запись всего одна — сразу открываем ее редактирование
        obj = BackupSettings.load()
        return redirect(reverse('admin:backups_backupsettings_change', args=[obj.pk]))

    def get_urls(self):
        return [
            path('check-yandex/', self.admin_site.admin_view(self.check_yandex_view), name='backups_check_yandex'),
        ] + super().get_urls()

    @admin.display(description='Шифрование копий')
    def encryption_status(self, obj):
        if encryption_enabled():
            return format_html('<strong style="color:#28a745">{}</strong>', '🔒 Включено — новые копии шифруются')
        return format_html(
            '<strong style="color:#dc3545">{}</strong><br>{}',
            '⚠️ Выключено — копии сохраняются незашифрованными, загрузка на Яндекс Диск недоступна',
            'Задайте BACKUP_ENCRYPTION_PASSWORD в .env и выполните docker compose up -d',
        )

    @admin.display(description='Токен')
    def token_status(self, obj):
        if obj.yandex_token_unreadable:
            return format_html('<strong style="color:#dc3545">{}</strong>',
                               'не расшифровывается (сменился DJANGO_SECRET_KEY) — введите токен заново')
        token = obj.get_yandex_token()
        if token:
            return f'сохранен в зашифрованном виде (…{token[-4:]})'
        return 'не задан'

    def check_yandex_view(self, request):
        if not request.user.is_superuser:
            raise Http404
        backup_settings = BackupSettings.load()
        token = backup_settings.get_yandex_token()
        if not token:
            messages.error(request, 'Сначала сохраните токен Яндекса')
        else:
            disk = YandexDisk(token)
            try:
                info = disk.check()
                disk.ensure_folder(backup_settings.yandex_folder)
            except YandexDiskError as error:
                messages.error(request, f'Не удалось подключиться: {error}')
            else:
                free = (info.get('total_space') or 0) - (info.get('used_space') or 0)
                owner = (info.get('user') or {}).get('login', '')
                messages.success(
                    request,
                    f'Подключение работает{f" (аккаунт {owner})" if owner else ""}. '
                    f'Папка {backup_settings.yandex_folder} готова, свободно {filesizeformat(free)}'
                )
        return redirect(reverse('admin:backups_backupsettings_change', args=[backup_settings.pk]))


@admin.register(Backup)
class BackupAdmin(SuperuserOnlyMixin, admin.ModelAdmin):
    change_list_template = 'admin/backups/backup/change_list.html'
    list_display = ('created_at', 'status_display', 'trigger', 'size_display', 'encrypted', 'yandex_status', 'download_link')
    list_filter = ('status', 'trigger', 'encrypted', 'yandex_status')
    readonly_fields = (
        'created_at', 'started_at', 'finished_at', 'duration_display', 'status', 'trigger', 'requested_by',
        'file_name', 'size_display', 'includes_media', 'encrypted', 'local_deleted', 'download_link',
        'yandex_status', 'yandex_path', 'error',
    )
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Записи журнала не редактируются, только просматриваются
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_urls(self):
        return [
            path('run/', self.admin_site.admin_view(self.run_view), name='backups_backup_run'),
            path('<int:backup_id>/download/', self.admin_site.admin_view(self.download_view), name='backups_backup_download'),
        ] + super().get_urls()

    @admin.display(description='Статус', ordering='status')
    def status_display(self, obj):
        colors = {'success': '#28a745', 'warning': '#e0a800', 'failed': '#dc3545'}
        return format_html('<strong style="color:{}">{}</strong>', colors.get(obj.status, '#6c757d'), obj.get_status_display())

    @admin.display(description='Размер', ordering='size')
    def size_display(self, obj):
        return filesizeformat(obj.size) if obj.size else '—'

    @admin.display(description='Длительность')
    def duration_display(self, obj):
        duration = obj.duration
        return f'{int(duration.total_seconds())} сек.' if duration else '—'

    @admin.display(description='Файл на сервере')
    def download_link(self, obj):
        if obj.local_available:
            return format_html('<a href="{}">⬇️ Скачать</a>', reverse('admin:backups_backup_download', args=[obj.pk]))
        if obj.local_deleted:
            return 'удален (старая копия)'
        return '—'

    def run_view(self, request):
        if request.method != 'POST' or not request.user.is_superuser:
            raise Http404
        if Backup.objects.filter(status__in=('pending', 'running')).exists():
            messages.warning(request, 'Копия уже создается — дождитесь окончания')
        else:
            Backup.objects.create(trigger='manual', requested_by=request.user)
            messages.success(
                request,
                'Копия поставлена в очередь и будет создана в течение минуты. Обновите страницу, чтобы увидеть результат'
            )
        return redirect(reverse('admin:backups_backup_changelist'))

    def download_view(self, request, backup_id):
        if not request.user.is_superuser:
            raise Http404
        backup = get_object_or_404(Backup, pk=backup_id)
        if not backup.local_available:
            raise Http404('Файл копии не найден на сервере')
        return FileResponse(open(backup.local_path, 'rb'), as_attachment=True, filename=backup.file_name)
