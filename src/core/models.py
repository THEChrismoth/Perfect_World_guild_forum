from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models

from .secrets import SECRET_PREFIX, decrypt_secret, encrypt_secret


class SiteSettings(models.Model):
    """Настройки сайта. Хранится единственная запись (pk=1), редактируется в админ-панели."""

    EMAIL_SECURITY_CHOICES = [
        ('tls', 'STARTTLS (обычно порт 587)'),
        ('ssl', 'SSL/TLS (обычно порт 465)'),
        ('none', 'Без шифрования (не рекомендуется)'),
    ]

    # ===== Основное =====
    site_name = models.CharField(
        'Название сайта',
        max_length=100,
        default='Гильдия',
        help_text='Отображается в заголовке вкладки браузера и в шапке сайта'
    )
    favicon = models.FileField(
        'Иконка сайта (favicon)',
        upload_to='site/',
        blank=True,
        validators=[FileExtensionValidator(['ico', 'png'])],
        help_text='Файл .ico или .png, лучше квадратный (32×32 или 64×64). Если не загружен — используется стандартная иконка'
    )

    # ===== Регистрация =====
    email_verification = models.BooleanField(
        'Подтверждать email при регистрации',
        default=False,
        help_text='Новый пользователь сможет войти только после перехода по ссылке из письма. '
                  'Нужна настроенная почта (раздел «Почта»). Если выключено — аккаунт активен сразу'
    )
    captcha_enabled = models.BooleanField(
        'Капча при регистрации',
        default=False,
        help_text='Защита формы регистрации от ботов капчей DDoS-Guard (dCAPTCHA). Нужны ключи (раздел «Капча»)'
    )

    # ===== Почта (SMTP) =====
    email_host = models.CharField('SMTP-сервер', max_length=255, blank=True, help_text='Например, smtp.yandex.ru или smtp.gmail.com')
    email_port = models.PositiveIntegerField(
        'Порт', default=587, validators=[MinValueValidator(1), MaxValueValidator(65535)]
    )
    email_security = models.CharField('Шифрование', max_length=4, choices=EMAIL_SECURITY_CHOICES, default='tls')
    email_host_user = models.CharField('Логин', max_length=255, blank=True, help_text='Обычно — полный адрес почты')
    # Хранится зашифрованным. Читать — get_email_password().
    email_host_password = models.CharField(
        'Пароль', max_length=500, blank=True,
        help_text='Для Яндекса и Gmail — пароль приложения, а не пароль от почты. '
                  'Оставьте поле пустым, чтобы не менять сохранённый пароль'
    )
    email_from = models.CharField(
        'Адрес отправителя', max_length=255, blank=True,
        help_text='Например: Гильдия <noreply@myguild.ru>. Если пусто — используется логин'
    )

    # ===== Капча DDoS-Guard =====
    captcha_site_key = models.CharField('Site key', max_length=255, blank=True, help_text='Открытый ключ — виден в коде страницы')
    # Хранится зашифрованным. Читать — get_captcha_private_key().
    captcha_private_key = models.CharField(
        'Private key', max_length=500, blank=True,
        help_text='Секретный ключ — используется только на сервере. Оставьте поле пустым, чтобы не менять сохранённый ключ'
    )

    class Meta:
        verbose_name = 'Настройки сайта'
        verbose_name_plural = 'Настройки сайта'

    def __str__(self):
        return 'Настройки сайта'

    def save(self, *args, **kwargs):
        self.pk = 1
        # Секреты никогда не записываются в базу открытым текстом.
        for field in ('email_host_password', 'captcha_private_key'):
            value = getattr(self, field)
            if value and not value.startswith(SECRET_PREFIX):
                setattr(self, field, encrypt_secret(value))
        # При замене иконки удаляем старый файл, чтобы не копился мусор в media.
        old = SiteSettings.objects.filter(pk=1).first()
        if old and old.favicon and old.favicon != self.favicon:
            old.favicon.delete(save=False)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Настройки не удаляются.
        pass

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    # ----- Почта -----

    def get_email_password(self):
        return decrypt_secret(self.email_host_password) or ''

    @property
    def email_configured(self):
        return bool(self.email_host)

    @property
    def sender(self):
        return self.email_from or self.email_host_user

    # ----- Капча -----

    def get_captcha_private_key(self):
        return decrypt_secret(self.captcha_private_key) or ''

    @property
    def captcha_configured(self):
        return bool(self.captcha_site_key and self.get_captcha_private_key())

    @property
    def captcha_active(self):
        """Капча включена и есть оба ключа."""
        return self.captcha_enabled and self.captcha_configured

    def secret_unreadable(self, field):
        """Секрет сохранён, но не расшифровывается — обычно после смены DJANGO_SECRET_KEY."""
        value = getattr(self, field)
        return bool(value) and decrypt_secret(value) is None
