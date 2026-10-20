"""Отправка писем с настройками SMTP из админ-панели (Настройки сайта → Почта).

Если почта не настроена, письма печатаются в консоль (в Docker — в логи контейнера web):
так удобно при разработке.
"""
from django.conf import settings
from django.core.mail import EmailMessage, get_connection

from .models import SiteSettings


def get_mail_connection(site_settings=None):
    site_settings = site_settings or SiteSettings.load()
    if not site_settings.email_configured:
        return get_connection('django.core.mail.backends.console.EmailBackend')
    return get_connection(
        'django.core.mail.backends.smtp.EmailBackend',
        host=site_settings.email_host,
        port=site_settings.email_port,
        username=site_settings.email_host_user,
        password=site_settings.get_email_password(),
        use_tls=site_settings.email_security == 'tls',
        use_ssl=site_settings.email_security == 'ssl',
        timeout=20,
    )


def send_site_mail(subject, message, recipients, site_settings=None):
    """Отправляет письмо. Ошибки SMTP пробрасываются — вызывающий код решает, что с ними делать."""
    site_settings = site_settings or SiteSettings.load()
    from_email = site_settings.sender or settings.DEFAULT_FROM_EMAIL
    EmailMessage(
        subject=subject,
        body=message,
        from_email=from_email,
        to=recipients,
        connection=get_mail_connection(site_settings),
    ).send()
