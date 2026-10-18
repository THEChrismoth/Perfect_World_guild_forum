import os
from dotenv import load_dotenv
import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'False') == 'True'

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('Не задана переменная окружения DJANGO_SECRET_KEY')
    SECRET_KEY = 'django-insecure-dev-only-key'

def _env_list(name):
    """Список из переменной окружения через запятую: 'a.ru, www.a.ru' -> ['a.ru', 'www.a.ru']"""
    return [item.strip() for item in os.getenv(name, '').split(',') if item.strip()]


# Домены сайта. При DEBUG=True и пустом списке Django сам разрешает localhost
ALLOWED_HOSTS = _env_list('ALLOWED_HOSTS')


# Application definition

INSTALLED_APPS = [
    "jazzmin",
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
    'forum',
    'koslist',
    'profiles',
    'captcha',
    'django_recaptcha',
    'auction',
    'reception',
    'notifications',
    'events',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'forum.middleware.UserActivityMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'notifications.context_processors.notifications_context',
                'core.context_processors.site_settings',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    'default': dj_database_url.config(
        default='sqlite:///' + os.path.join(BASE_DIR, 'db.sqlite3'),
        conn_max_age=600,
        conn_health_checks=True,
    )
}

if DATABASES['default']['ENGINE'] == 'django.db.backends.sqlite3':
    # Транзакция сразу берет блокировку на запись: параллельные ставки
    # на аукционе выполняются по очереди, а не перезаписывают друг друга.
    # В PostgreSQL то же самое обеспечивает select_for_update
    DATABASES['default'].setdefault('OPTIONS', {})['transaction_mode'] = 'IMMEDIATE'

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

SILENCED_SYSTEM_CHECKS = [
    'django_recaptcha.recaptcha_test_key_error',
]

LANGUAGE_CODE = 'ru-ru'
USE_TZ = True
TIME_ZONE = 'Europe/Moscow'
USE_I18N = True

STATIC_URL = '/static/'
# Исходники статики лежат в static_src, collectstatic собирает всё (вместе с admin/jazzmin) в static
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static_src')]
STATIC_ROOT = os.path.join(BASE_DIR, 'static')

LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
LOGIN_URL = '/login/'

# Для загрузки файлов (аватаров)
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Ограничения на загрузку файлов
DATA_UPLOAD_MAX_MEMORY_SIZE = 60 * 1024 * 1024  # общий размер запроса
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024   # крупнее — пишется во временный файл

# HTTPS-настройки включаются переменной USE_HTTPS=True в .env, когда на сервере есть SSL
USE_HTTPS = os.getenv('USE_HTTPS', 'False') == 'True'
if USE_HTTPS:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = USE_HTTPS
SESSION_COOKIE_SECURE = USE_HTTPS
CSRF_COOKIE_SECURE = USE_HTTPS

# За прокси (Caddy) Django проверяет, что формы отправлены с нашего домена.
# По умолчанию доверяем всем доменам из ALLOWED_HOSTS
CSRF_TRUSTED_ORIGINS = _env_list('CSRF_TRUSTED_ORIGINS') or [
    f"{'https' if USE_HTTPS else 'http'}://{host.lstrip('.')}"
    for host in ALLOWED_HOSTS if host != '*'
]

# Почта: если EMAIL_HOST не задан, письма печатаются в консоль (удобно для разработки)
EMAIL_HOST = os.getenv('EMAIL_HOST', '')
if EMAIL_HOST:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_PORT = int(os.getenv('EMAIL_PORT') or 587)
    EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
    EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'False') == 'True'
    EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL') or os.getenv('EMAIL_HOST_USER') or 'webmaster@localhost'

RECAPTCHA_PUBLIC_KEY = os.getenv('RECAPTCHA_PUBLIC_KEY')
RECAPTCHA_PRIVATE_KEY = os.getenv('RECAPTCHA_PRIVATE_KEY')
