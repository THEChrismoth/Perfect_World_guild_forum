import smtplib
import socket

from django import forms
from django.contrib import admin, messages
from django.http import Http404
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from .mail import send_site_mail
from .models import SiteSettings

SECRET_FIELDS = {
    'email_host_password': 'clear_email_password',
    'captcha_private_key': 'clear_captcha_private_key',
}


def _secret_widget():
    return forms.PasswordInput(render_value=False, attrs={'autocomplete': 'new-password', 'size': 50})


class SiteSettingsForm(forms.ModelForm):
    email_host_password = forms.CharField(
        label='Пароль', required=False, widget=_secret_widget(),
        help_text=SiteSettings._meta.get_field('email_host_password').help_text,
    )
    clear_email_password = forms.BooleanField(label='Удалить сохранённый пароль', required=False)
    captcha_private_key = forms.CharField(
        label='Private key', required=False, widget=_secret_widget(),
        help_text=SiteSettings._meta.get_field('captcha_private_key').help_text,
    )
    clear_captcha_private_key = forms.BooleanField(label='Удалить сохранённый ключ', required=False)

    class Meta:
        model = SiteSettings
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()

        # Пустое поле секрета — оставляем сохранённое значение (оно не показывается в форме).
        for field, clear_field in SECRET_FIELDS.items():
            value = (cleaned_data.get(field) or '').strip()
            if cleaned_data.get(clear_field):
                value = ''
            elif not value:
                value = getattr(self.instance, field)
            cleaned_data[field] = value

        if cleaned_data.get('email_verification') and not cleaned_data.get('email_host'):
            self.add_error('email_verification', 'Сначала настройте почту в разделе «Почта (SMTP)» — '
                                                 'иначе письма с подтверждением не будут отправляться')

        if cleaned_data.get('captcha_enabled'):
            if not cleaned_data.get('captcha_site_key'):
                self.add_error('captcha_site_key', 'Укажите Site key, чтобы включить капчу')
            if not cleaned_data.get('captcha_private_key') or (
                    cleaned_data['captcha_private_key'] == self.instance.captcha_private_key
                    and self.instance.secret_unreadable('captcha_private_key')):
                self.add_error('captcha_private_key', 'Укажите Private key, чтобы включить капчу')
        return cleaned_data


def _secret_status(obj, field, getter):
    if obj.secret_unreadable(field):
        return format_html('<strong style="color:#dc3545">{}</strong>',
                           'не расшифровывается (сменился DJANGO_SECRET_KEY) — введите заново')
    value = getter()
    if value:
        return f'сохранён в зашифрованном виде (…{value[-3:]})'
    return 'не задан'


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    form = SiteSettingsForm
    change_form_template = 'admin/core/sitesettings/change_form.html'
    readonly_fields = ('email_password_status', 'captcha_key_status', 'email_status', 'captcha_status')
    fieldsets = (
        ('Основное', {'fields': ('site_name', 'favicon')}),
        ('Регистрация', {
            'fields': ('email_verification', 'email_status', 'captcha_enabled', 'captcha_status'),
        }),
        ('Почта (SMTP)', {
            'fields': ('email_host', 'email_port', 'email_security', 'email_host_user',
                       'email_password_status', 'email_host_password', 'clear_email_password', 'email_from'),
            'description': 'Через эту почту отправляются письма подтверждения регистрации. '
                           'Сохраните настройки и нажмите «Отправить тестовое письмо» вверху страницы.',
        }),
        ('Капча DDoS-Guard', {
            'fields': ('captcha_site_key', 'captcha_key_status', 'captcha_private_key', 'clear_captcha_private_key'),
            'description': format_html(
                'Ключи выдаются в личном кабинете <a href="{}" target="_blank" rel="noopener">my.ddos-guard.net</a>: '
                'услуга dCAPTCHA → «Ключи» → «Добавить ключ». В списке доменов ключа укажите домен сайта.',
                'https://my.ddos-guard.net',
            ),
        }),
    )

    # Здесь хранятся пароль почты и ключи — только для суперпользователей.
    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Запись всего одна — сразу открываем ее редактирование.
        obj = SiteSettings.load()
        return redirect(reverse('admin:core_sitesettings_change', args=[obj.pk]))

    def get_urls(self):
        return [
            path('send-test-email/', self.admin_site.admin_view(self.send_test_email_view), name='core_send_test_email'),
        ] + super().get_urls()

    @admin.display(description='Сохранённый пароль')
    def email_password_status(self, obj):
        return _secret_status(obj, 'email_host_password', obj.get_email_password)

    @admin.display(description='Сохранённый ключ')
    def captcha_key_status(self, obj):
        return _secret_status(obj, 'captcha_private_key', obj.get_captcha_private_key)

    @admin.display(description='Почта')
    def email_status(self, obj):
        if obj.email_configured:
            return f'✅ настроена ({obj.email_host})'
        return '⚠️ не настроена — письма не отправляются, а печатаются в лог сервера'

    @admin.display(description='Капча')
    def captcha_status(self, obj):
        if obj.captcha_active:
            return '✅ включена'
        if obj.captcha_configured:
            return 'ключи заданы, капча выключена'
        return 'ключи не заданы'

    def send_test_email_view(self, request):
        if request.method != 'POST' or not request.user.is_superuser:
            raise Http404
        site_settings = SiteSettings.load()
        url = reverse('admin:core_sitesettings_change', args=[site_settings.pk])

        if not site_settings.email_configured:
            messages.error(request, 'Сначала заполните и сохраните настройки почты')
        elif not request.user.email:
            messages.error(request, 'У вашего аккаунта не указан email — укажите его в своём профиле в разделе «Пользователи»')
        else:
            try:
                send_site_mail(
                    f'Тестовое письмо — {site_settings.site_name}',
                    'Почта сайта настроена правильно: письма подтверждения регистрации будут доходить.',
                    [request.user.email],
                    site_settings,
                )
            except smtplib.SMTPAuthenticationError:
                messages.error(request, 'Сервер почты отклонил логин или пароль. '
                                        'Для Яндекса и Gmail нужен пароль приложения, а не пароль от почты')
            except (smtplib.SMTPException, socket.error, OSError) as error:
                messages.error(request, f'Не удалось отправить письмо: {error}')
            else:
                messages.success(request, f'Тестовое письмо отправлено на {request.user.email}. Проверьте почту и папку «Спам»')
        return redirect(url)
