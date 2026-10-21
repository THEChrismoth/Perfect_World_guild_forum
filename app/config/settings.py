import os
from dotenv import load_dotenv
import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from pathlib import Path

# BASE_DIR — папка app с кодом сайта (приложения, шаблоны, исходники статики).
# ROOT_DIR — корень репозитория: там лежат .env и данные (db.sqlite3, media, собранная статика).
BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent
load_dotenv(ROOT_DIR / '.env')


# Перед запуском на сервере сверьтесь с чек-листом: https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# Не включайте DEBUG на сервере: при ошибках он показывает настройки и код.
DEBUG = os.getenv('DEBUG', 'False') == 'True'

# Секретный ключ никому не сообщайте.
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('Не задана переменная окружения DJANGO_SECRET_KEY')
    SECRET_KEY = 'django-insecure-dev-only-key'

def _env_list(name):
    """Список из переменной окружения через запятую: 'a.ru, www.a.ru' -> ['a.ru', 'www.a.ru']."""
    return [item.strip() for item in os.getenv(name, '').split(',') if item.strip()]


# Домены сайта. При DEBUG=True и пустом списке Django сам разрешает localhost.
ALLOWED_HOSTS = _env_list('ALLOWED_HOSTS')


# Приложения.

INSTALLED_APPS = [
    # Стандартная админка Django с дашбордом и темой гильдии (core/admin_site.py).
    'core.apps.GuildAdminConfig',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
    'forum',
    'koslist',
    'profiles',
    'auction',
    'reception',
    'notifications',
    'events',
    'backups',
    'teamspeak',
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


# База данных: https://docs.djangoproject.com/en/6.0/ref/settings/#databases
# База берется из переменной окружения DATABASE_URL:
# - в Docker ее задает docker-compose.yml — сайт работает на PostgreSQL (контейнер db);
# - без Docker (runserver для разработки) переменной нет — используется SQLite db.sqlite3 в корне репозитория.
# Строка default ниже — только этот запасной вариант для разработки.
DATABASES = {
    'default': dj_database_url.config(
        default='sqlite:///' + os.path.join(ROOT_DIR, 'db.sqlite3'),
        conn_max_age=600,
        conn_health_checks=True,
    )
}

if DATABASES['default']['ENGINE'] == 'django.db.backends.sqlite3':
    # Транзакция сразу берет блокировку на запись: параллельные ставки
    # на аукционе выполняются по очереди, а не перезаписывают друг друга.
    # В PostgreSQL то же самое обеспечивает select_for_update.
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

LANGUAGE_CODE = 'ru-ru'
USE_TZ = True
TIME_ZONE = 'Europe/Moscow'
USE_I18N = True

STATIC_URL = '/static/'
# Исходники статики лежат в static_src, collectstatic собирает всё (вместе со статикой админки) в static.
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static_src')]
STATIC_ROOT = os.path.join(ROOT_DIR, 'static')

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    # Имена файлов статики с хэшем содержимого — браузер не держит старый CSS после обновления.
    # При DEBUG=True (runserver) ссылки остаются обычными.
    'staticfiles': {'BACKEND': 'core.storage.ForgivingManifestStaticFilesStorage'},
}

LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
LOGIN_URL = '/login/'

# Для загрузки файлов (аватаров).
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(ROOT_DIR, 'media')

# Резервные копии на сервере (настройки расписания и Яндекс Диска — в админ-панели).
BACKUP_DIR = os.getenv('BACKUP_DIR') or os.path.join(ROOT_DIR, 'backups')
# Пароль шифрования копий (GPG, AES-256). Намеренно только в .env, не в базе.
BACKUP_ENCRYPTION_PASSWORD = os.getenv('BACKUP_ENCRYPTION_PASSWORD', '')
# Путь к gpg, если его нет в PATH (например, gpg из Git для Windows).
BACKUP_GPG_BINARY = os.getenv('BACKUP_GPG_BINARY', '')

# Токен, которым бот TeamSpeak (tsbot/) входит в API сайта. Пусто — API бота отключено.
TSBOT_API_TOKEN = os.getenv('TSBOT_API_TOKEN', '')

# Ограничения на загрузку файлов.
DATA_UPLOAD_MAX_MEMORY_SIZE = 60 * 1024 * 1024  # Общий размер запроса
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024   # Крупнее — пишется во временный файл

# HTTPS-настройки включаются переменной USE_HTTPS=True в .env, когда на сервере есть SSL.
USE_HTTPS = os.getenv('USE_HTTPS', 'False') == 'True'
if USE_HTTPS:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = USE_HTTPS
SESSION_COOKIE_SECURE = USE_HTTPS
CSRF_COOKIE_SECURE = USE_HTTPS

# За прокси (Caddy) Django проверяет, что формы отправлены с нашего домена.
# По умолчанию доверяем всем доменам из ALLOWED_HOSTS.
CSRF_TRUSTED_ORIGINS = _env_list('CSRF_TRUSTED_ORIGINS') or [
    f"{'https' if USE_HTTPS else 'http'}://{host.lstrip('.')}"
    for host in ALLOWED_HOSTS if host != '*'
]

# Почта (SMTP), подтверждение email и капча настраиваются в админ-панели: Настройки сайта.
# Письма сайта отправляет core.mail; пока почта не настроена, они печатаются в консоль.
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = 'webmaster@localhost'
