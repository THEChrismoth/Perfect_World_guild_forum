# Разработка

## Стек

Python 3.13+, Django 6, PostgreSQL (в Docker) или SQLite (локально), django-jazzmin, django-recaptcha, Pillow, gunicorn, Caddy.

## Структура репозитория

```
├── src/                  весь сайт (Django)
│   ├── manage.py
│   ├── config/           настройки и корневые URL
│   ├── core/             настройки сайта (название, favicon)
│   ├── forum/            форум, права доступа к разделам
│   ├── profiles/         профили, регистрация, таблица очков активности
│   ├── reception/        заявки в гильдию и голосование
│   ├── auction/          аукцион за очки активности
│   ├── events/           ивенты, отряды, приглашения
│   ├── koslist/          кос-лист
│   ├── notifications/    уведомления
│   ├── templates/
│   └── static_src/       исходники статики (CSS, иконки)
├── docker/               Caddyfile и entrypoint.sh
├── docs/
├── Dockerfile, docker-compose.yml, .env.example
└── pyproject.toml, uv.lock, requirements.txt
```

`.env`, `db.sqlite3`, `media/` и собранная статика `static/` лежат в корне репозитория, а не в `src/`.

**PyCharm:** пометьте папку `src` как Sources Root (правый клик → *Mark Directory as* → *Sources Root*), а в конфигурации запуска Django укажите `src/manage.py` и рабочую папку `src`.

## Запуск без Docker

Удобно при правке кода: изменения подхватываются сразу. Используется отдельная база SQLite (`db.sqlite3`), с Docker-базой она не связана.

```bash
uv sync
# или: python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt
```

Создайте `.env` в корне репозитория:

```env
DEBUG=True
DJANGO_SECRET_KEY=любая-длинная-строка
```

Команды Django запускаются из папки `src`:

```bash
cd src
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Сайт — http://127.0.0.1:8000/, админ-панель — http://127.0.0.1:8000/admin/. Без `DEBUG=True` не будут работать стили и картинки. Письма при пустом `EMAIL_HOST` выводятся в консоль.

## Переменные окружения вне Docker

В Docker их выставляет `docker-compose.yml`, при запуске без Docker — задайте в `.env` сами:

| Переменная | Описание |
|---|---|
| `DEBUG` | `True` для разработки. По умолчанию `False` |
| `ALLOWED_HOSTS` | Домены через запятую (нужно при `DEBUG=False`) |
| `CSRF_TRUSTED_ORIGINS` | По умолчанию строится из `ALLOWED_HOSTS` |
| `DATABASE_URL` | Например `postgres://user:pass@localhost:5432/forum`. По умолчанию SQLite |
| `USE_HTTPS` | `True`, если сайт работает по HTTPS: редирект на https и secure-куки |

## Тесты

```bash
cd src
python manage.py test
```

## Миграции

```bash
cd src
python manage.py makemigrations
```

Модели должны принадлежать приложениям проекта. Не указывайте `app_label` встроенных приложений Django (`auth` и т. п.) — иначе миграция создастся внутри установленного Django в `.venv` и не попадёт в репозиторий.

## Статика

Исходники — в `src/static_src/`, `collectstatic` собирает их в `static/` в корне репозитория (в Docker это делается при старте контейнера `web`).

## Перенос данных со старой установки (SQLite → Docker)

Сделайте резервную копию `db.sqlite3` и `media/`. На старой установке (в версиях до переноса кода в `src/` файл `manage.py` лежит в корне):

```bash
python manage.py dumpdata --natural-foreign --natural-primary \
    -e contenttypes -e auth.permission -e admin.logentry -e sessions > data.json
```

На новой (после `docker compose up -d`):

```bash
docker compose cp data.json web:/app/data.json
docker compose exec web python manage.py loaddata /app/data.json
docker compose cp ./media/. web:/app/media/
```

## Docker-файлы

| Файл | Назначение |
|---|---|
| `Dockerfile` | Образ сайта (Django + gunicorn). Внутри та же структура: код в `/app/src`, данные в `/app/static` и `/app/media` |
| `docker/entrypoint.sh` | Миграции, `collectstatic` и создание администратора при старте |
| `docker/Caddyfile` | HTTPS, раздача `/static` и `/media`, проксирование в Django |
| `docker-compose.yml` | Сервисы `db`, `web`, `caddy` и тома с данными |
